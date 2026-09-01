import re
from collections.abc import Callable

from fastapi import APIRouter, Response, status
from fastapi.responses import PlainTextResponse

from cv_agent.config import Settings, get_settings
from cv_agent.metrics import render_metrics
from cv_agent.knowledge.repository import KnowledgeRepository

def knowledge_is_initialized(repository: KnowledgeRepository) -> bool:
    """Return whether the repository contains usable source or generated content."""
    try:
        pages = repository.list_pages()
    except (OSError, ValueError):
        return False
    for page in pages:
        relative = page.path
        try:
            relative = page.path.resolve().relative_to(repository.root.resolve())
        except (OSError, ValueError):
            pass
        if relative.as_posix() in {"knowledge/index.md", "knowledge/log.md"}:
            continue
        if relative.parts and relative.parts[0] in {"sources", "knowledge"}:
            if re.search(r"[A-Za-z\u00c1\u00c9\u00cd\u00d3\u00da\u00d1\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1]{3,}", page.body):
                return True
    return False


def build_health_router(
    settings: Settings,
    repository: KnowledgeRepository | None = None,
    knowledge_ready: Callable[[], bool] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readyz")
    def readyz(response: Response) -> dict[str, object]:
        missing: list[str] = []
        if not settings.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if not settings.openai_model or not settings.openai_model.strip():
            missing.append("OPENAI_MODEL")
        if not settings.agent_owner_name:
            missing.append("AGENT_OWNER_NAME")
        if not settings.agent_public_url:
            missing.append("AGENT_PUBLIC_URL")
        initialized = knowledge_ready() if knowledge_ready is not None else (
            knowledge_is_initialized(repository) if repository is not None else False
        )
        if not initialized:
            missing.append("knowledge")
        if missing:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not_ready", "missing": missing}
        return {"status": "ready", "missing": []}

    @router.get("/metrics")
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(render_metrics().decode("utf-8"), media_type="text/plain; version=0.0.4")

    return router


router = build_health_router(get_settings())
