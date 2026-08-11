# Task 7 Report: Observability, Metrics, And Optional Tracing

## Status

DONE

## Implemented

- Added Prometheus request, latency, OpenAI-call, and ingestion-event metrics, plus `GET /metrics` in Prometheus text format.
- Added JSON request logging middleware that propagates or generates `x-request-id` and records method, path, status, and latency only.
- Added optional OTLP/gRPC OpenTelemetry configuration controlled by `OTEL_ENABLED`, with the required Tempo/Collector settings.
- Added manual spans for agent answers, OpenAI Responses calls, wiki search, and file ingestion. Span attributes are restricted to safe counts, enums, booleans, extensions, and a 200-character capped title list; no prompts, answers, retrieved text, raw source text, document content, API keys, or bearer tokens are recorded.
- Added the Task 7 metric and tracing tests.

## TDD Evidence

`uv run --extra dev pytest tests/test_metrics.py -q` failed before implementation as expected: `/metrics` returned `404` and `x-request-id` was absent.

## Verification

- `uv run --extra dev pytest tests/test_metrics.py tests/test_tracing.py -q`: 5 passed.
- `uv run --extra dev pytest -q`: 34 passed.
- `git diff --check`: passed.

## Scope

Only Task 7 observability, metrics, tracing, configuration, dependency, environment-template, test, lockfile, and report changes were made. Docker, documentation, and evaluation work were not implemented.
