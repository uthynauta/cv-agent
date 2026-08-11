from pathlib import Path

from fastapi import APIRouter

from banorte_agent.api.auth import require_bearer
from banorte_agent.api.models import IngestRequest
from banorte_agent.config import Settings
from banorte_agent.wiki.ingest import IngestionService


def build_admin_router(settings: Settings, ingestion: IngestionService) -> APIRouter:
    router = APIRouter(dependencies=[require_bearer(settings.admin_api_key)])

    @router.post("/admin/ingest")
    def ingest(request: IngestRequest) -> dict[str, object]:
        path = Path(request.path)
        results = ingestion.ingest_directory(path) if path.is_dir() else [ingestion.ingest_file(path)]
        return {
            "status": "ok",
            "count": len(results),
            "sources": [str(result.source_page) for result in results],
        }

    return router
