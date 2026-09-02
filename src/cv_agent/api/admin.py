import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status

from cv_agent.config import Settings
from cv_agent.knowledge.ingest import IngestionService
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.repository import KnowledgeRepository, resolve_directory_path
from cv_agent.knowledge.storage import DataPaths, ensure_data_storage, safe_upload_filename
from cv_agent.knowledge.documents_service import (
    DocumentMutationError,
    DocumentService,
    DocumentValidationError,
)


def _knowledge_initialized(repository: KnowledgeRepository) -> bool:
    from cv_agent.api.health import knowledge_is_initialized

    return knowledge_is_initialized(repository)


def build_admin_status_payload(
    settings: Settings,
    paths: DataPaths | None = None,
    git_store: LocalKnowledgeGit | None = None,
    repository: KnowledgeRepository | None = None,
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
            detail="upload storage is unavailable",
        ) from exc
    return {
        "status": "ok",
        "admin": {"enabled": bool(settings.admin_api_key)},
        "storage": {
            "documents_dir": str(documents),
            "documents_dir_writable": documents.exists() and os.access(documents, os.W_OK),
        },
        "ingestion": {"mode": settings.ingestion_mode},
        "knowledge": {
            "initialized": _knowledge_initialized(repository),
            "repository_head": head,
        },
        "repository": {"head": head},
        "paths": {
            "root": str(paths.root),
            "documents": str(paths.documents),
            "repository": str(paths.repository),
            "sources": str(paths.sources),
            "knowledge": str(paths.knowledge),
            "staging": str(paths.staging),
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
    except DocumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.detail) from exc
    except DocumentMutationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"document mutation failed; operation {exc.operation_id}",
        ) from exc
    except (OSError, ValueError) as exc:
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
        if authorization != f"Bearer {settings.admin_api_key}":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")

    router = APIRouter(dependencies=[Depends(require_admin_key)])
    @router.post("/admin/documents")
    async def upload_document(file: UploadFile = File(...)) -> dict[str, object]:
        return await upload_document_payload(settings, paths, git_store, ingestion, file, document_service)

    @router.get("/admin/status")
    def admin_status() -> dict[str, object]:
        return build_admin_status_payload(settings, paths, git_store, ingestion.repository)

    return router
