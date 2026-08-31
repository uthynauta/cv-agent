from __future__ import annotations

from pathlib import Path
import subprocess


_SAFE_OPERATIONS = frozenset(
    {
        "add",
        "commit",
        "config",
        "diff",
        "init",
        "ls-files",
        "remote",
        "reset",
        "rev-parse",
        "status",
        "symbolic-ref",
    }
)


class GitStoreError(RuntimeError):
    """Raised when a local Git store operation cannot be completed."""


class LocalKnowledgeGit:
    def __init__(self, root: str | Path, author_name: str, author_email: str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.author_name = author_name
        self.author_email = author_email

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").exists():
            self._run("init", "--initial-branch=main", "--object-format=sha1")
        self._validate_object_format()
        self._run("config", "--local", "user.name", self.author_name)
        self._run("config", "--local", "user.email", self.author_email)

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        operation = args[0] if args and args[0] in _SAFE_OPERATIONS else "git command"
        command = ["git", "-C", str(self.root), *args]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError as exc:
            raise GitStoreError(f"Git operation '{operation}' failed: git executable not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitStoreError(f"Git operation '{operation}' timed out") from exc
        except OSError as exc:
            raise GitStoreError(f"Git operation '{operation}' failed") from exc

        if check and result.returncode:
            raise self._error(operation)
        return result

    @staticmethod
    def _error(operation: str) -> GitStoreError:
        return GitStoreError(f"Git operation '{operation}' failed")

    def _validate_object_format(self) -> None:
        result = self._run("rev-parse", "--show-object-format")
        if result.stdout.strip() != "sha1":
            raise GitStoreError("Git repository object format must be sha1")

    def commit(self, message: str) -> str:
        for scope in ("sources", "knowledge"):
            (self.root / scope).mkdir(parents=True, exist_ok=True)
        self._run("reset", "--")
        self._run("add", "--all", "--", "sources", "knowledge")
        staged = self._run("diff", "--cached", "--quiet", check=False)
        if staged.returncode == 0:
            return self.head()
        if staged.returncode != 1:
            raise self._error("diff")

        self._run("commit", "--message", message)
        return self._run("rev-parse", "HEAD").stdout.strip()

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
