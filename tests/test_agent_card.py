from fastapi.testclient import TestClient

from cv_agent.config import Settings
from cv_agent.main import create_app


def test_agent_card_exposes_public_a2a_metadata_without_auth():
    settings = Settings(
        openai_api_key="test-key",
        agent_api_key="agent-secret",
        agent_public_url="https://cv-agent.example.com",
        agent_owner_name="Example Candidate",
        agent_display_name="Example CV Agent",
        agent_description="Questions about Example Candidate's CV.",
        agent_model_name="example-model",
    )
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).get("/.well-known/agent-card.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Example CV Agent"
    assert payload["description"] == "Questions about Example Candidate's CV."
    assert payload["model"] == "example-model"
    assert payload["supportedInterfaces"] == [
        {
            "url": "https://cv-agent.example.com/v1/responses",
            "protocolBinding": "HTTP+JSON",
            "protocolVersion": "1.0",
        }
    ]
    assert "url" not in payload
    assert payload["capabilities"] == {"streaming": False}
    assert payload["securitySchemes"]["bearer"]["type"] == "http"
    assert payload["security"] == [{"bearer": []}]
    assert payload["skills"][0]["id"] == "knowledge_qa"


def test_agent_card_uses_generic_skill_metadata_and_configured_endpoint():
    settings = Settings(
        agent_public_url="https://example.test/base/",
        agent_display_name="Operations Knowledge",
        agent_description="Grounded operations answers.",
        agent_model_name="ops-model",
    )
    response = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")).get(
        "/.well-known/agent-card.json"
    )
    payload = response.json()
    assert payload["name"] == "Operations Knowledge"
    assert payload["description"] == "Grounded operations answers."
    assert payload["model"] == "ops-model"
    assert payload["supportedInterfaces"][0]["url"] == "https://example.test/base/v1/responses"
    assert payload["skills"][0]["name"] == "Knowledge Q&A"
    assert "CV" not in payload["skills"][0]["description"]
    assert payload["skills"][0]["tags"] == ["knowledge", "grounded", "qa"]
