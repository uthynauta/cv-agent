# Architecture

The Banorte CV Agent is one Dockerized FastAPI service. It exposes an Open Responses-compatible `POST /v1/responses`, an A2A-style agent card, operational endpoints, and an optional protected ingestion endpoint.

## Request Flow

1. `AGENT_API_KEY`, when set, protects the public endpoint.
2. FastAPI accepts common Open Responses request shapes and normalizes public fields without leaking raw validation objects.
3. Plain string input is used directly. Transcript-list input is reduced to the latest user/developer message plus bounded context from previous turns.
4. If the latest message is a short confirmation such as `si por favor`, the API binds it to the previous assistant follow-up question and previous assistant answer.
5. Wiki search normalizes case and accents, removes Spanish stopwords, matches token boundaries, and ranks the best sections/passages rather than whole pages.
6. With `RETRIEVAL_MODE=llm_rerank`, the agent sends lexical candidates plus page-level fallback candidates to a rerank model and keeps only selected pages/passages.
7. With `CONTEXT_MODE=page`, selected hits are deduplicated by path and expanded to full generated wiki pages within `MAX_CONTEXT_CHARS`; `CONTEXT_MODE=excerpt` keeps only matched excerpts.
8. The agent sends bounded wiki context and an isolated, untrusted reviewer question to the configured OpenAI model.
9. Post-generation checks require Spanish-like output and a final `Fuentes:` line whose Obsidian links match retrieved page titles.
10. Failed validation returns a safe Spanish fallback listing only available retrieved sources.
11. The API returns `status: completed`, the canonical `AGENT_MODEL_NAME`, message output, and top-level `output_text`.

## Knowledge And Ingestion

`WikiRepository` reads generated Markdown under `wiki/`; raw content under `wiki/raw/` is excluded from runtime search. LaTeX extraction preserves document text and headings while removing layout commands. PDF extraction uses selectable text and marks short results `needs_ocr: true`.

LaTeX CV files may be committed and their generated source pages may include full extracted text. PDF and Markdown raw files are Git-ignored; deterministic generated pages contain source metadata and a bounded snippet, never the full extracted text by default. The local CLI is the preferred ingestion interface. HTTP ingestion is disabled unless `ADMIN_API_KEY` is set and is confined to `wiki/raw`.

`INGESTION_MODE=openai` is the default and uses the configured `OPENAI_MODEL` to synthesize Obsidian-style `sources/`, `entities/`, `concepts/`, `education/`, `credentials/`, `experience/`, `projects/`, `publications/`, `skills/`, `questions/`, and `syntheses/` pages from extracted raw text. `INGESTION_MODE=deterministic` skips model calls and produces basic source pages, `index.md`, and `log.md`.

## Operations

Request logs are JSON and use generated or propagated request IDs. Prometheus labels use matched route templates or the bounded value `unmatched`; metrics cover HTTP counts/latency, wiki hit counts, OpenAI calls/latency, and ingestion outcomes. Exceptions produce a JSON 500 with `x-request-id`. Optional OpenTelemetry tracing applies `OTEL_RESOURCE_ATTRIBUTES` and exports OTLP/gRPC spans without prompts, raw documents, secrets, or retrieved text.

`/healthz` checks process liveness. `/readyz` requires an OpenAI key, a readable non-empty `wiki/index.md`, and at least one usable generated wiki page. `/metrics` exposes Prometheus text.

MVP retrieval remains local and transparent. `RETRIEVAL_MODE=lexical` performs one local search before answering. `RETRIEVAL_MODE=llm_rerank` performs local over-retrieval and, in page context mode, adds all generated wiki pages as fallback candidates so new categories remain discoverable. OpenAI then selects relevant paths, and the answer uses only those selected pages or excerpts. No vector database, OpenAI File Search, or conversation database is present.

## Conversation Behavior

The service should be registered in Banorte with transcript replay/stateless mode. It does not store conversations or depend on `previous_response_id`.

For transcript replay, the input adapter keeps only a small amount of prior dialogue to resolve references such as `despues`, `esa empresa`, or `si por favor`. The latest reviewer message remains the command to answer. Previous messages are context only and must not be answered again.

The prompt asks for recruiter-facing Spanish, brief answers by default, names before details, bullets only when useful, and one answerable follow-up question before the final `Fuentes:` line unless the reviewer explicitly asks for no follow-up.
