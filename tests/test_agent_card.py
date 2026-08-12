from fastapi.testclient import TestClient

from banorte_agent.config import Settings
from banorte_agent.main import create_app


def test_agent_card_exposes_public_a2a_metadata_without_auth():
    settings = Settings(
        openai_api_key="test-key",
        agent_api_key="agent-secret",
        agent_public_url="https://banorte-cv-agent.onrender.com",
    )
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).get("/.well-known/agent-card.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "CV Agent - Othon Gonzalez"
    assert payload["description"] == (
        "Agente de CV de Othon Gonzalez para responder preguntas sobre su perfil "
        "profesional, experiencia, habilidades, proyectos, educacion y publicaciones."
    )
    assert payload["url"] == "https://banorte-cv-agent.onrender.com/v1/responses"
    assert payload["capabilities"] == {"streaming": False}
    assert payload["securitySchemes"]["bearer"]["type"] == "http"
    assert payload["security"] == [{"bearer": []}]
    assert payload["skills"][0]["id"] == "cv_qa"
