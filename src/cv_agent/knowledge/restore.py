from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
from uuid import uuid4

from cv_agent.config import Settings
from cv_agent.knowledge.backup import BackupService, BackupTooLargeError
from cv_agent.knowledge.documents_service import DocumentService
from cv_agent.knowledge.frontmatter import load_frontmatter
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.locking import MutationLock
from cv_agent.knowledge.repository import KnowledgeRepository
from cv_agent.knowledge.storage import DataPaths
from cv_agent.knowledge.validation import validate_knowledge

class BackupValidationError(ValueError): pass
class RestoreError(RuntimeError): pass

@dataclass(frozen=True)
class RestoreResult:
    active_commit: str
    recovery_backup: str
    quarantined: tuple[str, ...] = ()

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

class RestoreService:
    """Stage and validate a backup, then atomically activate it under the lock."""
    def __init__(self, paths: DataPaths, git: LocalKnowledgeGit, settings: Settings,
                 documents: DocumentService | None = None, backup_service: BackupService | None = None) -> None:
        self.paths, self.git, self.settings = paths, git, settings
        self.documents = documents
        self.backup = backup_service or BackupService(paths, git, settings)
        self.max_bytes = settings.admin_backup_max_bytes
        self.max_members = 10000
        self.max_expanded_bytes = min(128 * 1024 * 1024, self.max_bytes)
        self.max_file_bytes = min(16 * 1024 * 1024, self.max_bytes)
        self._app = None

    def bind_app(self, app: object) -> None: self._app = app

    @staticmethod
    def _safe_name(name: str) -> str:
        if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
            raise BackupValidationError("archive member path is unsafe")
        path = PurePosixPath(name)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise BackupValidationError("archive member path is unsafe")
        return "/".join(path.parts)

    def _read_archive(self, source: Path) -> tuple[Path, dict[str, bytes], dict[str, object]]:
        try:
            if source.stat().st_size > self.max_bytes: raise BackupTooLargeError("backup exceeds configured size limit")
        except OSError as exc: raise BackupValidationError("backup cannot be read") from exc
        root = self.paths.staging / f"restore-{uuid4().hex}"; root.mkdir(mode=0o700)
        payloads: dict[str, bytes] = {}; expanded = 0
        try:
            with tarfile.open(source, "r:gz") as archive:
                members = archive.getmembers()
                if len(members) > self.max_members: raise BackupValidationError("archive contains too many members")
                for member in members:
                    name = self._safe_name(member.name)
                    if not member.isreg() or member.issym() or member.islnk() or member.isdir(): raise BackupValidationError("archive contains an unsupported member")
                    if name in payloads: raise BackupValidationError("archive contains duplicate members")
                    if member.size < 0 or member.size > self.max_file_bytes or expanded + member.size > self.max_expanded_bytes: raise BackupTooLargeError("expanded backup exceeds configured size limit")
                    handle = archive.extractfile(member)
                    if handle is None: raise BackupValidationError("archive member cannot be read")
                    data = handle.read(member.size + 1)
                    if len(data) != member.size: raise BackupValidationError("archive member size is invalid")
                    expanded += len(data); payloads[name] = data
            if set(payloads) < {"manifest.json", "knowledge.bundle"}: raise BackupValidationError("archive manifest or bundle is missing")
            try: manifest = json.loads(payloads["manifest.json"].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise BackupValidationError("manifest is invalid") from exc
            self._validate_manifest(manifest, payloads)
            return root, payloads, manifest
        except (tarfile.TarError, OSError) as exc: raise BackupValidationError("backup archive is invalid") from exc
        except Exception:
            shutil.rmtree(root, ignore_errors=True); raise

    def _validate_manifest(self, manifest: object, payloads: dict[str, bytes]) -> None:
        if not isinstance(manifest, dict) or set(manifest) != {"format_version", "created_at", "active_commit", "agent_model", "files"}: raise BackupValidationError("manifest schema is invalid")
        if type(manifest["format_version"]) is not int or manifest["format_version"] != 1: raise BackupValidationError("manifest schema is invalid")
        if not isinstance(manifest["created_at"], str): raise BackupValidationError("manifest date is invalid")
        try: datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
        except ValueError as exc: raise BackupValidationError("manifest date is invalid") from exc
        if not isinstance(manifest["active_commit"], str) or not _SHA1.fullmatch(manifest["active_commit"]): raise BackupValidationError("manifest commit is invalid")
        if not isinstance(manifest["agent_model"], str) or not manifest["agent_model"] or len(manifest["agent_model"]) > 256: raise BackupValidationError("manifest model is invalid")
        files = manifest["files"]
        if not isinstance(files, dict) or set(files) != set(payloads) - {"manifest.json"}: raise BackupValidationError("manifest file inventory is invalid")
        for name, record in files.items():
            self._safe_name(name)
            if not isinstance(record, dict) or set(record) != {"sha256", "size"}: raise BackupValidationError("manifest file record is invalid")
            digest, size = record["sha256"], record["size"]
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest) or type(size) is not int or size != len(payloads[name]): raise BackupValidationError("manifest checksum is invalid")
            if hashlib.sha256(payloads[name]).hexdigest() != digest: raise BackupValidationError("manifest checksum is invalid")
            if not (name == "knowledge.bundle" or (name.startswith("documents/") and name.count("/") == 1 and Path(name).suffix.lower() in {".pdf", ".md", ".tex"})): raise BackupValidationError("manifest contains an unexpected file")

    @staticmethod
    def _verify_bundle(bundle: Path) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}; env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1"})
        try: result = subprocess.run(["git", "bundle", "verify", str(bundle)], capture_output=True, timeout=30, env=env)
        except (OSError, subprocess.SubprocessError) as exc: raise BackupValidationError("Git bundle is invalid") from exc
        if result.returncode: raise BackupValidationError("Git bundle is invalid")

    def _stage_bundle(self, root: Path, source: Path) -> Path:
        bundle = root / "knowledge.bundle"
        try:
            with source.open("rb", buffering=0) as src, bundle.open("xb", mode=0o600) as dst:
                remaining = self.max_bytes
                while True:
                    chunk = src.read(min(1024 * 1024, remaining + 1))
                    if not chunk: break
                    remaining -= len(chunk)
                    if remaining < 0: raise BackupTooLargeError("backup exceeds configured size limit")
                    dst.write(chunk)
        except OSError as exc: raise BackupValidationError("backup cannot be read") from exc
        self._verify_bundle(bundle); return bundle

    def restore_full(self, source: str | Path, *, confirmed: bool = False) -> RestoreResult:
        if not confirmed: raise RestoreError("restore requires confirmation")
        root, payloads, manifest = self._read_archive(Path(source))
        try: return self._restore_locked(root, payloads, manifest)
        finally: shutil.rmtree(root, ignore_errors=True)

    def restore_knowledge(self, source: str | Path, *, confirmed: bool = False) -> RestoreResult:
        if not confirmed: raise RestoreError("restore requires confirmation")
        root = self.paths.staging / f"restore-{uuid4().hex}"; root.mkdir(mode=0o700)
        try:
            bundle = self._stage_bundle(root, Path(source))
            return self._restore_locked(root, {"knowledge.bundle": bundle}, {"active_commit": ""}, knowledge_only=True)
        finally: shutil.rmtree(root, ignore_errors=True)

    def _restore_locked(self, root: Path, payloads: dict[str, bytes | Path], manifest: dict[str, object], *, knowledge_only: bool = False) -> RestoreResult:
        with MutationLock(self.paths.locks / "mutation.lock"):
            bundle = root / "knowledge.bundle"; value = payloads["knowledge.bundle"]
            if isinstance(value, Path) and value != bundle: shutil.copyfile(value, bundle); os.chmod(bundle, 0o600)
            elif isinstance(value, bytes): bundle.write_bytes(value); os.chmod(bundle, 0o600)
            self._verify_bundle(bundle)
            candidate = root / "repository"; candidate.mkdir(mode=0o700)
            env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}; env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1"})
            try:
                subprocess.run(["git", "-C", str(candidate), "init", "--initial-branch=main"], check=True, capture_output=True, env=env, timeout=30)
                subprocess.run(
                    ["git", "-C", str(candidate), "fetch", str(bundle), "refs/heads/main"],
                    check=True,
                    capture_output=True,
                    env=env,
                    timeout=30,
                )
                subprocess.run(
                    ["git", "-C", str(candidate), "update-ref", "refs/heads/main", "FETCH_HEAD"],
                    check=True,
                    capture_output=True,
                    env=env,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError) as exc: raise BackupValidationError("Git bundle cannot be materialized") from exc
            candidate_git = LocalKnowledgeGit(candidate, self.settings.data_git_author_name, self.settings.data_git_author_email); candidate_git.initialize(); commit = candidate_git.head()
            if not commit or (manifest.get("active_commit") and commit != manifest["active_commit"]): raise BackupValidationError("bundle commit does not match manifest")
            candidate_git._run("read-tree", "--reset", "-u", commit)
            git_metadata = candidate / ".git"
            held_metadata = root / "candidate.git"
            git_metadata.rename(held_metadata)
            try:
                validate_knowledge(candidate)
            finally:
                held_metadata.rename(git_metadata)
            docs = root / "documents"; docs.mkdir(mode=0o700); expected: dict[str, str] = {}
            for page in (candidate / "sources").glob("*.md"):
                metadata, _ = load_frontmatter(page.read_text(encoding="utf-8"))
                if isinstance(metadata.get("document_id"), str) and isinstance(metadata.get("content_sha256"), str): expected[f"{metadata['document_id']}{Path(str(metadata.get('original_filename') or '')).suffix.lower()}"] = metadata["content_sha256"]
            if knowledge_only:
                for original in self.paths.documents.iterdir():
                    if original.name != "quarantine" and original.is_file() and not original.is_symlink() and hashlib.sha256(original.read_bytes()).hexdigest() == expected.get(original.name):
                        target = docs / original.name; target.write_bytes(original.read_bytes()); os.chmod(target, 0o600)
            else:
                for name, value in payloads.items():
                    data = value if isinstance(value, bytes) else value.read_bytes()
                    if name.startswith("documents/") and hashlib.sha256(data).hexdigest() == expected.get(Path(name).name):
                        target = docs / Path(name).name; target.write_bytes(data); os.chmod(target, 0o600)
            recovery = self.backup._create_full_backup_locked(); old_repo, old_docs = root / "prior-repository", root / "prior-documents"
            old_snapshot = self.documents.active._snapshot if self.documents is not None else None; quarantine_names: list[str] = []
            if knowledge_only:
                for original in self.paths.documents.iterdir():
                    if original.name != "quarantine" and original.is_file() and not original.is_symlink() and hashlib.sha256(original.read_bytes()).hexdigest() != expected.get(original.name): quarantine_names.append(original.name)
            self.git.root.rename(old_repo); self.paths.documents.rename(old_docs)
            previous_git = self.git
            try:
                candidate.rename(self.git.root); docs.rename(self.paths.documents); new_git = LocalKnowledgeGit(self.git.root, self.settings.data_git_author_name, self.settings.data_git_author_email); new_git.initialize()
                if self.documents is not None:
                    self.documents.git = new_git; self.documents.repository = KnowledgeRepository(new_git.root); self.documents.ingestion.repository = self.documents.repository; self.documents.active.reload(self.documents.repository)
                if quarantine_names:
                    quarantine = self.paths.quarantine / uuid4().hex; quarantine.mkdir(mode=0o700)
                    for name in quarantine_names: (old_docs / name).rename(quarantine / name)
                self.git = new_git
                if self._app is not None:
                    self._app.state.git_store = new_git; self._app.state.knowledge_git = new_git; self._app.state.repository = self.documents.repository if self.documents else KnowledgeRepository(new_git.root); self._app.state.knowledge_repository = self._app.state.repository
                return RestoreResult(commit, recovery.name, tuple(quarantine_names))
            except Exception as exc:
                if self.git.root.exists(): shutil.rmtree(self.git.root)
                if self.paths.documents.exists(): shutil.rmtree(self.paths.documents)
                old_repo.rename(self.git.root); old_docs.rename(self.paths.documents); self.git = previous_git
                if self.documents is not None:
                    self.documents.git = previous_git; self.documents.repository = KnowledgeRepository(previous_git.root); self.documents.ingestion.repository = self.documents.repository
                    if old_snapshot is not None: self.documents.active._snapshot = old_snapshot
                raise RestoreError("restore activation failed") from exc
