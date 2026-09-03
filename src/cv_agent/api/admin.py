import os
import hmac
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile, status

from cv_agent.config import Settings
from cv_agent.knowledge.ingest import IngestionService
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.repository import KnowledgeRepository, resolve_directory_path
from cv_agent.knowledge.storage import DataPaths, ensure_data_storage, safe_upload_filename
from cv_agent.knowledge.documents_service import (
    DocumentMutationError,
    DocumentIdentifierError,
    DocumentNotFoundError,
    DocumentService,
    DocumentValidationError,
    RevisionNotFoundError,
)
from cv_agent.knowledge.frontmatter import load_frontmatter
from cv_agent.knowledge.locking import MutationBusyError
from cv_agent.api.models import ConfirmationRequest


def _knowledge_initialized(repository: KnowledgeRepository) -> bool:
    from cv_agent.api.health import knowledge_is_initialized

    return knowledge_is_initialized(repository)


def _document_count(repository: KnowledgeRepository) -> int:
    """Count canonical source records without requiring the mutation service."""
    count = 0
    try:
        pages = sorted((repository.root / "sources").glob("*.md"))
    except OSError:
        return 0
    for page in pages:
        try:
            metadata, _ = load_frontmatter(page.read_text(encoding="utf-8"))
            document_id = metadata.get("document_id")
            if isinstance(document_id, str) and page.name == f"{document_id}.md":
                count += 1
        except Exception:
            continue
    return count


def build_admin_status_payload(
    settings: Settings,
    paths: DataPaths | None = None,
    git_store: LocalKnowledgeGit | None = None,
    repository: KnowledgeRepository | None = None,
    document_service: DocumentService | None = None,
) -> dict[str, object]:
    paths = paths or ensure_data_storage(settings.data_dir)
    if git_store is None:
        git_store = LocalKnowledgeGit(
            paths.repository, settings.data_git_author_name, settings.data_git_author_email
        )
        git_store.initialize()
    if repository is None:
        repository = KnowledgeRepository(paths.repository)
    try:
        documents = resolve_directory_path(paths.documents)
        head = git_store.head()
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"admin status unavailable; operation {uuid4().hex}",
        ) from exc
    document_count = _document_count(repository)
    return {
        "status": "ok",
        "admin": {"enabled": bool(settings.admin_api_key)},
        "storage": {
            "writable": documents.exists() and os.access(documents, os.W_OK),
            "document_count": document_count,
        },
        "ingestion": {"mode": settings.ingestion_mode},
        "knowledge": {
            "initialized": _knowledge_initialized(repository),
            "active_commit": head,
        },
    }


async def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="upload is too large")
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="upload is empty")
    return data


async def upload_document_payload(
    settings: Settings,
    paths: DataPaths,
    git_store: LocalKnowledgeGit,
    ingestion: IngestionService,
    file: UploadFile,
    document_service: DocumentService,
) -> dict[str, object]:
    try:
        filename = safe_upload_filename(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    data = await _read_upload(file, settings.admin_upload_max_bytes)
    try:
        result = document_service.add(filename, data, file.content_type)
    except MutationBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="another document mutation is running") from exc
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document was not found") from exc
    except DocumentIdentifierError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="document identifier is invalid") from exc
    except DocumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.detail) from exc
    except DocumentMutationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"document mutation failed; operation {exc.operation_id}",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="document ingestion is unavailable",
        ) from exc
    record = next(
        (item for item in document_service.list_documents() if item.document_id == result.document_id),
        None,
    )
    original = next(paths.documents.glob(f"{result.document_id}.*"), None)
    source_path = f"sources/{result.document_id}.md"
    kind = (
        {"application/pdf": "pdf", "text/markdown": "markdown", "application/x-tex": "latex"}.get(
            record.media_type
        )
        if record
        else Path(filename).suffix.lower().lstrip(".")
    )
    generated_paths = [
        path for path in result.changed_paths
        if path.startswith("knowledge/") and path not in {"knowledge/index.md", "knowledge/log.md"}
    ]
    return {
        "status": "ok",
        "document": {
            "document_id": result.document_id,
            "filename": filename,
            "path": str(original.relative_to(paths.root)) if original else f"documents/{result.document_id}{Path(filename).suffix.lower()}",
            "kind": kind,
            "source": source_path,
            "generated": generated_paths,
        },
        "ingestion": {"count": 1, "sources": [source_path], "generated": generated_paths},
        "revision": {"commit": result.commit},
    }


async def replace_document_payload(
    settings: Settings, paths: DataPaths, file: UploadFile, document_id: str, document_service: DocumentService
) -> dict[str, object]:
    try:
        filename = safe_upload_filename(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    data = await _read_upload(file, settings.admin_upload_max_bytes)
    try:
        result = document_service.replace(document_id, filename, data, file.content_type)
    except MutationBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="another document mutation is running") from exc
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document was not found") from exc
    except DocumentIdentifierError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="document identifier is invalid") from exc
    except DocumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.detail) from exc
    except DocumentMutationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"document mutation failed; operation {exc.operation_id}") from exc
    return {"status": "ok", "document_id": result.document_id, "content_sha256": result.content_sha256, "revision": {"commit": result.commit}}


def build_admin_router(
    settings: Settings,
    paths: DataPaths,
    git_store: LocalKnowledgeGit,
    ingestion: IngestionService,
    document_service: DocumentService,
) -> APIRouter:
    def require_admin_key(authorization: Annotated[str | None, Header()] = None) -> None:
        if not settings.admin_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="admin ingest is disabled",
            )
        if not hmac.compare_digest(
            (authorization or "").encode("utf-8"), f"Bearer {settings.admin_api_key}".encode("utf-8")
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")

    router = APIRouter(dependencies=[Depends(require_admin_key)])
    @router.post("/admin/documents")
    async def upload_document(file: UploadFile = File(...)) -> dict[str, object]:
        return await upload_document_payload(settings, paths, git_store, ingestion, file, document_service)

    @router.get("/admin/documents")
    def list_documents() -> dict[str, object]:
        return {"status": "ok", "documents": [record.__dict__ for record in document_service.list_documents()]}

    @router.put("/admin/documents/{document_id}")
    async def replace_document(document_id: str, file: UploadFile = File(...)) -> dict[str, object]:
        return await replace_document_payload(settings, paths, file, document_id, document_service)

    @router.delete("/admin/documents/{document_id}")
    def delete_document(document_id: str, request: ConfirmationRequest | None = None) -> dict[str, object]:
        if request is None or not request.confirm:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="confirmation required")
        try:
            result = document_service.delete(document_id)
        except MutationBusyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="another document mutation is running") from exc
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document was not found") from exc
        except DocumentIdentifierError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="document identifier is invalid") from exc
        except DocumentValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.detail) from exc
        except DocumentMutationError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"document mutation failed; operation {exc.operation_id}") from exc
        return {"status": "ok", "revision": {"commit": result.commit}}

    @router.post("/admin/rebuild")
    def rebuild() -> dict[str, object]:
        try:
            result = document_service.rebuild()
        except MutationBusyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="another document mutation is running") from exc
        except DocumentValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.detail) from exc
        except DocumentMutationError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"document mutation failed; operation {exc.operation_id}") from exc
        return {"status": "ok", "revision": {"commit": result.commit}}

    @router.get("/admin/revisions")
    def revisions(limit: int = Query(default=20, ge=0, le=100)) -> dict[str, object]:
        try:
            items = document_service.history(limit)
        except DocumentMutationError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"document mutation failed; operation {exc.operation_id}") from exc
        return {"status": "ok", "revisions": [{"commit": item.commit, "authored_at": item.authored_at, "subject": item.subject, "changed_paths": list(item.changed_paths)} for item in items]}

    @router.post("/admin/revisions/{commit}/rollback")
    def rollback(commit: str, request: ConfirmationRequest | None = None) -> dict[str, object]:
        if request is None or not request.confirm:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="confirmation required")
        try:
            result = document_service.rollback(commit, confirmed=True)
        except MutationBusyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="another document mutation is running") from exc
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document was not found") from exc
        except RevisionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="revision was not found") from exc
        except DocumentMutationError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"document mutation failed; operation {exc.operation_id}") from exc
        return {"status": "ok", "revision": {"commit": result.commit}}

    @router.get("/admin/status")
    def admin_status() -> dict[str, object]:
        return build_admin_status_payload(settings, paths, git_store, ingestion.repository, document_service)

    return router
