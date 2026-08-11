# Banorte CV Agent Design

Date: 2026-08-10

## Challenge Summary

The Banorte AI challenge asks for a deployed CV agent that represents Othon's professional trajectory through a useful, clear, natural conversation. The agent must help reviewers understand profile, experience, skills, and projects. It must expose a public endpoint compatible with the Open Responses protocol, be registered in the Banorte platform, and have source code available in a public GitHub repository.

Deadline: Thursday, 2026-08-13.

## Goals

- Build a public CV agent endpoint using Python FastAPI.
- Provide an OpenAI-like `POST /v1/responses` API.
- Use OpenAI API for generation.
- Answer reviewers in Spanish.
- Keep backend code, internal prompts, config, and implementation docs in English.
- Ground answers in an Obsidian-style local Markdown wiki.
- Support ingestion of LaTeX, PDF, and Markdown sources into the wiki.
- Package the service with Docker and Docker Compose for a simple cloud VM/container deployment.
- Include observability, tests, evals, demo documentation, and a sample transcript.

## Non-Goals For MVP

- No vector database.
- No server-side conversation database.
- No Kubernetes.
- No polished web chat UI.
- No full OCR pipeline unless time permits; scanned or image PDFs can be marked as needing OCR.
- No raw secret values in Git.

## Architecture

The project will build one Python FastAPI service packaged as a Docker image.

Main components:

- `api`: HTTP API with Open Responses-like endpoint and operational endpoints.
- `agent`: constructs prompts, calls OpenAI, formats Spanish answers, and enforces grounding/citation policy.
- `wiki`: Obsidian-style Markdown knowledge base under `wiki/`.
- `ingestion`: local CLI and protected HTTP endpoint that convert raw `.tex`, `.pdf`, and `.md` files into wiki pages.
- `search`: simple lexical search over committed Markdown wiki pages using frontmatter, headings, and body text.
- `observability`: structured logs, request IDs, latency/error metrics, and health/readiness checks.
- `tracing`: optional OpenTelemetry spans exported over OTLP/gRPC for Grafana Tempo or compatible collectors.
- `evals`: repeatable checks for answer language, citations, grounding behavior, and response shape.

High-level data flow:

1. Source files are added under `wiki/raw/`.
2. Ingestion extracts text and metadata from raw files.
3. Ingestion writes or updates generated Markdown pages under `wiki/sources/`, `wiki/entities/`, `wiki/concepts/`, `wiki/education/`, `wiki/credentials/`, `wiki/experience/`, `wiki/projects/`, `wiki/publications/`, `wiki/skills/`, and `wiki/questions/`.
4. Ingestion updates `wiki/index.md` and appends to `wiki/log.md`.
5. A reviewer sends a request to `POST /v1/responses`.
6. The API authenticates the request if `AGENT_API_KEY` is set.
7. Search retrieves relevant wiki pages.
8. The agent calls OpenAI with the system prompt, grounding mode, retrieved context, and user input.
9. The API returns an OpenAI-like response object with `output_text`.

## API Contract

Primary endpoint:

```http
POST /v1/responses
Authorization: Bearer <AGENT_API_KEY>
Content-Type: application/json
```

Authorization is optional by environment:

- If `AGENT_API_KEY` is set, the endpoint requires `Authorization: Bearer <AGENT_API_KEY>`.
- If `AGENT_API_KEY` is empty or unset, the endpoint is public.
- `OPENAI_API_KEY` is always required for live model calls and must only be supplied through environment variables.
- `input` is limited to 4,000 characters and `instructions` to 1,000 characters.
- Responses return the canonical configured `AGENT_MODEL_NAME`; arbitrary client model strings are not echoed.

Supported request body:

```json
{
  "model": "banorte-cv-agent",
  "input": "¿Qué experiencia tiene Othon con agentes de IA?",
  "instructions": "optional extra instructions"
}
```

Initial response body:

```json
{
  "id": "resp_...",
  "object": "response",
  "created_at": 1786370000,
  "model": "banorte-cv-agent",
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "..."
        }
      ]
    }
  ],
  "output_text": "..."
}
```

Additional endpoints:

- `GET /healthz`: process liveness.
- `GET /readyz`: wiki readable and required runtime configuration present.
- `GET /metrics`: Prometheus-style metrics.
- `POST /admin/ingest`: protected ingestion endpoint for later automation.

`POST /admin/ingest` is disabled when `ADMIN_API_KEY` is empty. When configured, the endpoint requires that bearer token. The local CLI remains the preferred ingestion path.

## Conversation State

The service is stateless for MVP.

- No server-side conversation database.
- Each response uses the latest wiki files plus the current request input.
- Request logs include metadata only and must not contain secrets.

## Agent Behavior

Internal implementation language:

- Code, config, tests, prompts, and internal docs use English.

Reviewer-facing behavior:

- Answers are in Spanish by default.
- Answers should be clear, concise, natural, and useful for recruiters or technical reviewers.
- If the user asks in English, the agent still answers in Spanish unless the request explicitly asks otherwise.
- Answers visibly cite wiki/source page names.

Citation format:

```text
Fuentes: [[Othon CV]], [[Proyecto Banorte Agent]]
```

Grounding modes:

- `GROUNDING_MODE=strict`: answer only from retrieved wiki facts; if information is missing, say so clearly.
- `GROUNDING_MODE=inference`: use retrieved wiki facts plus cautious, labeled inference.
- Default is `inference`.

Per-request grounding override is intentionally deferred. The implementation should keep the configuration boundary clear so a later request-level override can be added.

## OpenAI Integration

Environment variables:

- `OPENAI_API_KEY`: required for live model calls.
- `OPENAI_MODEL`: model name used by the agent; default `gpt-5.6`.
- `GROUNDING_MODE`: `strict` or `inference`; default `inference`.
- `AGENT_API_KEY`: optional public endpoint bearer token.
- `ADMIN_API_KEY`: optional admin endpoint bearer token.
- `OTEL_ENABLED`: optional tracing toggle; default `false`.
- `OTEL_SERVICE_NAME`: OpenTelemetry service name; default `banorte-cv-agent`.
- `OTEL_EXPORTER_OTLP_ENDPOINT`: OTLP/gRPC endpoint, for example `http://tempo:4317`.
- `OTEL_EXPORTER_OTLP_INSECURE`: set `true` for local plaintext OTLP.
- `OTEL_RESOURCE_ATTRIBUTES`: optional OpenTelemetry resource attributes.

The agent prompt includes:

- CV agent role and audience.
- Spanish output requirement.
- Grounding mode.
- Retrieved wiki context.
- Citation requirement.
- Missing-information behavior.
- Instruction to avoid inventing unsupported facts.

## Wiki Design

Directory shape:

```text
wiki/
  raw/
    cv/
    documents/
  sources/
  entities/
  concepts/
  education/
  credentials/
  experience/
  projects/
  publications/
  skills/
  questions/
  index.md
  log.md
```

Conventions:

- All generated wiki pages are Markdown.
- Generated pages use YAML frontmatter.
- Pages use Obsidian links such as `[[Python]]`, `[[Banorte Agent]]`, and `[[Othon Profile]]`.
- `sources/` contains one page per ingested source.
- `entities/` contains people, organizations, roles, companies, schools, and similar entities.
- `concepts/` contains technical themes and knowledge areas.
- `education/` contains formal degrees and academic background.
- `credentials/` contains courses, certifications, workshops, and training evidence that may be added later.
- `experience/` contains employment, consulting, teaching, research, and other professional roles.
- `projects/` contains portfolio or project pages.
- `publications/` contains scientific papers, patents, talks, and authored technical outputs.
- `skills/` contains skill pages with evidence links.
- `questions/` contains saved high-value Q&A/eval answers.
- `index.md` is the content-oriented catalog.
- `log.md` is the append-only chronological activity log.

## Raw Source Git Policy

Raw files live under `wiki/raw/`.

Git policy:

- `wiki/raw/**/*.tex` can be committed.
- Non-LaTeX raw files under `wiki/raw/` are ignored by Git.
- Generated Markdown wiki pages are committed.
- Secret files and local environment files are ignored.

This keeps the LaTeX CV versioned while avoiding accidental commits of PDFs, full private documents, or large raw files.

Generated pages from non-LaTeX sources contain metadata and bounded snippets only by default. Full extracted text is allowed only for committed LaTeX CV sources.

## Ingestion Design

Supported source extensions:

- `.tex`
- `.pdf`
- `.md`

Input location:

- `wiki/raw/`

Outputs:

- Source summary page in `wiki/sources/`.
- Updated pages in `wiki/entities/`, `wiki/concepts/`, `wiki/education/`, `wiki/credentials/`, `wiki/experience/`, `wiki/projects/`, `wiki/publications/`, `wiki/skills/`, or `wiki/questions/` when applicable.
- Updated `wiki/index.md`.
- Appended `wiki/log.md` entry.

PDF behavior:

- First try selectable text extraction.
- If extracted text is empty or too short, mark source as `needs_ocr: true`.
- OCR is deferred unless time permits.

Ingestion should be deterministic where practical:

- File discovery, hashing, text extraction, frontmatter handling, and index/log updates should use code.
- OpenAI should be used only for summarization, classification, entity extraction, contradiction notes, and synthesis when deterministic parsing is insufficient.

## Search Design

MVP search is lexical search over generated Markdown wiki pages. It normalizes case and accents, removes Spanish stopwords, matches token boundaries, and scores sections/passages so excerpts favor local evidence over generic page summaries.

Search uses:

- page path
- title/frontmatter
- headings
- body text
- links

Search returns:

- page path
- title
- excerpt or matched sections
- score

Vector search and embeddings are intentionally deferred. The search module should have a small interface so embeddings can be added later without rewriting the agent.

When `RETRIEVAL_MODE=llm_rerank` and `CONTEXT_MODE=page`, `RERANK_TOP_K` controls only the initial lexical over-retrieval. The rerank pool also includes generated wiki pages that did not match lexically, using bounded page excerpts. This prevents new categories such as courses, credentials, teaching, publications, or later training documents from becoming unrecoverable just because no fixed synonym list matched the reviewer question.

## Observability

Logs:

- JSON logs.
- Include request ID, route, status code, latency, search hit count, and OpenAI latency.
- Do not log API keys or full secret-bearing headers.

Metrics:

- request count by route/status
- request latency
- OpenAI call count
- OpenAI error count
- OpenAI latency
- search hit count
- ingest success count
- ingest failure count

Operational endpoints:

- `/healthz`: alive if the process is running.
- `/readyz`: ready if wiki/index is readable, at least one generated page is usable, and required config is present.
- `/metrics`: Prometheus text format.

Tracing:

- OpenTelemetry is optional and disabled by default.
- When `OTEL_ENABLED=true`, the service exports spans through OTLP/gRPC.
- The default target is compatible with Grafana Tempo, OpenTelemetry Collector, and other OTLP/gRPC backends.
- Span attributes must be low-cardinality and secret-safe.
- Do not put full prompts, raw source text, retrieved context, API keys, bearer tokens, or document contents into spans.
- Required spans:
  - HTTP request spans from FastAPI instrumentation.
  - agent response span around retrieval plus OpenAI generation.
  - wiki search span with query length, result count, and top page titles only.
  - OpenAI call span with model, success/error, and latency.
  - ingestion span with source extension, `needs_ocr`, success/error, and generated page count.

## Deployment

Deployment target:

- Cloud VM or simple container service running Docker Compose.
- No Kubernetes.

Repository includes:

- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- deployment guide

Runtime configuration comes from environment variables. Real `.env` files are ignored.

## Tests And Evals

Unit tests:

- API request/response schema.
- Optional bearer auth behavior.
- Wiki search.
- Parser fallbacks.
- Metrics endpoints.
- Readiness behavior.

Eval runner:

- Sends representative profile questions to the agent.
- Checks Spanish output.
- Checks visible citations.
- Checks missing-information behavior.
- Saves a sample transcript for the demo package.

Demo package:

- Architecture overview.
- Deployment guide.
- Sample transcript.
- Banorte registration notes.
- Example questions reviewers can ask.

## Risks And Mitigations

- Banorte protocol details may differ from the OpenAI-like shape.
  - Mitigation: keep the API adapter thin and add aliases or fields after testing in the Banorte platform.
- Raw PDF extraction may fail on scanned documents.
  - Mitigation: mark `needs_ocr: true` and defer OCR unless needed.
- Wiki may start sparse until the real CV and documents are added.
  - Mitigation: include clear missing-information behavior and seed pages from the LaTeX CV once available.
- OpenAI API key or model config may be missing in deployment.
  - Mitigation: readiness checks and `.env.example`.
- Deadline is short.
  - Mitigation: prioritize endpoint, wiki, ingestion basics, Docker, observability, and evals before optional polish.

## Open Decisions

- Final Banorte platform protocol quirks after testing with the challenge guide.
