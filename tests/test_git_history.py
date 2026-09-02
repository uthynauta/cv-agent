from pathlib import Path
from hashlib import sha256

import pytest

from cv_agent.config import Settings
from cv_agent.knowledge.documents_service import DocumentMutationError, DocumentService
from cv_agent.knowledge.git_store import GitStoreError, LocalKnowledgeGit
from cv_agent.knowledge.index import ActiveKnowledge
from cv_agent.knowledge.extractors import ExtractedSource
from cv_agent.knowledge.ingest import IngestionService
from cv_agent.knowledge.repository import KnowledgeRepository
from cv_agent.knowledge.storage import ensure_data_storage
from cv_agent.knowledge.locking import MutationBusyError, MutationLock


def make_store(tmp_path: Path) -> LocalKnowledgeGit:
    paths = ensure_data_storage(tmp_path / "data")
    store = LocalKnowledgeGit(paths.repository, "Test Author", "test@example.com")
    store.initialize()
    return store


@pytest.fixture
def document_service(tmp_path: Path) -> DocumentService:
    paths = ensure_data_storage(tmp_path / "data")
    settings = Settings(_env_file=None, data_dir=paths.root, ingestion_mode="deterministic")
    git = LocalKnowledgeGit(paths.repository, "Test Author", "test@example.com")
    git.initialize()
    repository = KnowledgeRepository(paths.repository)
    active = ActiveKnowledge.load(repository)
    ingestion = IngestionService(repository, settings)
    return DocumentService(paths, git, ingestion, active)


def commit_page(store: LocalKnowledgeGit, name: str, text: str, message: str) -> str:
    path = store.root / "sources" / name
    path.write_text(text, encoding="utf-8")
    return store.commit(message)


def test_history_is_newest_first_and_has_revision_fields(tmp_path: Path):
    store = make_store(tmp_path)
    first = commit_page(store, "first.md", "first", "first subject")
    second = commit_page(store, "second.md", "second", "second subject")

    revisions = store.history(10)

    assert [revision.commit for revision in revisions[:2]] == [second, first]
    assert revisions[0].subject == "second subject"
    assert revisions[0].authored_at
    assert "sources/second.md" in revisions[0].changed_paths


def test_history_caps_at_one_hundred_and_rejects_non_full_commit_ids(tmp_path: Path):
    store = make_store(tmp_path)
    commit_page(store, "source.md", "source", "initial")

    assert len(store.history(1000)) <= 100
    with pytest.raises(GitStoreError):
        store.contains_commit(store.head()[:8])
    with pytest.raises(GitStoreError):
        store.history(-1)


def test_checkout_tree_rejects_symlink_destination_and_materializes_markdown(tmp_path: Path):
    store = make_store(tmp_path)
    commit = commit_page(store, "source.md", "source", "initial")
    destination = tmp_path / "data" / "staging" / "checkout"

    store.checkout_tree(commit, destination)

    assert (destination / "sources" / "source.md").read_text(encoding="utf-8") == "source"
    assert (destination / "knowledge").is_dir()

    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(GitStoreError):
        store.checkout_tree(commit, linked)


def test_checkout_tree_rejects_malicious_tree_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = make_store(tmp_path)
    commit = commit_page(store, "source.md", "source", "initial")
    original_run = store._run

    def malicious_run(*args: str, **kwargs):
        if args[:3] == ("ls-tree", "-r", "-z"):
            return type("Result", (), {"stdout": "100644 blob " + "a" * 40 + "\tsources/../outside.md\0"})()
        return original_run(*args, **kwargs)

    monkeypatch.setattr(store, "_run", malicious_run)
    with pytest.raises(GitStoreError):
        store.checkout_tree(commit, tmp_path / "data" / "staging" / "bad")


def test_history_operations_reject_unreachable_dangling_commit(tmp_path: Path):
    store = make_store(tmp_path)
    first = commit_page(store, "first.md", "first", "first")
    second = commit_page(store, "second.md", "second", "second")
    store.restore_head(second, first)

    assert store.head() == first
    assert not store.contains_commit(second)
    with pytest.raises(GitStoreError):
        store.checkout_tree(second, tmp_path / "data" / "staging" / "dangling")


def test_service_history_delegates_to_local_git(document_service: DocumentService):
    first = document_service.add("candidate.md", b"Python")
    second = document_service.replace(first.document_id, "candidate.md", b"Rust")

    assert [item.commit for item in document_service.history(10)[:2]] == [second.commit, first.commit]


def test_rollback_requires_confirmation_and_rejects_unknown_commit(document_service: DocumentService):
    added = document_service.add("candidate.md", b"Python")

    with pytest.raises(DocumentMutationError):
        document_service.rollback(added.commit, confirmed=False)
    with pytest.raises(DocumentMutationError):
        document_service.rollback("f" * 40, confirmed=True)
    assert document_service.git.head() == added.commit


def test_rollback_creates_audit_commit_and_quarantines_mismatched_original(
    document_service: DocumentService, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "cv_agent.knowledge.ingest.extract_source",
        lambda path: ExtractedSource(path, path.read_bytes().decode(), "pdf", False, sha256(path.read_bytes()).hexdigest()),
    )
    first = document_service.add("candidate.pdf", b"first PDF")
    second = document_service.replace(first.document_id, "candidate.pdf", b"second PDF")

    rolled_back = document_service.rollback(first.commit, confirmed=True)

    assert rolled_back.commit not in {first.commit, second.commit}
    assert document_service.git.head() == rolled_back.commit
    assert document_service.active.search("first")
    assert not document_service.list_documents()[0].original_available
    assert list(document_service.paths.quarantine.rglob("*.pdf"))
    subject = document_service.history(1)[0].subject
    assert subject == f"Rollback knowledge to {first.commit[:8]}"


def test_rollback_retains_matching_original_and_reports_missing_original(
    document_service: DocumentService,
):
    first = document_service.add("candidate.md", b"Python")
    original = next(document_service.paths.documents.glob(f"{first.document_id}.*"))
    original_bytes = original.read_bytes()
    document_service.rebuild()

    retained = document_service.rollback(first.commit, confirmed=True)
    assert retained.commit
    restored = next(document_service.paths.documents.glob(f"{first.document_id}.*"))
    assert restored.read_bytes() == original_bytes
    assert document_service.list_documents()[0].original_available

    restored.unlink()
    document_service.rollback(first.commit, confirmed=True)
    assert not document_service.list_documents()[0].original_available


def test_rollback_quarantines_orphan_original(document_service: DocumentService):
    first = document_service.add("first.md", b"Python")
    second = document_service.add("second.md", b"Rust")

    document_service.rollback(first.commit, confirmed=True)

    assert not (document_service.paths.documents / f"{second.document_id}.md").exists()
    quarantined = list(document_service.paths.quarantine.rglob(f"{second.document_id}.md"))
    assert len(quarantined) == 1


def test_rollback_lock_contention_does_not_mutate(document_service: DocumentService):
    added = document_service.add("candidate.md", b"Python")

    with MutationLock(document_service.paths.locks / "mutation.lock"):
        with pytest.raises(MutationBusyError):
            document_service.rollback(added.commit, confirmed=True)

    assert document_service.git.head() == added.commit


def test_rollback_current_head_creates_distinct_empty_audit_commit(document_service: DocumentService):
    added = document_service.add("candidate.md", b"Python")

    rolled_back = document_service.rollback(added.commit, confirmed=True)

    assert rolled_back.commit != added.commit
    assert rolled_back.changed_paths == ()
    assert document_service.history(1)[0].commit == rolled_back.commit
    assert document_service.history(1)[0].subject == f"Rollback knowledge to {added.commit[:8]}"


def test_rollback_rejects_dangling_commit(document_service: DocumentService):
    first = document_service.add("first.md", b"Python")
    second = document_service.add("second.md", b"Rust")
    document_service.git.restore_head(second.commit, first.commit)

    with pytest.raises(DocumentMutationError):
        document_service.rollback(second.commit, confirmed=True)
    assert document_service.git.head() == first.commit
