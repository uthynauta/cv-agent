import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from banorte_agent.agent.openai_client import OpenAITextClient
from banorte_agent.config import Settings
from banorte_agent.main import create_app
from banorte_agent.logging import request_observability_middleware
from banorte_agent.metrics import render_metrics
from banorte_agent.wiki.repository import WikiRepository
from banorte_agent.wiki.search import WikiSearch


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


def test_metrics_use_route_template_and_bound_unmatched_paths():
    app = FastAPI()
    app.middleware("http")(request_observability_middleware)

    @app.get("/items/{item_id}")
    def item(item_id: str):
        return {"item_id": item_id}

    client = TestClient(app)
    client.get("/items/unique-123")
    client.get("/missing/unique-456")
    metrics = render_metrics().decode("utf-8")

    assert 'path="/items/{item_id}"' in metrics
    assert 'path="unmatched"' in metrics
    assert "unique-123" not in metrics
    assert "unique-456" not in metrics


def test_exception_returns_request_id_log_and_bounded_metrics(caplog):
    app = FastAPI()
    app.middleware("http")(request_observability_middleware)

    @app.get("/fail/{failure_id}")
    def fail(failure_id: str):
        raise RuntimeError(failure_id)

    with caplog.at_level("INFO", logger="banorte_agent"):
        response = TestClient(app, raise_server_exceptions=False).get(
            "/fail/private-value", headers={"x-request-id": "req-failure"}
        )

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "req-failure"
    records = [json.loads(record.message) for record in caplog.records]
    assert any(
        record["request_id"] == "req-failure"
        and record["route"] == "/fail/{failure_id}"
        and record["status"] == 500
        for record in records
    )
    metrics = render_metrics().decode("utf-8")
    assert 'path="/fail/{failure_id}",status="500"' in metrics
    assert "private-value" not in metrics


def test_search_hit_metric_is_recorded(tmp_path: Path):
    repo = WikiRepository(tmp_path)
    repo.write_page("skills/python.md", "Python", {"kind": "skill"}, "Python and FastAPI")

    WikiSearch(repo).search("Python")

    metrics = render_metrics().decode("utf-8")
    assert "banorte_wiki_search_hits_count" in metrics


def test_openai_latency_metric_is_recorded():
    client = OpenAITextClient(Settings(openai_api_key="test-key"))

    class FakeResponses:
        kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return type("Response", (), {"output_text": "respuesta"})()

    responses = FakeResponses()
    client.client = type("FakeClient", (), {"responses": responses})()
    client.create_response("instructions", "input")

    metrics = render_metrics().decode("utf-8")
    assert "banorte_openai_call_duration_seconds_count" in metrics
    assert responses.kwargs["max_output_tokens"] == 1200
