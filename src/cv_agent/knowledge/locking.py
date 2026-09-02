from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path
import stat
from typing import IO


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

        parent_fd: int | None = None
        try:
            parent_fd = _open_or_create_directory(self.path.parent)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NONBLOCK", 0)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self.path.name, flags, 0o600, dir_fd=parent_fd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise MutationLockError("mutation lock path uses a symlink") from None
            if exc.errno in {errno.EISDIR, errno.ENXIO}:
                raise MutationLockError("mutation lock must be a regular file") from None
            raise MutationLockError("mutation lock cannot be opened") from None
        except MutationLockError:
            raise
        except Exception:
            raise MutationLockError("mutation lock parent is unsafe") from None
        finally:
            if parent_fd is not None:
                try:
                    os.close(parent_fd)
                except OSError:
                    pass

        handle: IO[str] | None = None
        try:
            mode = os.fstat(descriptor).st_mode
            if not stat.S_ISREG(mode):
                raise MutationLockError("mutation lock must be a regular file")
        except MutationLockError:
            os.close(descriptor)
            raise
        except OSError as exc:
            os.close(descriptor)
            raise MutationLockError("mutation lock cannot be acquired") from None

        try:
            handle = os.fdopen(descriptor, "a+", encoding="utf-8")
        except OSError:
            os.close(descriptor)
            raise MutationLockError("mutation lock cannot be acquired") from None

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise MutationBusyError("another knowledge mutation is running") from exc
        except OSError as exc:
            handle.close()
            if exc.errno in {errno.EAGAIN, errno.EWOULDBLOCK}:
                raise MutationBusyError("another knowledge mutation is running") from None
            raise MutationLockError("mutation lock cannot be acquired") from None

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


def _directory_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _open_or_create_directory(path: Path) -> int:
    absolute = path.absolute()
    if absolute.anchor != "/":
        raise MutationLockError("mutation lock parent is unsafe")
    current = os.open("/", _directory_flags())
    try:
        for component in absolute.parts[1:]:
            if component in {"", ".", ".."}:
                raise MutationLockError("mutation lock parent is unsafe")
            try:
                child = os.open(component, _directory_flags(), dir_fd=current)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=current)
                except FileExistsError:
                    pass
                child = os.open(component, _directory_flags(), dir_fd=current)
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise MutationLockError("mutation lock parent uses a symlink") from None
                raise MutationLockError("mutation lock parent is unsafe") from None
            os.close(current)
            current = child
        return current
    except Exception:
        try:
            os.close(current)
        except OSError:
            pass
        raise
