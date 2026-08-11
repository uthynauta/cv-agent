from pathlib import Path

from fastapi import APIRouter, Response, status

from banorte_agent.config import Settings, get_settings



def build_health_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readyz")
    def readyz(response: Response) -> dict[str, object]:
        missing: list[str] = []
        if not settings.openai_api_key:
            missing.append("OPENAI_API_KEY")
        index_path = Path(settings.wiki_dir) / "index.md"
        if not index_path.exists():
            missing.append("wiki/index.md")
        if missing:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not_ready", "missing": missing}
        return {"status": "ready", "missing": []}

    return router


router = build_health_router(get_settings())
