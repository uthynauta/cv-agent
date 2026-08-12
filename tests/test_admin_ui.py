from pathlib import Path

from fastapi import APIRouter
from fastapi.testclient import TestClient

from banorte_agent.config import Settings
from banorte_agent.main import create_app


def ui_settings(tmp_path, **overrides):
    values = {
        "_env_file": None,
        "openai_api_key": "test-key",
        "wiki_dir": str(tmp_path),
        "admin_api_key": "admin-secret",
        "admin_ui_password": "ui-secret",
        "admin_ui_session_secret": "session-secret",
    }
    values.update(overrides)
    return Settings(**values)


def test_admin_login_disabled_without_ui_config(tmp_path):
    settings = ui_settings(tmp_path, admin_ui_password=None)

    response = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")).get(
        "/admin/login"
    )

    assert response.status_code == 503
    assert "Admin UI is disabled" in response.text


def test_admin_login_page_renders_when_configured(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).get("/admin/login")

    assert response.status_code == 200
    assert "Admin Dashboard" in response.text
    assert 'type="password"' in response.text


def test_invalid_admin_login_does_not_set_session(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).post("/admin/login", data={"password": "wrong"})

    assert response.status_code == 401
    assert "Invalid password" in response.text
    assert "banorte_admin_session" not in response.cookies


def test_non_ascii_invalid_admin_login_does_not_set_session(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).post("/admin/login", data={"password": "á"})

    assert response.status_code == 401
    assert "Invalid password" in response.text
    assert "banorte_admin_session" not in response.cookies


def test_valid_admin_login_sets_session_and_redirects(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).post("/admin/login", data={"password": "ui-secret"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/ui"
    assert response.cookies.get("banorte_admin_session")


def test_admin_dashboard_rejects_non_ascii_session_cookie(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).get("/admin/ui", headers={"cookie": b"banorte_admin_session=payload.\xc3\xa1"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_admin_dashboard_rejects_non_ascii_session_payload(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).get("/admin/ui", headers={"cookie": b"banorte_admin_session=\xc3\xa1.payload"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_admin_logout_clears_session(tmp_path):
    client = TestClient(create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok"))
    client.post("/admin/login", data={"password": "ui-secret"})

    response = client.post("/admin/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"
    set_cookie = response.headers["set-cookie"].lower()
    assert "banorte_admin_session=" in set_cookie
    assert "path=/admin" in set_cookie
    assert "max-age=0" in set_cookie or "expires=" in set_cookie


def logged_in_client(tmp_path):
    client = TestClient(create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok"))
    response = client.post("/admin/login", data={"password": "ui-secret"})
    assert response.status_code == 200
    return client


def test_dashboard_requires_session(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok"),
        follow_redirects=False,
    ).get("/admin/ui")

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_dashboard_renders_status_tiles_and_actions(tmp_path):
    client = logged_in_client(tmp_path)

    response = client.get("/admin/ui")

    assert response.status_code == 200
    assert 'data-status-grid' in response.text
    assert 'data-upload-form' in response.text
    assert 'data-publish-button' in response.text
    assert 'Last updated' in response.text


def test_ui_status_requires_session(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).get("/admin/ui/status")

    assert response.status_code == 401


def test_ui_status_returns_payload_without_secrets(tmp_path, monkeypatch):
    settings = ui_settings(tmp_path, github_token="secret-token")

    class FakeGitHub:
        def __init__(self, settings):
            pass

        def status(self):
            return {
                "configured": True,
                "connected": True,
                "base_branch": "main",
                "pending_wiki_changes": True,
                "error": None,
            }

    monkeypatch.setattr("banorte_agent.api.admin.GitHubAdminService", FakeGitHub)
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))
    client.post("/admin/login", data={"password": "ui-secret"})

    response = client.get("/admin/ui/status")

    assert response.status_code == 200
    assert response.json()["github"]["pending_wiki_changes"] is True
    assert "secret-token" not in response.text


def test_ui_upload_requires_session(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).post(
        "/admin/ui/documents",
        files={"file": ("Uploaded PDF.pdf", b"%PDF-1.4 text", "application/pdf")},
    )

    assert response.status_code == 401


def test_ui_upload_reuses_document_upload_behavior(tmp_path, monkeypatch):
    settings = ui_settings(tmp_path, admin_upload_max_bytes=1024)

    class Extracted:
        kind = "pdf"
        needs_ocr = False
        text = "retrievable text " * 20
        sha256 = "a" * 64

    class Result:
        source_page = Path("sources/uploaded.md")

    def fake_extract(path: Path):
        assert path.name.endswith(".pdf")
        return Extracted()

    def fake_ingest_file(self, path: Path):
        assert path.parent == tmp_path / "raw" / "uploads"
        assert path.read_bytes() == b"%PDF-1.4 text"
        return Result()

    monkeypatch.setattr("banorte_agent.api.admin.extract_source", fake_extract)
    monkeypatch.setattr("banorte_agent.api.admin.IngestionService.ingest_file", fake_ingest_file)
    monkeypatch.setattr("banorte_agent.api.admin.wiki_has_changes", lambda _: True)

    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))
    client.post("/admin/login", data={"password": "ui-secret"})

    response = client.post(
        "/admin/ui/documents",
        files={"file": ("Uploaded PDF.pdf", b"%PDF-1.4 text", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["document"]["filename"] == "Uploaded-PDF.pdf"
    assert payload["document"]["kind"] == "pdf"
    assert payload["ingestion"] == {"count": 1, "sources": ["sources/uploaded.md"]}
    assert payload["publish"] == {"pending": True}


def test_ui_upload_uses_shared_admin_ingestion(tmp_path, monkeypatch):
    settings = ui_settings(tmp_path)
    captured = {}

    def fake_build_admin_router(settings_arg, ingestion):
        captured["api_ingestion"] = ingestion
        return APIRouter()

    async def fake_upload_document_payload(settings_arg, ingestion, file):
        captured["ui_ingestion"] = ingestion
        return {
            "status": "ok",
            "document": {"filename": "Uploaded-PDF.pdf", "path": "raw/uploads/Uploaded-PDF.pdf", "kind": "pdf"},
            "ingestion": {"count": 1, "sources": ["sources/uploaded.md"]},
            "publish": {"pending": False},
        }

    monkeypatch.setattr("banorte_agent.main.build_admin_router", fake_build_admin_router)
    monkeypatch.setattr("banorte_agent.admin.ui.upload_document_payload", fake_upload_document_payload)

    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))
    client.post("/admin/login", data={"password": "ui-secret"})

    response = client.post(
        "/admin/ui/documents",
        files={"file": ("Uploaded PDF.pdf", b"%PDF-1.4 text", "application/pdf")},
    )

    assert response.status_code == 200
    assert captured["ui_ingestion"] is captured["api_ingestion"]


def test_ui_publish_requires_session(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).post("/admin/ui/publish")

    assert response.status_code == 401


def test_ui_publish_returns_redacted_result(tmp_path, monkeypatch):
    settings = ui_settings(tmp_path, github_token="secret-token")

    class FakeGitHub:
        def __init__(self, settings):
            pass

        def publish(self):
            return {
                "status": "published",
                "changed_files": ["wiki/index.md", "logs/secret-token.txt"],
                "remote_url": "https://github.com/example/repo",
                "error": "publish detail secret-token",
            }

    monkeypatch.setattr("banorte_agent.api.admin.GitHubAdminService", FakeGitHub)
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))
    client.post("/admin/login", data={"password": "ui-secret"})

    response = client.post("/admin/ui/publish")

    assert response.status_code == 200
    assert response.json() == {
        "status": "published",
        "changed_files": ["wiki/index.md", "logs/[redacted].txt"],
        "remote_url": "https://github.com/example/repo",
        "error": "publish detail [redacted]",
    }
    assert "secret-token" not in response.text
    assert "[redacted]" in response.text
