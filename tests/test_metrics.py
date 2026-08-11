from fastapi.testclient import TestClient

from banorte_agent.main import create_app


def test_metrics_endpoint_exposes_prometheus_text(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    app = create_app(agent_answerer=lambda text, instructions=None: "ok. Fuentes: [[Test]]")
    client = TestClient(app)
    client.get("/healthz")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "banorte_http_requests_total" in response.text


def test_request_id_header_is_returned(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    app = create_app(agent_answerer=lambda text, instructions=None: "ok. Fuentes: [[Test]]")
    response = TestClient(app).get("/healthz", headers={"x-request-id": "req-test"})
    assert response.headers["x-request-id"] == "req-test"
