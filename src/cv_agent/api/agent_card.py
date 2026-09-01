from fastapi import APIRouter

from cv_agent.config import Settings


def build_agent_card_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/.well-known/agent-card.json")
    def agent_card() -> dict[str, object]:
        public_url = (settings.agent_public_url or "").rstrip("/")
        responses_url = f"{public_url}/v1/responses"
        owner = settings.agent_owner_name or "the candidate"
        card: dict[str, object] = {
            "name": settings.agent_display_name,
            "description": settings.agent_description,
            "version": "1.0.0",
            "supportedInterfaces": [
                {
                    "url": responses_url,
                    "protocolBinding": "HTTP+JSON",
                    "protocolVersion": "1.0",
                }
            ],
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "capabilities": {"streaming": False},
            "skills": [
                {
                    "id": "cv_qa",
                    "name": "CV Q&A",
                    "description": (
                        "Responde preguntas sobre trayectoria profesional, experiencia, "
                        f"habilidades, proyectos, educacion y publicaciones de {owner}."
                    ),
                    "tags": ["cv", "career", "ai"],
                }
            ],
        }
        if settings.agent_api_key:
            card["securitySchemes"] = {
                "bearer": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Use the API key as a Bearer token.",
                }
            }
            card["security"] = [{"bearer": []}]
        return card

    return router
