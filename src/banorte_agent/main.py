from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from banorte_agent.agent.openai_client import OpenAITextClient
from banorte_agent.agent.service import AgentService
from banorte_agent.api.admin import build_admin_router
from banorte_agent.api.health import router as health_router
from banorte_agent.api.responses import build_responses_router
from banorte_agent.config import Settings, get_settings
from banorte_agent.wiki.ingest import IngestionService
from banorte_agent.wiki.repository import WikiRepository
from banorte_agent.wiki.search import WikiSearch


def create_app(
    settings: Settings | None = None,
    agent_answerer: Callable[[str, str | None], str] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Banorte CV Agent", version="0.1.0")
    app.include_router(health_router)
    repository = WikiRepository(Path(settings.wiki_dir))
    if agent_answerer is None:
        def agent_answerer(text: str, instructions: str | None = None) -> str:
            agent = AgentService(settings, WikiSearch(repository), OpenAITextClient(settings))
            return agent.answer(text, instructions)
    app.include_router(build_responses_router(settings, agent_answerer))
    app.include_router(build_admin_router(settings, IngestionService(repository)))
    return app


app = create_app()
