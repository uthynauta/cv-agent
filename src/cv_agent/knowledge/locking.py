from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path
import stat
from typing import IO

from cv_agent.knowledge.repository import resolve_directory_path


class MutationLockError(RuntimeError):
    """Raised when the mutation lock cannot be safely opened or released."""


class MutationBusyError(MutationLockError):
    """Raised when another process already owns the mutation lock."""


class MutationLock:
    """An exclusive, non-blocking lock backed by a local regular file.

    A lock instance may be reused after its context exits. Re-entering the same
    instance while it owns the lock raises ``MutationBusyError`` and leaves the
    outer lock untouched.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._handle: IO[str] | None = None

    def __enter__(self) -> "MutationLock":
        if self._handle is not None:
            raise MutationBusyError("mutation lock is already held")

        if "\x00" in str(self.path) or ".." in self.path.parts:
            raise MutationLockError("mutation lock path is unsafe")
        if not self.path.name or self.path.name in {".", ".."}:
            raise MutationLockError("mutation lock path is unsafe")

        try:
            parent = resolve_directory_path(self.path.parent, create=True)
        except (OSError, ValueError):
            raise MutationLockError("mutation lock parent is unsafe") from None
        lock_path = parent / self.path.name

        try:
            existing = os.lstat(lock_path)
        except FileNotFoundError:
            existing = None
        except OSError:
            raise MutationLockError("mutation lock path cannot be inspected") from None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            raise MutationLockError("mutation lock must be a regular file")

        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise MutationBusyError("another knowledge mutation is running") from None
            raise MutationLockError("mutation lock cannot be opened") from None

        handle: IO[str] | None = None
        try:
            mode = os.fstat(descriptor).st_mode
            if not stat.S_ISREG(mode):
                raise MutationLockError("mutation lock must be a regular file")
            handle = os.fdopen(descriptor, "a+", encoding="utf-8")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            if handle is not None:
                handle.close()
            else:
                os.close(descriptor)
            raise MutationBusyError("another knowledge mutation is running") from exc
        except OSError as exc:
            if handle is not None:
                handle.close()
            else:
                os.close(descriptor)
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise MutationBusyError("another knowledge mutation is running") from None
            raise MutationLockError("mutation lock cannot be acquired") from None
        except MutationLockError:
            if handle is not None:
                handle.close()
            else:
                os.close(descriptor)
            raise

        self._handle = handle
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        handle = self._handle
        self._handle = None
        if handle is None:
            return False

        failure: MutationLockError | None = None
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            failure = MutationLockError("mutation lock cannot be released")
        finally:
            try:
                handle.close()
            except OSError:
                if failure is None:
                    failure = MutationLockError("mutation lock cannot be closed")
        if failure is not None:
            raise failure
        return False
