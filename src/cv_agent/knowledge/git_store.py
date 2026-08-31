from __future__ import annotations

from pathlib import Path
import subprocess


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
            self._run("init", "--initial-branch=main")
        self._run("config", "--local", "user.name", self.author_name)
        self._run("config", "--local", "user.email", self.author_email)

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        operation = args[0] if args else "command"
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
            raise self._error(operation, result.stderr)
        return result

    @staticmethod
    def _error(operation: str, stderr: str | None) -> GitStoreError:
        detail = " ".join((stderr or "").split())[:240]
        if detail:
            return GitStoreError(f"Git operation '{operation}' failed: {detail}")
        return GitStoreError(f"Git operation '{operation}' failed")

    def commit(self, message: str) -> str:
        self._run("add", "--all", "--", "sources", "knowledge")
        staged = self._run("diff", "--cached", "--quiet", check=False)
        if staged.returncode == 0:
            return self.head()
        if staged.returncode != 1:
            raise self._error("diff", staged.stderr)

        self._run("commit", "--message", message)
        return self._run("rev-parse", "HEAD").stdout.strip()

    def head(self) -> str:
        result = self._run("rev-parse", "--verify", "HEAD", check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        if result.returncode == 128 and (self.root / ".git").exists():
            return ""
        raise self._error("rev-parse", result.stderr)

    def remotes(self) -> list[str]:
        return [line for line in self._run("remote").stdout.splitlines() if line]

    def tracked_paths(self) -> list[str]:
        output = self._run("ls-files", "-z").stdout
        return sorted(path for path in output.split("\0") if path)
