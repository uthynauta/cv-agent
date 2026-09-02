from __future__ import annotations

from multiprocessing import get_context
from pathlib import Path
from threading import Barrier, Thread
import os
import time

import pytest

import cv_agent.knowledge.locking as locking_module
from cv_agent.knowledge.locking import MutationBusyError, MutationLock


def _hold_lock(path: str, ready, release) -> None:
    with MutationLock(Path(path)):
        ready.set()
        release.wait(10)


def test_second_lock_fails_without_waiting(tmp_path: Path):
    path = tmp_path / "locks" / "mutation.lock"
    first = MutationLock(path)
    second = MutationLock(path)

    with first:
        started = time.monotonic()
        with pytest.raises(MutationBusyError, match="mutation"):
            with second:
                pass
        assert time.monotonic() - started < 1


def test_lock_process_contention_is_nonblocking(tmp_path: Path):
    path = tmp_path / "locks" / "mutation.lock"
    context = get_context("fork")
    ready = context.Event()
    release = context.Event()
    process = context.Process(target=_hold_lock, args=(str(path), ready, release))
    process.start()
    try:
        assert ready.wait(5)
        started = time.monotonic()
        with pytest.raises(MutationBusyError):
            with MutationLock(path):
                pass
        assert time.monotonic() - started < 1
    finally:
        release.set()
        process.join(5)
        assert process.exitcode == 0


def test_lock_thread_contention_is_nonblocking(tmp_path: Path):
    path = tmp_path / "locks" / "mutation.lock"
    barrier = Barrier(2)
    failures: list[Exception] = []

    def hold() -> None:
        try:
            with MutationLock(path):
                barrier.wait()
                time.sleep(0.2)
        except Exception as exc:  # pragma: no cover - makes thread errors visible
            failures.append(exc)

    thread = Thread(target=hold)
    thread.start()
    barrier.wait()
    try:
        with pytest.raises(MutationBusyError):
            with MutationLock(path):
                pass
    finally:
        thread.join(5)
    assert not failures


def test_same_instance_reentry_preserves_outer_lock(tmp_path: Path):
    path = tmp_path / "locks" / "mutation.lock"
    lock = MutationLock(path)
    with lock:
        with pytest.raises(MutationBusyError):
            lock.__enter__()
        assert lock._handle is not None
    assert lock._handle is None

    with MutationLock(path):
        pass


def test_lock_can_be_reused_after_contention(tmp_path: Path):
    path = tmp_path / "locks" / "mutation.lock"
    first = MutationLock(path)
    second = MutationLock(path)
    with first:
        with pytest.raises(MutationBusyError):
            second.__enter__()
        assert second._handle is None
    with second:
        assert second._handle is not None
    assert second._handle is None


def test_lock_clears_handle_after_acquisition_error(tmp_path: Path, monkeypatch):
    path = tmp_path / "locks" / "mutation.lock"
    lock = MutationLock(path)
    original_flock = locking_module.fcntl.flock

    def fail_once(fd: int, operation: int) -> None:
        monkeypatch.setattr(locking_module.fcntl, "flock", original_flock)
        raise OSError("injected failure")

    monkeypatch.setattr(locking_module.fcntl, "flock", fail_once)
    with pytest.raises(locking_module.MutationLockError):
        lock.__enter__()
    assert lock._handle is None

    with lock:
        pass


@pytest.mark.parametrize("target_kind", ["symlink", "fifo", "directory"])
def test_lock_rejects_unsafe_target(tmp_path: Path, target_kind: str):
    path = tmp_path / "locks" / "mutation.lock"
    path.parent.mkdir()
    if target_kind == "symlink":
        target = tmp_path / "outside.lock"
        target.write_text("sentinel", encoding="utf-8")
        path.symlink_to(target)
    elif target_kind == "fifo":
        os.mkfifo(path)
    else:
        path.mkdir()

    with pytest.raises((ValueError, RuntimeError), match="lock|regular|special|symlink"):
        with MutationLock(path):
            pass


def test_lock_rejects_symlinked_parent(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "locks").symlink_to(outside, target_is_directory=True)

    with pytest.raises((ValueError, RuntimeError), match="lock|symlink"):
        with MutationLock(tmp_path / "locks" / "mutation.lock"):
            pass


def test_lock_final_open_survives_parent_ancestor_swap(tmp_path: Path, monkeypatch):
    locks = tmp_path / "locks"
    outside = tmp_path / "outside"
    locks.mkdir()
    outside.mkdir()
    path = locks / "mutation.lock"
    original_open = os.open
    swapped = False

    def race_open(name, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if name == path.name and dir_fd is not None and not swapped:
            locks.rename(tmp_path / "locks.real")
            locks.symlink_to(outside, target_is_directory=True)
            swapped = True
        if mode == 0o777:
            return original_open(name, flags, dir_fd=dir_fd)
        return original_open(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(locking_module.os, "open", race_open)
    with MutationLock(path):
        pass

    assert (tmp_path / "locks.real" / "mutation.lock").is_file()
    assert not (outside / "mutation.lock").exists()
