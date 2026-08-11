# Deployment

## Environment

Copy `.env.example` to `.env` before serving model requests. Configure these values as needed:

- `OPENAI_API_KEY` is required for live calls to `POST /v1/responses` and default OpenAI ingestion.
- `AGENT_API_KEY` enables bearer authentication for the public endpoint.
- `ADMIN_API_KEY` enables and protects `POST /admin/ingest`; an empty value disables it with HTTP 503.
- `GROUNDING_MODE=inference`, `INGESTION_MODE=openai`, and `OPENAI_MODEL=gpt-5.6` are current defaults. Set `OPENAI_MODEL=gpt-5.6-luna` when running the current agent model.
- `AGENT_MODEL_NAME=banorte-cv-agent` is the canonical model name returned to clients.

The `.env` file is optional for Compose validation and startup. Do not send model requests without a real key. For OpenTelemetry export, set `OTEL_ENABLED=true`, `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, and optional comma-separated `OTEL_RESOURCE_ATTRIBUTES`. The default OTLP endpoint assumes a `tempo` service is available on the Compose network; this repository does not define that service.

## Run

```bash
docker compose up -d --build
docker compose logs -f banorte-agent
```

## Checks

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
curl http://localhost:8000/metrics
```

Readiness returns 503 until `OPENAI_API_KEY`, readable `wiki/index.md`, and at least one usable generated page are available.

## API Requests

No `AGENT_API_KEY` configured:

```bash
curl -sS http://localhost:8000/v1/responses \
  -H 'Content-Type: application/json' \
  -d '{"input":"Resume la experiencia de Othon en Continental."}'
```

With public bearer auth:

```bash
curl -sS http://localhost:8000/v1/responses \
  -H 'Authorization: Bearer YOUR_AGENT_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"input":"Resume la experiencia de Othon en Continental."}'
```

Requests accept at most 4,000 `input` characters and 1,000 `instructions` characters. OpenAI output is capped at 1,200 tokens.

With `ADMIN_API_KEY` configured, ingestion paths must resolve inside the mounted `/app/wiki/raw` tree. Default ingestion uses OpenAI synthesis; set `INGESTION_MODE=deterministic` for offline extraction:

```bash
curl -sS http://localhost:8000/admin/ingest \
  -H 'Authorization: Bearer YOUR_ADMIN_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"path":"wiki/raw/cv"}'
```

Stop the local Compose deployment when finished:

```bash
docker compose down
```

## Banorte Registration

Banorte platform URL, authentication requirements, and registration details are not available yet. Do not infer them from this Open Responses-like local adapter. Until a public deployment and Banorte contract are available, use `http://localhost:8000/v1/responses` only for local testing.
