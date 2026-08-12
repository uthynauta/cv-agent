import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.responses import Response

from banorte_agent.api.admin import build_admin_status_payload, publish_wiki_payload, upload_document_payload
from banorte_agent.config import Settings
from banorte_agent.wiki.ingest import IngestionService


SESSION_COOKIE = "banorte_admin_session"


def build_admin_ui_router(settings: Settings, ingestion: IngestionService) -> APIRouter:
    router = APIRouter()

    def ui_enabled() -> bool:
        return bool(settings.admin_ui_password and settings.admin_ui_session_secret)

    def disabled_response() -> HTMLResponse:
        return HTMLResponse("Admin UI is disabled", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    def login_page(message: str | None = None, status_code: int = status.HTTP_200_OK) -> HTMLResponse:
        error_html = f"<p>{message}</p>" if message else ""
        return HTMLResponse(
            f"""<!doctype html>
<html lang="en">
<head><title>Admin Dashboard</title></head>
<body>
<main>
<h1>Admin Dashboard</h1>
{error_html}
<form method="post" action="/admin/login">
<label>Password <input name="password" type="password" autocomplete="current-password"></label>
<button type="submit">Log in</button>
</form>
</main>
</body>
</html>""",
            status_code=status_code,
        )

    def dashboard_page() -> HTMLResponse:
        return HTMLResponse(
            """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Admin Dashboard</title>
<style>
:root {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f6f7f9;
  color: #17202a;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: #f6f7f9;
}
button, input {
  font: inherit;
}
.shell {
  width: min(1120px, calc(100% - 32px));
  margin: 0 auto;
  padding: 28px 0 40px;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
}
.title h1 {
  margin: 0 0 4px;
  font-size: 28px;
  line-height: 1.2;
}
.title p {
  margin: 0;
  color: #5c6875;
}
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.button {
  border: 1px solid #cfd6df;
  border-radius: 6px;
  background: #ffffff;
  color: #17202a;
  cursor: pointer;
  min-height: 40px;
  padding: 0 14px;
}
.button.primary {
  border-color: #1f6f5b;
  background: #1f6f5b;
  color: #ffffff;
}
.button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.panel {
  background: #ffffff;
  border: 1px solid #dde3ea;
  border-radius: 8px;
  padding: 18px;
}
.layout {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 18px;
  align-items: start;
}
.status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}
.tile {
  border: 1px solid #e1e6ec;
  border-radius: 8px;
  min-height: 116px;
  padding: 16px;
  background: #fbfcfd;
}
.tile span {
  display: block;
  color: #697584;
  font-size: 13px;
  margin-bottom: 8px;
}
.tile strong {
  display: block;
  font-size: 22px;
  line-height: 1.2;
  overflow-wrap: anywhere;
}
.tile small {
  display: block;
  color: #697584;
  margin-top: 8px;
  overflow-wrap: anywhere;
}
.side {
  display: grid;
  gap: 14px;
}
.side h2 {
  margin: 0 0 12px;
  font-size: 17px;
}
.field {
  display: grid;
  gap: 8px;
}
.field input {
  width: 100%;
  border: 1px solid #cfd6df;
  border-radius: 6px;
  min-height: 42px;
  padding: 8px 10px;
  background: #ffffff;
}
.form-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
.message {
  min-height: 20px;
  color: #5c6875;
  font-size: 14px;
  margin-top: 10px;
  overflow-wrap: anywhere;
}
.error { color: #a33a2b; }
.success { color: #1f6f5b; }
.timestamp {
  color: #5c6875;
  font-size: 14px;
}
@media (max-width: 840px) {
  .topbar, .actions {
    align-items: stretch;
    flex-direction: column;
  }
  .layout, .status-grid {
    grid-template-columns: 1fr;
  }
}
</style>
</head>
<body>
<main class="shell" data-admin-dashboard>
  <header class="topbar">
    <div class="title">
      <h1>Admin Dashboard</h1>
      <p class="timestamp">Last updated <span data-last-updated>never</span></p>
    </div>
    <div class="actions">
      <button class="button" type="button" data-refresh-button>Refresh</button>
      <form method="post" action="/admin/logout">
        <button class="button" type="submit">Log out</button>
      </form>
    </div>
  </header>
  <section class="layout">
    <div class="panel">
      <div class="status-grid" data-status-grid>
        <article class="tile">
          <span>Admin API</span>
          <strong data-admin-status>Checking</strong>
          <small>Protected admin routes</small>
        </article>
        <article class="tile">
          <span>Wiki Uploads</span>
          <strong data-upload-status>Checking</strong>
          <small data-upload-dir>Upload directory</small>
        </article>
        <article class="tile">
          <span>GitHub</span>
          <strong data-github-status>Checking</strong>
          <small data-github-detail>Repository connection</small>
        </article>
        <article class="tile">
          <span>Pending Changes</span>
          <strong data-pending-status>Checking</strong>
          <small data-branch-status>Base branch</small>
        </article>
      </div>
      <p class="message" data-status-message></p>
    </div>
    <aside class="side">
      <section class="panel">
        <h2>Upload Document</h2>
        <form data-upload-form>
          <label class="field">
            <span>PDF file</span>
            <input type="file" name="file" accept="application/pdf">
          </label>
          <div class="form-actions">
            <button class="button primary" type="submit">Upload</button>
          </div>
        </form>
        <p class="message" data-upload-message></p>
      </section>
      <section class="panel">
        <h2>Publish Wiki</h2>
        <button class="button primary" type="button" data-publish-button>Publish</button>
        <p class="message" data-publish-message></p>
      </section>
    </aside>
  </section>
</main>
<script>
const text = (selector, value) => {
  const element = document.querySelector(selector);
  if (element) element.textContent = value;
};

const setMessage = (selector, value, className = "") => {
  const element = document.querySelector(selector);
  if (!element) return;
  element.textContent = value;
  element.className = `message ${className}`.trim();
};

async function refreshStatus() {
  try {
    const response = await fetch("/admin/ui/status", {headers: {"Accept": "application/json"}});
    if (!response.ok) throw new Error(`Status request failed: ${response.status}`);
    const payload = await response.json();
    const github = payload.github || {};
    const wiki = payload.wiki || {};
    text("[data-admin-status]", payload.admin && payload.admin.enabled ? "Enabled" : "Disabled");
    text("[data-upload-status]", wiki.upload_dir_writable ? "Writable" : "Unavailable");
    text("[data-upload-dir]", wiki.upload_dir || "Upload directory");
    text("[data-github-status]", github.connected ? "Connected" : (github.configured ? "Configured" : "Not configured"));
    text("[data-github-detail]", github.error || "Repository connection");
    text("[data-pending-status]", github.pending_wiki_changes ? "Pending" : "Clean");
    text("[data-branch-status]", github.base_branch ? `Base branch: ${github.base_branch}` : "Base branch");
    text("[data-last-updated]", new Date().toLocaleString());
    setMessage("[data-status-message]", "");
  } catch (error) {
    setMessage("[data-status-message]", error.message, "error");
  }
}

document.querySelector("[data-refresh-button]")?.addEventListener("click", refreshStatus);
document.querySelector("[data-upload-form]")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  setMessage("[data-upload-message]", "Uploading...");
  try {
    const response = await fetch("/admin/ui/documents", {method: "POST", body: data});
    if (!response.ok) throw new Error(`Upload failed: ${response.status}`);
    setMessage("[data-upload-message]", "Upload complete", "success");
    form.reset();
    refreshStatus();
  } catch (error) {
    setMessage("[data-upload-message]", error.message, "error");
  }
});
document.querySelector("[data-publish-button]")?.addEventListener("click", async () => {
  setMessage("[data-publish-message]", "Publishing...");
  try {
    const response = await fetch("/admin/ui/publish", {method: "POST"});
    if (!response.ok) throw new Error(`Publish failed: ${response.status}`);
    setMessage("[data-publish-message]", "Publish complete", "success");
    refreshStatus();
  } catch (error) {
    setMessage("[data-publish-message]", error.message, "error");
  }
});
refreshStatus();
setInterval(refreshStatus, 10000);
</script>
</body>
</html>"""
        )

    def sign_payload(payload: str) -> str:
        assert settings.admin_ui_session_secret is not None
        digest = hmac.new(
            settings.admin_ui_session_secret.encode("utf-8"),
            payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def encode_payload(payload: dict[str, Any]) -> str:
        data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    def decode_payload(payload: str) -> dict[str, Any] | None:
        try:
            padded = payload + "=" * (-len(payload) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
            parsed = json.loads(decoded)
        except (ValueError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def build_session_token() -> str:
        now = int(time.time())
        payload = encode_payload(
            {
                "iat": now,
                "exp": now + settings.admin_ui_session_max_age_seconds,
            }
        )
        return f"{payload}.{sign_payload(payload)}"

    def verify_session_token(token: str | None) -> bool:
        if not token or "." not in token:
            return False
        payload, signature = token.rsplit(".", 1)
        try:
            payload.encode("ascii")
            signature_bytes = signature.encode("ascii")
        except UnicodeEncodeError:
            return False
        if not hmac.compare_digest(signature_bytes, sign_payload(payload).encode("ascii")):
            return False
        parsed = decode_payload(payload)
        if parsed is None:
            return False
        exp = parsed.get("exp")
        return isinstance(exp, int) and exp >= int(time.time())

    def request_is_https(request: Request) -> bool:
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        return request.url.scheme == "https" or forwarded_proto.split(",", 1)[0].strip().lower() == "https"

    @router.get("/admin/login", response_class=HTMLResponse)
    async def get_login() -> HTMLResponse:
        if not ui_enabled():
            return disabled_response()
        return login_page()

    @router.post("/admin/login")
    async def post_login(request: Request) -> Response:
        if not ui_enabled():
            return disabled_response()
        form = await request.form()
        password = str(form.get("password", ""))
        assert settings.admin_ui_password is not None
        if not hmac.compare_digest(password.encode("utf-8"), settings.admin_ui_password.encode("utf-8")):
            return login_page("Invalid password", status.HTTP_401_UNAUTHORIZED)

        response = RedirectResponse("/admin/ui", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            SESSION_COOKIE,
            build_session_token(),
            httponly=True,
            secure=request_is_https(request),
            samesite="lax",
            path="/admin",
            max_age=settings.admin_ui_session_max_age_seconds,
        )
        return response

    @router.post("/admin/logout")
    async def post_logout() -> RedirectResponse:
        response = RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie(SESSION_COOKIE, path="/admin", samesite="lax")
        return response

    @router.get("/admin/ui", response_class=HTMLResponse)
    async def get_dashboard(request: Request) -> Response:
        if not ui_enabled():
            return disabled_response()
        if not verify_session_token(request.cookies.get(SESSION_COOKIE)):
            return RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)
        return dashboard_page()

    @router.get("/admin/ui/status")
    async def get_ui_status(request: Request) -> Any:
        if not ui_enabled():
            return disabled_response()
        if not verify_session_token(request.cookies.get(SESSION_COOKIE)):
            return JSONResponse({"detail": "invalid session"}, status_code=status.HTTP_401_UNAUTHORIZED)
        return build_admin_status_payload(settings)

    @router.post("/admin/ui/documents")
    async def post_ui_document(request: Request, file: UploadFile = File(...)) -> Any:
        if not ui_enabled():
            return disabled_response()
        if not verify_session_token(request.cookies.get(SESSION_COOKIE)):
            return JSONResponse({"detail": "invalid session"}, status_code=status.HTTP_401_UNAUTHORIZED)
        return await upload_document_payload(settings, ingestion, file)

    @router.post("/admin/ui/publish")
    async def post_ui_publish(request: Request) -> Any:
        if not ui_enabled():
            return disabled_response()
        if not verify_session_token(request.cookies.get(SESSION_COOKIE)):
            return JSONResponse({"detail": "invalid session"}, status_code=status.HTTP_401_UNAUTHORIZED)
        return publish_wiki_payload(settings)

    return router
