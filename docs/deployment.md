# Deployment

## Environment

Copy `.env.example` to `.env` before serving model requests. Configure these values as needed:

- `OPENAI_API_KEY` is required for live calls to `POST /v1/responses`.
- `AGENT_API_KEY` enables bearer authentication for the public endpoint.
- `ADMIN_API_KEY` protects `POST /admin/ingest`.
- `GROUNDING_MODE=inference` and `OPENAI_MODEL=gpt-5.6` are current defaults.

The `.env` file is optional for Compose validation and startup. A placeholder key may be used only for configuration or readiness checks; do not send model requests without a real key. For OpenTelemetry export, set `OTEL_ENABLED=true`, `OTEL_SERVICE_NAME`, and `OTEL_EXPORTER_OTLP_ENDPOINT`. The default OTLP endpoint assumes a `tempo` service is available on the Compose network.

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

Stop the local Compose deployment when finished:

```bash
docker compose down
```

## Banorte Registration

Banorte platform URL and registration details are not available yet. When a public URL is available, register its `/v1/responses` path with the Banorte platform. Until then, use `http://localhost:8000/v1/responses` locally.
