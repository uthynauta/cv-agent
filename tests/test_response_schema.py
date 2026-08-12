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
    assert payload["status"] == "completed"
    assert payload["model"] == "banorte-cv-agent"
    assert payload["output_text"].endswith("Fuentes: [[Othon CV]]")
    assert payload["output"][0]["id"].startswith("msg_")
    assert payload["output"][0]["status"] == "completed"
    assert payload["output"][0]["content"][0]["type"] == "output_text"


def test_responses_endpoint_returns_canonical_model_name():
    settings = __import__("banorte_agent.config", fromlist=["Settings"]).Settings(
        openai_api_key="test-key", agent_model_name="banorte-cv-agent"
    )
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "Respuesta")

    response = TestClient(app).post(
        "/v1/responses", json={"model": "arbitrary-client-model", "input": "hola"}
    )

    assert response.status_code == 200
    assert response.json()["model"] == "banorte-cv-agent"


def test_responses_endpoint_accepts_open_responses_message_array_input():
    seen: dict[str, str | None] = {}

    def answerer(text: str, instructions: str | None = None) -> str:
        seen["text"] = text
        seen["instructions"] = instructions
        return "Respuesta en español. Fuentes: [[Othon CV]]"

    app = create_app(
        settings=__import__("banorte_agent.config", fromlist=["Settings"]).Settings(
            openai_api_key="test-key"
        ),
        agent_answerer=answerer,
    )

    response = TestClient(app).post(
        "/v1/responses",
        json={
            "model": "banorte-cv-agent",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "¿Qué experiencia tiene Othon con agentes de IA?",
                        }
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    assert seen["text"] == "¿Qué experiencia tiene Othon con agentes de IA?"


def test_responses_endpoint_uses_latest_user_message_with_light_transcript_context():
    seen: dict[str, str | None] = {}

    def answerer(text: str, instructions: str | None = None) -> str:
        seen["text"] = text
        return "Respuesta en español. Fuentes: [[Othon CV]]"

    app = create_app(
        settings=__import__("banorte_agent.config", fromlist=["Settings"]).Settings(
            openai_api_key="test-key"
        ),
        agent_answerer=answerer,
    )

    response = TestClient(app).post(
        "/v1/responses",
        json={
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Resume la experiencia en IA."}],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Respuesta anterior muy larga que no debe reusarse.",
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Y en temas de IA, que proyectos relevantes lideró?",
                        }
                    ],
                },
            ],
        },
    )

    assert response.status_code == 200
    assert "Conversation context" in (seen["text"] or "")
    assert "User: Resume la experiencia en IA." in (seen["text"] or "")
    assert "Assistant: Respuesta anterior muy larga" in (seen["text"] or "")
    assert "Latest reviewer request:\nY en temas de IA, que proyectos relevantes lideró?" in (
        seen["text"] or ""
    )


def test_responses_endpoint_resolves_short_confirmation_to_previous_followup():
    seen: dict[str, str | None] = {}

    def answerer(text: str, instructions: str | None = None) -> str:
        seen["text"] = text
        return "Respuesta en español. Fuentes: [[Othon CV]]"

    app = create_app(
        settings=__import__("banorte_agent.config", fromlist=["Settings"]).Settings(
            openai_api_key="test-key"
        ),
        agent_answerer=answerer,
    )

    previous_answer = (
        "Othón ha laborado en Teradata, Continental Autonomous Mobility, CentroGEO "
        "y Aeroméxico. ¿Quieres que las ordene cronológicamente?"
    )
    response = TestClient(app).post(
        "/v1/responses",
        json={
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "¿En qué empresas ha laborado?"}],
                },
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": previous_answer}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "sí por favor"}],
                },
            ],
        },
    )

    assert response.status_code == 200
    assert "Previous assistant answer for this follow-up:" in (seen["text"] or "")
    assert "Teradata, Continental Autonomous Mobility, CentroGEO" in (seen["text"] or "")
    assert "Previous assistant follow-up question:\n¿Quieres que las ordene cronológicamente?" in (
        seen["text"] or ""
    )
    assert "Interpret the latest reviewer request as confirmation" in (seen["text"] or "")


def test_responses_endpoint_accepts_open_responses_content_array_input():
    seen: dict[str, str | None] = {}

    def answerer(text: str, instructions: str | None = None) -> str:
        seen["text"] = text
        return "Respuesta en español. Fuentes: [[Othon CV]]"

    app = create_app(
        settings=__import__("banorte_agent.config", fromlist=["Settings"]).Settings(
            openai_api_key="test-key"
        ),
        agent_answerer=answerer,
    )

    response = TestClient(app).post(
        "/v1/responses",
        json={
            "input": [
                {
                    "type": "input_text",
                    "text": "Resume el perfil profesional de Othon.",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert seen["text"] == "Resume el perfil profesional de Othon."


def test_responses_endpoint_ignores_overlong_client_model_without_validation_leak():
    app = create_app(
        settings=__import__("banorte_agent.config", fromlist=["Settings"]).Settings(
            openai_api_key="test-key"
        ),
        agent_answerer=lambda text, instructions=None: "Respuesta",
    )

    response = TestClient(app).post(
        "/v1/responses", json={"model": "x" * 129, "input": "hola"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["model"] == "banorte-cv-agent"
    assert "detail" not in payload


def test_responses_endpoint_rejects_oversized_request_body():
    app = create_app(
        settings=__import__("banorte_agent.config", fromlist=["Settings"]).Settings(
            openai_api_key="test-key"
        ),
        agent_answerer=lambda text, instructions=None: "Respuesta",
    )

    response = TestClient(app).post(
        "/v1/responses", json={"input": "hola", "padding": "x" * 17_000}
    )

    assert response.status_code == 413


def test_responses_endpoint_truncates_public_input_without_validation_leak():
    seen: dict[str, str] = {}

    def answerer(text: str, instructions=None):
        seen["text"] = text
        return "Respuesta"

    app = create_app(
        settings=__import__("banorte_agent.config", fromlist=["Settings"]).Settings(
            openai_api_key="test-key"
        ),
        agent_answerer=answerer,
    )

    response = TestClient(app).post("/v1/responses", json={"input": "x" * 4001})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert len(seen["text"]) == 4000


def test_responses_endpoint_truncates_public_instructions_without_validation_leak():
    seen: dict[str, str | None] = {}

    def answerer(text: str, instructions=None):
        seen["instructions"] = instructions
        return "Respuesta"

    app = create_app(
        settings=__import__("banorte_agent.config", fromlist=["Settings"]).Settings(
            openai_api_key="test-key"
        ),
        agent_answerer=answerer,
    )

    response = TestClient(app).post(
        "/v1/responses", json={"input": "hola", "instructions": "x" * 1001}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert len(seen["instructions"] or "") == 1000


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
