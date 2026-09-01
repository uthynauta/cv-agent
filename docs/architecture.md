# Architecture

CV Agent is one Dockerized FastAPI service with generic identity and mounted candidate storage. It exposes Open Responses-compatible responses, an agent card, health/readiness, metrics, and authenticated local administration.

## Request Flow

1. Optional `AGENT_API_KEY` bearer authentication and bounded request-size checks run first.
2. The request adapter accepts common Open Responses input shapes and extracts the latest user/developer request plus bounded transcript context.
3. Local lexical search reads Markdown pages from the mounted repository. Optional LLM reranking selects among retrieved and page-level fallback candidates.
4. Page or excerpt context is bounded by `MAX_CONTEXT_CHARS` and passed to the configured OpenAI model with reviewer text isolated as untrusted input.
5. Generated output is checked for the effective language and a final `Fuentes:` line citing only retrieved page titles. Invalid output falls back to a safe cited response.
6. The completed response includes the canonical `AGENT_MODEL_NAME`, message output, and top-level `output_text`.

The endpoint remains stateless and non-streaming. Earlier transcript turns are context only; no conversation database or `previous_response_id` state is maintained.

## Mounted Storage

`DATA_DIR` is the sole runtime data root:

```text
DATA_DIR/
├── documents/             # current original files; never Git-tracked
├── repository/            # local Git work tree and history
│   ├── sources/           # normalized source Markdown
│   └── knowledge/         # generated retrieval Markdown
├── backups/
├── staging/
└── locks/
```

A fresh root is created with an empty local repository. Readiness remains unavailable until a usable source has been ingested. No bundled candidate corpus is present in the application image or repository, and no remote publishing integration exists.

## Ingestion

Supported source types are `.pdf`, `.md`, and `.tex`. Originals remain in `DATA_DIR/documents/`; normalized sources and generated pages are committed under `DATA_DIR/repository/`. Deterministic ingestion is repeatable and offline. OpenAI ingestion can generate categorized Markdown pages from extracted source text. Admin uploads and the CLI use the same mounted repository semantics.

Each successful mutation creates a local Git commit using `DATA_GIT_AUTHOR_NAME` and `DATA_GIT_AUTHOR_EMAIL`. Git commands are bounded to the resolved mounted repository path. No remote is added or contacted.

## Operations

Request logs and metrics use bounded route labels and do not contain prompts, document content, retrieved text, or secrets. Optional OpenTelemetry export is configured through `OTEL_*` settings.

`/healthz` reports process liveness. `/readyz` checks required public configuration and usable mounted knowledge. `/metrics` exposes Prometheus text. Admin status reports document storage writability, ingestion mode, knowledge readiness, paths, and local repository revision.
