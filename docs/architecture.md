# Architecture

The Banorte CV Agent is one Dockerized FastAPI service. It exposes an Open Responses-like `POST /v1/responses`, operational endpoints, and an optional protected ingestion endpoint.

## Request Flow

1. FastAPI validates the 4,000-character `input` and optional 1,000-character `instructions`.
2. `AGENT_API_KEY`, when set, protects the public endpoint.
3. Wiki search normalizes case and accents, removes Spanish stopwords, matches token boundaries, and ranks the best sections/passages rather than whole pages.
4. With `RETRIEVAL_MODE=llm_rerank`, the agent sends lexical candidates plus page-level fallback candidates to a rerank model and keeps only selected pages/passages.
5. With `CONTEXT_MODE=page`, selected hits are deduplicated by path and expanded to full generated wiki pages within `MAX_CONTEXT_CHARS`; `CONTEXT_MODE=excerpt` keeps only matched excerpts.
6. The agent sends bounded wiki context and an isolated, untrusted reviewer question to the configured OpenAI model.
7. Post-generation checks require Spanish-like output and a final `Fuentes:` line whose Obsidian links match retrieved page titles.
8. Failed validation returns a safe Spanish fallback listing only available retrieved sources.
9. The API returns the canonical `AGENT_MODEL_NAME` in the response.

## Knowledge And Ingestion

`WikiRepository` reads generated Markdown under `wiki/`; raw content under `wiki/raw/` is excluded from runtime search. LaTeX extraction preserves document text and headings while removing layout commands. PDF extraction uses selectable text and marks short results `needs_ocr: true`.

LaTeX CV files may be committed and their generated source pages may include full extracted text. PDF and Markdown raw files are Git-ignored; deterministic generated pages contain source metadata and a bounded snippet, never the full extracted text by default. The local CLI is the preferred ingestion interface. HTTP ingestion is disabled unless `ADMIN_API_KEY` is set and is confined to `wiki/raw`.

`INGESTION_MODE=openai` is the default and uses the configured `OPENAI_MODEL` to synthesize Obsidian-style `sources/`, `entities/`, `concepts/`, `education/`, `credentials/`, `experience/`, `projects/`, `publications/`, `skills/`, `questions/`, and `syntheses/` pages from extracted raw text. `INGESTION_MODE=deterministic` skips model calls and produces basic source pages, `index.md`, and `log.md`.

## Operations

Request logs are JSON and use generated or propagated request IDs. Prometheus labels use matched route templates or the bounded value `unmatched`; metrics cover HTTP counts/latency, wiki hit counts, OpenAI calls/latency, and ingestion outcomes. Exceptions produce a JSON 500 with `x-request-id`. Optional OpenTelemetry tracing applies `OTEL_RESOURCE_ATTRIBUTES` and exports OTLP/gRPC spans without prompts, raw documents, secrets, or retrieved text.

`/healthz` checks process liveness. `/readyz` requires an OpenAI key, a readable non-empty `wiki/index.md`, and at least one usable generated wiki page. `/metrics` exposes Prometheus text.

MVP retrieval remains local and transparent. `RETRIEVAL_MODE=lexical` performs one local search before answering. `RETRIEVAL_MODE=llm_rerank` performs local over-retrieval and, in page context mode, adds all generated wiki pages as fallback candidates so new categories remain discoverable. OpenAI then selects relevant paths, and the answer uses only those selected pages or excerpts. No vector database, OpenAI File Search, or conversation database is present.
