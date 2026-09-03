from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import tarfile
import io
import os
from typing import BinaryIO
from typing import Literal
from uuid import uuid4
import yaml

from cv_agent.config import Settings
from cv_agent.knowledge.git_store import GitStoreError, GitStoreTooLargeError, LocalKnowledgeGit
from cv_agent.knowledge.storage import DataPaths
from cv_agent.knowledge.frontmatter import load_frontmatter
from cv_agent.knowledge.locking import MutationBusyError, MutationLock


BackupKind = Literal["knowledge", "full"]
_NAME = re.compile(r"^(knowledge|full)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}\.(bundle|tar\.gz)$")


def _managed_name(name: object) -> tuple[BackupKind, str] | None:
    if not isinstance(name, str):
        return None
    match = _NAME.fullmatch(name)
    if match is None:
        return None
    kind = match.group(1)
    suffix = match.group(2)
    if (kind == "knowledge" and suffix != "bundle") or (kind == "full" and suffix != "tar.gz"):
        return None
    return kind, suffix


@dataclass(frozen=True)
class BackupRecord:
    name: str
    kind: BackupKind
    path: Path
    created_at: str
    size_bytes: int
    sha256: str


class BackupError(RuntimeError):
    """Base class for bounded, user-safe backup failures."""


class BackupNotFoundError(BackupError):
    pass


class BackupTooLargeError(BackupError):
    pass


class BackupUnavailableError(BackupError):
    """Raised when no committed knowledge snapshot exists to export."""
    pass


class _LimitedWriter:
    def __init__(self, handle: BinaryIO, limit: int) -> None:
        self.handle = handle
        self.limit = limit
        self.total = 0

    def write(self, data: bytes) -> int:
        if self.total + len(data) > self.limit:
            raise BackupTooLargeError("backup exceeds configured size limit")
        written = self.handle.write(data)
        self.total += written
        return written

    def flush(self) -> None:
        self.handle.flush()


class BackupService:
    def __init__(
        self,
        paths: DataPaths,
        git: LocalKnowledgeGit,
        settings: Settings,
        *,
        retention_count: int | None = None,
    ) -> None:
        self.paths = paths
        self.git = git
        self.settings = settings
        self.max_bytes = settings.admin_backup_max_bytes
        self.retention_count = retention_count if retention_count is not None else settings.backup_retention_count

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _digest(path: Path, limit: int | None = None) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
                if limit is not None and size > limit:
                    raise BackupTooLargeError("backup exceeds configured size limit")
        return size, digest.hexdigest()

    def _new_path(self, kind: BackupKind, suffix: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return self.paths.backups / f"{kind}-{stamp}-{uuid4().hex[:16]}.{suffix}"

    def _publish(self, source: Path, destination: Path) -> None:
        backups_fd = -1
        try:
            backups_fd = os.open(
                self.paths.backups,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            os.rename(source, destination.name, dst_dir_fd=backups_fd)
        finally:
            if backups_fd >= 0:
                os.close(backups_fd)

    def _record(self, path: Path, kind: BackupKind, created_at: str | None = None) -> BackupRecord:
        size, digest = self._digest(path)
        return BackupRecord(path.name, kind, path, created_at or self._now(), size, digest)

    @staticmethod
    def _record_values(path: Path, kind: BackupKind, size: int, digest: str, created_at: str) -> BackupRecord:
        return BackupRecord(path.name, kind, path, created_at, size, digest)

    @staticmethod
    def _digest_handle(handle: BinaryIO, limit: int | None = None) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        while True:
            read_size = 1024 * 1024
            if limit is not None:
                read_size = min(read_size, limit - size + 1)
            chunk = handle.read(max(1, read_size))
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
            if limit is not None and size > limit:
                raise BackupTooLargeError("backup exceeds configured size limit")
        handle.seek(0)
        return size, digest.hexdigest()

    def _digest_fd(self, descriptor: int) -> tuple[int, str]:
        with os.fdopen(os.dup(descriptor), "rb") as handle:
            size, digest = self._digest_handle(handle, self.max_bytes)
        return size, digest

    def _enforce_size(self, path: Path) -> None:
        if path.stat().st_size > self.max_bytes:
            path.unlink(missing_ok=True)
            raise BackupTooLargeError("backup exceeds configured size limit")

    def create_knowledge_bundle(self) -> BackupRecord:
        with MutationLock(self.paths.locks / "mutation.lock"):
            return self._create_knowledge_bundle_locked()

    def _create_knowledge_bundle_locked(self) -> BackupRecord:
        try:
            if not self.git.head():
                raise BackupUnavailableError("knowledge backup is unavailable before the first commit")
        except BackupUnavailableError:
            raise
        except GitStoreError as exc:
            raise BackupError("knowledge backup could not inspect repository state") from exc
        operation = self.paths.staging / f"backup-{uuid4().hex}"
        operation.mkdir(mode=0o700)
        path = operation / "knowledge.bundle"
        try:
            self.git.bundle_create(path, max_bytes=self.max_bytes)
            self._enforce_size(path)
            published = self._new_path("knowledge", "bundle")
            size, digest = self._digest(path)
            record = self._record_values(published, "knowledge", size, digest, self._now())
            self._publish(path, published)
            try:
                self._prune_unlocked()
            except (BackupError, OSError):
                pass
            return record
        except (BackupTooLargeError, GitStoreTooLargeError) as exc:
            if isinstance(exc, GitStoreTooLargeError):
                raise BackupTooLargeError("backup exceeds configured size limit") from exc
            raise
        except (GitStoreError, OSError) as exc:
            raise BackupError("knowledge backup could not be created") from exc
        finally:
            import shutil
            shutil.rmtree(operation, ignore_errors=True)

    def _current_originals(self, budget: int = 0) -> list[tuple[str, bytes, str]]:
        result: list[tuple[str, bytes, str]] = []
        expected: dict[str, str] = {}
        aggregate = budget
        root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            sources_fd = os.open(self.paths.sources, root_flags)
            documents_fd = os.open(self.paths.documents, root_flags)
            for name in sorted(os.listdir(sources_fd)):
                if not name.endswith(".md"):
                    continue
                descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=sources_fd)
                try:
                    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                        continue
                    with os.fdopen(descriptor, "rb") as handle:
                        descriptor = -1
                        source_bytes = handle.read(self.max_bytes + 1)
                        if len(source_bytes) > self.max_bytes:
                            raise BackupTooLargeError("backup exceeds configured size limit")
                        source = source_bytes.decode("utf-8")
                        metadata, _ = load_frontmatter(source)
                finally:
                    if descriptor >= 0:
                        os.close(descriptor)
                document_id = metadata.get("document_id")
                digest = metadata.get("content_sha256")
                filename = metadata.get("original_filename")
                media_type = metadata.get("media_type")
                suffix = {"application/pdf": ".pdf", "application/x-tex": ".tex", "text/markdown": ".md"}.get(media_type)
                if isinstance(document_id, str) and isinstance(digest, str) and isinstance(filename, str) and suffix:
                    expected[f"{document_id}{suffix}"] = digest
            for name in sorted(os.listdir(documents_fd)):
                if name == "quarantine":
                    continue
                descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=documents_fd)
                try:
                    if not stat.S_ISREG(os.fstat(descriptor).st_mode) or name not in expected:
                        continue
                    with os.fdopen(descriptor, "rb") as handle:
                        descriptor = -1
                        remaining = self.max_bytes - aggregate
                        if remaining < 0:
                            raise BackupTooLargeError("backup exceeds configured size limit")
                        data = handle.read(remaining + 1)
                    if len(data) > remaining:
                        raise BackupTooLargeError("backup exceeds configured size limit")
                    aggregate += len(data)
                    digest = hashlib.sha256(data).hexdigest()
                    if digest == expected[name]:
                        result.append((f"documents/{name}", data, digest))
                finally:
                    if descriptor >= 0:
                        os.close(descriptor)
        except (OSError, UnicodeError, ValueError, TypeError, yaml.YAMLError) as exc:
            raise BackupError("backup source metadata is unavailable") from exc
        finally:
            for fd in (locals().get("sources_fd", -1), locals().get("documents_fd", -1)):
                if fd >= 0:
                    os.close(fd)
        return result

    def create_full_backup(self) -> BackupRecord:
        try:
            with MutationLock(self.paths.locks / "mutation.lock"):
                return self._create_full_backup_locked()
        except MutationBusyError:
            raise

    def _create_full_backup_locked(self) -> BackupRecord:
        try:
            if not self.git.head():
                raise BackupUnavailableError("full backup is unavailable before the first commit")
        except BackupUnavailableError:
            raise
        except GitStoreError as exc:
            raise BackupError("full backup could not inspect repository state") from exc
        created_at = self._now()
        import shutil
        operation = self.paths.staging / f"backup-{uuid4().hex}"
        operation.mkdir(mode=0o700)
        bundle = operation / "knowledge.bundle"
        archive_path = operation / "backup.tar.gz"
        files: dict[str, dict[str, int | str]] = {}
        try:
            self.git.bundle_create(bundle, max_bytes=self.max_bytes)
            bundle_size, bundle_hash = self._digest(bundle)
            files["knowledge.bundle"] = {"sha256": bundle_hash, "size": bundle_size}
            originals = []
            for member, data, expected_digest in self._current_originals(bundle_size):
                copy = operation / Path(member)
                copy.parent.mkdir(parents=True, exist_ok=True)
                self._snapshot(
                    data,
                    copy,
                    expected_digest=expected_digest,
                    budget=bundle_size + sum(item[1].stat().st_size for item in originals),
                    max_bytes=self.max_bytes,
                )
                originals.append((member, copy, expected_digest))
            for member, source, expected_digest in originals:
                size, digest = self._digest(source, self.max_bytes)
                if digest != expected_digest:
                    raise BackupError("document changed while backup was being created")
                files[member] = {"sha256": digest, "size": size}
            manifest = {
                "format_version": 1,
                "created_at": created_at,
                "active_commit": self.git.head(),
                "agent_model": self.settings.agent_model_name,
                "files": files,
            }
            with archive_path.open("xb") as raw_archive:
                limited = _LimitedWriter(raw_archive, self.max_bytes)
                archive = tarfile.open(fileobj=limited, mode="w:gz")
                try:
                    self._add_file(archive, "knowledge.bundle", bundle)
                    for member, source, _expected_digest in originals:
                        self._add_file(archive, member, source)
                    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
                    info = tarfile.TarInfo("manifest.json")
                    info.size = len(payload)
                    info.mode = 0o600
                    archive.addfile(info, io.BytesIO(payload))
                finally:
                    archive.close()
            self._enforce_size(archive_path)
            published = self._new_path("full", "tar.gz")
            size, digest = self._digest(archive_path)
            record = self._record_values(published, "full", size, digest, created_at)
            self._publish(archive_path, published)
            try:
                self._prune_unlocked()
            except (BackupError, OSError):
                pass
            return record
        except (BackupTooLargeError, GitStoreTooLargeError) as exc:
            if isinstance(exc, GitStoreTooLargeError):
                raise BackupTooLargeError("backup exceeds configured size limit") from exc
            bundle.unlink(missing_ok=True)
            raise
        except (GitStoreError, OSError, tarfile.TarError, ValueError) as exc:
            raise BackupError("full backup could not be created") from exc
        finally:
            shutil.rmtree(operation, ignore_errors=True)

    @staticmethod
    def _snapshot(source: bytes, destination: Path, *, expected_digest: str, budget: int = 0, max_bytes: int | None = None) -> None:
        digest = hashlib.sha256(source).hexdigest()
        if digest != expected_digest:
            raise BackupError("document changed while backup was being created")
        if max_bytes is not None and budget + len(source) > max_bytes:
            raise BackupTooLargeError("backup exceeds configured size limit")
        with destination.open("xb") as dst:
            dst.write(source)
            dst.flush()
            os.fsync(dst.fileno())

    @staticmethod
    def _add_file(archive: tarfile.TarFile, member: str, source: Path) -> None:
        info = archive.gettarinfo(str(source), arcname=member)
        info.mode = 0o600
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        with source.open("rb") as handle:
            archive.addfile(info, handle)

    def list(self) -> list[BackupRecord]:
        records: list[BackupRecord] = []
        backups_fd = -1
        try:
            backups_fd = os.open(self.paths.backups, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
            for name in os.listdir(backups_fd):
                parsed = _managed_name(name)
                if parsed is None:
                    continue
                descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=backups_fd)
                try:
                    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                        continue
                    size, digest = self._digest_fd(descriptor)
                finally:
                    os.close(descriptor)
                if size > self.max_bytes:
                    raise BackupTooLargeError("backup exceeds configured size limit")
                kind = parsed[0]
                records.append(self._record_values(self.paths.backups / name, kind, size, digest, self._now()))
        except BackupError:
            raise
        except OSError as exc:
            raise BackupError("backup listing unavailable") from exc
        finally:
            if backups_fd >= 0:
                os.close(backups_fd)
        return sorted(records, key=lambda record: record.name, reverse=True)

    def resolve_download(self, name: str) -> BackupRecord:
        parsed = _managed_name(name)
        if parsed is None:
            raise BackupNotFoundError("backup was not found")
        backups_fd = -1
        descriptor = -1
        try:
            backups_fd = os.open(self.paths.backups, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
            descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=backups_fd)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise BackupNotFoundError("backup was not found")
            size, digest = self._digest_fd(descriptor)
            return self._record_values(self.paths.backups / name, parsed[0], size, digest, self._now())
        except BackupError:
            raise
        except OSError as exc:
            raise BackupNotFoundError("backup was not found") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if backups_fd >= 0:
                os.close(backups_fd)

    def open_download(self, name: str) -> tuple[BackupRecord, BinaryIO]:
        parsed = _managed_name(name)
        if parsed is None:
            raise BackupNotFoundError("backup was not found")
        backups_fd = -1
        descriptor = -1
        try:
            backups_fd = os.open(self.paths.backups, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
            descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=backups_fd)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise BackupNotFoundError("backup was not found")
            size, digest = self._digest_fd(descriptor)
            handle = os.fdopen(descriptor, "rb")
            descriptor = -1
            return self._record_values(self.paths.backups / name, parsed[0], size, digest, self._now()), handle
        except BackupError:
            raise
        except (OSError, ValueError) as exc:
            raise BackupNotFoundError("backup was not found") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if backups_fd >= 0:
                os.close(backups_fd)

    def delete(self, name: str, confirmed: bool) -> None:
        if not confirmed:
            raise BackupError("confirmation required")
        record = self.resolve_download(name)
        backups_fd = -1
        try:
            backups_fd = os.open(
                self.paths.backups,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            os.unlink(record.name, dir_fd=backups_fd)
        except OSError as exc:
            raise BackupError("backup could not be deleted") from exc
        finally:
            if backups_fd >= 0:
                os.close(backups_fd)

    def prune(self) -> list[str]:
        with MutationLock(self.paths.locks / "mutation.lock"):
            return self._prune_unlocked()

    def _prune_unlocked(self) -> list[str]:
        records = self.list()
        removed: list[str] = []
        for record in records[self.retention_count :]:
            try:
                record.path.unlink()
                removed.append(record.name)
            except OSError:
                continue
        return removed
