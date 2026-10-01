# Public links to processed CV originals

## Intent and scope

Readers of the CV chat should be able to open official PDF originals behind its cited sources. Only PDFs successfully processed by the agent's ingestion or legacy-migration flow may become public. This rule also applies automatically to future successful ingestions. Markdown and LaTeX may still be ingested as knowledge but must never receive public links. Fix the stray commas left in the blog transcript when the Worker removes the agent's Obsidian-style citations.

This change spans the agent repository and the `~/blog/site` repository. It does not publish the entire mounted data directory, backups, quarantined uploads, unprocessed files, or admin APIs. A citation with no verified original remains visible as plain text.

## Existing flow and cause

The agent answers with a final `Sources:` or `Fuentes:` line containing `[[page title]]` citations. A title may identify a canonical `sources/<document_id>.md` page or a generated `knowledge/...` page. Generated pages contain validated `[[sources/<document_id>]]` references. The source page records `document_id`, `original_filename`, and `content_sha256`; the original is stored as `documents/<document_id>.<extension>` on Render's persistent disk.

The blog Worker currently removes citation tokens and returns title strings. It leaves the punctuation between tokens, producing the commas seen in the widget. The browser renders each title as plain text.

## Agent: eligibility and download

Add a public, read-only `GET /v1/documents/{document_id}/original` route. A download is eligible only when the active knowledge snapshot has a canonical `sources/<document_id>.md` page with `kind: source`, matching `document_id`, meaningful extracted text, an original filename ending in `.pdf`, and a valid SHA-256 digest. If the record has a media type, it must be `application/pdf`; legacy-migrated records may omit it. The canonical `<document_id>.pdf` original must exist as a regular, non-symlink file under the mounted `documents` directory, begin with the PDF signature, and have a SHA-256 matching the source page. This makes successful PDF processing, not mere file presence, the publication boundary. A deleted/replaced source or mismatched original becomes unavailable immediately. The route must reject malformed IDs and non-PDF records without disclosing filesystem paths or internal metadata.

Open the PDF without following symlinks and stream from that already-verified descriptor, preventing a path swap after verification. Serve it as `application/pdf` with inline disposition so the browser may preview it. Set `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, and a safe PDF filename. Missing or ineligible documents return 404. The route requires no bearer token because these eligible PDFs are intentionally public; existing admin routes remain authenticated.

## Agent: citation metadata

Keep the existing `output_text` and OpenAI-compatible response shape intact. Add an optional structured `source_documents` field to `/v1/responses`, derived on the server from the answer's final cited titles and the pinned active knowledge, never from URLs written by the language model. For a directly cited source page, associate its one original. For a cited generated page, follow its validated `[[sources/<document_id>]]` references and associate each verified original, deduplicated by document ID. A title that ambiguously matches more than one page, an unknown title, or a source without a verified original produces no link; the citation title itself remains visible. Each document entry carries a display filename and only a relative path under `/v1/documents/`, not an arbitrary URL.

The metadata describes only titles actually present in the answer's final sources line. Keep ordering stable: citation order, then source-reference order. The answer and metadata should use the same pinned knowledge revision so a concurrent ingestion or rollback cannot pair a citation with unrelated data. A later download rechecks eligibility against current state.

## Blog Worker and widget

The Worker continues to proxy chat requests and handle Turnstile/rate limiting. It extracts the final `Sources:`/`Fuentes:` citation line, removes the whole citation-only line and its separators from the answer, and returns each source title with zero or more original-document links. For older agent responses lacking `source_documents`, return title-only sources. Accept only relative paths matching the public original route and build absolute HTTPS URLs using the validated `CV_AGENT_URL`; never relay model-supplied or arbitrary external URLs.

The widget renders the source title as text and each eligible PDF as a real anchor, with a discernible filename, `target="_blank"`, and `rel="noopener noreferrer"`. This opens the PDF in another tab when the browser supports it; there is no embedded viewer. Sources backed only by Markdown, LaTeX, or an unavailable PDF remain text. Continue to insert text through DOM text APIs, not HTML injection. The transcript must not display orphan commas or an empty sources label.

## Rollout and verification

Deploy the agent before the blog so the old Worker can ignore the additive response field. The new Worker tolerates older agent responses during rollout. Tests cover direct source citations, generated pages with multiple PDFs, duplicate/unknown titles, Markdown/LaTeX records without links, missing/unprocessed/mismatched/symlink PDFs, malformed IDs, concurrent snapshot changes, source-line punctuation in both languages, backward compatibility, safe URL handling, and clickable widget links. Run both repositories' unit/integration suites and blog E2E tests, then verify a real processed PDF citation and download in production. Do not display secrets or document contents in logs.
