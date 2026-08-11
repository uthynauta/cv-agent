from pathlib import Path

from fastapi.testclient import TestClient

from banorte_agent.config import Settings
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


def test_readyz_uses_injected_settings(tmp_path):
    (tmp_path / "index.md").write_text("# Wiki", encoding="utf-8")
    settings = Settings(openai_api_key="injected-key", wiki_dir=str(tmp_path))

    response = TestClient(create_app(settings=settings)).get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "missing": []}
