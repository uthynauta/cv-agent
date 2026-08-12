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
