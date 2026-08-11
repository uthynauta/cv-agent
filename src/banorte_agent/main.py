from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from banorte_agent.agent.openai_client import OpenAITextClient
from banorte_agent.agent.rerank import LLMReranker
from banorte_agent.agent.service import AgentService
from banorte_agent.api.admin import build_admin_router
from banorte_agent.api.health import build_health_router
from banorte_agent.api.responses import build_responses_router
from banorte_agent.api.request_limits import public_request_size_middleware
from banorte_agent.config import Settings, get_settings
from banorte_agent.logging import configure_logging, request_observability_middleware
from banorte_agent.tracing import configure_tracing
from banorte_agent.wiki.ingest import IngestionService
from banorte_agent.wiki.repository import WikiRepository
from banorte_agent.wiki.search import WikiSearch


def create_app(
    settings: Settings | None = None,
    agent_answerer: Callable[[str, str | None], str] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Banorte CV Agent", version="0.1.0")
    configure_logging()
    configure_tracing(app, settings)
    app.middleware("http")(
        lambda request, call_next: public_request_size_middleware(
            request, call_next, settings.public_request_body_limit_bytes
        )
    )
    app.middleware("http")(request_observability_middleware)
    app.include_router(build_health_router(settings))
    repository = WikiRepository(Path(settings.wiki_dir))
    if agent_answerer is None:
        def agent_answerer(text: str, instructions: str | None = None) -> str:
            answer_client = OpenAITextClient(settings)
            reranker = None
            if settings.retrieval_mode == "llm_rerank":
                rerank_settings = settings.model_copy(
                    update={"openai_model": settings.rerank_model or settings.openai_model}
                )
                reranker = LLMReranker(OpenAITextClient(rerank_settings), settings.answer_top_k)
            agent = AgentService(settings, WikiSearch(repository), answer_client, reranker)
            return agent.answer(text, instructions)
    app.include_router(build_responses_router(settings, agent_answerer))
    app.include_router(build_admin_router(settings, IngestionService(repository, settings)))
    return app


app = create_app()
