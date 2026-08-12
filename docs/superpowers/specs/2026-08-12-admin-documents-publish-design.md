# Admin Documents And Wiki Publish Design

## Context

The Banorte CV Agent already exposes a protected admin ingestion endpoint:

- `POST /admin/ingest`
- Enabled only when `ADMIN_API_KEY` is configured.
- Accepts an existing server-side path under `WIKI_DIR/raw`.
- Runs the current ingestion pipeline over that file or directory.

The ingestion pipeline already supports `.pdf`, `.md`, and `.tex` sources. Markdown and LaTeX sources remain Git-managed. The missing workflow is uploading text-retrievable PDFs at runtime, ingesting them into the wiki, and later publishing the generated wiki changes back to GitHub through a manual admin action.

Render's default filesystem is ephemeral. Runtime uploads must live on a Render Persistent Disk or an external object store to survive restarts and redeploys. Version 1 uses a Render Persistent Disk because it is simpler and fits the single-instance Banorte review deployment.

## Goals

- Let an admin upload a text-retrievable PDF with curl or a future UI.
- Save uploaded PDFs under the wiki raw tree.
- Ingest uploaded PDFs immediately after upload.
- Keep GitHub publishing manual, so multiple uploads can be batched into one pull request.
- Expose admin-only status for upload storage and GitHub connectivity.
- Keep public readiness focused on the answer-serving agent, not GitHub admin dependencies.
- Keep secrets managed by Render environment variables, never by admin API mutation.

## Non-Goals

- Do not add general environment variable or secret mutation endpoints.
- Do not make GitHub connectivity affect `/readyz`.
- Do not support Markdown or LaTeX upload in version 1.
- Do not implement a full admin web UI yet.
- Do not use Google Drive as persistent runtime storage.

## Deployment Model

Render should attach a Persistent Disk to the web service. Recommended mount path:

```text
/app/data
```

Recommended runtime wiki path after the code supports durable wiki seeding:

```text
WIKI_DIR=/app/data/wiki
```

The service should not be switched to `WIKI_DIR=/app/data/wiki` before the seeding logic is deployed, because an empty persistent wiki can make readiness fail. It is acceptable to create the disk earlier at `/app/data` while leaving `WIKI_DIR=wiki`; the disk will be unused until the env var is changed.

On startup or before the first document operation, the app ensures:

- `WIKI_DIR` exists.
- `WIKI_DIR/raw/uploads` exists.
- If `WIKI_DIR` is empty and the image contains a bundled `/app/wiki`, committed wiki files are copied into `WIKI_DIR`.

The seed step must not overwrite an existing persistent wiki.

## Admin Endpoints

All endpoints use the existing `ADMIN_API_KEY` bearer-token dependency.

### `POST /admin/documents`

Uploads and ingests one PDF.

Request:

- `multipart/form-data`
- Field: `file`
- Accepted content: `.pdf`

Behavior:

1. Authenticate with `Authorization: Bearer <ADMIN_API_KEY>`.
2. Validate that the uploaded filename is safe and has a `.pdf` extension.
3. Enforce a configured upload size limit.
4. Save to `WIKI_DIR/raw/uploads/<safe-unique-name>.pdf`.
5. Extract PDF text using the existing extractor.
6. Reject encrypted, unreadable, or image-only PDFs. Use the current `needs_ocr` threshold as the text-retrievability gate.
7. Run ingestion immediately with the current `INGESTION_MODE`.
8. Return saved path, ingest count, generated source pages, and whether wiki changes are pending publication.

Response shape:

```json
{
  "status": "ok",
  "document": {
    "filename": "example.pdf",
    "path": "wiki/raw/uploads/example.pdf",
    "kind": "pdf"
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
- Current git branch.
- Whether wiki changes are pending publication.
- Last GitHub/status error, if any, without secrets.

GitHub connection failures should make this endpoint report `github.connected=false`; they should not affect public health or readiness.

### `POST /admin/publish`

Publishes generated wiki changes to GitHub through a pull request.

Behavior:

1. Authenticate with `ADMIN_API_KEY`.
2. Check configured GitHub token, repository, base branch, and commit author settings.
3. Detect changed `wiki/` files.
4. If no wiki changes exist, return a no-op result.
5. Create a unique branch, for example `wiki/upload-YYYYMMDD-HHMMSS`.
6. Commit the changed wiki files.
7. Push the branch.
8. Open a pull request against the configured base branch.
9. Return branch name, commit SHA, PR URL, and changed files.

Publish should be manual rather than automatic. Upload and ingestion can succeed even if GitHub auth, network, or PR creation fails.

## Configuration

New environment variables:

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
  -> validate PDF
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
  -> detect changed wiki files
  -> create branch
  -> commit
  -> push
  -> create PR
  -> return PR details
```

## Error Handling

- Missing `ADMIN_API_KEY`: existing `503` disabled behavior.
- Missing or invalid bearer token: existing `401`.
- Non-PDF upload: `400`.
- Unsafe filename: `400`.
- Oversized upload: `413`.
- Encrypted/unreadable PDF: `400`.
- Image-only or low-text PDF: `422`, with a message that OCR is required.
- Ingestion failure: `500`, with request ID and no raw document text in logs.
- GitHub not configured: admin status reports unavailable; publish returns `503`.
- GitHub push or PR failure: publish returns `502` or `503` with a redacted error.
- No wiki changes: publish returns `200` with `"status": "noop"`.

## Security

- Reuse the existing admin bearer-token dependency.
- Never log uploaded PDF contents, extracted text, or secrets.
- Restrict writes to `WIKI_DIR/raw/uploads`.
- Normalize filenames and add uniqueness to avoid overwrites.
- Return relative wiki paths where possible.
- Keep GitHub token in Render env vars only.
- Keep public `/readyz` independent of GitHub status.

## Testing

Add focused tests for:

- Upload requires admin auth.
- Upload rejects non-PDF files.
- Upload rejects unsafe filenames.
- Upload rejects low-text PDFs.
- Upload saves under `raw/uploads`.
- Upload runs ingestion immediately.
- Upload response reports pending publication.
- Admin status redacts secrets and reports GitHub configuration/connection.
- Public `/readyz` does not depend on GitHub.
- Publish no-ops with no wiki changes.
- Publish creates branch/commit/PR through mocked GitHub integration when wiki changes exist.
- Publish reports redacted failures when GitHub is unavailable.

Existing admin ingest tests remain valid.

