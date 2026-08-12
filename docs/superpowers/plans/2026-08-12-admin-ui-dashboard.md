# Admin UI Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use $subagent-driven-development (recommended) or $executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a simple browser admin dashboard for status, PDF upload, and manual wiki publish without exposing admin API tokens to browser JavaScript.

**Architecture:** Serve a small server-rendered UI from the existing FastAPI app under `/admin/*`. Add signed session-cookie auth using `ADMIN_UI_PASSWORD` and `ADMIN_UI_SESSION_SECRET`, then add UI proxy routes that reuse the same internal admin service functions as the bearer-token API. Keep existing JSON bearer admin endpoints unchanged for curl and automation.

**Tech Stack:** FastAPI, Pydantic Settings, stdlib `hmac`/`hashlib`/`base64`/`json`, plain HTML/CSS/JavaScript, pytest, FastAPI `TestClient`.

---

## File Structure

- Modify `src/banorte_agent/config.py`: add UI password/session settings and normalize blanks.
- Modify `.env.example`: document UI env vars without real secrets.
- Create `src/banorte_agent/admin/ui.py`: signed session helpers, HTML renderers, and UI router.
- Modify `src/banorte_agent/api/admin.py`: extract reusable functions for status, upload, and publish so UI and API share behavior.
- Modify `src/banorte_agent/main.py`: include the admin UI router.
- Create `tests/test_admin_ui.py`: browser login/session/dashboard/proxy tests.
- Modify `tests/test_config.py`: config coverage for UI defaults and blank normalization.
- Modify `tests/test_admin.py`: keep existing API tests passing after refactor.
- Modify `README.md` and `docs/deployment.md`: document `/admin/login`, UI env vars, and Render setup.

## Task 1: Admin UI Settings

**Files:**
- Modify: `src/banorte_agent/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing settings tests**

Append to `tests/test_config.py`:

```python
def test_admin_ui_defaults():
    settings = Settings(_env_file=None, openai_api_key="test-key")

    assert settings.admin_ui_password is None
    assert settings.admin_ui_session_secret is None
    assert settings.admin_ui_session_max_age_seconds == 12 * 60 * 60


def test_blank_admin_ui_secrets_normalize_to_none():
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        admin_ui_password="",
        admin_ui_session_secret="",
    )

    assert settings.admin_ui_password is None
    assert settings.admin_ui_session_secret is None
```

- [ ] **Step 2: Run failing settings tests**

Run:

```bash
uv run --extra dev pytest tests/test_config.py::test_admin_ui_defaults tests/test_config.py::test_blank_admin_ui_secrets_normalize_to_none -q
```

Expected: fail with `AttributeError` for missing `admin_ui_password` or `admin_ui_session_secret`.

- [ ] **Step 3: Add settings fields**

In `src/banorte_agent/config.py`, add fields after `admin_api_key`:

```python
    admin_ui_password: str | None = Field(default=None, alias="ADMIN_UI_PASSWORD")
    admin_ui_session_secret: str | None = Field(default=None, alias="ADMIN_UI_SESSION_SECRET")
    admin_ui_session_max_age_seconds: int = Field(
        default=12 * 60 * 60,
        gt=0,
        alias="ADMIN_UI_SESSION_MAX_AGE_SECONDS",
    )
```

Update the existing optional-secret validator decorator:

```python
    @field_validator(
        "github_token",
        "github_commit_author_email",
        "admin_ui_password",
        "admin_ui_session_secret",
        mode="before",
    )
```

- [ ] **Step 4: Document env vars**

Append to `.env.example` after `ADMIN_API_KEY=`:

```dotenv
ADMIN_UI_PASSWORD=
ADMIN_UI_SESSION_SECRET=
ADMIN_UI_SESSION_MAX_AGE_SECONDS=43200
```

- [ ] **Step 5: Verify settings tests pass**

Run:

```bash
uv run --extra dev pytest tests/test_config.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/banorte_agent/config.py .env.example tests/test_config.py
git commit -m "feat: add admin ui settings"
```

## Task 2: Session Helpers And Login Routes

**Files:**
- Create: `src/banorte_agent/admin/ui.py`
- Test: `tests/test_admin_ui.py`

- [ ] **Step 1: Write failing UI auth tests**

Create `tests/test_admin_ui.py`:

```python
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
    assert response.cookies.get("banorte_admin_session") == ""
```

- [ ] **Step 2: Run failing UI auth tests**

Run:

```bash
uv run --extra dev pytest tests/test_admin_ui.py -q
```

Expected: fail because `/admin/login` and `/admin/logout` do not exist.

- [ ] **Step 3: Implement session helpers and login/logout routes**

Create `src/banorte_agent/admin/ui.py`:

```python
from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from banorte_agent.config import Settings


SESSION_COOKIE = "banorte_admin_session"


def build_admin_ui_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    def require_ui_enabled() -> None:
        if not settings.admin_ui_password or not settings.admin_ui_session_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admin UI is disabled",
            )

    def require_admin_session(
        session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> None:
        require_ui_enabled()
        if not session or not _verify_session(session, settings):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")

    @router.get("/admin/login", response_class=HTMLResponse)
    def login_page(_: Annotated[None, Depends(require_ui_enabled)]) -> HTMLResponse:
        return HTMLResponse(_login_html())

    @router.post("/admin/login", response_class=HTMLResponse)
    def login(
        request: Request,
        _: Annotated[None, Depends(require_ui_enabled)],
        password: Annotated[str, Form()],
    ) -> Response:
        if not hmac.compare_digest(password, settings.admin_ui_password or ""):
            return HTMLResponse(_login_html("Invalid password"), status_code=status.HTTP_401_UNAUTHORIZED)
        response = RedirectResponse("/admin/ui", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            SESSION_COOKIE,
            _sign_session(settings),
            httponly=True,
            secure=_is_secure_request(request),
            samesite="lax",
            max_age=settings.admin_ui_session_max_age_seconds,
            path="/admin",
        )
        return response

    @router.post("/admin/logout")
    def logout() -> RedirectResponse:
        response = RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie(SESSION_COOKIE, path="/admin")
        return response

    @router.get("/admin/ui", response_class=HTMLResponse)
    def dashboard(_: Annotated[None, Depends(require_admin_session)]) -> HTMLResponse:
        return HTMLResponse(_dashboard_html())

    return router


def _is_secure_request(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def _sign_session(settings: Settings) -> str:
    now = int(datetime.now(UTC).timestamp())
    payload = {
        "iat": now,
        "exp": now + settings.admin_ui_session_max_age_seconds,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded_payload = urlsafe_b64encode(payload_bytes).decode("ascii")
    signature = hmac.new(
        (settings.admin_ui_session_secret or "").encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded_payload}.{signature}"


def _verify_session(value: str, settings: Settings) -> bool:
    try:
        encoded_payload, signature = value.split(".", 1)
    except ValueError:
        return False
    expected = hmac.new(
        (settings.admin_ui_session_secret or "").encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        payload = json.loads(urlsafe_b64decode(encoded_payload.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return False
    return int(payload.get("exp", 0)) >= int(datetime.now(UTC).timestamp())


def _login_html(error: str | None = None) -> str:
    error_html = f'<p class="error">{_escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Admin Dashboard Login</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; background: #f5f7fb; color: #1f2937; }}
    main {{ max-width: 360px; margin: 12vh auto; padding: 24px; background: white; border: 1px solid #d8dee9; border-radius: 8px; }}
    label, input, button {{ display: block; width: 100%; box-sizing: border-box; }}
    input {{ margin: 8px 0 16px; padding: 10px; border: 1px solid #b8c0cc; border-radius: 6px; }}
    button {{ padding: 10px; border: 0; border-radius: 6px; background: #1f6feb; color: white; font-weight: 600; }}
    .error {{ color: #b42318; }}
  </style>
</head>
<body>
  <main>
    <h1>Admin Dashboard</h1>
    {error_html}
    <form method="post" action="/admin/login">
      <label>Password<input type="password" name="password" autocomplete="current-password" required></label>
      <button type="submit">Log in</button>
    </form>
  </main>
</body>
</html>"""


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Admin Dashboard</title></head>
<body><main data-admin-dashboard><h1>Admin Dashboard</h1></main></body>
</html>"""


def _escape(value: str | None) -> str:
    return (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
```

- [ ] **Step 4: Wire router in app**

In `src/banorte_agent/main.py`, import:

```python
from banorte_agent.admin.ui import build_admin_ui_router
```

Inside `create_app`, after `app.include_router(build_health_router(settings))`, add:

```python
    app.include_router(build_admin_ui_router(settings))
```

- [ ] **Step 5: Verify UI auth tests pass**

Run:

```bash
uv run --extra dev pytest tests/test_admin_ui.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/banorte_agent/admin/ui.py src/banorte_agent/main.py tests/test_admin_ui.py
git commit -m "feat: add admin ui login"
```

## Task 3: Reusable Admin Actions

**Files:**
- Modify: `src/banorte_agent/api/admin.py`
- Test: `tests/test_admin.py`

- [ ] **Step 1: Write refactor safety tests**

Append to `tests/test_admin.py`:

```python
def test_admin_status_payload_helper_redacts_secrets(tmp_path, monkeypatch):
    from banorte_agent.api.admin import build_admin_status_payload

    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        github_token="secret-token",
    )

    class FakeGitHub:
        def __init__(self, settings):
            pass

        def status(self):
            return {
                "configured": True,
                "connected": True,
                "base_branch": "main",
                "pending_wiki_changes": False,
                "error": None,
            }

    monkeypatch.setattr("banorte_agent.api.admin.GitHubAdminService", FakeGitHub)

    payload = build_admin_status_payload(settings)

    assert payload["status"] == "ok"
    assert payload["wiki"]["upload_dir"].endswith("raw/uploads")
    assert payload["github"]["connected"] is True
    assert "secret-token" not in str(payload)
```

- [ ] **Step 2: Run failing helper test**

Run:

```bash
uv run --extra dev pytest tests/test_admin.py::test_admin_status_payload_helper_redacts_secrets -q
```

Expected: fail because `build_admin_status_payload` does not exist.

- [ ] **Step 3: Extract reusable helpers**

In `src/banorte_agent/api/admin.py`, add after `_read_upload`:

```python
def build_admin_status_payload(settings: Settings) -> dict[str, object]:
    uploads = upload_directory(settings.wiki_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    return {
        "status": "ok",
        "admin": {"enabled": bool(settings.admin_api_key)},
        "wiki": {
            "dir": settings.wiki_dir,
            "upload_dir": str(uploads),
            "upload_dir_writable": uploads.exists() and os.access(uploads, os.W_OK),
        },
        "ingestion": {"mode": settings.ingestion_mode},
        "github": GitHubAdminService(settings).status(),
    }


def publish_wiki_payload(settings: Settings) -> dict[str, object]:
    try:
        return GitHubAdminService(settings).publish()
    except RuntimeError as exc:
        detail = _redact_detail(str(exc), settings)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc
    except HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_github_http_error_detail(exc, settings)) from exc
    except (URLError, OSError) as exc:
        detail = _redact_detail(f"GitHub publish failed: {exc}", settings)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc
```

Change existing `/admin/status` route body to:

```python
        return build_admin_status_payload(settings)
```

Change existing `/admin/publish` route body to:

```python
        return publish_wiki_payload(settings)
```

- [ ] **Step 4: Verify admin API tests pass**

Run:

```bash
uv run --extra dev pytest tests/test_admin.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/banorte_agent/api/admin.py tests/test_admin.py
git commit -m "refactor: share admin action helpers"
```

## Task 4: Dashboard And UI Status Proxy

**Files:**
- Modify: `src/banorte_agent/admin/ui.py`
- Test: `tests/test_admin_ui.py`

- [ ] **Step 1: Write failing dashboard/status tests**

Append to `tests/test_admin_ui.py`:

```python
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
```

- [ ] **Step 2: Run failing dashboard/status tests**

Run:

```bash
uv run --extra dev pytest tests/test_admin_ui.py::test_dashboard_requires_session tests/test_admin_ui.py::test_dashboard_renders_status_tiles_and_actions tests/test_admin_ui.py::test_ui_status_requires_session tests/test_admin_ui.py::test_ui_status_returns_payload_without_secrets -q
```

Expected: fail because dashboard currently returns minimal HTML and `/admin/ui/status` does not exist.

- [ ] **Step 3: Implement redirecting session dependency and status proxy**

In `src/banorte_agent/admin/ui.py`, import:

```python
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from banorte_agent.api.admin import build_admin_status_payload
```

Replace `require_admin_session` with:

```python
    def require_admin_session(
        session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> None:
        require_ui_enabled()
        if not session or not _verify_session(session, settings):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")

    def require_dashboard_session(
        session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> None:
        require_ui_enabled()
        if not session or not _verify_session(session, settings):
            raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"location": "/admin/login"})
```

Change the dashboard route dependency to `require_dashboard_session`.

Add a UI status route:

```python
    @router.get("/admin/ui/status")
    def ui_status(_: Annotated[None, Depends(require_admin_session)]) -> dict[str, object]:
        return build_admin_status_payload(settings)
```

- [ ] **Step 4: Replace dashboard HTML**

Replace `_dashboard_html()` in `src/banorte_agent/admin/ui.py`:

```python
def _dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Admin Dashboard</title>
  <style>
    :root { color-scheme: light; }
    body { margin: 0; font-family: system-ui, sans-serif; background: #f5f7fb; color: #1f2937; }
    header { display: flex; justify-content: space-between; gap: 16px; align-items: center; padding: 20px 24px; background: #111827; color: white; }
    main { max-width: 1120px; margin: 0 auto; padding: 24px; }
    button, input { font: inherit; }
    button { border: 0; border-radius: 6px; padding: 10px 14px; background: #1f6feb; color: white; font-weight: 600; cursor: pointer; }
    button.secondary { background: #4b5563; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 20px 0; }
    .tile { border: 1px solid #d8dee9; border-radius: 8px; background: white; padding: 14px; min-height: 82px; }
    .tile strong { display: block; font-size: 13px; color: #4b5563; margin-bottom: 8px; }
    .tile span { font-size: 20px; font-weight: 700; word-break: break-word; }
    .ok { border-top: 5px solid #1a7f37; }
    .bad { border-top: 5px solid #d1242f; }
    .warn { border-top: 5px solid #bf8700; }
    .neutral { border-top: 5px solid #64748b; }
    section { margin-top: 22px; padding: 18px; border: 1px solid #d8dee9; border-radius: 8px; background: white; }
    form.inline { display: inline; }
    input[type=file] { display: block; margin: 12px 0; }
    pre { white-space: pre-wrap; background: #0f172a; color: #e5e7eb; padding: 12px; border-radius: 8px; overflow: auto; }
    .muted { color: #64748b; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Admin Dashboard</h1>
      <div class="muted">Last updated: <span data-last-updated>Never</span></div>
    </div>
    <form class="inline" method="post" action="/admin/logout"><button class="secondary" type="submit">Log out</button></form>
  </header>
  <main>
    <div class="actions"><button type="button" data-refresh-button>Refresh</button></div>
    <div class="grid" data-status-grid></div>
    <section>
      <h2>Upload Document</h2>
      <form data-upload-form>
        <input type="file" name="file" accept="application/pdf,.pdf" required>
        <button type="submit">Upload PDF</button>
      </form>
      <pre data-upload-result>Waiting for upload.</pre>
    </section>
    <section>
      <h2>Publish Wiki</h2>
      <button type="button" data-publish-button>Publish changes</button>
      <pre data-publish-result>Waiting for publish.</pre>
    </section>
  </main>
  <script>
    const grid = document.querySelector("[data-status-grid]");
    const lastUpdated = document.querySelector("[data-last-updated]");
    const uploadForm = document.querySelector("[data-upload-form]");
    const uploadResult = document.querySelector("[data-upload-result]");
    const publishResult = document.querySelector("[data-publish-result]");
    const publishButton = document.querySelector("[data-publish-button]");
    const refreshButton = document.querySelector("[data-refresh-button]");

    function tile(label, value, state) {
      return `<div class="tile ${state}"><strong>${label}</strong><span>${value}</span></div>`;
    }
    function yesNo(value) { return value ? "OK" : "No"; }
    function renderStatus(data) {
      const github = data.github || {};
      const wiki = data.wiki || {};
      grid.innerHTML = [
        tile("Admin UI", "Enabled", "ok"),
        tile("Wiki writable", yesNo(wiki.upload_dir_writable), wiki.upload_dir_writable ? "ok" : "bad"),
        tile("Upload directory", wiki.upload_dir || "Unknown", wiki.upload_dir_writable ? "ok" : "bad"),
        tile("GitHub configured", yesNo(github.configured), github.configured ? "ok" : "bad"),
        tile("GitHub connected", yesNo(github.connected), github.connected ? "ok" : "bad"),
        tile("Pending changes", github.pending_wiki_changes ? "Pending" : "None", github.pending_wiki_changes ? "warn" : "ok"),
        tile("Ingestion mode", (data.ingestion || {}).mode || "Unknown", "neutral"),
        tile("GitHub error", github.error || "None", github.error ? "bad" : "ok")
      ].join("");
      lastUpdated.textContent = new Date().toLocaleTimeString();
    }
    async function refreshStatus() {
      try {
        const response = await fetch("/admin/ui/status");
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || response.statusText);
        renderStatus(data);
      } catch (error) {
        grid.innerHTML = tile("Dashboard refresh", error.message, "bad");
      }
    }
    uploadForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      uploadResult.textContent = "Uploading...";
      const response = await fetch("/admin/ui/documents", { method: "POST", body: new FormData(uploadForm) });
      const data = await response.json();
      uploadResult.textContent = JSON.stringify(data, null, 2);
      refreshStatus();
    });
    publishButton.addEventListener("click", async () => {
      publishResult.textContent = "Publishing...";
      const response = await fetch("/admin/ui/publish", { method: "POST" });
      const data = await response.json();
      publishResult.textContent = JSON.stringify(data, null, 2);
      refreshStatus();
    });
    refreshButton.addEventListener("click", refreshStatus);
    refreshStatus();
    setInterval(refreshStatus, 10000);
  </script>
</body>
</html>"""
```

- [ ] **Step 5: Verify dashboard/status tests pass**

Run:

```bash
uv run --extra dev pytest tests/test_admin_ui.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/banorte_agent/admin/ui.py tests/test_admin_ui.py
git commit -m "feat: add admin dashboard"
```

## Task 5: UI Upload And Publish Proxies

**Files:**
- Modify: `src/banorte_agent/admin/ui.py`
- Test: `tests/test_admin_ui.py`

- [ ] **Step 1: Write failing UI action tests**

Append to `tests/test_admin_ui.py`:

```python
def test_ui_upload_requires_session(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).post(
        "/admin/ui/documents",
        files={"file": ("cv.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 401


def test_ui_upload_reuses_document_upload_behavior(tmp_path, monkeypatch):
    settings = ui_settings(tmp_path)
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))
    client.post("/admin/login", data={"password": "ui-secret"})

    class Extracted:
        kind = "pdf"
        needs_ocr = False
        text = "retrievable text " * 20
        sha256 = "a" * 64

    class Result:
        source_page = Path("sources/uploaded.md")

    monkeypatch.setattr("banorte_agent.api.admin.extract_source", lambda path: Extracted())
    monkeypatch.setattr("banorte_agent.api.admin.IngestionService.ingest_file", lambda self, path: Result())
    monkeypatch.setattr("banorte_agent.api.admin.wiki_has_changes", lambda settings: True)

    response = client.post(
        "/admin/ui/documents",
        files={"file": ("Uploaded PDF.pdf", b"%PDF-1.4 text", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["document"]["filename"] == "Uploaded-PDF.pdf"
    assert response.json()["publish"]["pending"] is True


def test_ui_publish_requires_session(tmp_path):
    response = TestClient(
        create_app(settings=ui_settings(tmp_path), agent_answerer=lambda text, instructions=None: "ok")
    ).post("/admin/ui/publish")

    assert response.status_code == 401


def test_ui_publish_returns_redacted_result(tmp_path, monkeypatch):
    settings = ui_settings(tmp_path, github_token="secret-token")
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))
    client.post("/admin/login", data={"password": "ui-secret"})

    class FakeGitHub:
        def __init__(self, settings):
            pass

        def publish(self):
            return {
                "status": "ok",
                "branch": "wiki/upload-test",
                "commit": "abc123",
                "pull_request_url": "https://github.com/uthynauta/cv-agent/pull/99",
                "changed_files": ["wiki/index.md"],
            }

    monkeypatch.setattr("banorte_agent.api.admin.GitHubAdminService", FakeGitHub)

    response = client.post("/admin/ui/publish")

    assert response.status_code == 200
    assert response.json()["pull_request_url"].endswith("/99")
    assert "secret-token" not in response.text
```

- [ ] **Step 2: Run failing UI action tests**

Run:

```bash
uv run --extra dev pytest tests/test_admin_ui.py::test_ui_upload_requires_session tests/test_admin_ui.py::test_ui_upload_reuses_document_upload_behavior tests/test_admin_ui.py::test_ui_publish_requires_session tests/test_admin_ui.py::test_ui_publish_returns_redacted_result -q
```

Expected: fail because `/admin/ui/documents` and `/admin/ui/publish` do not exist.

- [ ] **Step 3: Extract reusable upload helper**

In `src/banorte_agent/api/admin.py`, add:

```python
async def upload_document_payload(
    settings: Settings,
    ingestion: IngestionService,
    file: UploadFile,
) -> dict[str, object]:
    try:
        filename = safe_upload_filename(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    data = await _read_upload(file, settings.admin_upload_max_bytes)
    target_dir = upload_directory(settings.wiki_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"{timestamp}-{filename}"
    target.write_bytes(data)

    try:
        extracted = extract_source(target)
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PDF is unreadable") from exc
    if extracted.needs_ocr:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="PDF requires OCR before upload",
        )

    result = ingestion.ingest_file(target)
    return {
        "status": "ok",
        "document": {
            "filename": filename,
            "path": str(target.relative_to(Path(settings.wiki_dir))),
            "kind": extracted.kind,
        },
        "ingestion": {
            "count": 1,
            "sources": [str(result.source_page)],
        },
        "publish": {
            "pending": wiki_has_changes(settings),
        },
    }
```

Replace the existing `/admin/documents` route body with:

```python
        return await upload_document_payload(settings, ingestion, file)
```

- [ ] **Step 4: Add UI proxy routes**

In `src/banorte_agent/admin/ui.py`, import:

```python
from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from banorte_agent.api.admin import build_admin_status_payload, publish_wiki_payload, upload_document_payload
from banorte_agent.wiki.ingest import IngestionService
from banorte_agent.wiki.repository import WikiRepository
```

Add inside `build_admin_ui_router` after `/admin/ui/status`:

```python
    @router.post("/admin/ui/documents")
    async def ui_upload_document(
        _: Annotated[None, Depends(require_admin_session)],
        file: UploadFile = File(...),
    ) -> dict[str, object]:
        ingestion = IngestionService(WikiRepository(Path(settings.wiki_dir)), settings)
        return await upload_document_payload(settings, ingestion, file)

    @router.post("/admin/ui/publish")
    def ui_publish(_: Annotated[None, Depends(require_admin_session)]) -> dict[str, object]:
        return publish_wiki_payload(settings)
```

Add `from pathlib import Path`.

- [ ] **Step 5: Verify UI action and API tests pass**

Run:

```bash
uv run --extra dev pytest tests/test_admin_ui.py tests/test_admin.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/banorte_agent/admin/ui.py src/banorte_agent/api/admin.py tests/test_admin_ui.py
git commit -m "feat: add admin ui actions"
```

## Task 6: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/deployment.md`

- [ ] **Step 1: Update README**

In `README.md`, after the admin curl examples, add:

```markdown
### Browser Admin Dashboard

Set these environment variables to enable the browser UI:

```text
ADMIN_UI_PASSWORD=...
ADMIN_UI_SESSION_SECRET=...
ADMIN_UI_SESSION_MAX_AGE_SECONDS=43200
```

Open:

```text
https://banorte-cv-agent.onrender.com/admin/login
```

The dashboard shows storage, ingestion, and GitHub publish status, refreshes automatically, supports PDF upload, and can trigger manual wiki publish. The browser UI uses a signed session cookie and does not expose `ADMIN_API_KEY` or `GITHUB_TOKEN`.
```

- [ ] **Step 2: Update deployment docs**

In `docs/deployment.md`, add to the admin/GitHub environment section:

```markdown
For the browser admin dashboard, configure:

- `ADMIN_UI_PASSWORD`: password entered at `/admin/login`.
- `ADMIN_UI_SESSION_SECRET`: long random signing secret for browser sessions.
- `ADMIN_UI_SESSION_MAX_AGE_SECONDS=43200`: optional session lifetime.

Use a different value from `ADMIN_API_KEY` so browser access and curl automation can be rotated independently.
```

- [ ] **Step 3: Verify docs references**

Run:

```bash
rg -n "ADMIN_UI_PASSWORD|ADMIN_UI_SESSION_SECRET|admin/login|browser admin" README.md docs/deployment.md
```

Expected: references appear in both docs files.

- [ ] **Step 4: Commit**

Run:

```bash
git add README.md docs/deployment.md
git commit -m "docs: document admin ui dashboard"
```

## Task 7: Final Verification

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run full tests**

Run:

```bash
uv run --extra dev pytest
```

Expected: all tests pass.

- [ ] **Step 2: Run app import smoke check**

Run:

```bash
uv run python -c "from banorte_agent.main import create_app; app = create_app(); print(app.title)"
```

Expected output:

```text
Banorte CV Agent
```

- [ ] **Step 3: Optional local browser smoke test**

Run:

```bash
ADMIN_UI_PASSWORD=ui-secret ADMIN_UI_SESSION_SECRET=session-secret ADMIN_API_KEY=admin-secret INGESTION_MODE=deterministic uv run uvicorn banorte_agent.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
curl -sS http://127.0.0.1:8000/admin/login | rg "Admin Dashboard"
```

Expected: login page HTML contains `Admin Dashboard`.

- [ ] **Step 4: Inspect git state**

Run:

```bash
git status --short --branch
git log --oneline -8
```

Expected: working tree clean after commits; branch ahead of `origin/main` with admin UI commits.

## Self-Review

Spec coverage:

- Browser dashboard on existing Render app URL: Tasks 2, 4.
- Separate `ADMIN_UI_PASSWORD`: Task 1 and Task 2.
- Signed HttpOnly session cookie: Task 2.
- Status tiles, auto-refresh, last updated: Task 4.
- Upload PDF and publish actions: Task 5.
- No browser exposure of `ADMIN_API_KEY` or `GITHUB_TOKEN`: Tasks 4 and 5 use session-only UI proxy routes.
- Existing bearer-token API unchanged: Tasks 3 and 5 preserve existing tests.
- Docs: Task 6.

Placeholder scan:

- No incomplete implementation gaps remain.
- No undefined functions are referenced before their task creates them.

Type consistency:

- `build_admin_status_payload`, `publish_wiki_payload`, and `upload_document_payload` are introduced in `api/admin.py` before UI routes import them.
- `build_admin_ui_router(settings)` is introduced before `main.py` includes it.
- New `Settings` fields match `.env.example`, tests, and docs.
