# Deployment

## Environment

Copy `.env.example` to `.env` on the server and set:

- `OPENAI_API_KEY`
- `AGENT_API_KEY` if the public endpoint should require bearer auth
- `ADMIN_API_KEY` if `/admin/ingest` is exposed
- `GROUNDING_MODE=inference`
- `OPENAI_MODEL=gpt-5.6`

The Compose service reads `.env` directly. To export traces to Grafana Tempo or an OpenTelemetry Collector, set `OTEL_ENABLED=true`, `OTEL_SERVICE_NAME`, and `OTEL_EXPORTER_OTLP_ENDPOINT` to the reachable OTLP/gRPC endpoint. The default endpoint `http://tempo:4317` assumes a Tempo service named `tempo` is available on the Compose network; set `OTEL_EXPORTER_OTLP_INSECURE=true` for plaintext local OTLP and use `OTEL_RESOURCE_ATTRIBUTES` for optional resource metadata.

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

## Banorte Registration

Register the public URL:

```text
https://<host>/v1/responses
```

If `AGENT_API_KEY` is set, register the same value as the endpoint API key in the Banorte platform.
