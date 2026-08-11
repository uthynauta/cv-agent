from fastapi.testclient import TestClient

from banorte_agent.main import create_app


def test_responses_endpoint_returns_openai_like_shape(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    app = create_app(agent_answerer=lambda text, instructions=None: "Respuesta en español. Fuentes: [[Othon CV]]")
    client = TestClient(app)
    response = client.post("/v1/responses", json={"model": "banorte-cv-agent", "input": "¿Quién es Othon?"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "response"
    assert payload["model"] == "banorte-cv-agent"
    assert payload["output_text"].endswith("Fuentes: [[Othon CV]]")
    assert payload["output"][0]["content"][0]["type"] == "output_text"


def test_responses_endpoint_enforces_agent_key():
    app = create_app(
        settings=__import__("banorte_agent.config", fromlist=["Settings"]).Settings(
            openai_api_key="test-key",
            agent_api_key="agent-secret",
        ),
        agent_answerer=lambda text, instructions=None: "Respuesta. Fuentes: [[Test]]",
    )
    response = TestClient(app).post("/v1/responses", json={"input": "hola"})
    assert response.status_code == 401
