# Banorte CV Agent Final Fix Report

## Status

DONE

All Critical, Important, and requested cheap Minor branch-review findings were addressed. No live OpenAI request, external evaluation, or Banorte registration call was made because no real OpenAI key or Banorte URL/contract is available.

## Findings Addressed

1. Retrieval now normalizes accents/case, removes Spanish stopwords, stems common plural forms, matches token boundaries, scores local heading/passage windows, and selects the best matching passage as the excerpt. Real-CV coverage proves `¿Qué hizo Othon en Continental con radares?` returns Continental radar testing and virtualization evidence first.
2. HTTP Prometheus labels now use matched route templates or bounded `unmatched`; arbitrary URL values do not create time series.
3. `/admin/ingest` now returns HTTP 503 when `ADMIN_API_KEY` is absent and HTTP 401 for a wrong/missing configured token.
4. User `instructions` and reviewer questions are JSON encoded in explicit untrusted-data boundaries before final mandatory rules. Generated output is validated for Spanish-like answer text, a final `Fuentes:` line, and citations restricted to retrieved hit titles. Invalid output receives a safe Spanish fallback with available sources.
5. Request middleware handles exceptions with JSON HTTP 500 responses, `x-request-id`, JSON logs, and bounded request count/latency metrics. Wiki hit and OpenAI call latency histograms were added and tested.
6. Non-LaTeX ingestion writes metadata and a bounded snippet only with `content_policy: snippet_only`; full extracted PDF/Markdown text is omitted. LaTeX remains `full_text` by policy.
7. LaTeX extraction now isolates document content, preserves accented text and adjacent command arguments, creates searchable headings, and removes layout declarations/measurements. Actual CV header fixtures preserve `Othón González`. Both committed CV source pages were regenerated.
8. Public `input` is limited to 4,000 characters, `instructions` to 1,000 characters, and OpenAI output to 1,200 tokens.
9. Dockerfile copies `uv.lock` and installs with `uv sync --frozen --no-dev`. Docker Compose build completed.
10. `OTEL_RESOURCE_ATTRIBUTES` is parsed and applied, while configured service name remains canonical.
11. Readiness now requires a readable non-empty `wiki/index.md` and at least one usable generated page in addition to `OPENAI_API_KEY`.
12. API responses always return canonical `settings.agent_model_name` instead of echoing arbitrary request model values.
13. README and current docs now describe actual architecture, Docker Compose deployment, authenticated/unauthenticated API calls, admin ingest disablement/auth, limits, privacy, readiness, and current external limitations.

## Files Changed

- Runtime/config: `.env.example`, `Dockerfile`, `src/banorte_agent/logging.py`, `metrics.py`, `tracing.py`.
- API: `src/banorte_agent/api/admin.py`, `health.py`, `models.py`, `responses.py`.
- Agent: `src/banorte_agent/agent/openai_client.py`, `prompts.py`, `service.py`.
- Wiki: `src/banorte_agent/wiki/extractors.py`, `ingest.py`, `search.py`, `wiki/sources/cv-ogc-ai.md`, `wiki/sources/cv-ogc-ats.md`.
- Tests: `tests/test_admin.py`, `test_agent_service.py`, `test_extractors.py`, `test_health.py`, `test_ingest.py`, `test_metrics.py`, `test_response_schema.py`, `test_search.py`, `test_tracing.py`, plus `tests/fixtures/cv-header-ai.tex` and `cv-header-ats.tex`.
- Docs: `README.md`, `docs/architecture.md`, `docs/deployment.md`, `docs/demo.md`, `docs/sample-transcript.md`, and the design spec.

## TDD Evidence

Initial new-regression run:

```text
19 failed, 24 passed
```

Failures reproduced passage ranking, raw-path metrics, missing 500 request IDs, absent metrics, public admin ingest, prompt/output validation gaps, non-LaTeX full-text copying, broken CV names/layout debris, unbounded fields, weak readiness, missing OTEL attributes, and arbitrary model echoing.

Focused green run before final self-review:

```text
...........................................                              [100%]
```

## Final Verification

`uv run --extra dev pytest -q`

```text
.......................................................                  [100%]
```

Result: 55 passed, exit 0.

`uv run python -m compileall -q src tests evals`

```text
(no output)
```

Result: exit 0.

`uv lock --check`

```text
Resolved 58 packages in 1ms
```

Result: exit 0.

`git diff --check`

```text
(no output)
```

Result: exit 0.

`docker compose config -q`

```text
(no output)
```

Result: exit 0.

Real-CV search check:

```text
CV-OGC-ATS: Continental Autonomous Mobility. Algorithms Test / Data Engineer (ADAS) Jul 2022 -- Nov 2025. Developed and implemented AI-driven testing tools for radar perception systems, reducing validation time for AI-based radar and camera model workflows.. Developed radar virtualization methods to support training and evaluation of AI models for perception-related use cases.
```

`docker compose build`

```text
Successfully built ec84caba0022
Successfully tagged banorte-cv-agent-impl-banorte-agent:latest
Image banorte-cv-agent-impl-banorte-agent Built
```

Result: exit 0. Compose warned that the optional Buildx plugin is absent, then completed with Docker's classic builder.

Container import smoke test:

```text
Banorte CV Agent
```

Result: exit 0.

## Residual Concerns

- Live OpenAI behavior and evals remain unverified until a real `OPENAI_API_KEY` is supplied.
- Banorte platform compatibility and registration remain unverified because no Banorte URL or protocol details are available.
- Spanish/citation checks are deterministic safety gates, not semantic fact verification; unsupported prose could still pass if it is Spanish-like and cites retrieved titles. Strict prompting and evidence excerpts reduce this risk.
- Retrieval remains lexical by MVP design. It now handles the reviewed real-CV query, but embeddings may be useful after challenge validation if broader paraphrase recall is required.
- Docker Buildx is not installed in the current environment; the final frozen-lock image nevertheless built successfully with the classic builder.
