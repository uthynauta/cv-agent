from pathlib import Path

import pytest

from cv_agent.config import Settings
from cv_agent.knowledge.documents_service import (
    DocumentMutationError,
    DocumentService,
)
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.index import ActiveKnowledge
from cv_agent.knowledge.ingest import IngestionService
from cv_agent.knowledge.locking import MutationBusyError, MutationLock
from cv_agent.knowledge.repository import KnowledgeRepository
from cv_agent.knowledge.storage import ensure_data_storage


@pytest.fixture
def document_service(tmp_path: Path) -> DocumentService:
    paths = ensure_data_storage(tmp_path / "data")
    settings = Settings(_env_file=None, data_dir=paths.root, ingestion_mode="deterministic")
    git = LocalKnowledgeGit(paths.repository, "Test", "test@example.com")
    git.initialize()
    repository = KnowledgeRepository(paths.repository)
    active = ActiveKnowledge.load(repository)
    ingestion = IngestionService(repository, settings)
    return DocumentService(paths, git, ingestion, active)


def test_add_and_replace_preserve_id_and_activate_snapshot(document_service: DocumentService):
    first = document_service.add("candidate.md", b"Python experience")
    second = document_service.replace(first.document_id, "candidate.md", b"Rust experience")

    assert second.document_id == first.document_id
    assert second.content_sha256 != first.content_sha256
    assert document_service.active.search("Rust")
    assert document_service.active.search("Python") == []
    assert all(
        path.startswith(("sources/", "knowledge/")) and path.endswith(".md")
        for path in document_service.git.tracked_paths()
    )


def test_delete_removes_source_and_original(document_service: DocumentService):
    added = document_service.add("candidate.md", b"Python experience")
    result = document_service.delete(added.document_id)

    assert result.document_id == added.document_id
    assert document_service.list_documents() == []
    assert document_service.active.search("Python") == []


def test_rebuild_uses_versioned_source_when_original_is_unavailable(document_service: DocumentService):
    added = document_service.add("candidate.md", b"Python experience")
    original = next(document_service.paths.documents.glob(f"{added.document_id}.*"))
    original.unlink()

    rebuilt = document_service.rebuild()

    assert rebuilt.commit == document_service.git.head()
    assert document_service.active.search("Python")


def test_failed_snapshot_activation_restores_head_and_active(
    document_service: DocumentService, monkeypatch: pytest.MonkeyPatch
):
    added = document_service.add("candidate.md", b"Python experience")
    prior_head = document_service.git.head()
    monkeypatch.setattr(document_service.active, "reload", lambda repository: (_ for _ in ()).throw(ValueError("bad")))

    with pytest.raises(DocumentMutationError) as error:
        document_service.replace(added.document_id, "candidate.md", b"Rust experience")

    assert error.value.operation_id
    assert document_service.git.head() == prior_head
    assert document_service.active.search("Python")
    assert document_service.active.search("Rust") == []
    assert list(document_service.paths.staging.iterdir()) == []


@pytest.mark.parametrize("failure", ["validate", "commit", "originals"])
def test_post_or_pre_commit_failures_restore_everything(
    document_service: DocumentService,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
):
    added = document_service.add("candidate.md", b"Python experience")
    prior_head = document_service.git.head()
    original = next(document_service.paths.documents.glob(f"{added.document_id}.*"))
    prior_bytes = original.read_bytes()
    if failure == "validate":
        monkeypatch.setattr(document_service, "_validate_staged", lambda path: (_ for _ in ()).throw(ValueError("invalid")))
    elif failure == "commit":
        monkeypatch.setattr(document_service.git, "commit", lambda message: (_ for _ in ()).throw(RuntimeError("git")))
    else:
        monkeypatch.setattr(document_service, "_activate_originals", lambda candidate, backup: (_ for _ in ()).throw(OSError("disk")))

    with pytest.raises(DocumentMutationError):
        document_service.replace(added.document_id, "candidate.md", b"Rust experience")

    assert document_service.git.head() == prior_head
    assert original.read_bytes() == prior_bytes
    assert document_service.active.search("Python")
    assert document_service.active.search("Rust") == []
    assert list(document_service.paths.staging.iterdir()) == []


def test_mutation_lock_contention_is_reported_without_mutating(document_service: DocumentService):
    with MutationLock(document_service.paths.locks / "mutation.lock"):
        with pytest.raises(MutationBusyError):
            document_service.add("candidate.md", b"Python")
    assert document_service.list_documents() == []
