from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter

from banorte_agent.api.auth import require_bearer
from banorte_agent.api.models import ResponseRequest
from banorte_agent.config import Settings


def build_responses_router(settings: Settings, answerer: Callable[[str, str | None], str]) -> APIRouter:
    router = APIRouter(dependencies=[require_bearer(settings.agent_api_key)])

    @router.post("/v1/responses")
    def create_response(request: ResponseRequest) -> dict[str, object]:
        text = answerer(request.input, request.instructions)
        model = request.model or settings.agent_model_name
        return {
            "id": f"resp_{uuid4().hex}",
            "object": "response",
            "created_at": int(datetime.now(UTC).timestamp()),
            "model": model,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
            "output_text": text,
        }

    return router
