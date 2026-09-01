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

The browser dashboard at `/admin/login` offers the same upload and local status workflow when both UI settings are configured. It does not publish to or connect to a remote repository.

## Open Responses Registration

Use the deployment's public URLs, for example:

```text
https://cv-agent.example.com/v1/responses
https://cv-agent.example.com/.well-known/agent-card.json
```

The API is stateless and accepts transcript replay with bounded context. Configure the same `AGENT_API_KEY` with the client when bearer authentication is enabled.

## Backups

Local Git history is not an off-volume backup. Use volume snapshots or lifecycle backup features against the mounted `DATA_DIR`; retain archives outside the running container and test restore procedures separately.

```bash
docker compose down
```
