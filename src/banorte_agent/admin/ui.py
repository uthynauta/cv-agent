import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response

from banorte_agent.config import Settings


SESSION_COOKIE = "banorte_admin_session"


def build_admin_ui_router(settings: Settings) -> APIRouter:
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
        return HTMLResponse(
            """<!doctype html>
<html lang="en">
<head><title>Admin Dashboard</title></head>
<body>
<main data-admin-dashboard>
<h1>Admin Dashboard</h1>
</main>
</body>
</html>"""
        )

    return router
