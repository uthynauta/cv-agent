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
    )
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).get("/.well-known/agent-card.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Example CV Agent"
    assert payload["description"] == "Questions about Example Candidate's CV."
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
    assert payload["skills"][0]["id"] == "cv_qa"
