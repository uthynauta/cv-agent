# Admin Documents And Wiki Publish Design

## Context

The Banorte CV Agent already exposes a protected admin ingestion endpoint:

- `POST /admin/ingest`
- Enabled only when `ADMIN_API_KEY` is configured.
- Accepts an existing server-side path under `WIKI_DIR/raw`.
- Runs the current ingestion pipeline over that file or directory.

The ingestion pipeline supports `.pdf`, `.md`, and `.tex` sources. Runtime document upload, immediate wiki ingestion, admin status, and manual GitHub PR publishing are implemented as protected admin workflows. A browser dashboard is implemented separately and reuses these same service functions.

Render's default filesystem is ephemeral. Runtime uploads must live on a Render Persistent Disk or an external object store to survive restarts and redeploys. Version 1 uses a Render Persistent Disk because it is simpler and fits the single-instance Banorte review deployment.

## Goals

- Let an admin upload a `.pdf`, `.md`, or `.tex` source document with curl or the browser dashboard.
- Save uploaded source documents under the wiki raw tree.
- Ingest uploaded documents immediately after upload.
- Keep GitHub publishing manual, so multiple uploads can be batched into one pull request.
- Expose admin-only status for upload storage and GitHub connectivity.
- Keep public readiness focused on the answer-serving agent, not GitHub admin dependencies.
- Keep secrets managed by Render environment variables, never by admin API mutation.

## Non-Goals

- Do not add general environment variable or secret mutation endpoints.
- Do not make GitHub connectivity affect `/readyz`.
- Do not use Google Drive as persistent runtime storage.

## Deployment Model

Render should attach a Persistent Disk to the web service. Recommended mount path:

```text
/app/data
```

Recommended runtime wiki path:

```text
WIKI_DIR=/app/data/wiki
```

Do not switch `WIKI_DIR` to `/app/data/wiki` before deploying the storage seeding code. An empty persistent wiki can make readiness fail. Creating the disk earlier is safe if `WIKI_DIR` remains `wiki`; the disk will be unused until the env var is changed.

On startup or before the first document operation, the app ensures:

- `WIKI_DIR` exists.
- `WIKI_DIR/raw/uploads` exists.
- If `WIKI_DIR` is empty and the image contains a bundled `/app/wiki`, committed wiki files are copied into `WIKI_DIR`.

The seed step must not overwrite an existing persistent wiki.

## Admin Endpoints

All endpoints use the existing `ADMIN_API_KEY` bearer-token dependency.

### `POST /admin/documents`

Uploads and ingests one source document.

Request:

- `multipart/form-data`
- Field: `file`
- Accepted content: `.pdf`, `.md`, or `.tex`

Behavior:

1. Authenticate with `Authorization: Bearer <ADMIN_API_KEY>`.
2. Validate that the uploaded filename is safe and has a supported extension.
3. Enforce a configured upload size limit.
4. Save to `WIKI_DIR/raw/uploads/<timestamp>-<safe-name>`.
5. Extract text using the existing extractor.
6. Reject encrypted, unreadable, or image-only PDFs. Use the current PDF `needs_ocr` threshold as the text-retrievability gate. Reject unreadable Markdown or LaTeX text files.
7. Run ingestion immediately with the current `INGESTION_MODE`.
8. Return saved path, ingest count, generated source pages, and whether wiki changes are pending publication.

Response shape:

```json
{
  "status": "ok",
  "document": {
    "filename": "example.md",
    "path": "raw/uploads/20260812-190000-example.md",
    "kind": "markdown"
  },
  "ingestion": {
    "count": 1,
    "sources": ["sources/example.md"]
  },
  "publish": {
    "pending": true
  }
}
```

### `GET /admin/status`

Returns admin-only operational status. It must never return secret values.

Fields:

- Admin endpoint enabled.
- Wiki directory path.
- Upload directory path.
- Upload directory writable.
- Ingestion mode.
- GitHub configured.
- GitHub connected.
- Configured GitHub base branch.
- Whether wiki changes are pending publication.
- Last GitHub/status error, if any, without secrets.

GitHub connection failures should make this endpoint report `github.connected=false`; they should not affect public health or readiness.

### `POST /admin/publish`

Publishes generated wiki changes to GitHub through a pull request.

The deployed Docker image must not depend on local `.git` metadata. Runtime wiki files may live on a Render Persistent Disk at `WIKI_DIR=/app/data/wiki`, outside the image's bundled source tree. Therefore publish uses the GitHub API against the configured repository and base branch.

Behavior:

1. Authenticate with `ADMIN_API_KEY`.
2. Check configured GitHub token, repository, base branch, and commit author settings.
3. Compare local `WIKI_DIR` files to the GitHub base branch's `wiki/` tree.
4. If no wiki changes exist, return a no-op result.
5. Create a unique branch, for example `wiki/upload-YYYYMMDD-HHMMSS`.
6. Create one Git tree and commit through the GitHub Git Data API.
7. Create a GitHub ref for the branch.
8. Open a pull request against the configured base branch.
9. Return branch name, commit SHA, PR URL, and changed files.

Publish should be manual rather than automatic. Upload and ingestion can succeed even if GitHub auth, network, or PR creation fails.

## Configuration

Environment variables:

```text
ADMIN_UPLOAD_MAX_BYTES=10485760
GITHUB_TOKEN=
GITHUB_REPOSITORY=uthynauta/cv-agent
GITHUB_BASE_BRANCH=main
GITHUB_COMMIT_AUTHOR_NAME=Banorte Agent Admin
GITHUB_COMMIT_AUTHOR_EMAIL=
```

Secrets are configured in the Render Dashboard. The admin API does not create, update, or reveal secrets.

## Data Flow

Upload:

```text
Admin curl/UI
  -> POST /admin/documents
  -> validate supported extension
  -> write WIKI_DIR/raw/uploads
  -> extract text
  -> ingest
  -> update generated wiki pages
  -> return result
```

Publish:

```text
Admin curl/UI
  -> POST /admin/publish
  -> compare local WIKI_DIR files with GitHub base wiki tree
  -> create branch
  -> create GitHub tree and commit
  -> create PR
  -> return PR details
```

## Error Handling

- Missing `ADMIN_API_KEY`: existing `503` disabled behavior.
- Missing or invalid bearer token: existing `401`.
- Unsupported extension: `400`.
- Unsafe filename: `400`.
- Oversized upload: `413`.
- Encrypted/unreadable PDF or invalid text upload: `400`.
- Image-only or low-text PDF: `422`, with a message that OCR is required.
- Ingestion failure: `500`, with request ID and no raw document text in logs.
- GitHub not configured: admin status reports unavailable; publish returns `503`.
- GitHub compare, commit, ref, or PR failure: publish returns `502` or `503` with a redacted error.
- No wiki changes: publish returns `200` with `"status": "noop"`.

## Security

- Reuse the existing admin bearer-token dependency.
- Never log uploaded document contents, extracted text, or secrets.
- Restrict writes to `WIKI_DIR/raw/uploads`.
- Normalize filenames and add uniqueness to avoid overwrites.
- Return relative wiki paths where possible.
- Keep GitHub token in Render env vars only.
- Keep public `/readyz` independent of GitHub status.

## Testing

Focused tests cover:

- Upload requires admin auth.
- Upload accepts PDF, Markdown, and LaTeX files.
- Upload rejects unsupported extensions.
- Upload rejects unsafe filenames.
- Upload rejects low-text PDFs.
- Upload saves under `raw/uploads`.
- Upload runs ingestion immediately.
- Upload response reports pending publication.
- Admin status redacts secrets and reports GitHub configuration/connection.
- Public `/readyz` does not depend on GitHub.
- Publish no-ops with no wiki changes.
- Publish creates branch/tree/commit/PR through mocked GitHub API integration when wiki changes exist.
- Publish reports redacted failures when GitHub is unavailable.

Existing admin ingest tests remain valid.
