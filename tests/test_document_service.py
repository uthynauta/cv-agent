from pathlib import Path
import stat

import pytest

from cv_agent.config import Settings
from cv_agent.knowledge.documents_service import (
    DocumentCompensationError,
    DocumentMutationError,
    DocumentNotFoundError,
    DocumentService,
)
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.index import ActiveKnowledge
from cv_agent.knowledge.ingest import IngestionService
from cv_agent.knowledge.locking import MutationBusyError, MutationLock
from cv_agent.knowledge.frontmatter import load_frontmatter
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


@pytest.mark.parametrize("document_id", ["../knowledge/index", "../../documents/other"])
def test_replace_and_delete_reject_traversal_document_ids(
    document_service: DocumentService, document_id: str
):
    with pytest.raises(ValueError):
        document_service.replace(document_id, "candidate.md", b"bad")
    with pytest.raises(ValueError):
        document_service.delete(document_id)
    assert not (document_service.repository.root / "knowledge" / "index").exists()


def test_first_commit_snapshot_failure_restores_empty_git_state(
    document_service: DocumentService, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(document_service.active, "reload", lambda repository: (_ for _ in ()).throw(ValueError("bad")))

    with pytest.raises(DocumentMutationError):
        document_service.add("candidate.md", b"Python")

    assert document_service.git.head() == ""
    assert document_service.git.tracked_paths() == []
    assert document_service.list_documents() == []
    assert document_service.active.search("Python") == []
    assert list(document_service.paths.documents.glob("*")) == [document_service.paths.documents / "quarantine"]
    assert list(document_service.paths.staging.iterdir()) == []
    monkeypatch.undo()
    added = document_service.add("candidate.md", b"Python")
    assert added.commit == document_service.git.head()


def test_compensation_runs_while_mutation_lock_is_held(
    document_service: DocumentService, monkeypatch: pytest.MonkeyPatch
):
    original_compensate = document_service._compensate
    observed = False

    def observe_lock(*args, **kwargs):
        nonlocal observed
        with pytest.raises(MutationBusyError):
            with MutationLock(document_service.paths.locks / "mutation.lock"):
                pass
        observed = True
        return original_compensate(*args, **kwargs)

    monkeypatch.setattr(document_service, "_compensate", observe_lock)
    monkeypatch.setattr(document_service.active, "reload", lambda repository: (_ for _ in ()).throw(ValueError("bad")))
    with pytest.raises(DocumentMutationError):
        document_service.add("candidate.md", b"Python")
    assert observed


def test_result_changed_paths_are_limited_to_commit(document_service: DocumentService):
    first = document_service.add("first.md", b"Python")
    second = document_service.add("second.md", b"Rust")

    assert "sources/" + first.document_id + ".md" not in second.changed_paths
    assert "sources/" + second.document_id + ".md" in second.changed_paths
    assert all(path.startswith(("sources/", "knowledge/")) for path in second.changed_paths)


def test_rebuild_preserves_source_identity_and_text(document_service: DocumentService):
    added = document_service.add("candidate.md", b"Python experience")
    source = document_service.repository.root / "sources" / f"{added.document_id}.md"
    before = source.read_text(encoding="utf-8")
    metadata_before, body_before = load_frontmatter(before)

    document_service.rebuild()

    metadata_after, body_after = load_frontmatter(source.read_text(encoding="utf-8"))
    assert metadata_after == metadata_before
    assert body_after == body_before


def test_mutation_uses_isolated_candidate_ingestion_service(
    document_service: DocumentService, monkeypatch: pytest.MonkeyPatch
):
    original_ingest_file = IngestionService.ingest_file
    original_repository = document_service.ingestion.repository
    observed: list[IngestionService] = []

    def observe_ingest(service, path, document_id, original_filename=None):
        observed.append(service)
        return original_ingest_file(service, path, document_id, original_filename)

    monkeypatch.setattr(IngestionService, "ingest_file", observe_ingest)
    document_service.add("candidate.md", b"Python experience")

    assert observed
    assert observed[0] is not document_service.ingestion
    assert observed[0].repository is not original_repository
    assert document_service.ingestion.repository is original_repository


def test_rebuild_preserves_extracted_text_with_reserved_heading(document_service: DocumentService):
    added = document_service.add("candidate.md", b"Intro\n## Extracted Text\nTail")

    document_service.rebuild()

    source = document_service.repository.root / "sources" / f"{added.document_id}.md"
    assert "Intro\n## Extracted Text\nTail" in source.read_text(encoding="utf-8")


def test_lifecycle_log_uses_logical_filename_not_staging_path(document_service: DocumentService):
    added = document_service.add("candidate.md", b"Python experience")
    document_service.rebuild()
    log = (document_service.repository.root / "knowledge" / "log.md").read_text(encoding="utf-8")

    assert "Source: `candidate.md`" in log
    assert str(document_service.paths.root) not in log
    assert str(document_service.paths.staging) not in log
    assert added.operation_id not in log


def test_partial_original_activation_restores_prior_state(
    document_service: DocumentService, monkeypatch: pytest.MonkeyPatch
):
    added = document_service.add("candidate.md", b"Python")
    prior_head = document_service.git.head()
    original = next(document_service.paths.documents.glob(f"{added.document_id}.*"))
    prior_bytes = original.read_bytes()
    original.chmod(0o640)

    def partially_activate(candidate: Path, backup: Path) -> None:
        document_service.paths.documents.rename(backup)
        document_service.paths.documents.mkdir()
        (document_service.paths.documents / "partial.md").write_bytes(b"partial")
        raise OSError("activation failed")

    monkeypatch.setattr(document_service, "_activate_originals", partially_activate)
    with pytest.raises(DocumentMutationError):
        document_service.replace(added.document_id, "candidate.md", b"Rust")

    assert document_service.git.head() == prior_head
    assert original.read_bytes() == prior_bytes
    assert not (document_service.paths.documents / "partial.md").exists()
    assert stat.S_IMODE(original.stat().st_mode) == 0o640
    assert document_service.active.search("Python")
    assert document_service.active.search("Rust") == []


def test_missing_document_preserves_not_found_error_and_id(document_service: DocumentService):
    with pytest.raises(DocumentNotFoundError) as error:
        document_service.delete("missing-document")
    assert error.value.document_id == "missing-document"


def test_compensation_failure_is_explicit_and_snapshot_still_restored(
    document_service: DocumentService, monkeypatch: pytest.MonkeyPatch
):
    added = document_service.add("candidate.md", b"Python")
    prior_head = document_service.git.head()
    prior_snapshot = document_service.active._snapshot
    restore_heads: list[tuple[str, str]] = []
    monkeypatch.setattr(document_service.active, "reload", lambda repository: (_ for _ in ()).throw(ValueError("activation")))
    monkeypatch.setattr(document_service, "_restore_directory_from_backup", lambda live, backup: (_ for _ in ()).throw(OSError("restore")))
    original_restore_head = document_service.git.restore_head

    def observe_restore_head(expected_current: str, prior: str) -> None:
        restore_heads.append((expected_current, prior))
        original_restore_head(expected_current, prior)

    monkeypatch.setattr(document_service.git, "restore_head", observe_restore_head)

    with pytest.raises(DocumentCompensationError) as error:
        document_service.replace(added.document_id, "candidate.md", b"Rust")

    assert error.value.operation_id
    assert restore_heads and restore_heads[0][1] == prior_head
    assert document_service.git.head() == prior_head
    assert document_service.active._snapshot is prior_snapshot


def test_failure_before_original_activation_keeps_original_directory_untouched(
    document_service: DocumentService, monkeypatch: pytest.MonkeyPatch
):
    added = document_service.add("candidate.md", b"Python")
    original_directory = document_service.paths.documents
    original = next(original_directory.glob(f"{added.document_id}.*"))
    prior_bytes = original.read_bytes()
    original.chmod(0o640)
    restore_calls: list[tuple[Path, Path]] = []

    def record_restore(live: Path, backup: Path) -> None:
        restore_calls.append((live, backup))

    monkeypatch.setattr(document_service.git, "changed_paths", lambda commit: (_ for _ in ()).throw(RuntimeError("paths")))
    monkeypatch.setattr(document_service, "_restore_directory_from_backup", record_restore)

    with pytest.raises(DocumentMutationError):
        document_service.replace(added.document_id, "candidate.md", b"Rust")

    assert all(live != document_service.paths.documents for live, _backup in restore_calls)
    assert document_service.paths.documents == original_directory
    assert original.read_bytes() == prior_bytes
    assert stat.S_IMODE(original.stat().st_mode) == 0o640
