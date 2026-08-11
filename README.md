# Banorte CV Agent

Dockerized FastAPI CV agent for the Banorte challenge. It retrieves evidence from a local Markdown wiki, calls OpenAI, validates Spanish output and citations, and exposes an Open Responses-like API.

## Current Status

The service is currently local-only at `http://localhost:8000`. No Banorte platform URL or registration contract has been provided, and this repository has no live `OPENAI_API_KEY`. Health, tests, ingestion, and container builds work without live model calls; `/v1/responses` needs a real key when using the built-in OpenAI client.

## Architecture

Request flow: optional public bearer auth -> bounded request validation -> normalized passage-level wiki search -> OpenAI Responses API -> Spanish/citation validation -> Open Responses-like response. Invalid generated output is replaced with a safe Spanish answer citing only retrieved pages.

Raw `.tex`, `.pdf`, and `.md` sources are ingested from `wiki/raw/`. Committed LaTeX CV sources may generate full-text pages. Git-ignored PDF and Markdown sources generate metadata and a bounded snippet only, so their full extracted text is not copied into committed Markdown by default.

See [architecture](docs/architecture.md), [deployment](docs/deployment.md), [demo guide](docs/demo.md), and [sample transcript](docs/sample-transcript.md).

## Local Development

```bash
uv run --extra dev pytest
uv run uvicorn banorte_agent.main:app --host 127.0.0.1 --port 8000
curl http://localhost:8000/healthz
```

## Docker Compose

Create `.env` from `.env.example`, set a real `OPENAI_API_KEY` for model requests, then run:

```bash
docker compose up -d --build
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
docker compose down
```

## Call The API

Without public bearer auth, leave `AGENT_API_KEY` empty:

```bash
curl -sS http://localhost:8000/v1/responses \
  -H 'Content-Type: application/json' \
  -d '{"model":"banorte-cv-agent","input":"¿Qué hizo Othon en Continental con radares?"}'
```

With `AGENT_API_KEY` configured:

```bash
curl -sS http://localhost:8000/v1/responses \
  -H 'Authorization: Bearer YOUR_AGENT_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"input":"¿Qué experiencia tiene Othon con agentes de IA?","instructions":"Responde brevemente."}'
```

`input` is limited to 4,000 characters and `instructions` to 1,000. `instructions` are treated as untrusted preferences and cannot override grounding, Spanish, or citation policy. Responses always identify the canonical configured model (`AGENT_MODEL_NAME`, default `banorte-cv-agent`) rather than echoing a client model string.

## Ingestion

Local CLI is preferred:

```bash
uv run banorte-agent ingest wiki/raw
```

`POST /admin/ingest` is disabled with HTTP 503 unless `ADMIN_API_KEY` is configured. When enabled, it requires that bearer token and accepts only paths inside `wiki/raw`:

```bash
curl -sS http://localhost:8000/admin/ingest \
  -H 'Authorization: Bearer YOUR_ADMIN_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"path":"wiki/raw/cv"}'
```

## Evaluation

Run only after configuring a real OpenAI key:

```bash
uv run python evals/run_eval.py --base-url http://localhost:8000
```

The runner reads `AGENT_API_KEY` or accepts `--api-key`. No live eval is run as part of offline verification.
