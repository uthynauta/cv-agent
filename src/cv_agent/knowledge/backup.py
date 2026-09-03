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

from cv_agent.config import Settings
from cv_agent.knowledge.git_store import GitStoreError, LocalKnowledgeGit
from cv_agent.knowledge.storage import DataPaths
from cv_agent.knowledge.frontmatter import load_frontmatter
from cv_agent.knowledge.locking import MutationBusyError, MutationLock


BackupKind = Literal["knowledge", "full"]
_NAME = re.compile(r"^(knowledge|full)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}\.(bundle|tar\.gz)$")


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
    def _digest(path: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        return size, digest.hexdigest()

    def _new_path(self, kind: BackupKind, suffix: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return self.paths.backups / f"{kind}-{stamp}-{uuid4().hex[:16]}.{suffix}"

    def _record(self, path: Path, kind: BackupKind, created_at: str | None = None) -> BackupRecord:
        size, digest = self._digest(path)
        return BackupRecord(path.name, kind, path, created_at or self._now(), size, digest)

    def _enforce_size(self, path: Path) -> None:
        if path.stat().st_size > self.max_bytes:
            path.unlink(missing_ok=True)
            raise BackupTooLargeError("backup exceeds configured size limit")

    def create_knowledge_bundle(self) -> BackupRecord:
        with MutationLock(self.paths.locks / "mutation.lock"):
            return self._create_knowledge_bundle_locked()

    def _create_knowledge_bundle_locked(self) -> BackupRecord:
        operation = self.paths.staging / f"backup-{uuid4().hex}"
        operation.mkdir(mode=0o700)
        path = operation / "knowledge.bundle"
        try:
            self.git.bundle_create(path)
            self._enforce_size(path)
            published = self._new_path("knowledge", "bundle")
            path.replace(published)
            record = self._record(published, "knowledge")
            self._prune_unlocked()
            return record
        except BackupTooLargeError:
            raise
        except (GitStoreError, OSError) as exc:
            raise BackupError("knowledge backup could not be created") from exc
        finally:
            import shutil
            shutil.rmtree(operation, ignore_errors=True)

    def _current_originals(self) -> list[tuple[str, Path]]:
        result: list[tuple[str, Path]] = []
        if not self.paths.documents.is_dir() or self.paths.documents.is_symlink():
            return result
        expected: dict[str, str] = {}
        try:
            for source in sorted(self.paths.sources.glob("*.md")):
                if source.is_symlink() or not source.is_file():
                    continue
                metadata, _ = load_frontmatter(source.read_text(encoding="utf-8"))
                document_id = metadata.get("document_id")
                digest = metadata.get("content_sha256")
                filename = metadata.get("original_filename")
                media_type = metadata.get("media_type")
                suffix = {"application/pdf": ".pdf", "application/x-tex": ".tex", "text/markdown": ".md"}.get(media_type)
                if isinstance(document_id, str) and isinstance(digest, str) and isinstance(filename, str) and suffix:
                    expected[f"{document_id}{suffix}"] = digest
        except (OSError, UnicodeError, ValueError, TypeError):
            return result
        for path in sorted(self.paths.documents.iterdir()):
            if path.name == "quarantine" or path.is_symlink() or not path.is_file():
                continue
            if path.name not in expected:
                continue
            try:
                if self._digest(path)[1] != expected[path.name]:
                    continue
            except OSError:
                continue
            result.append((f"documents/{path.name}", path))
        return result

    def create_full_backup(self) -> BackupRecord:
        try:
            with MutationLock(self.paths.locks / "mutation.lock"):
                return self._create_full_backup_locked()
        except MutationBusyError:
            raise

    def _create_full_backup_locked(self) -> BackupRecord:
        created_at = self._now()
        import shutil
        operation = self.paths.staging / f"backup-{uuid4().hex}"
        operation.mkdir(mode=0o700)
        bundle = operation / "knowledge.bundle"
        archive_path = operation / "backup.tar.gz"
        files: dict[str, dict[str, int | str]] = {}
        try:
            self.git.bundle_create(bundle)
            bundle_size, bundle_hash = self._digest(bundle)
            files["knowledge.bundle"] = {"sha256": bundle_hash, "size": bundle_size}
            originals = []
            for member, source in self._current_originals():
                copy = operation / Path(member)
                copy.parent.mkdir(parents=True, exist_ok=True)
                self._snapshot(source, copy)
                originals.append((member, copy))
            for member, source in originals:
                size, digest = self._digest(source)
                files[member] = {"sha256": digest, "size": size}
            manifest = {
                "format_version": 1,
                "created_at": created_at,
                "active_commit": self.git.head(),
                "agent_model": self.settings.agent_model_name,
                "files": files,
            }
            with tarfile.open(archive_path, "w:gz") as archive:
                self._add_file(archive, "knowledge.bundle", bundle)
                for member, source in originals:
                    self._add_file(archive, member, source)
                payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
                info = tarfile.TarInfo("manifest.json")
                info.size = len(payload)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(payload))
            self._enforce_size(archive_path)
            published = self._new_path("full", "tar.gz")
            archive_path.replace(published)
            record = self._record(published, "full", created_at)
            self._prune_unlocked()
            return record
        except BackupTooLargeError:
            bundle.unlink(missing_ok=True)
            raise
        except (GitStoreError, OSError, tarfile.TarError, ValueError) as exc:
            raise BackupError("full backup could not be created") from exc
        finally:
            shutil.rmtree(operation, ignore_errors=True)

    @staticmethod
    def _snapshot(source: Path, destination: Path) -> None:
        import os
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, flags)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OSError("original is not regular")
            with os.fdopen(descriptor, "rb") as src:
                descriptor = -1
                with destination.open("xb") as dst:
                    for chunk in iter(lambda: src.read(1024 * 1024), b""):
                        dst.write(chunk)
                    dst.flush()
                    os.fsync(dst.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)

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
        try:
            entries = self.paths.backups.iterdir()
            for path in entries:
                if path.is_symlink() or not path.is_file():
                    continue
                match = _NAME.fullmatch(path.name)
                if not match:
                    continue
                kind: BackupKind = "knowledge" if match.group(1) == "knowledge" else "full"
                records.append(self._record(path, kind))
        except OSError as exc:
            raise BackupError("backup listing unavailable") from exc
        return sorted(records, key=lambda record: record.name, reverse=True)

    def resolve_download(self, name: str) -> BackupRecord:
        if not isinstance(name, str) or _NAME.fullmatch(name) is None:
            raise BackupNotFoundError("backup was not found")
        path = self.paths.backups / name
        try:
            if path.parent != self.paths.backups or path.is_symlink() or not path.is_file():
                raise BackupNotFoundError("backup was not found")
            kind: BackupKind = "knowledge" if name.startswith("knowledge-") else "full"
            return self._record(path, kind)
        except OSError as exc:
            raise BackupNotFoundError("backup was not found") from exc

    def open_download(self, name: str) -> tuple[BackupRecord, BinaryIO]:
        record = self.resolve_download(name)
        try:
            descriptor = os.open(record.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                raise BackupNotFoundError("backup was not found")
            size = os.fstat(descriptor).st_size
            if size > self.max_bytes:
                os.close(descriptor)
                raise BackupTooLargeError("backup exceeds configured size limit")
            return record, os.fdopen(descriptor, "rb")
        except BackupError:
            raise
        except (OSError, ValueError) as exc:
            raise BackupNotFoundError("backup was not found") from exc

    def delete(self, name: str, confirmed: bool) -> None:
        if not confirmed:
            raise BackupError("confirmation required")
        record = self.resolve_download(name)
        try:
            record.path.unlink()
        except OSError as exc:
            raise BackupError("backup could not be deleted") from exc

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
