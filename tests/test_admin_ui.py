from fastapi import APIRouter
from fastapi.testclient import TestClient

from cv_agent.config import Settings
from cv_agent.main import create_app


def ui_settings(tmp_path, **overrides):
    values = {
        "_env_file": None,
        "openai_api_key": "test-key",
        "data_dir": tmp_path,
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
    assert "cv_agent_admin_session" not in response.cookies


def test_non_ascii_invalid_admin_login_does_not_set_session(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).post("/admin/login", data={"password": "á"})

    assert response.status_code == 401
    assert "Invalid password" in response.text
    assert "cv_agent_admin_session" not in response.cookies


def test_valid_admin_login_sets_session_and_redirects(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).post("/admin/login", data={"password": "ui-secret"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/ui"
    assert response.cookies.get("cv_agent_admin_session")


def test_admin_dashboard_rejects_non_ascii_session_cookie(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).get("/admin/ui", headers={"cookie": b"cv_agent_admin_session=payload.\xc3\xa1"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_admin_dashboard_rejects_non_ascii_session_payload(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).get("/admin/ui", headers={"cookie": b"cv_agent_admin_session=\xc3\xa1.payload"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_admin_logout_clears_session(tmp_path):
    client = TestClient(create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok"))
    client.post("/admin/login", data={"password": "ui-secret"})

    response = client.post("/admin/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"
    set_cookie = response.headers["set-cookie"].lower()
    assert "cv_agent_admin_session=" in set_cookie
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
    assert 'accept=".pdf,.md,.tex,application/pdf,text/markdown,text/x-tex,application/x-tex"' in response.text
    assert "Document file" in response.text
    assert 'data-repository-status' in response.text
    assert 'data-document-table' in response.text
    assert 'data-revision-table' in response.text
    assert 'data-create-full-backup' in response.text
    assert 'data-restore-form' in response.text
    assert "Publish" not in response.text
    assert "GitHub" not in response.text
    assert 'Last updated' in response.text


def test_ui_lifecycle_proxies_require_session(tmp_path):
    client = TestClient(create_app(settings=ui_settings(tmp_path), agent_answerer=lambda *_: "ok"))

    for path in ("/admin/ui/documents", "/admin/ui/revisions", "/admin/ui/backups"):
        assert client.get(path).status_code == 401


def test_ui_destructive_actions_require_confirmation(tmp_path):
    client = logged_in_client(tmp_path)

    assert client.request("DELETE", "/admin/ui/documents/doc", json={"confirm": False}).status_code == 409
    assert client.post("/admin/ui/revisions/" + "a" * 40 + "/rollback", json={"confirm": False}).status_code == 409
    assert client.request("DELETE", "/admin/ui/backups/missing", json={"confirm": False}).status_code == 409


def test_ui_restore_reads_multipart_confirmation(tmp_path):
    client = logged_in_client(tmp_path)
    response = client.post(
        "/admin/ui/restore",
        files={"file": ("backup.tar.gz", b"invalid", "application/gzip")},
        data={"confirm": "true"},
    )

    assert response.status_code == 422


def test_ui_status_requires_session(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).get("/admin/ui/status")

    assert response.status_code == 401


def test_ui_status_returns_local_repository_payload(tmp_path):
    settings = ui_settings(tmp_path)
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))
    client.post("/admin/login", data={"password": "ui-secret"})

    response = client.get("/admin/ui/status")

    assert response.status_code == 200
    assert "knowledge" in response.json()
    assert "active_commit" in response.json()["knowledge"]
    assert "repository" not in response.json()
    assert "github" not in response.text.lower()


def test_ui_upload_requires_session(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).post(
        "/admin/ui/documents",
        files={"file": ("Uploaded PDF.pdf", b"%PDF-1.4 text", "application/pdf")},
    )

    assert response.status_code == 401


def test_ui_upload_uses_shared_admin_ingestion(tmp_path, monkeypatch):
    settings = ui_settings(tmp_path)
    captured = {}

    def fake_build_admin_router(settings_arg, paths, git_store, ingestion, document_service, backup_service=None):
        captured["api_ingestion"] = ingestion
        captured["api_service"] = document_service
        return APIRouter()

    async def fake_upload_document_payload(settings_arg, paths, git_store, ingestion, file, document_service):
        captured["ui_ingestion"] = ingestion
        captured["ui_service"] = document_service
        return {
            "status": "ok",
            "document": {"filename": "Uploaded-PDF.pdf", "path": "documents/uploaded.pdf", "kind": "pdf"},
            "ingestion": {"count": 1, "sources": ["sources/uploaded.md"], "generated": []},
            "revision": {"commit": "commit"},
        }

    monkeypatch.setattr("cv_agent.main.build_admin_router", fake_build_admin_router)
    monkeypatch.setattr("cv_agent.admin.ui.upload_document_payload", fake_upload_document_payload)

    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))
    client.post("/admin/login", data={"password": "ui-secret"})

    response = client.post(
        "/admin/ui/documents",
        files={"file": ("Uploaded PDF.pdf", b"%PDF-1.4 text", "application/pdf")},
    )

    assert response.status_code == 200
    assert captured["ui_ingestion"] is captured["api_ingestion"]
