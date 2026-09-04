from collections.abc import Callable

from fastapi import FastAPI

from cv_agent.agent.openai_client import OpenAITextClient
from cv_agent.agent.rerank import LLMReranker
from cv_agent.agent.service import AgentService
from cv_agent.admin.ui import build_admin_ui_router
from cv_agent.api.admin import build_admin_router
from cv_agent.api.agent_card import build_agent_card_router
from cv_agent.api.health import build_health_router
from cv_agent.api.responses import build_responses_router
from cv_agent.api.request_limits import public_request_size_middleware
from cv_agent.config import Settings, get_settings
from cv_agent.logging import configure_logging, request_observability_middleware
from cv_agent.tracing import configure_tracing
from cv_agent.knowledge.ingest import IngestionService
from cv_agent.knowledge.repository import KnowledgeRepository
from cv_agent.knowledge.search import KnowledgeSearch
from cv_agent.knowledge.index import ActiveKnowledge
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.storage import ensure_data_storage
from cv_agent.knowledge.documents_service import DocumentService
from cv_agent.knowledge.backup import BackupService
from cv_agent.knowledge.restore import RestoreService


def create_app(
    settings: Settings | None = None,
    agent_answerer: Callable[[str, str | None], str] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="CV Agent", version="0.3.0")
    configure_logging()
    configure_tracing(app, settings)
    app.middleware("http")(
        lambda request, call_next: public_request_size_middleware(
            request, call_next, settings.public_request_body_limit_bytes
        )
    )
    app.middleware("http")(request_observability_middleware)
    app.include_router(build_agent_card_router(settings))
    paths = ensure_data_storage(settings.data_dir)
    git_store = LocalKnowledgeGit(
        paths.repository,
        settings.data_git_author_name,
        settings.data_git_author_email,
    )
    git_store.initialize()
    repository = KnowledgeRepository(paths.repository)
    active_knowledge = ActiveKnowledge.load(repository)
    knowledge_search = KnowledgeSearch(active_knowledge)
    ingestion = IngestionService(repository, settings)
    document_service = DocumentService(paths, git_store, ingestion, active_knowledge)
    backup_service = BackupService(paths, git_store, settings)
    restore_service = RestoreService(paths, git_store, settings, document_service, backup_service)
    restore_service.bind_app(app)
    document_service.restore_service = restore_service
    app.state.data_paths = paths
    app.state.paths = paths
    app.state.knowledge_git = git_store
    app.state.git_store = git_store
    app.state.knowledge_repository = repository
    app.state.repository = repository
    app.state.active_knowledge = active_knowledge
    app.state.knowledge_search = knowledge_search
    app.state.ingestion_service = ingestion
    app.state.ingestion = ingestion
    app.state.document_service = document_service
    app.state.documents_service = document_service
    app.state.backup_service = backup_service
    app.state.restore_service = restore_service
    app.include_router(
        build_health_router(settings, repository, lambda: active_knowledge.initialized)
    )
    app.include_router(build_admin_ui_router(settings, paths, git_store, ingestion, document_service))
    if agent_answerer is None:
        def agent_answerer(text: str, instructions: str | None = None) -> str:
            answer_client = OpenAITextClient(settings)
            reranker = None
            if settings.retrieval_mode == "llm_rerank":
                rerank_settings = settings.model_copy(
                    update={"openai_model": settings.rerank_model or settings.openai_model}
                )
                reranker = LLMReranker(OpenAITextClient(rerank_settings), settings.answer_top_k)
            agent = AgentService(settings, knowledge_search, answer_client, reranker)
            return agent.answer(text, instructions)
    app.include_router(
        build_responses_router(settings, agent_answerer, lambda: active_knowledge.initialized)
    )
    router_args = (settings, paths, git_store, ingestion, document_service)
    app.include_router(build_admin_router(*router_args, backup_service=backup_service))
    return app


app = create_app()
