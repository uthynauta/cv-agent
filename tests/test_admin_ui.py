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


def test_valid_admin_login_sets_session_and_redirects(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).post("/admin/login", data={"password": "ui-secret"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/ui"
    assert response.cookies.get("banorte_admin_session")


def test_admin_logout_clears_session(tmp_path):
    client = TestClient(create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok"))
    client.post("/admin/login", data={"password": "ui-secret"})

    response = client.post("/admin/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"
    set_cookie = response.headers["set-cookie"].lower()
    assert "banorte_admin_session=" in set_cookie
    assert "max-age=0" in set_cookie or "expires=" in set_cookie
