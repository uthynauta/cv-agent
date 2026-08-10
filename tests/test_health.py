from fastapi.testclient import TestClient

from banorte_agent.main import create_app


def test_healthz_returns_alive():
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_missing_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(create_app())
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "OPENAI_API_KEY" in response.json()["missing"]
