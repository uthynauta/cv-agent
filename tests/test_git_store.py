from pathlib import Path
import os
import subprocess
import traceback

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


def test_git_commands_set_command_scope_safe_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    commands = []
    real_run = subprocess.run

    def recording_run(command, **kwargs):
        commands.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    store = LocalKnowledgeGit(tmp_path / "repository", "Test Author", "test@example.com")

    store.initialize()

    assert commands
    assert all(
        ["-c", f"safe.directory={store.root}"] == command[3:5]
        for command in commands
    )


def test_commit_does_not_execute_repo_pre_commit_hook(tmp_path: Path):
    store, _ = make_store(tmp_path)
    store.initialize()
    marker = tmp_path / "hook-executed"
    hook = store.root / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\nprintf executed > '{marker}'\n", encoding="utf-8")
    hook.chmod(0o700)
    (store.root / "sources" / "source.md").write_text("source", encoding="utf-8")

    store.commit("commit with hook")

    assert not marker.exists()


def test_commit_rejects_filter_command_before_it_executes(tmp_path: Path):
    store, _ = make_store(tmp_path)
    store.initialize()
    marker = tmp_path / "filter-executed"
    store._run(
        "config",
        "--local",
        "filter.secret.clean",
        f"sh -c \"printf executed > '{marker}'; cat\"",
    )
    (store.root / "sources" / "source.md").write_text("source", encoding="utf-8")

    with pytest.raises(GitStoreError):
        store.commit("commit with filter")

    assert not marker.exists()


def test_initialize_rejects_post_init_execution_configuration(tmp_path: Path):
    store, _ = make_store(tmp_path)
    store.initialize()
    store._run("config", "--local", "core.fsmonitor", "sh -c 'echo executed'")

    with pytest.raises(GitStoreError):
        LocalKnowledgeGit(store.root, "Replacement Author", "replacement@example.com").initialize()


def test_git_environment_cannot_redirect_store_to_an_external_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    external = tmp_path / "external"
    external.mkdir()
    subprocess.run(
        ["git", "-C", str(external), "init", "--initial-branch=main"],
        check=True,
        capture_output=True,
        text=True,
    )
    monkeypatch.setenv("GIT_DIR", str(external / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(external))
    monkeypatch.setenv("GIT_INDEX_FILE", str(external / "index"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(external / "objects"))

    store = LocalKnowledgeGit(tmp_path / "repository", "Test Author", "test@example.com")
    store.initialize()
    source = store.root / "sources" / "source.md"
    source.parent.mkdir()
    source.write_text("source", encoding="utf-8")

    commit_sha = store.commit("add source")

    assert (store.root / ".git").is_dir()
    assert len(commit_sha) == 40
    clean_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    external_head = subprocess.run(
        ["git", "-C", str(external), "rev-parse", "--verify", "HEAD"],
        env=clean_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert external_head.returncode != 0


def test_head_is_empty_before_first_commit(tmp_path: Path):
    store, _ = make_store(tmp_path)
    store.initialize()

    assert store.head() == ""


@pytest.mark.parametrize("filename", ["source.pdf", "source.txt"])
def test_commit_rejects_non_markdown_files_in_allowed_scopes(tmp_path: Path, filename: str):
    store, _ = make_store(tmp_path)
    store.initialize()
    (store.root / "sources" / filename).write_bytes(b"not markdown")

    with pytest.raises(GitStoreError):
        store.commit("reject non-markdown")


def test_commit_rejects_symlink_in_allowed_scopes(tmp_path: Path):
    store, _ = make_store(tmp_path)
    store.initialize()
    target = tmp_path / "outside.md"
    target.write_text("outside", encoding="utf-8")
    (store.root / "knowledge" / "linked.md").symlink_to(target)

    with pytest.raises(GitStoreError):
        store.commit("reject symlink")


def test_initialize_rejects_existing_repository_with_remote_without_mutating_it(tmp_path: Path):
    store = LocalKnowledgeGit(tmp_path / "repository", "Test Author", "test@example.com")
    store.initialize()
    store._run("remote", "add", "origin", "https://example.invalid/repository.git")
    store._run("config", "--local", "user.name", "Original Author")

    with pytest.raises(GitStoreError):
        LocalKnowledgeGit(store.root, "Replacement Author", "replacement@example.com").initialize()

    assert store.remotes() == ["origin"]
    assert store._run("config", "--local", "user.name").stdout.strip() == "Original Author"


def test_initialize_rejects_historical_unrelated_paths(tmp_path: Path):
    store = LocalKnowledgeGit(tmp_path / "repository", "Test Author", "test@example.com")
    store.initialize()
    legacy = store.root / "legacy.md"
    legacy.write_text("legacy", encoding="utf-8")
    store._run("add", "--", "legacy.md")
    store._run("commit", "--message", "legacy path")
    legacy.unlink()
    source = store.root / "sources" / "source.md"
    source.parent.mkdir()
    source.write_text("source", encoding="utf-8")
    store._run("add", "--all", "--", "sources")
    store._run("commit", "--message", "allowed path")

    with pytest.raises(GitStoreError):
        LocalKnowledgeGit(store.root, "Replacement Author", "replacement@example.com").initialize()

    assert store._run("config", "--local", "user.name").stdout.strip() == "Test Author"


def test_initialize_rejects_historical_shared_tree_alias_outside_allowed_scopes(tmp_path: Path):
    store = LocalKnowledgeGit(tmp_path / "repository", "Test Author", "test@example.com")
    store.initialize()
    allowed = store.root / "knowledge" / "shared.md"
    outside = store.root / "zarchive" / "shared.md"
    allowed.parent.mkdir()
    outside.parent.mkdir()
    allowed.write_text("shared", encoding="utf-8")
    outside.write_text("shared", encoding="utf-8")
    store._run("add", "--all")
    store._run("commit", "--message", "shared tree alias")
    outside.unlink()
    store._run("add", "--all")
    store._run("commit", "--message", "remove alias")

    with pytest.raises(GitStoreError):
        LocalKnowledgeGit(store.root, "Test Author", "test@example.com").initialize()


def test_initialize_existing_allowed_repository_preserves_head_and_paths(tmp_path: Path):
    store, _ = make_store(tmp_path)
    store.initialize()
    source = store.root / "sources" / "source.md"
    knowledge = store.root / "knowledge" / "page.md"
    source.write_text("source", encoding="utf-8")
    knowledge.write_text("page", encoding="utf-8")
    commit_sha = store.commit("add allowed content")
    tracked = store.tracked_paths()

    restarted = LocalKnowledgeGit(store.root, "Test Author", "test@example.com")
    restarted.initialize()

    assert restarted.head() == commit_sha
    assert restarted.tracked_paths() == tracked


@pytest.mark.parametrize("root_name", ["sources", "knowledge"])
def test_initialize_rejects_root_blob_named_allowed_scope(tmp_path: Path, root_name: str):
    store = LocalKnowledgeGit(tmp_path / "repository", "Test Author", "test@example.com")
    store.initialize()
    (store.root / root_name).write_text("root blob", encoding="utf-8")
    store._run("add", "--", root_name)
    store._run("commit", "--message", "invalid root path")

    with pytest.raises(GitStoreError):
        LocalKnowledgeGit(store.root, "Test Author", "test@example.com").initialize()


@pytest.mark.parametrize("metadata_kind", ["symlink", "gitfile"])
def test_initialize_rejects_repository_metadata_outside_root(tmp_path: Path, metadata_kind: str):
    external = tmp_path / "external"
    external.mkdir()
    subprocess.run(
        ["git", "-C", str(external), "init", "--initial-branch=main"],
        check=True,
        capture_output=True,
        text=True,
    )
    root = tmp_path / "repository"
    root.mkdir()
    git_metadata = root / ".git"
    if metadata_kind == "symlink":
        git_metadata.symlink_to(external / ".git", target_is_directory=True)
    else:
        git_metadata.write_text(f"gitdir: {external / '.git'}\n", encoding="utf-8")

    with pytest.raises(GitStoreError):
        LocalKnowledgeGit(root, "Test Author", "test@example.com").initialize()

    assert not (root / "config").exists()


def test_commit_stages_sources_but_not_documents(tmp_path: Path):
    store, data_root = make_store(tmp_path)
    store.initialize()
    (store.root / "sources" / "source.md").write_text("source", encoding="utf-8")
    (data_root / "documents" / "source.pdf").write_bytes(b"pdf")

    commit_sha = store.commit("add source")

    assert len(commit_sha) == 40
    assert store.tracked_paths() == ["sources/source.md"]
    assert "documents/source.pdf" not in store.tracked_paths()


def test_commit_forces_ignored_files_in_allowed_scopes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store, _ = make_store(tmp_path)
    store.initialize()
    (store.root / ".gitignore").write_text("sources/root-ignored.md\n", encoding="utf-8")
    (store.root / ".git" / "info" / "exclude").write_text("knowledge/info-ignored.md\n", encoding="utf-8")
    global_home = tmp_path / "global-home"
    global_config = global_home / ".config" / "git"
    global_config.mkdir(parents=True)
    global_ignore = global_config / "ignore"
    global_ignore.write_text("sources/global-ignored.md\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(global_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(global_home / ".config"))
    source_root = store.root / "sources" / "root-ignored.md"
    source_global = store.root / "sources" / "global-ignored.md"
    knowledge_info = store.root / "knowledge" / "info-ignored.md"
    source_root.parent.mkdir(exist_ok=True)
    knowledge_info.parent.mkdir(exist_ok=True)
    source_root.write_text("root", encoding="utf-8")
    source_global.write_text("global", encoding="utf-8")
    knowledge_info.write_text("info", encoding="utf-8")

    store.commit("force ignored knowledge")

    assert store.tracked_paths() == [
        "knowledge/info-ignored.md",
        "sources/global-ignored.md",
        "sources/root-ignored.md",
    ]


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


@pytest.mark.parametrize("failure", [
    subprocess.TimeoutExpired("SECRET_TIMEOUT_ARGUMENT", 30, output="SECRET_TIMEOUT_OUTPUT"),
    FileNotFoundError("SECRET_MISSING_EXECUTABLE"),
    OSError("SECRET_OS_ERROR"),
])
def test_git_failure_exception_context_and_traceback_do_not_retain_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: BaseException
):
    store = LocalKnowledgeGit(tmp_path / "repository", "Test Author", "test@example.com")
    secret = "sensitive-secret-document-content"

    def failed_run(command, **kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", failed_run)

    with pytest.raises(GitStoreError) as raised:
        store._run(secret, secret)

    error = raised.value
    rendered = "".join(traceback.format_exception(error))
    assert error.__cause__ is None
    assert error.__context__ is None
    assert secret not in str(error)
    assert secret not in rendered


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
