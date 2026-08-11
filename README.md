# Banorte CV Agent

Dockerized FastAPI agent for the Banorte CV challenge. It searches the local wiki and exposes an Open Responses-like API that returns Spanish answers with visible source citations.

## Local Development

Install the project dependencies with `uv`, then run the test suite:

```bash
uv run --extra dev pytest
```

Start the service locally. A real `OPENAI_API_KEY` is required only when sending requests to `POST /v1/responses`; health and observability checks do not call OpenAI.

```bash
uv run uvicorn banorte_agent.main:app --host 127.0.0.1 --port 8000
curl http://localhost:8000/healthz
```

## API and Operations

- `POST /v1/responses` is the Open Responses-like endpoint.
- `GET /healthz`, `GET /readyz`, and `GET /metrics` provide observability endpoints.
- `POST /admin/ingest` ingests supported documents from the local wiki source directory when protected with `ADMIN_API_KEY`.

The `wiki/` directory contains the generated Obsidian-style Markdown knowledge base. Use the project CLI to ingest new source material before serving it.

## Docker Compose

```bash
docker compose up -d --build
curl http://localhost:8000/healthz
docker compose down
```

See [deployment instructions](docs/deployment.md).

## Evaluation

```bash
uv run python evals/run_eval.py --base-url http://localhost:8000
```

The eval runner checks Spanish output, visible citations, and missing-information behavior. It makes requests to `/v1/responses`, so run it only with a real `OPENAI_API_KEY`. `AGENT_API_KEY`, when configured, is read from the environment or passed with `--api-key`.

## Banorte Registration

Banorte platform URL and registration details are not available yet. When a public URL is available, register its `/v1/responses` path with the platform. Until then, use `http://localhost:8000/v1/responses` for local development.
