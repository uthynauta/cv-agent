# OpenAI Ingestion Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use $subagent-driven-development (recommended) or $executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a toggleable wiki ingestion mode that defaults to OpenAI synthesis and can fall back to deterministic extraction.

**Architecture:** Keep `POST /admin/ingest` and the CLI as the only ingestion entry points. `IngestionService` selects an ingestion renderer from `INGESTION_MODE`; OpenAI mode extracts source text, asks the configured model to produce a compact Obsidian-style wiki bundle, writes generated pages, and falls back to deterministic mode when OpenAI is unavailable only if the operator explicitly selected deterministic mode.

**Tech Stack:** Python 3.12, FastAPI, OpenAI Responses API, pytest, existing wiki repository/frontmatter helpers.

---

### Task 1: Configuration

**Files:**
- Modify: `src/banorte_agent/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

- [x] Add `IngestionMode = Literal["openai", "deterministic"]`.
- [x] Add `ingestion_mode` setting with alias `INGESTION_MODE` and default `openai`.
- [x] Validate invalid values with a clear error.
- [x] Document `INGESTION_MODE=openai` in `.env.example` without changing user secrets.

### Task 2: OpenAI Wiki Renderer

**Files:**
- Create: `src/banorte_agent/wiki/openai_ingest.py`
- Modify: `src/banorte_agent/wiki/ingest.py`
- Test: `tests/test_ingest.py`

- [x] Add a small OpenAI ingestion client using `settings.openai_model`.
- [x] Request JSON with pages containing `path`, `title`, `metadata`, and `body`.
- [x] Accept only paths under `sources/`, `entities/`, `concepts/`, `projects/`, `skills/`, `questions/`, and `syntheses/`.
- [x] Write `index.md` and `log.md` after ingest.
- [x] Keep deterministic ingestion as the fallback mode selected by env var.

### Task 3: CLI And Admin Wiring

**Files:**
- Modify: `src/banorte_agent/cli.py`
- Modify: `src/banorte_agent/main.py`
- Test: `tests/test_ingest.py` or API tests if needed

- [x] Construct `IngestionService` with settings.
- [x] Ensure CLI and `/admin/ingest` use the same mode.
- [x] Preserve raw-path restrictions in the admin endpoint.

### Task 4: Docs And Verification

**Files:**
- Modify: `README.md`

- [x] Document OpenAI/default and deterministic ingestion commands.
- [x] Note that `OPENAI_MODEL=gpt-5.6-luna` controls both chat and OpenAI ingestion.
- [x] Run `uv run --extra dev pytest`.
