# Admin UI Dashboard Design

## Context

The Banorte CV Agent already exposes protected admin JSON endpoints:

- `GET /admin/status`
- `POST /admin/documents`
- `POST /admin/publish`
- `POST /admin/ingest`

These endpoints are useful from curl, but routine document upload and publish flows are easier from a browser. Render exposes one public web service port, so the admin UI is served by the existing FastAPI app rather than by a separate frontend service.

## Goals

- Provide a simple browser admin dashboard on the existing Render app URL.
- Keep the current bearer-token admin API unchanged for curl and automation.
- Add a browser login flow protected by a separate `ADMIN_UI_PASSWORD`.
- Show status tiles with green, red, yellow, or neutral state.
- Auto-refresh status and show the last updated time.
- Let an admin upload a `.pdf`, `.md`, or `.tex` source document.
- Let an admin trigger manual GitHub publish.
- Show success, errors, and pull request URLs clearly.
- Document how admins update the wiki from browser and curl.

## Non-Goals

- Do not build a React/Vite frontend.
- Do not add multi-user accounts, roles, password reset, or database-backed sessions.
- Do not expose or edit secrets through the dashboard.
- Do not replace the existing bearer-token admin API.
- Do not add document delete/edit workflows in version 1.
- Do not accept image-only scanned PDFs without OCR.

## Architecture

The implemented UI uses server-rendered HTML served by FastAPI:

- `GET /admin/login`: login page.
- `POST /admin/login`: validate password and set an HttpOnly signed session cookie.
- `POST /admin/logout`: clear the session cookie.
- `GET /admin/ui`: dashboard page, protected by the session cookie.
- Existing JSON endpoints remain protected by `ADMIN_API_KEY` bearer auth.
- UI-specific JSON proxy endpoints avoid exposing `ADMIN_API_KEY` in browser JavaScript.

The browser login must use `ADMIN_UI_PASSWORD`, not `ADMIN_API_KEY`. This keeps UI access separately rotatable from automation tokens.

## Authentication

Environment variables:

```text
ADMIN_UI_PASSWORD=
ADMIN_UI_SESSION_SECRET=
ADMIN_UI_SESSION_MAX_AGE_SECONDS=43200
```

Behavior:

- If `ADMIN_UI_PASSWORD` or `ADMIN_UI_SESSION_SECRET` is unset, UI routes return `503`.
- Login compares submitted password with `ADMIN_UI_PASSWORD` using constant-time comparison.
- On success, the app sets a signed cookie with:
  - `HttpOnly`
  - `Secure` when request scheme is HTTPS or `X-Forwarded-Proto=https`
  - `SameSite=Lax`
  - bounded max age
- The cookie payload contains only issued-at/expiry metadata, no secrets.
- Logout clears the cookie.

## Dashboard

`GET /admin/ui` renders a compact operational dashboard:

- Header with service name, logout button, and last updated timestamp.
- Status tiles:
  - Admin UI enabled.
  - Wiki storage writable.
  - Upload directory writable.
  - GitHub configured.
  - GitHub connected.
  - Pending wiki changes.
  - Ingestion mode.
  - Last publish result.
- Upload form:
  - Document file input accepting `.pdf`, `.md`, and `.tex`.
  - Upload button.
  - Result area showing saved path and generated source pages.
- Publish action:
  - Publish button.
  - Result area showing no-op, PR URL, commit SHA, changed files, or redacted error.
- Refresh button.

Tile colors:

- Green: healthy/available/connected/no blocking issue.
- Red: unavailable/error.
- Yellow: action needed, such as pending wiki changes.
- Neutral: informational value, such as ingestion mode.

The dashboard auto-refreshes status every 10 seconds and updates the "Last updated" timestamp after every successful status fetch. Failed refreshes mark the dashboard status as red and show the redacted error message.

## Data Flow

Login:

```text
Browser
  -> GET /admin/login
  -> POST /admin/login password
  -> signed session cookie
  -> redirect /admin/ui
```

Status refresh:

```text
Browser session
  -> UI status endpoint
  -> server calls same status logic as /admin/status
  -> browser updates tiles and timestamp
```

Upload:

```text
Browser session
  -> multipart document upload
  -> server reuses existing document upload service/path
  -> browser displays saved path, generated pages, pending publish state
```

Upload restrictions:

- One file per request.
- Only `.pdf`, `.md`, and `.tex` uploads are accepted.
- PDFs must contain selectable/extractable text.
- Markdown and LaTeX uploads must be readable UTF-8 text.
- Image-only scans, unreadable/encrypted PDFs, and low-text PDFs are rejected.
- Oversized uploads are rejected according to `ADMIN_UPLOAD_MAX_BYTES`.
- Uploaded files are stored under `wiki/raw/uploads`.
- Runtime uploads persist across deploys only when `WIKI_DIR` points at durable storage, for example `/app/data/wiki` on a Render Persistent Disk.

Publish:

```text
Browser session
  -> publish request
  -> server reuses GitHub publish service
  -> browser displays PR URL or redacted error
```

Publish behavior:

- Publish is manual.
- The app creates a GitHub branch, commit, and pull request for changed wiki files.
- The app does not merge its own pull request.
- The admin reviews and merges the pull request in GitHub.

## Implementation Boundary

To avoid duplicating admin behavior, small reusable service functions in `api/admin.py` back both route sets:

- Upload document behavior.
- Status payload construction.
- Publish error handling/redaction.

Then both the bearer API routes and UI session routes call the same internal functions.

## Error Handling

- UI disabled: `503` with a short HTML message.
- Bad login: re-render login with a generic invalid password message.
- Missing/expired session: redirect to `/admin/login`.
- Upload validation failure: show the API error in the result area.
- Publish failure: show the redacted API error in the result area.
- Status refresh failure: keep existing page visible, show dashboard error tile.

## Security

- Do not put `ADMIN_API_KEY`, `GITHUB_TOKEN`, or any secret in HTML or JavaScript.
- Do not rely on client-side-only checks for admin access.
- Use signed, HttpOnly cookies for browser access.
- Use constant-time password comparison.
- Keep the dashboard under `/admin/*`.
- Keep all admin actions unavailable when the relevant env vars are unset.
- Manage Render environment variables and secrets in Render, not through the admin UI.

## Operator Workflow

Browser:

1. Deploy the branch containing the admin UI.
2. Configure `ADMIN_UI_PASSWORD`, `ADMIN_UI_SESSION_SECRET`, `ADMIN_API_KEY`, `GITHUB_TOKEN`, and persistent `WIKI_DIR` in Render.
3. Open `/admin/login` and authenticate with `ADMIN_UI_PASSWORD`.
4. Confirm storage and GitHub status tiles are healthy.
5. Upload a `.pdf`, `.md`, or `.tex` source document.
6. Confirm the generated wiki page and pending publish status.
7. Trigger publish.
8. Review and merge the GitHub pull request.

Curl:

```bash
curl -sS https://banorte-cv-agent.onrender.com/admin/documents \
  -H 'Authorization: Bearer YOUR_ADMIN_API_KEY' \
  -F 'file=@/path/to/document.md'
```

The `@` is required so curl uploads file bytes instead of sending the path string.

## Testing

Focused tests cover:

- UI disabled when password or session secret is missing.
- Login page renders when UI env vars are configured.
- Invalid login does not set session.
- Valid login sets a session cookie and redirects to dashboard.
- Dashboard requires session.
- Dashboard renders with status tile containers.
- UI status JSON requires session and does not expose secrets.
- UI upload requires session and reuses existing document upload behavior.
- UI publish requires session and returns redacted publish results.
- Logout clears session.

Existing admin API tests remain valid.
