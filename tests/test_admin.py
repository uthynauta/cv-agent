from pathlib import Path

from fastapi.testclient import TestClient

from banorte_agent.config import Settings
from banorte_agent.main import create_app


def test_admin_ingest_allows_file_inside_raw(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = raw_dir / "cv.md"
    source.write_text("# CV", encoding="utf-8")
    settings = Settings(wiki_dir=str(tmp_path), admin_api_key="admin-secret")

    class Result:
        source_page = Path("sources/cv.md")

    def ingest_file(self, path: Path):
        assert path == source
        return Result()

    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    monkeypatch.setattr("banorte_agent.api.admin.IngestionService.ingest_file", ingest_file)

    response = TestClient(app).post(
        "/admin/ingest",
        headers={"Authorization": "Bearer admin-secret"},
        json={"path": str(source)},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "count": 1, "sources": ["sources/cv.md"]}


def test_admin_ingest_rejects_path_outside_raw(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    outside = tmp_path / "raw-other"
    outside.mkdir()
    source = outside / "secret.md"
    source.write_text("secret", encoding="utf-8")
    settings = Settings(wiki_dir=str(tmp_path), admin_api_key="admin-secret")
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post(
        "/admin/ingest",
        headers={"Authorization": "Bearer admin-secret"},
        json={"path": str(source)},
    )

    assert response.status_code == 400


def test_admin_ingest_requires_admin_key(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = raw_dir / "cv.md"
    source.write_text("# CV", encoding="utf-8")
    settings = Settings(wiki_dir=str(tmp_path), admin_api_key="admin-secret")
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post("/admin/ingest", json={"path": str(source)})

    assert response.status_code == 401


def test_admin_ingest_is_disabled_without_configured_key(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = raw_dir / "cv.md"
    source.write_text("# CV", encoding="utf-8")
    settings = Settings(wiki_dir=str(tmp_path), admin_api_key=None)

    response = TestClient(
        create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    ).post("/admin/ingest", json={"path": str(source)})

    assert response.status_code == 503
    assert response.json()["detail"] == "admin ingest is disabled"
