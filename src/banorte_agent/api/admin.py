from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Annotated
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status

from banorte_agent.admin.github import GitHubAdminService
from banorte_agent.api.models import IngestRequest
from banorte_agent.config import Settings
from banorte_agent.wiki.extractors import extract_source
from banorte_agent.wiki.ingest import IngestionService
from banorte_agent.wiki.storage import safe_upload_filename, upload_directory


def wiki_has_changes(settings: Settings) -> bool:
    return GitHubAdminService(settings).wiki_has_changes()


def _redact_detail(detail: str, settings: Settings) -> str:
    if settings.github_token:
        detail = detail.replace(settings.github_token, "[redacted]")
    return detail


def _github_http_error_detail(exc: HTTPError, settings: Settings) -> str:
    reason = exc.reason or str(exc)
    return _redact_detail(f"GitHub publish failed: {exc.code} {reason}", settings)


async def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="upload is too large")
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="upload is empty")
    return data


def build_admin_router(settings: Settings, ingestion: IngestionService) -> APIRouter:
    def require_admin_key(authorization: Annotated[str | None, Header()] = None) -> None:
        if not settings.admin_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="admin ingest is disabled",
            )
        if authorization != f"Bearer {settings.admin_api_key}":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")

    router = APIRouter(dependencies=[Depends(require_admin_key)])
    raw_root = (Path(settings.wiki_dir) / "raw").resolve()

    @router.post("/admin/ingest")
    def ingest(request: IngestRequest) -> dict[str, object]:
        path = Path(request.path).resolve()
        try:
            path.relative_to(raw_root)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="path must be within the wiki raw directory",
            ) from exc
        results = ingestion.ingest_directory(path) if path.is_dir() else [ingestion.ingest_file(path)]
        return {
            "status": "ok",
            "count": len(results),
            "sources": [str(result.source_page) for result in results],
        }

    @router.post("/admin/documents")
    async def upload_document(file: UploadFile = File(...)) -> dict[str, object]:
        try:
            filename = safe_upload_filename(file.filename or "")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        data = await _read_upload(file, settings.admin_upload_max_bytes)
        target_dir = upload_directory(settings.wiki_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        target = target_dir / f"{timestamp}-{filename}"
        target.write_bytes(data)

        try:
            extracted = extract_source(target)
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PDF is unreadable") from exc
        if extracted.needs_ocr:
            target.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="PDF requires OCR before upload",
            )

        result = ingestion.ingest_file(target)
        return {
            "status": "ok",
            "document": {
                "filename": filename,
                "path": str(target.relative_to(Path(settings.wiki_dir))),
                "kind": extracted.kind,
            },
            "ingestion": {
                "count": 1,
                "sources": [str(result.source_page)],
            },
            "publish": {
                "pending": wiki_has_changes(settings),
            },
        }

    @router.get("/admin/status")
    def admin_status() -> dict[str, object]:
        uploads = upload_directory(settings.wiki_dir)
        uploads.mkdir(parents=True, exist_ok=True)
        return {
            "status": "ok",
            "admin": {"enabled": bool(settings.admin_api_key)},
            "wiki": {
                "dir": settings.wiki_dir,
                "upload_dir": str(uploads),
                "upload_dir_writable": uploads.exists() and os.access(uploads, os.W_OK),
            },
            "ingestion": {"mode": settings.ingestion_mode},
            "github": GitHubAdminService(settings).status(),
        }

    @router.post("/admin/publish")
    def publish_wiki() -> dict[str, object]:
        try:
            return GitHubAdminService(settings).publish()
        except RuntimeError as exc:
            detail = _redact_detail(str(exc), settings)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc
        except HTTPError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_github_http_error_detail(exc, settings)) from exc
        except (URLError, OSError) as exc:
            detail = _redact_detail(f"GitHub publish failed: {exc}", settings)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc

    return router
