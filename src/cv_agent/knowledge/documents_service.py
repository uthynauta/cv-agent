from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import shutil
from pathlib import Path
import re
from typing import Callable
from uuid import uuid4

from cv_agent.knowledge.extractors import ExtractedSource
from cv_agent.knowledge.frontmatter import load_frontmatter
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.index import ActiveKnowledge, KnowledgeSnapshot
from cv_agent.knowledge.ingest import IngestionService, validate_document_id
from cv_agent.knowledge.locking import MutationBusyError, MutationLock
from cv_agent.knowledge.repository import KnowledgeRepository, resolve_directory_path
from cv_agent.knowledge.storage import DataPaths, safe_upload_filename
from cv_agent.knowledge.validation import validate_knowledge


_OPERATION_ID = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    original_filename: str
    media_type: str
    content_sha256: str
    uploaded_at: str
    original_available: bool


@dataclass(frozen=True)
class MutationResult:
    document_id: str
    content_sha256: str
    commit: str
    changed_paths: tuple[str, ...]
    operation_id: str = ""


class DocumentMutationError(RuntimeError):
    def __init__(self, operation_id: str, message: str = "document mutation failed") -> None:
        self.operation_id = operation_id
        bounded = str(message).replace("\n", " ").replace("\r", " ")[:240]
        super().__init__(f"{bounded} (operation {operation_id})")


class DocumentCompensationError(DocumentMutationError):
    """Raised when restoring a failed mutation also encounters an error."""

    def __init__(self, operation_id: str) -> None:
        super().__init__(operation_id, "document mutation compensation failed")


class DocumentNotFoundError(DocumentMutationError):
    def __init__(self, document_id: str, operation_id: str = "") -> None:
        super().__init__(operation_id or uuid4().hex, "document was not found")
        self.document_id = document_id


@dataclass
class _Candidate:
    operation_id: str
    root: Path
    repository: KnowledgeRepository
    documents: Path
    ingestion: IngestionService


class DocumentService:
    """Coordinate document, Markdown, Git, and active-index mutations."""

    def __init__(
        self,
        paths: DataPaths,
        git: LocalKnowledgeGit,
        ingestion: IngestionService,
        active: ActiveKnowledge,
        repository: KnowledgeRepository | None = None,
    ) -> None:
        self.paths = paths
        self.git = git
        self.ingestion = ingestion
        self.active = active
        self.repository = repository or ingestion.repository

    def list_documents(self) -> list[DocumentRecord]:
        records: list[DocumentRecord] = []
        for page in self.repository.list_pages():
            try:
                page.path.resolve().relative_to((self.repository.root / "sources").resolve())
            except ValueError:
                continue
            metadata = page.metadata
            document_id = metadata.get("document_id")
            if not isinstance(document_id, str) or page.path.name != f"{document_id}.md":
                continue
            filename = str(metadata.get("original_filename") or page.path.stem)
            available = any(
                path.is_file() and not path.is_symlink()
                for path in self.paths.documents.glob(f"{document_id}.*")
            )
            records.append(
                DocumentRecord(
                    document_id=document_id,
                    original_filename=filename,
                    media_type=str(metadata.get("media_type") or "application/octet-stream"),
                    content_sha256=str(metadata.get("content_sha256") or ""),
                    uploaded_at=str(metadata.get("uploaded_at") or ""),
                    original_available=available,
                )
            )
        return sorted(records, key=lambda item: item.document_id)

    def add(self, original_filename: str, data: bytes, media_type: str | None = None) -> MutationResult:
        filename = safe_upload_filename(original_filename)
        document_id = uuid4().hex
        return self._mutate(
            "add",
            lambda candidate: self._stage_new_document(candidate, document_id, filename, data),
            document_id,
            data,
        )

    def replace(
        self,
        document_id: str,
        original_filename: str,
        data: bytes,
        media_type: str | None = None,
    ) -> MutationResult:
        validate_document_id(document_id)
        filename = safe_upload_filename(original_filename)
        return self._mutate(
            "replace",
            lambda candidate: self._stage_new_document(candidate, document_id, filename, data, replace=True),
            document_id,
            data,
        )

    def delete(self, document_id: str) -> MutationResult:
        validate_document_id(document_id)
        return self._mutate(
            "delete",
            lambda candidate: self._stage_delete(candidate, document_id),
            document_id,
            None,
        )

    def rebuild(self) -> MutationResult:
        return self._mutate("rebuild", self._stage_rebuild, "", None)

    def _mutate(
        self,
        operation: str,
        action: Callable[[_Candidate], tuple[str, str]],
        requested_id: str,
        data: bytes | None,
    ) -> MutationResult:
        operation_id = uuid4().hex
        if not _OPERATION_ID.fullmatch(operation_id):
            raise DocumentMutationError(operation_id, "could not allocate operation ID")
        root: Path | None = None
        prior_head = ""
        prior_snapshot = KnowledgeSnapshot(())
        scopes_backup: Path | None = None
        documents_backup: Path | None = None
        replaced = False
        documents_activation_attempted = False
        try:
            with MutationLock(self.paths.locks / "mutation.lock"):
                prior_head = self.git.head()
                prior_snapshot = self._snapshot()
                root = resolve_directory_path(self.paths.staging / operation_id, create=True)
                candidate_root = root / "repository"
                candidate_docs = root / "documents"
                originals_backup = root / "originals-backup"
                candidate_root.mkdir()
                candidate_docs.mkdir()
                self._copy_tree(self.repository.root / "sources", candidate_root / "sources")
                self._copy_tree(self.repository.root / "knowledge", candidate_root / "knowledge")
                self._copy_tree(self.paths.documents, originals_backup)
                self._copy_tree(originals_backup, candidate_docs)
                candidate_repo = KnowledgeRepository(candidate_root)
                candidate_ingestion = self.ingestion
                original_repository = candidate_ingestion.repository
                try:
                    candidate_ingestion.repository = candidate_repo
                    candidate = _Candidate(operation_id, root, candidate_repo, candidate_docs, candidate_ingestion)
                    result_id, digest = action(candidate)
                    self._validate_staged(candidate_root)

                    scopes_backup = root / "scope-backup"
                    scopes_backup.mkdir()
                    self._swap_directory(candidate_root / "sources", self.repository.root / "sources", scopes_backup / "sources")
                    try:
                        self._swap_directory(candidate_root / "knowledge", self.repository.root / "knowledge", scopes_backup / "knowledge")
                    except Exception:
                        self._restore_directory(self.repository.root / "sources", scopes_backup / "sources")
                        raise
                    replaced = True
                    commit = self.git.commit(
                        f"{operation.title()} document {result_id or 'knowledge'} operation {operation_id}"
                    )
                    changed = () if commit == prior_head else self.git.changed_paths(commit)

                    documents_backup = root / "documents-backup"
                    documents_backup.mkdir()
                    documents_activation_attempted = True
                    self._activate_originals(candidate_docs, documents_backup)
                    self.active.reload(self.repository)
                    return MutationResult(result_id, digest, commit, changed, operation_id)
                except MutationBusyError:
                    raise
                except DocumentMutationError:
                    self._compensate(
                        operation_id, prior_head, prior_snapshot, root, scopes_backup,
                        documents_backup, replaced, documents_activation_attempted, originals_backup,
                    )
                    raise
                except Exception as exc:
                    self._compensate(
                        operation_id, prior_head, prior_snapshot, root, scopes_backup,
                        documents_backup, replaced, documents_activation_attempted, originals_backup,
                    )
                    raise DocumentMutationError(operation_id) from exc
                finally:
                    candidate_ingestion.repository = original_repository
            # The lock scope intentionally includes all compensation below.
        except MutationBusyError:
            raise
        except DocumentMutationError:
            raise
        except Exception as exc:
            raise DocumentMutationError(operation_id) from exc
        finally:
            if root is not None:
                shutil.rmtree(root, ignore_errors=True)

    def _stage_new_document(
        self, candidate: _Candidate, document_id: str, filename: str, data: bytes, replace: bool = False
    ) -> tuple[str, str]:
        source = _safe_source_path(candidate.repository.root, document_id)
        if source.exists() and not replace:
            raise DocumentMutationError(candidate.operation_id, "document already exists")
        if replace and not source.is_file():
            raise DocumentNotFoundError(document_id, candidate.operation_id)
        if replace:
            self._remove_document_pages(candidate.repository, document_id)
            for old in candidate.documents.glob(f"{document_id}.*"):
                if old.is_file():
                    old.unlink()
        target = candidate.documents / f"{document_id}{Path(filename).suffix.lower()}"
        self._write_exclusive(target, data)
        result = candidate.ingestion.ingest_file(target, document_id, filename)
        if result.needs_ocr:
            raise DocumentMutationError(candidate.operation_id, "document requires OCR")
        return document_id, sha256(data).hexdigest()

    def _stage_delete(self, candidate: _Candidate, document_id: str) -> tuple[str, str]:
        source = _safe_source_path(candidate.repository.root, document_id)
        if not source.is_file():
            raise DocumentNotFoundError(document_id, candidate.operation_id)
        self._remove_document_pages(candidate.repository, document_id)
        for old in candidate.documents.glob(f"{document_id}.*"):
            if old.is_file():
                old.unlink()
        candidate.ingestion._write_index()
        return document_id, ""

    def _stage_rebuild(self, candidate: _Candidate) -> tuple[str, str]:
        knowledge = candidate.repository.root / "knowledge"
        for page in list(knowledge.rglob("*.md")):
            if page.name not in {"index.md", "log.md"}:
                page.unlink()
        source_pages = sorted((candidate.repository.root / "sources").glob("*.md"))
        for page in source_pages:
            source_text = page.read_text(encoding="utf-8")
            metadata, body = load_frontmatter(source_text)
            document_id = metadata.get("document_id")
            if not isinstance(document_id, str):
                raise ValueError("source identity is invalid")
            extracted_text = _extracted_text(body)
            kind = _kind_for_media_type(str(metadata.get("media_type") or "text/markdown"))
            extracted = ExtractedSource(page, extracted_text, kind, False, str(metadata.get("content_sha256") or ""))
            candidate.ingestion.ingest_extracted_text(
                page, extracted, document_id, str(metadata.get("original_filename") or page.stem)
            )
            # Ingestion may rewrite the source while generating derived pages;
            # the source itself is immutable during rebuild.
            page.write_text(source_text, encoding="utf-8")
        candidate.ingestion._write_index()
        return "", ""

    def _validate_staged(self, path: Path) -> None:
        validate_knowledge(path)

    def _activate_originals(self, candidate_documents: Path, backup: Path) -> None:
        self._swap_directory(candidate_documents, self.paths.documents, backup)

    def _remove_document_pages(self, repository: KnowledgeRepository, document_id: str) -> None:
        source = _safe_source_path(repository.root, document_id)
        source.unlink(missing_ok=True)
        for page in repository.list_pages():
            if page.path == source:
                continue
            if page.metadata.get("document_id") == document_id or f"[[sources/{document_id}]]" in page.body or f"[[sources/{document_id}.md]]" in page.body:
                page.path.unlink(missing_ok=True)

    def _compensate(
        self, operation_id: str, prior_head: str, prior_snapshot: KnowledgeSnapshot, root: Path | None,
        scopes_backup: Path | None, documents_backup: Path | None, replaced: bool,
        documents_activation_attempted: bool, originals_backup: Path
    ) -> None:
        try:
            if documents_activation_attempted:
                self._restore_directory_from_backup(self.paths.documents, originals_backup)
            if scopes_backup is not None and replaced:
                for scope in ("sources", "knowledge"):
                    live = self.repository.root / scope
                    backup = scopes_backup / scope
                    if live.exists():
                        shutil.rmtree(live, ignore_errors=True)
                    if backup.exists():
                        backup.rename(live)
            current = self.git.head()
            if current and current != prior_head:
                self.git.restore_head(current, prior_head)
            elif current == prior_head:
                self.git._run("reset", "--", check=False)
        except Exception as exc:
            failure: Exception | None = exc
        else:
            failure = None
        finally:
            try:
                self._restore_snapshot(prior_snapshot)
            except Exception as exc:
                failure = failure or exc
        if failure is not None:
            raise DocumentCompensationError(operation_id) from failure

    def _snapshot(self) -> KnowledgeSnapshot:
        return self.active._snapshot

    def _restore_snapshot(self, snapshot: KnowledgeSnapshot) -> None:
        with self.active._lock:
            self.active._snapshot = snapshot

    @staticmethod
    def _write_exclusive(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)

    @staticmethod
    def _swap_directory(candidate: Path, live: Path, backup: Path) -> None:
        if candidate.is_symlink() or live.is_symlink():
            raise ValueError("knowledge directory uses a symlink")
        moved = False
        try:
            if live.exists():
                live.rename(backup)
                moved = True
            candidate.rename(live)
        except Exception:
            if moved and backup.exists() and not live.exists():
                backup.rename(live)
            raise

    @staticmethod
    def _restore_directory(live: Path, backup: Path) -> None:
        if live.exists():
            shutil.rmtree(live, ignore_errors=True)
        if backup.exists():
            backup.rename(live)

    @classmethod
    def _copy_tree(cls, source: Path, destination: Path) -> None:
        if source.is_symlink() or (source.exists() and not source.is_dir()):
            raise ValueError("staged directory is not safe")
        destination.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            return
        for entry in source.iterdir():
            target = destination / entry.name
            if entry.is_symlink():
                raise ValueError("staged tree contains a symlink")
            if entry.is_dir():
                cls._copy_tree(entry, target)
            elif entry.is_file():
                shutil.copyfile(entry, target)
            else:
                raise ValueError("staged tree contains a special file")

    @classmethod
    def _restore_directory_from_backup(cls, live: Path, backup: Path) -> None:
        if live.exists():
            shutil.rmtree(live, ignore_errors=True)
        cls._copy_tree(backup, live)

def _extracted_text(body: str) -> str:
    marker = "## Extracted Text"
    if marker not in body:
        raise ValueError("source page is missing extracted text")
    return body.split(marker, 1)[1].strip()


def _kind_for_media_type(media_type: str) -> str:
    return {"application/pdf": "pdf", "application/x-tex": "latex"}.get(media_type, "markdown")


def _safe_source_path(repository_root: Path, document_id: str) -> Path:
    validate_document_id(document_id)
    source_root = (repository_root / "sources").resolve()
    candidate = (source_root / f"{document_id}.md").resolve()
    try:
        candidate.relative_to(source_root)
    except ValueError as exc:
        raise ValueError("document path is outside sources") from exc
    return candidate
