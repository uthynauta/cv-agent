from fastapi import APIRouter

from banorte_agent.config import Settings


def build_agent_card_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/.well-known/agent-card.json")
    def agent_card() -> dict[str, object]:
        card: dict[str, object] = {
            "name": "CV Agent - Othon Gonzalez",
            "description": (
                "Agente de CV de Othon Gonzalez para responder preguntas sobre su perfil "
                "profesional, experiencia, habilidades, proyectos, educacion y publicaciones."
            ),
            "version": "1.0.0",
            "protocolVersion": "0.2.5",
            "url": f"{settings.agent_public_url.rstrip('/')}/v1/responses",
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "capabilities": {"streaming": False},
            "skills": [
                {
                    "id": "cv_qa",
                    "name": "CV Q&A",
                    "description": (
                        "Responde preguntas sobre trayectoria profesional, experiencia, "
                        "habilidades, proyectos, educacion y publicaciones de Othon Gonzalez."
                    ),
                    "tags": ["cv", "career", "ai", "banorte"],
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
