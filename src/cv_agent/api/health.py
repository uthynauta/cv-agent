from collections.abc import Callable

from fastapi import APIRouter, Response, status
from fastapi.responses import PlainTextResponse

from cv_agent.config import Settings, get_settings
from cv_agent.metrics import render_metrics
from cv_agent.knowledge.policy import has_initialized_knowledge, has_usable_evidence
from cv_agent.knowledge.repository import KnowledgeRepository


# Kept as a private compatibility alias for callers that imported the old helper.
_has_usable_evidence = has_usable_evidence


def knowledge_is_initialized(repository: KnowledgeRepository) -> bool:
    """Return whether the repository contains usable source or generated content."""
    try:
        pages = repository.list_pages()
    except (OSError, ValueError):
        return False
    return has_initialized_knowledge(pages, repository.root)


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
