from pathlib import Path
import subprocess

import pytest

from cv_agent.knowledge.git_store import GitStoreError, LocalKnowledgeGit
from cv_agent.knowledge.storage import ensure_data_storage


def make_store(tmp_path: Path) -> tuple[LocalKnowledgeGit, Path]:
    paths = ensure_data_storage(tmp_path / "data")
    return LocalKnowledgeGit(paths.repository, "Test Author", "test@example.com"), paths.root


def test_initialize_creates_repository_without_remotes(tmp_path: Path):
    store, _ = make_store(tmp_path)

    store.initialize()

    assert (store.root / ".git").is_dir()
    assert store.remotes() == []


def test_head_is_empty_before_first_commit(tmp_path: Path):
    store, _ = make_store(tmp_path)
    store.initialize()

    assert store.head() == ""


def test_commit_stages_sources_but_not_documents(tmp_path: Path):
    store, data_root = make_store(tmp_path)
    store.initialize()
    (store.root / "sources" / "source.md").write_text("source", encoding="utf-8")
    (data_root / "documents" / "source.pdf").write_bytes(b"pdf")

    commit_sha = store.commit("add source")

    assert len(commit_sha) == 40
    assert store.tracked_paths() == ["sources/source.md"]
    assert "documents/source.pdf" not in store.tracked_paths()


def test_commit_ignores_unrelated_pre_staged_files_without_deleting_them(tmp_path: Path):
    store = LocalKnowledgeGit(tmp_path / "repository", "Test Author", "test@example.com")
    store.initialize()
    source = store.root / "sources" / "source.md"
    source.parent.mkdir()
    source.write_text("source", encoding="utf-8")
    note = store.root / "notes.txt"
    binary = store.root / "payload.bin"
    note.write_text("keep in working tree", encoding="utf-8")
    binary.write_bytes(b"keep in working tree")
    store._run("add", "--", "notes.txt", "payload.bin")

    store.commit("add source")

    assert store.tracked_paths() == ["sources/source.md"]
    assert note.read_text(encoding="utf-8") == "keep in working tree"
    assert binary.read_bytes() == b"keep in working tree"
    status = store._run("status", "--short").stdout
    assert "?? notes.txt" in status
    assert "?? payload.bin" in status


def test_second_commit_without_changes_keeps_same_sha_and_history(tmp_path: Path):
    store, _ = make_store(tmp_path)
    store.initialize()
    (store.root / "sources" / "source.md").write_text("source", encoding="utf-8")

    first_sha = store.commit("add source")
    second_sha = store.commit("nothing changed")
    history = store._run("rev-list", "--count", "HEAD").stdout.strip()

    assert second_sha == first_sha
    assert history == "1"


def test_knowledge_and_deletions_are_tracked_but_root_files_are_not(tmp_path: Path):
    store, _ = make_store(tmp_path)
    store.initialize()
    source = store.root / "sources" / "source.md"
    knowledge = store.root / "knowledge" / "page.md"
    source.write_text("source", encoding="utf-8")
    knowledge.write_text("page", encoding="utf-8")
    store.commit("add content")

    source.unlink()
    knowledge.write_text("updated page", encoding="utf-8")
    (store.root / "notes.txt").write_text("do not stage", encoding="utf-8")
    (store.root / "payload.bin").write_bytes(b"do not stage")

    store.commit("update knowledge")

    assert store.tracked_paths() == ["knowledge/page.md"]
    assert (store.root / "notes.txt").exists()
    assert (store.root / "payload.bin").exists()
    assert "?? notes.txt" in store._run("status", "--short").stdout
    assert "?? payload.bin" in store._run("status", "--short").stdout


def test_failed_git_operation_raises_bounded_git_store_error(tmp_path: Path):
    store, _ = make_store(tmp_path)
    store.initialize()

    with pytest.raises(GitStoreError) as raised:
        store._run("not-a-real-git-operation", "secret-document-content")

    message = str(raised.value)
    assert "Git operation 'git command' failed" in message
    assert "secret-document-content" not in message
    assert len(message) <= 500


def test_git_error_redacts_huge_sensitive_operation_arguments_and_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = LocalKnowledgeGit(tmp_path / "repository", "Test Author", "test@example.com")
    secret = "TOP_SECRET_DOCUMENT_CONTENT"

    def failed_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", secret * 1000)

    monkeypatch.setattr(subprocess, "run", failed_run)

    with pytest.raises(GitStoreError) as raised:
        store._run(secret * 1000, secret * 1000)

    message = str(raised.value)
    assert message == "Git operation 'git command' failed"
    assert secret not in message
    assert len(message) <= 200


def test_head_rejects_corrupt_head_instead_of_treating_it_as_unborn(tmp_path: Path):
    store = LocalKnowledgeGit(tmp_path / "repository", "Test Author", "test@example.com")
    store.initialize()
    (store.root / ".git" / "HEAD").write_text("corrupt-head", encoding="utf-8")

    with pytest.raises(GitStoreError):
        store.head()


def test_empty_commit_in_fresh_repository_without_scope_directories_returns_empty_head(
    tmp_path: Path,
):
    store = LocalKnowledgeGit(tmp_path / "repository", "Test Author", "test@example.com")
    store.initialize()

    assert not (store.root / "sources").exists()
    assert not (store.root / "knowledge").exists()
    assert store.commit("nothing to commit") == ""


def test_initialize_forces_sha1_when_default_hash_is_sha256(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GIT_DEFAULT_HASH", "sha256")
    store = LocalKnowledgeGit(tmp_path / "repository", "Test Author", "test@example.com")
    store.initialize()
    source = store.root / "sources" / "source.md"
    source.parent.mkdir()
    source.write_text("source", encoding="utf-8")

    commit_sha = store.commit("add source")

    assert len(commit_sha) == 40
    assert store._run("rev-parse", "--show-object-format").stdout.strip() == "sha1"
