# Deployment

## Environment

Copy `.env.example` to `.env` and set deployment values. Required public readiness settings are `OPENAI_API_KEY`, `OPENAI_MODEL`, `AGENT_OWNER_NAME`, `AGENT_PUBLIC_URL`, and usable mounted knowledge. `ADMIN_API_KEY` protects document ingestion; `ADMIN_UI_PASSWORD` plus `ADMIN_UI_SESSION_SECRET` enables the browser dashboard. Keep secrets outside source control.

Set `DATA_DIR` to the mounted root. The container image defaults to `/data`, and Compose mounts the host data directory there. Mount the whole root so originals, local Git history, generated pages, and operational files survive restarts.

The service accepts `AGENT_LANGUAGE=auto`, `es`, or `en`; `RETRIEVAL_MODE=lexical` or `llm_rerank`; and `CONTEXT_MODE=page` or `excerpt`. `INGESTION_MODE=deterministic` is useful for offline initialization, while `openai` uses `OPENAI_API_KEY` and `OPENAI_MODEL`.

## Container

```bash
cp .env.example .env
docker compose up -d --build
curl -fsS http://localhost:8000/healthz
curl -i http://localhost:8000/readyz
```

The image installs the Git CLI for local mounted-repository versioning. It does not copy or seed a candidate corpus. The application has no remote Git publishing route or runtime configuration.

## Initialize Knowledge

A new deployment is empty by design. With `ADMIN_API_KEY` configured, upload one source:

```bash
curl -sS http://localhost:8000/admin/documents \
  -H 'Authorization: Bearer YOUR_ADMIN_API_KEY' \
  -F 'file=@/path/to/document.pdf'
```

The upload endpoint validates extension, size, encoding, and extractability; writes the original under `DATA_DIR/documents/`; generates versioned Markdown under `DATA_DIR/repository/`; and creates one local Git revision. Image-only PDFs must be OCR-processed before upload. Inspect the result and status:

```bash
curl -sS http://localhost:8000/admin/status \
  -H 'Authorization: Bearer YOUR_ADMIN_API_KEY'
curl -fsS http://localhost:8000/readyz
```

For an offline local build, place supported files in `DATA_DIR/documents/` and run:

```bash
DATA_DIR=./data INGESTION_MODE=deterministic uv run cv-agent ingest ./data/documents
```

To import an existing legacy wiki, run the migration explicitly before starting the service:

```bash
uv run cv-agent migrate-data --from-wiki /old/wiki --to-data-dir ./data
```

The command validates and commits the imported Markdown in one local Git revision. It refuses a non-empty destination unless `--replace-existing` is supplied; replacement moves the previous directory to a timestamped recovery sibling. Migration is never performed during application startup.

The browser dashboard at `/admin/login` offers document CRUD, rebuild, revision rollback, backup export, and restore when both UI settings are configured. The bearer-authenticated `/admin/*` API exposes the same lifecycle operations. It does not publish to or connect to a remote repository.

## Open Responses Registration

Use the deployment's public URLs, for example:

```text
https://cv-agent.example.com/v1/responses
https://cv-agent.example.com/.well-known/agent-card.json
```

The API is stateless and accepts transcript replay with bounded context. Configure the same `AGENT_API_KEY` with the client when bearer authentication is enabled.

## Backups

Create either a portable knowledge bundle containing local Git history or a full archive containing history, current originals, and a manifest. Backups are stored under `DATA_DIR/backups/` and can be downloaded from the admin API or dashboard. `ADMIN_BACKUP_MAX_BYTES` bounds uploads and generated archives; `BACKUP_RETENTION_COUNT` controls retained artifacts.

Restore requires explicit confirmation, validates and stages the archive before activation, and creates a recovery backup of the current state. A knowledge bundle restores only the versioned repository; a full archive restores both repository and originals. Local Git history and in-volume archives are not off-volume backups, so retain downloaded archives or volume snapshots outside the running container and periodically test restore.

```bash
docker compose down
```
