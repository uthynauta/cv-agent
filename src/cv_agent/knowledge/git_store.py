from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import re
import stat
import subprocess


_SAFE_OPERATIONS = frozenset(
    {
        "add",
        "cat-file",
        "commit",
        "config",
        "diff",
        "diff-tree",
        "for-each-ref",
        "fsck",
        "init",
        "log",
        "merge-base",
        "ls-files",
        "ls-tree",
        "remote",
        "read-tree",
        "rev-list",
        "reset",
        "rev-parse",
        "status",
        "symbolic-ref",
        "update-ref",
    }
)

_ALLOWED_PATH_PREFIXES = ("sources/", "knowledge/")
_REGULAR_FILE_MODES = frozenset({"100644", "100755"})
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class Revision:
    commit: str
    authored_at: str
    subject: str
    changed_paths: tuple[str, ...]


class GitStoreError(RuntimeError):
    """Raised when a local Git store operation cannot be completed."""


class LocalKnowledgeGit:
    def __init__(self, root: str | Path, author_name: str, author_email: str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.author_name = author_name
        self.author_email = author_email

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        git_metadata = self.root / ".git"
        existing = git_metadata.exists() or git_metadata.is_symlink()
        if not existing:
            self._run("init", "--initial-branch=main", "--object-format=sha1")
        self._validate_repository_state(git_metadata)
        if existing:
            self._validate_repository_invariants()
        self._run("config", "--local", "user.name", self.author_name)
        self._run("config", "--local", "user.email", self.author_email)

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        operation = args[0] if args and args[0] in _SAFE_OPERATIONS else "git command"
        command = [
            "git",
            "-C",
            str(self.root),
            "--git-dir",
            str(self.root / ".git"),
            "--work-tree",
            str(self.root),
            "-c",
            f"safe.directory={self.root}",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgSign=false",
            *args,
        ]
        failure: str | None = None
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                env=self._git_environment(),
            )
        except FileNotFoundError:
            failure = f"Git operation '{operation}' failed: git executable not found"
        except subprocess.TimeoutExpired:
            failure = f"Git operation '{operation}' timed out"
        except OSError:
            failure = f"Git operation '{operation}' failed"

        if failure is not None:
            raise GitStoreError(failure) from None

        if check and result.returncode:
            raise self._error(operation)
        return result

    @staticmethod
    def _git_environment() -> dict[str, str]:
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment["GIT_CONFIG_GLOBAL"] = os.devnull
        environment["GIT_CONFIG_NOSYSTEM"] = "1"
        environment["GIT_NO_REPLACE_OBJECTS"] = "1"
        return environment

    @staticmethod
    def _error(operation: str) -> GitStoreError:
        return GitStoreError(f"Git operation '{operation}' failed")

    def _validate_object_format(self) -> None:
        result = self._run("rev-parse", "--show-object-format")
        if result.stdout.strip() != "sha1":
            raise GitStoreError("Git repository object format must be sha1")

    def _validate_repository_state(self, git_metadata: Path) -> None:
        if git_metadata.is_symlink() or not git_metadata.is_dir():
            raise GitStoreError("Git repository metadata must be a local directory")
        self._validate_history_metadata(git_metadata)
        self._validate_object_storage(git_metadata)
        self._validate_safe_configuration()
        self._validate_repository_locality(git_metadata)
        self._validate_object_format()
        self._run("fsck", "--full", "--strict", "--no-reflogs")
        if self.remotes():
            raise GitStoreError("Git repository remotes are not allowed")
        if self._run("for-each-ref", "--format=%(refname)", "refs/replace/").stdout.splitlines():
            raise GitStoreError("Git replacement refs are not allowed")

    @staticmethod
    def _validate_history_metadata(git_metadata: Path) -> None:
        for metadata in (git_metadata / "shallow", git_metadata / "info" / "grafts"):
            if metadata.exists() or metadata.is_symlink():
                raise GitStoreError("Git shallow or graft history metadata is not allowed")

    @staticmethod
    def _validate_object_storage(git_metadata: Path) -> None:
        objects = git_metadata / "objects"
        if objects.is_symlink() or not objects.is_dir():
            raise GitStoreError("Git object storage must be a local directory")
        alternates = objects / "info" / "alternates"
        if alternates.exists() or alternates.is_symlink():
            raise GitStoreError("Git object alternates are not allowed")
        directories = [objects]
        while directories:
            directory = directories.pop()
            try:
                entries = list(directory.iterdir())
            except OSError:
                raise GitStoreError("Git object storage cannot be inspected") from None
            for entry in entries:
                if entry.is_symlink():
                    raise GitStoreError("Git object storage must not contain symlinks")
                try:
                    mode = entry.stat(follow_symlinks=False).st_mode
                except OSError:
                    raise GitStoreError("Git object storage cannot be inspected") from None
                if stat.S_ISDIR(mode):
                    directories.append(entry)
                elif not stat.S_ISREG(mode):
                    raise GitStoreError("Git object storage contains a non-regular entry")

    def _validate_safe_configuration(self) -> None:
        entries = self._run(
            "config", "--includes", "--null", "--show-origin", "--list"
        ).stdout.split("\0")
        for index in range(0, len(entries) - 1, 2):
            origin = entries[index]
            key_value = entries[index + 1]
            key, _, value = key_value.partition("\n")
            key = key.lower()
            if origin == "command line:" and (
                (key == "safe.directory" and value == str(self.root))
                or (key == "core.hookspath" and value == "/dev/null")
                or (key == "commit.gpgsign" and value == "false")
            ):
                continue
            if (
                key in {
                    "core.hookspath",
                    "core.fsmonitor",
                    "core.fsmonitorhook",
                    "core.alternaterefscommand",
                    "core.worktree",
                    "diff.external",
                    "extensions.worktreeconfig",
                }
                or key.startswith("hook.")
                or key.startswith("filter.")
                and key.endswith((".clean", ".smudge", ".process"))
                or key.startswith("diff.")
                and key.endswith(".textconv")
                or key == "include.path"
                or key.startswith("includeif.")
            ):
                raise GitStoreError("Git repository contains executable configuration")

    def _validate_repository_locality(self, git_metadata: Path) -> None:
        if git_metadata.is_symlink() or not git_metadata.is_dir():
            raise GitStoreError("Git repository metadata must be a local directory")

        top_level = Path(self._run("rev-parse", "--show-toplevel").stdout.strip()).resolve()
        git_dir = Path(self._run("rev-parse", "--git-dir").stdout.strip())
        common_dir = Path(self._run("rev-parse", "--git-common-dir").stdout.strip())
        if not git_dir.is_absolute():
            git_dir = self.root / git_dir
        if not common_dir.is_absolute():
            common_dir = self.root / common_dir
        expected_git_dir = git_metadata.resolve()
        if (
            top_level != self.root
            or git_dir.resolve() != expected_git_dir
            or common_dir.resolve() != expected_git_dir
        ):
            raise GitStoreError("Git repository metadata must resolve within the store root")

    def _validate_repository_invariants(self) -> None:
        if self.remotes():
            raise GitStoreError("Git repository remotes are not allowed")

        self._validate_index_entries(self._run("ls-files", "--stage", "-z").stdout)
        commits = self._run("rev-list", "--all").stdout.splitlines()
        for commit in commits:
            self._validate_tree_entries(self._run("ls-tree", "-r", "-z", commit).stdout)

    def _validate_index_entries(self, output: str) -> None:
        for record in output.split("\0"):
            if not record:
                continue
            try:
                metadata, path = record.split("\t", 1)
                mode, _object_id, _stage = metadata.split()
            except ValueError:
                raise GitStoreError("Git index contains invalid entries") from None
            self._validate_file_entry(path, mode, "blob")

    def _validate_tree_entries(self, output: str) -> None:
        for record in output.split("\0"):
            if not record:
                continue
            try:
                metadata, path = record.split("\t", 1)
                mode, object_type, _object_id = metadata.split(" ", 2)
            except ValueError:
                raise GitStoreError("Git tree contains invalid entries") from None
            self._validate_file_entry(path, mode, object_type)

    def _validate_file_entry(
        self, path: str, mode: str, object_type: str, object_id: str | None = None
    ) -> None:
        if (
            not self._is_allowed_path(path)
            or not path.lower().endswith(".md")
            or mode not in _REGULAR_FILE_MODES
            or object_type != "blob"
            or (object_id is not None and _FULL_SHA.fullmatch(object_id) is None)
        ):
            raise GitStoreError("Git repository contains non-Markdown or out-of-scope paths")

    @staticmethod
    def _is_allowed_path(path: str) -> bool:
        if not isinstance(path, str) or "\x00" in path or "\\" in path:
            return False
        if not path.startswith(_ALLOWED_PATH_PREFIXES):
            return False
        parts = path.split("/")
        return all(part not in {"", ".", ".."} for part in parts)

    def _validate_scope_filesystem(self) -> None:
        directories = [self.root / scope for scope in ("sources", "knowledge")]
        while directories:
            directory = directories.pop()
            if directory.is_symlink() or not directory.is_dir():
                raise GitStoreError("Knowledge scopes must contain only local directories")
            try:
                entries = list(directory.iterdir())
            except OSError:
                raise GitStoreError("Knowledge scopes cannot be inspected") from None
            for entry in entries:
                if entry.is_symlink():
                    raise GitStoreError("Knowledge scopes must not contain symlinks")
                try:
                    mode = entry.stat(follow_symlinks=False).st_mode
                except OSError:
                    raise GitStoreError("Knowledge scopes cannot be inspected") from None
                if stat.S_ISDIR(mode):
                    directories.append(entry)
                elif not stat.S_ISREG(mode) or not entry.name.lower().endswith(".md"):
                    raise GitStoreError("Knowledge scopes contain non-Markdown files")

    def commit(self, message: str, *, allow_empty: bool = False) -> str:
        self._validate_repository_state(self.root / ".git")
        self._run("reset", "--")
        for scope in ("sources", "knowledge"):
            scope_path = self.root / scope
            if scope_path.exists() or scope_path.is_symlink():
                continue
            try:
                scope_path.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise GitStoreError("Knowledge scopes cannot be created") from None
        try:
            self._validate_scope_filesystem()
            self._run("add", "--all", "--force", "--", "sources", "knowledge")
            self._validate_index_entries(self._run("ls-files", "--stage", "-z").stdout)
            staged = self._run("diff", "--cached", "--quiet", check=False)
            if staged.returncode == 0 and not allow_empty:
                return self.head()
            if staged.returncode not in (0, 1):
                raise self._error("diff")

            args = ["commit", "--message", message]
            if allow_empty:
                args.insert(1, "--allow-empty")
            self._run(*args)
            return self._run("rev-parse", "HEAD").stdout.strip()
        except GitStoreError:
            self._run("reset", "--", check=False)
            raise

    def head(self) -> str:
        result = self._run("rev-parse", "--verify", "HEAD", check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        if result.returncode == 128 and (self.root / ".git").exists():
            symbolic_head = self._run("symbolic-ref", "--quiet", "HEAD", check=False)
            ref = symbolic_head.stdout.strip()
            if symbolic_head.returncode == 0 and ref.startswith("refs/heads/") and ref != "refs/heads/":
                return ""
        raise self._error("rev-parse")

    def remotes(self) -> list[str]:
        return [line for line in self._run("remote").stdout.splitlines() if line]

    def tracked_paths(self) -> list[str]:
        output = self._run("ls-files", "-z").stdout
        return sorted(path for path in output.split("\0") if path)

    def changed_paths(self, commit: str) -> tuple[str, ...]:
        """Return only Markdown paths changed by one validated commit."""
        if not _FULL_SHA.fullmatch(commit):
            raise GitStoreError("Git changed paths requires a full commit ID")
        verified = self._run("rev-parse", "--verify", f"{commit}^{{commit}}", check=False)
        if verified.returncode or verified.stdout.strip() != commit:
            raise GitStoreError("Git changed paths commit is invalid")
        output = self._run(
            "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-z", commit
        ).stdout
        paths: list[str] = []
        for path in output.split("\0"):
            if not path:
                continue
            if not self._is_allowed_path(path) or not path.lower().endswith(".md"):
                raise GitStoreError("Git commit contains non-Markdown or out-of-scope paths")
            paths.append(path)
        return tuple(sorted(set(paths)))

    def history(self, limit: int = 20) -> list[Revision]:
        """Return bounded local history, newest revision first."""
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise GitStoreError("Git history limit is invalid")
        if limit == 0:
            return []
        count = min(limit, 100)
        listed = self._run("rev-list", f"--max-count={count}", "HEAD", check=False)
        if listed.returncode:
            if listed.returncode == 128 and not self.head():
                return []
            raise self._error("rev-list")
        revisions: list[Revision] = []
        for commit in listed.stdout.splitlines():
            if not _FULL_SHA.fullmatch(commit):
                raise GitStoreError("Git history contains an invalid commit")
            metadata = self._run(
                "log", "-1", "--format=%H%x00%aI%x00%s", commit
            ).stdout.rstrip("\n")
            fields = metadata.split("\0")
            if len(fields) != 3 or fields[0] != commit:
                raise GitStoreError("Git history metadata is invalid")
            revisions.append(Revision(commit, fields[1], fields[2], self.changed_paths(commit)))
        return revisions

    def contains_commit(self, commit: str) -> bool:
        self._require_full_sha(commit, "Git commit ID")
        verified = self._run("rev-parse", "--verify", f"{commit}^{{commit}}", check=False)
        if verified.returncode != 0 or verified.stdout.strip() != commit:
            return False
        head = self.head()
        if not head:
            return False
        reachable = self._run("merge-base", "--is-ancestor", commit, head, check=False)
        if reachable.returncode == 0:
            return True
        if reachable.returncode == 1:
            return False
        raise self._error("merge-base")

    def checkout_tree(self, commit: str, destination: Path) -> None:
        """Materialize a validated commit tree into a new confined directory."""
        self._require_full_sha(commit, "Git checkout commit ID")
        if not self.contains_commit(commit):
            raise GitStoreError("Git checkout commit is invalid")
        entries = self._tree_entries(commit)
        target = self._safe_checkout_destination(destination)
        try:
            for mode, object_id, path in entries:
                blob = self._run("cat-file", "blob", object_id).stdout
                output = target / Path(path)
                output.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(
                    output,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                try:
                    os.fchmod(descriptor, 0o600)
                    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                        descriptor = -1
                        handle.write(blob)
                finally:
                    if descriptor >= 0:
                        os.close(descriptor)
            for scope in (target / "sources", target / "knowledge"):
                scope.mkdir(exist_ok=True)
        except (OSError, UnicodeError):
            raise GitStoreError("Git checkout tree could not be materialized") from None

    def _tree_entries(self, commit: str) -> list[tuple[str, str, str]]:
        output = self._run("ls-tree", "-r", "-z", commit).stdout
        entries: list[tuple[str, str, str]] = []
        for record in output.split("\0"):
            if not record:
                continue
            try:
                metadata, path = record.split("\t", 1)
                mode, object_type, object_id = metadata.split(" ", 2)
            except ValueError:
                raise GitStoreError("Git tree contains invalid entries") from None
            self._validate_file_entry(path, mode, object_type, object_id)
            entries.append((mode, object_id, path))
        return entries

    @staticmethod
    def _require_full_sha(commit: str, label: str) -> None:
        if not isinstance(commit, str) or _FULL_SHA.fullmatch(commit) is None:
            raise GitStoreError(f"{label} requires a full lowercase commit ID")

    def _safe_checkout_destination(self, destination: Path) -> Path:
        if not isinstance(destination, Path):
            destination = Path(destination)
        if not destination.is_absolute():
            raise GitStoreError("Git checkout destination must be absolute")
        base = self.root.parent.absolute()
        target = destination.absolute()
        try:
            relative = target.relative_to(base)
        except ValueError:
            raise GitStoreError("Git checkout destination is outside the data store") from None
        if not relative.parts or target == self.root.absolute():
            raise GitStoreError("Git checkout destination is not isolated")
        current = base
        for part in relative.parts:
            current /= part
            if current.is_symlink() or (current.exists() and not current.is_dir()):
                raise GitStoreError("Git checkout destination uses an unsafe path")
        try:
            target.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise GitStoreError("Git checkout destination must be new") from None
        except OSError:
            raise GitStoreError("Git checkout destination is unavailable") from None
        return target

    def restore_head(self, expected_current: str, prior: str) -> None:
        """Atomically restore a transaction's prior commit and Markdown tree."""
        if not _FULL_SHA.fullmatch(expected_current) or (
            prior and not _FULL_SHA.fullmatch(prior)
        ):
            raise GitStoreError("Git restore requires full commit IDs")
        current = self.head()
        if current != expected_current:
            raise GitStoreError("Git restore current commit does not match expectation")
        if prior:
            verified = self._run("rev-parse", "--verify", f"{prior}^{{commit}}", check=False)
            if verified.returncode or verified.stdout.strip() != prior:
                raise GitStoreError("Git restore prior commit is invalid")
            self._run("update-ref", "refs/heads/main", prior, expected_current)
            self._clear_scope_filesystem()
            # Repository invariants guarantee that every tracked path is in one
            # of these scopes, so resetting the complete index is bounded here.
            self._run("read-tree", "--reset", "-u", prior)
        else:
            self._run("update-ref", "-d", "refs/heads/main", expected_current)
            # With no prior commit, discard the transaction's index entirely.
            # An empty read-tree index references Git's empty-tree sentinel,
            # which may not exist in a repository whose first commit was
            # compensated; removing the index avoids requiring object pruning.
            index = self.root / ".git" / "index"
            if index.exists() or index.is_symlink():
                index.unlink()
            for scope in (self.root / "sources", self.root / "knowledge"):
                if scope.is_symlink() or (scope.exists() and not scope.is_dir()):
                    raise GitStoreError("knowledge scope is not a local directory")
                if scope.exists():
                    for path in sorted(scope.rglob("*"), reverse=True):
                        if path.is_symlink() or (path.exists() and not path.is_file() and not path.is_dir()):
                            raise GitStoreError("knowledge scope contains unsafe entry")
                        if path.is_file():
                            path.unlink()
                        elif path.is_dir():
                            path.rmdir()
        self._validate_scope_filesystem()

    def _clear_scope_filesystem(self) -> None:
        for scope in (self.root / "sources", self.root / "knowledge"):
            if scope.is_symlink() or (scope.exists() and not scope.is_dir()):
                raise GitStoreError("knowledge scope is not a local directory")
            if not scope.exists():
                scope.mkdir(parents=True)
                continue
            for path in sorted(scope.rglob("*"), reverse=True):
                if path.is_symlink():
                    raise GitStoreError("knowledge scope contains a symlink")
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
