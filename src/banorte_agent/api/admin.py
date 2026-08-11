from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from banorte_agent.api.auth import require_bearer
from banorte_agent.api.models import IngestRequest
from banorte_agent.config import Settings
from banorte_agent.wiki.ingest import IngestionService


def build_admin_router(settings: Settings, ingestion: IngestionService) -> APIRouter:
    router = APIRouter(dependencies=[require_bearer(settings.admin_api_key)])
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

    return router
