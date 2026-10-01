# Public CV PDF Source Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make verified, processed PDF originals clickable from CV chat citations and remove orphan citation commas.

**Architecture:** The agent resolves citation titles to canonical source IDs in the same pinned knowledge revision used for the answer. A public, hash-verified PDF route serves eligible originals. The blog Worker converts safe relative agent paths to direct Render URLs; the widget renders anchors. Both APIs retain fallback behavior during staggered rollout.

**Tech Stack:** Python 3.12+, FastAPI, pytest/uv; TypeScript, Cloudflare Worker, Astro, Vitest, Playwright, pnpm.

**Spec:** `docs/superpowers/specs/2026-09-30-public-cv-source-links-design.md`

## Global Constraints

- Only processed, hash-matching PDF originals are public; Markdown, LaTeX, unprocessed files, backups, and quarantine are never public.
- Preserve `output_text` and the OpenAI-compatible response shape; add only the optional `source_documents` metadata field.
- Do not put workspace-specific owner names in agent source/tests; use generic fixtures.
- Do not log secrets, document contents, or filesystem paths in public errors.
- Deploy agent first, then blog; the new Worker must tolerate absent agent metadata.

## Review Focus

- A generated page referring to several source IDs gives links only for eligible PDFs, in source-reference order: Task 2 tests.
- A same-title page ambiguity gives no link, not a guessed PDF: Task 2 tests.
- A symlink swap or hash mismatch cannot serve bytes from an ineligible file: Task 1 tests.
- A malicious path or full URL in agent metadata cannot become a browser anchor: Task 3 tests.
- Citation separators and labels disappear in both languages without deleting ordinary answer punctuation: Task 3 tests.

---

### Task 1: Verified public PDF route (agent repository)

**Files:** Create `src/cv_agent/knowledge/public_pdfs.py`; create `src/cv_agent/api/public_documents.py`; modify `src/cv_agent/main.py`; test `tests/test_public_documents.py`.

**Interfaces:** `ProcessedPdfCatalog(paths: DataPaths, active: ActiveKnowledge)` provides `open_pdf(document_id: str) -> VerifiedPdf | None` and `describe_pdf(document_id: str, pages: list[KnowledgePage]) -> dict[str, str] | None`. `VerifiedPdf` owns one verified, open descriptor and safe display filename. `build_public_documents_router(catalog: ProcessedPdfCatalog) -> APIRouter` serves `GET /v1/documents/{document_id}/original`.

- [ ] Write route tests for valid processed PDF (200, inline PDF, safe headers/bytes), missing source page, missing original, Markdown/LaTeX source, wrong media type, bad ID, wrong digest, wrong PDF signature, symlink original, and replaced/deleted source.
- [ ] Run `uv run --extra dev pytest tests/test_public_documents.py -q`; confirm tests fail for the missing route/catalog.
- [ ] Implement catalog eligibility using canonical source page, validated ID, `.pdf` filename, optional PDF media type, meaningful extracted text, digest, `O_NOFOLLOW` descriptor, regular-file check, signature, and SHA-256; stream only from the verified descriptor. Return 404 for all ineligible cases.
- [ ] Run focused tests and `uv run --extra dev pytest -q`; confirm zero failures, then commit the task.

### Task 2: Grounded citation-to-PDF metadata (agent repository)

**Files:** Modify `src/cv_agent/agent/service.py`, `src/cv_agent/api/responses.py`, `src/cv_agent/main.py`; create `src/cv_agent/agent/source_documents.py`; test `tests/test_source_documents.py`, `tests/test_agent_service.py`, `tests/test_response_schema.py`.

**Interfaces:** `resolve_source_documents(answer: str, pages: list[KnowledgePage], catalog: ProcessedPdfCatalog) -> list[dict[str, object]]` returns `{title, documents:[{filename,path}]}` entries for final-line citations. `AgentService.answer_with_sources(input_text: str, extra_instructions: str | None = None) -> AgentAnswer` returns text plus metadata from the same pinned search; `answer()` remains a string-returning compatibility wrapper. `/v1/responses` adds `source_documents` while retaining existing fields and supporting injected string-only answerers in tests.

- [ ] Write tests for direct source, generated page with two PDFs, one PDF plus one Markdown/LaTeX, repeated refs, duplicate titles, unknown title, citation only in prose, absent original, and snapshot reload between answer and metadata resolution.
- [ ] Run focused tests; confirm red failures before product edits.
- [ ] Implement final-line citation parsing, exact unique title resolution, `[[sources/<id>]]` traversal, stable deduplication, and metadata assembly without trusting model URLs. Wire the service result through the responses router and app.
- [ ] Run `uv run --extra dev pytest -q` and `git diff --check`; confirm zero failures, then commit the task.

### Task 3: Clean citations and safe links (blog repository `~/blog/site`)

**Files:** Modify `src/worker/citations.ts`, `src/worker/cv-chat.ts`; test `tests/integration/cv-worker.test.ts`; add `tests/unit/cv-citations.test.ts` if needed for focused parser cases.

**Interfaces:** Worker response becomes `{answer: string, sources: Array<{title: string, documents: Array<{filename: string, url: string}>}>}`. Agent metadata uses `{title, documents:[{filename,path}]}`. `extractCitations(answer)` returns clean answer text plus cited titles. A Worker helper accepts only `/v1/documents/<safe-id>/original` paths and constructs URLs from `CV_AGENT_URL`.

- [ ] Write tests for `Sources:`/`Fuentes:` with one/multiple citations and commas, ordinary prose punctuation, empty/malformed citations, valid agent PDF metadata, missing metadata, unknown title, malformed path, absolute URL, traversal, and non-HTTPS origin.
- [ ] Run `corepack pnpm@11.3.0 test:integration`; confirm expected red failures.
- [ ] Implement citation-only final-line removal and strict metadata/path matching; preserve title-only sources when agent metadata is absent.
- [ ] Run `corepack pnpm@11.3.0 test` and `corepack pnpm@11.3.0 lint`; confirm zero failures, then commit on a blog feature branch.

### Task 4: Clickable PDF sources (blog repository `~/blog/site`)

**Files:** Modify `src/scripts/cv-chat-state.ts`, `src/scripts/cv-chat.ts`, `src/pages/cv.astro`; test `tests/unit/cv-chat-state.test.ts`, `tests/integration/cv-page.test.ts`, `tests/e2e/cv-chat.spec.ts`.

**Interfaces:** `FormattedAnswer.sources` uses the Worker's structured source objects. Each source title remains text, and each verified PDF document becomes a DOM-created `<a>` with filename, direct URL, `target="_blank"`, and `rel="noopener noreferrer"`.

- [ ] Write unit, integration, and E2E tests for clickable PDFs, title-only Markdown/LaTeX sources, accessible filename, safe DOM insertion, and absence of orphan commas.
- [ ] Run focused tests; confirm red failures before product edits.
- [ ] Update state types, payload validation, DOM rendering, and source-list styling without changing other chat behavior.
- [ ] Run `corepack pnpm@11.3.0 test`, `corepack pnpm@11.3.0 test:e2e`, `corepack pnpm@11.3.0 lint`, `corepack pnpm@11.3.0 format:check`, and `corepack pnpm@11.3.0 run build`; confirm zero failures, then commit.

### Task 5: Review, release, and production checks (both repositories)

**Files:** No product files unless review or verification identifies a defect.

**Interfaces:** Agent PR merges before blog PR. Render auto-deploys agent `main`; Wrangler deploys blog after its PR merges.

- [ ] Request independent code review of both branches and fix material findings with tests.
- [ ] Re-run full suites and clean-diff checks; push branches, create PRs, and merge after checks pass.
- [ ] Confirm Render's merged commit is live, then deploy the merged blog Worker and confirm `/cv/` and `/api/cv-config` return 200.
- [ ] Verify a real cited PDF link returns 200 with `application/pdf` and PDF signature; verify a Markdown/LaTeX citation has no link and the transcript has no orphan comma. Avoid printing secrets or PDF contents.
