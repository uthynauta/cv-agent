# CV Agent

Reusable Dockerized FastAPI service for answering questions about a candidate's CV. The repository contains only application code and synthetic tests. Candidate documents and generated knowledge live under the mounted DATA_DIR.

## Runtime

The service exposes a stateless, non-streaming Open Responses surface:

```text
POST /v1/responses
GET /.well-known/agent-card.json
GET /healthz
GET /readyz
GET /metrics
```

`/v1/responses` performs local Markdown retrieval, optionally reranks candidates with OpenAI, validates grounded citations, and returns completed Open Responses-compatible JSON. Conversations are not stored server-side; transcript replay may include bounded prior context for resolving follow-ups.

Public readiness requires `OPENAI_API_KEY`, `OPENAI_MODEL`, `AGENT_OWNER_NAME`, `AGENT_PUBLIC_URL`, and at least one usable source in mounted storage. A fresh deployment is intentionally empty. Upload a document through the authenticated admin API or browser dashboard to initialize knowledge.

## Configuration

Copy `.env.example` to `.env` and set values for the deployment:

```text
DATA_DIR=/data
AGENT_OWNER_NAME=Example Candidate
AGENT_DISPLAY_NAME=CV Agent
AGENT_DESCRIPTION=Ask questions about this candidate's CV.
AGENT_PUBLIC_URL=https://cv-agent.example.com
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6
ADMIN_API_KEY=
ADMIN_UI_PASSWORD=
ADMIN_UI_SESSION_SECRET=
```

`AGENT_API_KEY` protects public requests when configured. `AGENT_LANGUAGE` accepts `auto`, `es`, or `en`. Retrieval, context, upload, backup, Git author, and observability settings are documented in `.env.example`.

## Local Development

```bash
uv run --extra dev pytest -q
uv run uvicorn cv_agent.main:app --host 127.0.0.1 --port 8000
curl http://localhost:8000/healthz
```

The CLI writes to the mounted local repository derived from `DATA_DIR`:

```bash
DATA_DIR=./data INGESTION_MODE=deterministic uv run cv-agent ingest ./data/documents
```

## Docker Compose

Compose mounts a host data directory at `/data` and sets `DATA_DIR=/data`. No candidate corpus is copied into the image and no remote Git repository is configured.

```bash
cp .env.example .env
docker compose up -d --build
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
docker compose down
```

## API Examples

Without public bearer authentication:

```bash
curl -sS http://localhost:8000/v1/responses \
  -H 'Content-Type: application/json' \
  -d '{"input":"Resume el perfil profesional del candidato."}'
```

Upload and ingest one supported source document:

```bash
curl -sS http://localhost:8000/admin/documents \
  -H 'Authorization: Bearer YOUR_ADMIN_API_KEY' \
  -F 'file=@/path/to/document.pdf'
```

The endpoint accepts `.pdf`, `.md`, and `.tex` files, stores originals below `DATA_DIR/documents/`, and commits normalized Markdown below the local Git repository at `DATA_DIR/repository/`. Original binaries are never added to that repository. The admin status endpoint reports storage, knowledge, and local revision state:

```bash
curl -sS http://localhost:8000/admin/status \
  -H 'Authorization: Bearer YOUR_ADMIN_API_KEY'
```

The browser dashboard is available at `/admin/login` when `ADMIN_UI_PASSWORD` and `ADMIN_UI_SESSION_SECRET` are configured. It supports authenticated uploads and local storage status. There is no remote publishing action.

## Persistence

Mount the entire `DATA_DIR` volume. It contains original documents, generated Markdown, local Git history, staging files, locks, and backup artifacts. Local Git is version history, not an off-volume backup. Protect the mounted volume with normal snapshot or archive procedures.

See [architecture](docs/architecture.md), [deployment](docs/deployment.md), [demo guide](docs/demo.md), and [sample transcript](docs/sample-transcript.md).
