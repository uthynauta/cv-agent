# Deployment

## Environment

Copy `.env.example` to `.env` before serving model requests. Configure these values as needed:

- `OPENAI_API_KEY` is required for live calls to `POST /v1/responses` and default OpenAI ingestion.
- `AGENT_API_KEY` enables bearer authentication for the public endpoint.
- `ADMIN_API_KEY` enables and protects `POST /admin/ingest`; an empty value disables it with HTTP 503.
- `GROUNDING_MODE=inference`, `INGESTION_MODE=openai`, and `OPENAI_MODEL=gpt-5.6` are current defaults. Set `OPENAI_MODEL=gpt-5.6-luna` when running the current agent model.
- `RETRIEVAL_MODE=lexical` is the lowest-latency default. Set `RETRIEVAL_MODE=llm_rerank` to add an OpenAI rerank pass. `RERANK_TOP_K` controls lexical over-retrieval; with `CONTEXT_MODE=page`, generated wiki pages not found lexically are also sent as fallback candidates before answering from `ANSWER_TOP_K` selected pages/passages.
- `RERANK_MODEL` is optional; when empty, reranking uses `OPENAI_MODEL`.
- `CONTEXT_MODE=page` expands selected hits to full generated wiki pages within `MAX_CONTEXT_CHARS`; `CONTEXT_MODE=excerpt` sends only matched excerpts.
- `AGENT_MODEL_NAME=banorte-cv-agent` is the canonical model name returned to clients.
- `AGENT_PUBLIC_URL` is the public service base URL advertised by `/.well-known/agent-card.json`.

The `.env` file is optional for Compose validation and startup. Do not send model requests without a real key. For OpenTelemetry export, set `OTEL_ENABLED=true`, `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, and optional comma-separated `OTEL_RESOURCE_ATTRIBUTES`. The default OTLP endpoint assumes a `tempo` service is available on the Compose network; this repository does not define that service.

## Render

The current public deployment runs as a Render Web Service:

```text
https://banorte-cv-agent.onrender.com
```

Recommended Render settings:

- Runtime: Docker.
- Branch: `main`.
- Region: keep the default unless latency testing suggests otherwise.
- Instance: use a paid instance for the Banorte review window to avoid free-tier sleep.
- Health check path: `/healthz`.
- Required environment variables: `OPENAI_API_KEY`, `AGENT_PUBLIC_URL=https://banorte-cv-agent.onrender.com`.
- Optional environment variables: `AGENT_API_KEY`, `ADMIN_API_KEY`, retrieval and observability settings from `.env.example`.

Do not put secrets in the repository. Configure API keys only through Render environment variables.

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

Register the Open Responses endpoint:

```text
https://banorte-cv-agent.onrender.com/v1/responses
```

If Banorte offers agent-card import, use:

```text
https://banorte-cv-agent.onrender.com/.well-known/agent-card.json
```

If `AGENT_API_KEY` is set, register the same value as the endpoint API key in Banorte.

Recommended Banorte options:

- Conversation mode: `reproducir transcripcion (sin estado)`. The service is stateless and already extracts the latest user message plus bounded context from transcript replay.
- Avoid `previous_response_id` unless server-side state is later implemented.
- Capability content: choose inline Base64 when available. Use URL fetching only if the runtime must retrieve a capability file from Parley during execution.

Quick public checks after each deploy:

```bash
curl -sS https://banorte-cv-agent.onrender.com/healthz
curl -sS https://banorte-cv-agent.onrender.com/readyz
curl -sS https://banorte-cv-agent.onrender.com/.well-known/agent-card.json
```
