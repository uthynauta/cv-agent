# Generic CV Agent And Mounted Storage Design

## Context

The current service is a working FastAPI CV RAG agent with an Open Responses-compatible endpoint, ingestion, local Markdown retrieval, an admin dashboard, and optional remote publishing. It is coupled to one candidate and its original deployment through package names, service metadata, prompts, examples, defaults, deployment documentation, and a committed wiki corpus.

This refactor turns the repository into a reusable CV agent template. Application code and candidate knowledge become separate concerns: the repository contains the generic service, while all candidate documents, extracted text, generated knowledge, and local version history live on mounted storage.

Existing Git history remains unchanged. The refactor is a normal forward commit; it does not rewrite or purge historical commits.

## Goals

- Rename the application and Python package from the legacy namespace to `cv_agent`.
- Remove active references to the legacy brand, original challenge, current candidate, employers, and current deployment.
- Make the repository safe and practical to fork for another person's CV agent.
- Keep candidate documents and generated RAG knowledge out of the application repository.
- Use a mounted data directory as the sole runtime knowledge store.
- Version extracted and generated Markdown in a local Git repository on the mounted disk.
- Keep original PDF binaries persistent but outside Git history.
- Support document upload, replacement, deletion, rebuild, history inspection, and rollback.
- Support knowledge-only and full backup export plus validated restore.
- Configure identity, language, paths, models, authentication, public metadata, retrieval, and operations through environment variables.
- Preserve the existing stateless, non-streaming Open Responses-compatible endpoint and agent card.
- Preserve retrieval, optional reranking, grounding, citations, metrics, tracing, and admin authentication where they remain generic.

## Non-Goals

- Do not rewrite existing Git history.
- Do not retain a candidate corpus or real CV fixtures in the application repository.
- Do not publish candidate data to GitHub or another remote Git server.
- Do not support arbitrary model providers in this refactor; the model backend remains OpenAI.
- Do not add streaming Responses output or server-side conversation state.
- Do not add a hosted vector store or database.
- Do not add multi-user admin accounts or roles.
- Do not treat local Git history as encryption or as a substitute for volume backups.

## Architecture

The application remains one Dockerized FastAPI service with these boundaries:

- `cv_agent.api`: Open Responses endpoint, agent card, health, readiness, metrics, and request normalization.
- `cv_agent.agent`: grounded response generation, citation validation, configurable identity, and language behavior.
- `cv_agent.knowledge`: extraction, ingestion, generated Markdown, repository access, lexical search, and optional reranking.
- `cv_agent.admin`: admin authentication, browser UI, document management, status, local history, rollback, backup, and restore.
- `cv_agent.config`: environment-backed runtime configuration.

The application repository contains code, tests, documentation, and synthetic fixtures only. The Docker image does not copy or seed a wiki or candidate corpus.

The container installs the Git CLI as an explicit runtime dependency. Storage code invokes only bounded, argument-list Git commands against the resolved mounted repository path; it never evaluates user-provided command strings.

## Naming

The active application uses generic names throughout:

- Python package: `cv_agent`
- Python distribution: `cv-agent`
- CLI command: `cv-agent`
- Compose service: `cv-agent`
- FastAPI title: `CV Agent`
- Default public model identifier: `cv-agent`
- Browser session cookie: `cv_agent_admin_session`

Tests, examples, prompts, agent-card fields, observability defaults, and deployment documentation use synthetic or generic candidate data. Historical Git commits are allowed to retain old names.

## Mounted Storage

`DATA_DIR` identifies the persistent mount root. The application derives all other data paths from it:

```text
DATA_DIR/
├── documents/             # current original files; persistent and never Git-tracked
│   └── quarantine/        # rollback mismatches; excluded from active inventory
├── repository/
│   ├── .git/              # local-only history; no remote
│   ├── sources/           # versioned normalized source Markdown
│   └── knowledge/         # versioned generated RAG Markdown
├── backups/               # generated bundles and full archives
├── staging/               # temporary transactional work
└── locks/                 # mutation lock files
```

A fresh deployment creates this structure with an initialized local Git repository and no candidate knowledge. `/healthz` reports process health. `/readyz` reports that knowledge is not initialized until at least one source has been ingested successfully. Admin routes remain available while public answering is not ready.

No Git remote is configured. The admin UI cannot add one. Candidate information never enters the application repository through runtime behavior.

## Configuration

The primary configuration surface is environment-based:

```text
DATA_DIR=/data

AGENT_OWNER_NAME=
AGENT_DISPLAY_NAME=CV Agent
AGENT_DESCRIPTION=Ask questions about this candidate's CV.
AGENT_LANGUAGE=auto
AGENT_PUBLIC_URL=
AGENT_MODEL_NAME=cv-agent

OPENAI_API_KEY=
OPENAI_MODEL=
AGENT_API_KEY=

ADMIN_API_KEY=
ADMIN_UI_PASSWORD=
ADMIN_UI_SESSION_SECRET=
ADMIN_UI_SESSION_MAX_AGE_SECONDS=43200
ADMIN_UPLOAD_MAX_BYTES=10485760
ADMIN_BACKUP_MAX_BYTES=104857600
BACKUP_RETENTION_COUNT=10

DATA_GIT_AUTHOR_NAME=CV Agent
DATA_GIT_AUTHOR_EMAIL=cv-agent@localhost

RETRIEVAL_MODE=lexical
RERANK_MODEL=
RERANK_TOP_K=20
ANSWER_TOP_K=5
CONTEXT_MODE=page
MAX_CONTEXT_CHARS=12000

OTEL_ENABLED=false
OTEL_SERVICE_NAME=cv-agent
OTEL_EXPORTER_OTLP_ENDPOINT=
OTEL_EXPORTER_OTLP_INSECURE=true
OTEL_RESOURCE_ATTRIBUTES=
```

The legacy wiki-path setting and all remote-publishing settings are removed. Configuration validation rejects unsupported language/retrieval/context values, unsafe data paths, and invalid limits without exposing secrets. This release accepts `AGENT_LANGUAGE=auto`, `AGENT_LANGUAGE=es`, or `AGENT_LANGUAGE=en`.

Public readiness requires a configured owner name, public URL, OpenAI API key and model, plus usable active knowledge. Missing public configuration never blocks authenticated admin initialization routes.

### Language Behavior

- `AGENT_LANGUAGE=auto` detects and follows the latest user request language.
- A configured language code, such as `es` or `en`, enforces that output language.
- Generated answers, deterministic fallbacks, validation messages, and the sources heading follow the effective language.
- Client instructions may adjust tone and detail but cannot override configured language enforcement, grounding, identity, or citation policy.

### Identity Behavior

`AGENT_OWNER_NAME`, `AGENT_DISPLAY_NAME`, and `AGENT_DESCRIPTION` drive prompts and agent-card metadata. Career facts are never supplied through these settings; they come only from active mounted knowledge.

## Source Documents And Markdown Identity

Supported source types remain `.pdf`, `.md`, and `.tex`.

Original files are stored under `DATA_DIR/documents/` so the current source set survives restarts and redeploys. These files are outside the local Git work tree and are never added to Git history.

Every accepted source produces stable, versioned Markdown under `repository/sources/`. The source page contains full normalized extracted text plus identity metadata:

```yaml
document_id: <stable server-generated identifier>
original_filename: cv.pdf
media_type: application/pdf
uploaded_at: <UTC timestamp>
content_sha256: <digest>
extractor_version: <version>
```

`document_id` remains stable when an admin replaces a logical source. `content_sha256` changes with source bytes and identifies the exact extracted version. The full normalized text makes the usable source knowledge independently versionable and reconstructable without placing the PDF binary in Git. Generated pages under `repository/knowledge/` cite these source pages.

Binary files are included only in a full backup, not in a knowledge Git bundle.

## Knowledge Lifecycle

The admin UI and bearer-authenticated admin API support:

- Listing current sources with document ID, checksum, type, and update time.
- Uploading a new source.
- Replacing a source while retaining its stable logical identity.
- Deleting a source and all knowledge derived only from it.
- Rebuilding generated knowledge from the current source set.
- Viewing local commit history and changed-file summaries.
- Rolling back to a prior local commit.
- Exporting and restoring backups.

### Transactional Mutation

Every upload, replacement, deletion, rebuild, rollback, or restore follows one mutation path:

1. Acquire an exclusive filesystem mutation lock.
2. Create an operation ID and isolated staging area.
3. Validate source type, size, path, encoding, and extractability.
4. Extract full normalized text and create source identity Markdown.
5. Generate or rebuild affected knowledge pages in staging.
6. Validate paths, manifests, citations, index contents, and minimum usable knowledge.
7. Prepare current original documents under the mounted `documents/` store.
8. Commit all Markdown changes to the mounted local Git repository.
9. Build a new immutable in-memory retrieval index from the committed revision.
10. Atomically activate the new retrieval index and finish original-document replacement.

If any pre-commit step fails, staging is discarded and active state remains unchanged. If index activation or final document activation fails after commit, the operation restores the prior commit and active index before releasing the lock. Logs contain operation IDs, document IDs, and commit IDs, never document contents.

Public response requests use the last successfully activated in-memory index, so they do not observe partially written files during admin mutations.

### Local Git Commits

Each successful mutation creates one commit with a deterministic operation-oriented message and configured automated author. Commit metadata records the operation and affected document IDs without embedding document content in the message.

The service exposes bounded history and changed-file summaries through admin routes. It does not expose arbitrary Git commands, repository paths, or raw `.git` contents.

## Backup And Restore

Two export formats are available:

- **Knowledge bundle:** a Git bundle containing complete versioned Markdown history.
- **Full backup:** a compressed archive containing the knowledge Git bundle, current original documents, and a checksummed manifest.

Restore behavior:

1. Authenticate as admin and require explicit destructive-action confirmation.
2. Stream the upload under the configured size limit.
3. Reject absolute paths, traversal paths, links, unexpected file types, invalid manifests, and checksum failures.
4. Validate the Git bundle and materialize candidate state in staging.
5. Validate the resulting knowledge repository and build a candidate retrieval index.
6. Create a recovery full backup of current state.
7. Atomically activate restored storage and index.
8. Retain the recovery backup and report the new active commit.

Rollback to a local commit restores versioned Markdown and retrieval state. It cannot restore an older original binary unless that binary is supplied by a full backup. During rollback, each current original is checked against the restored source page's `content_sha256`; mismatched originals are quarantined outside the active document set and reported as missing originals. This prevents an older Markdown revision from being falsely associated with newer binary bytes. The UI makes this limitation explicit before rollback.

Backup upload/download size uses `ADMIN_BACKUP_MAX_BYTES`, independently from source upload limits. Completed backups are retained according to `BACKUP_RETENTION_COUNT`; automatic cleanup never rewrites local Git history. Backup files remain on mounted storage until retention cleanup or deletion through a bounded admin action. Volume snapshot procedures are documented. Local Git is not an off-volume backup.

## Open Responses Surface

The public surface remains:

- `POST /v1/responses`
- `GET /.well-known/agent-card.json`
- `GET /healthz`
- `GET /readyz`
- `GET /metrics`

`POST /v1/responses` remains stateless and non-streaming. It accepts supported plain and transcript-replay input forms, extracts the latest user request, retains bounded context for reference resolution, and returns completed Open Responses-compatible message and `output_text` fields.

The response path:

1. Apply optional `AGENT_API_KEY` bearer authentication and request-size limits.
2. Normalize the request and extract the latest user command plus bounded context.
3. Search the active mounted knowledge index.
4. Optionally rerank candidates through the configured OpenAI model.
5. Assemble bounded page or excerpt context.
6. Ask the configured OpenAI model for a grounded answer using configured identity and language.
7. Validate language, grounding, and citations.
8. Return generated output or a grounded deterministic fallback.

When no active knowledge exists, `/v1/responses` returns a clear `503` without attempting a model call. The agent card uses configured generic metadata and public URL.

Streaming, `previous_response_id` state, alternate model providers, hosted retrieval, and complete protocol expansion are deferred.

## Admin UI

The browser dashboard retains signed-session authentication and provides:

- Runtime, storage, OpenAI, and readiness status.
- Active candidate identity and effective language configuration without secret values.
- Current source inventory.
- Upload, replace, delete, and rebuild actions.
- Active local commit and bounded history.
- Changed-file summaries and rollback controls.
- Knowledge-bundle and full-backup export.
- Validated restore/import.
- Last operation status with actionable redacted errors.

Delete, rollback, restore, and backup deletion require explicit confirmation. The UI never displays API keys, session secrets, source document text, Git internals, or raw exception details.

## Security

- Keep public bearer auth and separate admin bearer/session credentials.
- Use signed, HttpOnly, appropriately Secure and SameSite browser cookies.
- Compare passwords and tokens in constant time where applicable.
- Normalize uploaded filenames and assign server-controlled document paths.
- Confine all data operations to resolved paths under `DATA_DIR`.
- Validate archive entries before extraction and reject links and traversal.
- Use exclusive filesystem locking for mutations.
- Never configure or invoke a Git remote.
- Never log prompts, source text, generated knowledge, secrets, or archive contents.
- Treat mounted disk permissions, hosting access controls, encryption at rest, and snapshots as deployment responsibilities.

## Error Handling

- Missing or unwritable `DATA_DIR`: health remains live; readiness and affected admin status fail with an actionable redacted reason.
- Missing candidate knowledge: public responses return `503`; initialization routes remain available.
- Invalid or image-only PDF: reject before changing active state and explain OCR requirement.
- Extraction, ingestion, or validation failure: discard staging and keep prior revision/index active.
- Git commit failure: keep prior revision/index active.
- Index activation failure: restore prior commit/index before completing the operation.
- Lock contention: return a bounded conflict response with operation status rather than run concurrent mutations.
- Invalid or corrupt backup: reject before mutation.
- Restore failure: retain current state and recovery artifacts; never partially activate restored files.
- OpenAI failure: preserve existing redacted model-error and grounded-fallback behavior where context permits.

## Legacy Migration

Existing installations can migrate explicitly before removing their old wiki mount:

```bash
cv-agent migrate-data \
  --from-wiki /old/wiki \
  --to-data-dir /data
```

The command:

1. Refuses a non-empty destination unless an explicit supported merge/replace option is selected.
2. Copies current original documents to the mounted document store when available.
3. Converts or imports generated Markdown into `sources/` and `knowledge/`.
4. Initializes the local Git repository and creates one migration commit.
5. Builds the retrieval index and runs the same knowledge validation as startup.
6. Reports the active commit and required `DATA_DIR` configuration.

Migration is never automatic. This avoids silently mixing bundled legacy data with a new candidate store. After migration, tracked legacy corpus files are removed from the application repository in the forward refactor commit.

## Testing

Focused tests cover:

- Package, distribution, CLI, Compose service, cookie, and application-title rename.
- Absence of active legacy-brand, challenge, candidate, employer, and deployment-specific references.
- Docker build context and image contain no bundled candidate corpus.
- Environment defaults, validation, blank normalization, and secret redaction.
- Empty mounted-storage initialization and health/readiness behavior.
- Safe path confinement under `DATA_DIR`.
- PDF extraction into full source Markdown with identity metadata.
- Stable document identity across replacement with changing content checksum.
- Confirmation that original PDFs are persistent but absent from local Git history.
- Upload, replace, delete, rebuild, commit creation, history, and rollback.
- Exclusive mutation locking and failure rollback at each transaction stage.
- Retrieval index activation only after successful commit and validation.
- Knowledge Git bundle export and full backup export.
- Independent source-upload and backup size limits plus backup retention.
- Archive traversal, link, type, manifest, and checksum rejection.
- Restore recovery checkpoint and atomic activation.
- Rollback quarantine for original binaries that do not match restored checksums.
- Legacy wiki migration into mounted local Git storage.
- Configured identity in prompts and agent-card output.
- Automatic and enforced response language, including deterministic fallbacks.
- Stateless Open Responses request normalization and response shape.
- Admin bearer/session authentication and destructive-action confirmation.
- Existing retrieval, optional reranking, grounding, citations, metrics, and tracing.
- Container startup and focused end-to-end upload/query/backup/restore flow.

## Implementation Strategy

Implementation proceeds as an in-place refactor, preserving tested behavior and Git history. Work is divided into bounded tasks suitable for `gpt-5.6-luna` subagents, with central integration, diff review, and full verification before completion.

Likely task boundaries are:

1. Generic package/branding/configuration rename.
2. Mounted local Git storage and source identity Markdown.
3. Transactional document management and retrieval-index activation.
4. Backup, restore, history, and rollback services.
5. Admin API/UI changes.
6. Legacy migration, Docker/deployment documentation, and corpus removal.
7. Cross-cutting tests, container checks, and final branding/data audit.
