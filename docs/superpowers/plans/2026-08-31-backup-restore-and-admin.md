# Backup Restore And Admin Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use $subagent-driven-development (recommended) or $executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete generic identity/language behavior, safe backup/restore, browser lifecycle controls, legacy migration, and final deployment/data audits.

**Architecture:** Language and identity policy remain isolated from retrieval. `BackupService` creates bounded Git bundles and manifest-based full archives, while `RestoreService` validates entirely in staging and reuses the lifecycle lock/activation path. Admin API and server-rendered dashboard call the same services; migration is explicit CLI-only.

**Tech Stack:** Python 3.12+, FastAPI, OpenAI SDK, stdlib `tarfile`/`hashlib`/`json`, Git CLI, HTML/CSS/JavaScript, pytest, Docker.

---

## File Structure

- Create `src/cv_agent/agent/language.py`: `auto`/English/Spanish prompt and validation policy.
- Modify `src/cv_agent/agent/prompts.py`, `service.py`, and agent card for generic identity.
- Create `src/cv_agent/knowledge/backup.py`: bundle/archive creation, manifests, retention.
- Create `src/cv_agent/knowledge/restore.py`: archive/bundle validation and recovery activation.
- Modify `src/cv_agent/api/admin.py`: backup/restore endpoints.
- Rewrite `src/cv_agent/admin/ui.py`: source/history/backup/restore workflows.
- Add `migrate-data` command to `src/cv_agent/cli.py`.
- Complete generic docs, Compose/Docker checks, and end-to-end tests.

### Task 1: Configurable Identity And Language Enforcement

**Files:**
- Create: `src/cv_agent/agent/language.py`
- Modify: `src/cv_agent/agent/prompts.py`
- Modify: `src/cv_agent/agent/service.py`
- Modify: `src/cv_agent/api/agent_card.py`
- Modify: `src/cv_agent/config.py`
- Test: `tests/test_language.py`
- Modify: `tests/test_agent_service.py`
- Modify: `tests/test_agent_card.py`

- [ ] **Step 1: Write failing language-policy tests**

```python
@pytest.mark.parametrize(
    ("configured", "question", "expected"),
    [("es", "Tell me about Python", "es"), ("en", "¿Qué experiencia tiene?", "en"),
     ("auto", "¿Qué experiencia tiene?", "es"), ("auto", "Tell me about Python", "en")],
)
def test_effective_language(configured, question, expected):
    assert LanguagePolicy(configured).effective_language(question) == expected


def test_spanish_setting_rejects_english_answer():
    policy = LanguagePolicy("es")
    assert policy.validate("The candidate uses Python. Sources: [[Python]]", "es") is False


def test_english_setting_rejects_spanish_answer():
    policy = LanguagePolicy("en")
    assert policy.validate("La persona usa Python. Fuentes: [[Python]]", "en") is False
```

- [ ] **Step 2: Verify missing policy**

```bash
uv run --extra dev pytest tests/test_language.py -q
```

Expected: FAIL because `LanguagePolicy` is missing.

- [ ] **Step 3: Implement bounded policy**

For this release, validate `AGENT_LANGUAGE` as exactly `auto`, `es`, or `en`. `auto` detects Spanish using inverted punctuation, accented characters, and a bounded stopword set; otherwise it selects English. `LanguagePolicy` exposes:

Implement `LanguagePolicy` with typed methods `effective_language(question)`, `instruction(effective)`, `sources_label(effective)`, `validate(answer, effective)`, and `fallback(effective, source_titles)`. Constructor accepts only `Literal["auto", "es", "en"]`.

Use deterministic lexical validators for Spanish/English, ignore citation titles when scoring language, and require final localized `Fuentes:`/`Sources:` line.

- [ ] **Step 4: Make prompts and card generic**

Build mandatory instructions from settings:

```python
identity = (
    f"You are {settings.agent_display_name}, a grounded CV assistant for "
    f"{settings.agent_owner_name or 'the configured candidate'}. "
    f"{settings.agent_description}"
)
```

Remove reviewer/challenge/candidate-specific assumptions. Apply effective language to generation, validation, and fallback. Agent-card `name`, `description`, model identifier, endpoint URL, and capabilities come only from settings plus generic constants.

- [ ] **Step 5: Verify and commit**

```bash
uv run --extra dev pytest tests/test_language.py tests/test_agent_service.py tests/test_agent_card.py -q
```

Expected: PASS.

```bash
git add src/cv_agent/agent src/cv_agent/api/agent_card.py src/cv_agent/config.py tests/test_language.py tests/test_agent_service.py tests/test_agent_card.py
git commit -m "feat(agent): configure identity and language"
```

### Task 2: Knowledge Bundle And Full Backup Export

**Files:**
- Create: `src/cv_agent/knowledge/backup.py`
- Modify: `src/cv_agent/knowledge/git_store.py`
- Modify: `src/cv_agent/api/admin.py`
- Test: `tests/test_backup.py`
- Test: `tests/test_admin_backup.py`

- [ ] **Step 1: Write failing backup tests**

```python
def test_knowledge_backup_is_valid_git_bundle(backup_service):
    result = backup_service.create_knowledge_bundle()
    completed = subprocess.run(
        ["git", "bundle", "verify", str(result.path)], capture_output=True, text=True
    )
    assert completed.returncode == 0
    assert result.path.suffix == ".bundle"


def test_full_backup_contains_bundle_originals_and_checksums(backup_service):
    result = backup_service.create_full_backup()
    with tarfile.open(result.path, "r:gz") as archive:
        names = set(archive.getnames())
        manifest = json.load(archive.extractfile("manifest.json"))
    assert "knowledge.bundle" in names
    assert "documents/doc-1.pdf" in names
    assert manifest["format_version"] == 1
    assert manifest["active_commit"]
    assert manifest["files"]["documents/doc-1.pdf"]["sha256"]


def test_retention_removes_only_old_managed_backups(backup_service):
    for _ in range(4):
        backup_service.create_knowledge_bundle()
    backup_service.retention_count = 2
    backup_service.prune()
    assert len(backup_service.list()) == 2
```

- [ ] **Step 2: Verify missing service**

```bash
uv run --extra dev pytest tests/test_backup.py -q
```

Expected: FAIL.

- [ ] **Step 3: Implement bundle and archive types**

```python
@dataclass(frozen=True)
class BackupRecord:
    name: str
    kind: Literal["knowledge", "full"]
    path: Path
    created_at: str
    size_bytes: int
    sha256: str


```

Implement `BackupService.create_knowledge_bundle()`, `create_full_backup()`, `list()`, `resolve_download(name)`, `delete(name, confirmed)`, and `prune()` with the `BackupRecord` return types shown above.

Create bundles with `git bundle create <path> main`. Build full archives using server-generated member names only. `manifest.json` records format version, UTC creation time, active commit, agent model identifier, and SHA-256/size for bundle and each current original. Never include secrets, absolute paths, staging, locks, existing backups, or quarantined mismatches.

- [ ] **Step 4: Add authenticated backup routes**

```text
GET    /admin/backups
POST   /admin/backups/knowledge
POST   /admin/backups/full
GET    /admin/backups/{name}
DELETE /admin/backups/{name}  body: {"confirm": true}
```

Use attachment responses, server-controlled filenames, `ADMIN_BACKUP_MAX_BYTES`, and generic redacted errors.

- [ ] **Step 5: Verify and commit**

```bash
uv run --extra dev pytest tests/test_backup.py tests/test_admin_backup.py -q
```

Expected: PASS.

```bash
git add src/cv_agent/knowledge/backup.py src/cv_agent/knowledge/git_store.py src/cv_agent/api/admin.py tests/test_backup.py tests/test_admin_backup.py
git commit -m "feat(admin): export mounted knowledge"
```

### Task 3: Safe Restore With Recovery Checkpoint

**Files:**
- Create: `src/cv_agent/knowledge/restore.py`
- Modify: `src/cv_agent/knowledge/backup.py`
- Modify: `src/cv_agent/knowledge/documents_service.py`
- Modify: `src/cv_agent/api/admin.py`
- Test: `tests/test_restore.py`
- Modify: `tests/test_admin_backup.py`

- [ ] **Step 1: Write failing restore-security tests**

```python
@pytest.mark.parametrize("member", ["../escape", "/absolute", "documents/../../escape"])
def test_restore_rejects_unsafe_member(restore_service, archive_factory, member):
    archive = archive_factory(extra_member=member)
    with pytest.raises(BackupValidationError):
        restore_service.restore_full(archive, confirmed=True)


def test_restore_rejects_links(restore_service, archive_factory):
    archive = archive_factory(link_member="documents/link.pdf")
    with pytest.raises(BackupValidationError):
        restore_service.restore_full(archive, confirmed=True)


def test_failed_restore_preserves_state_and_recovery_backup(restore_service, corrupt_archive):
    previous = restore_service.documents.git.head()
    with pytest.raises(BackupValidationError):
        restore_service.restore_full(corrupt_archive, confirmed=True)
    assert restore_service.documents.git.head() == previous
```

- [ ] **Step 2: Verify missing restore service**

```bash
uv run --extra dev pytest tests/test_restore.py -q
```

Expected: FAIL.

- [ ] **Step 3: Implement archive validation before extraction**

`RestoreService` accepts a staged upload path and confirmation. Before mutation it checks compressed byte size, tar member count, normalized relative paths, allowed regular-file types, no links/devices, per-file size, total expanded size, exact manifest schema, all checksums, and `git bundle verify`. Extraction uses explicit validated members into a fresh staging directory, never `extractall()` on untrusted members.

- [ ] **Step 4: Implement recovery and activation**

Under the lifecycle mutation lock:

1. fully validate/materialize restore candidate;
2. run knowledge validation and build candidate snapshot;
3. create a recovery full backup of current state;
4. activate restored local Git repository and matching originals;
5. activate candidate index;
6. on any failure, restore recovery state and old index;
7. report active commit and recovery backup name.

Knowledge-bundle restore quarantines current originals not matching restored source hashes. Full restore activates only originals matching the restored manifest.

- [ ] **Step 5: Add restore endpoint and verify**

Expose `POST /admin/restore` as multipart `file` plus form field `confirm=true`. Require admin auth; map confirmation to `409`, invalid archive to `422`, excessive input to `413`, lock contention to `409`.

```bash
uv run --extra dev pytest tests/test_restore.py tests/test_admin_backup.py tests/test_document_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cv_agent/knowledge src/cv_agent/api/admin.py tests/test_restore.py tests/test_admin_backup.py tests/test_document_service.py
git commit -m "feat(storage): restore validated backups"
```

### Task 4: Complete Browser Administration

**Files:**
- Create: `src/cv_agent/admin/templates.py`
- Modify: `src/cv_agent/admin/ui.py`
- Modify: `src/cv_agent/main.py`
- Modify: `tests/test_admin_ui.py`

- [ ] **Step 1: Write failing dashboard workflow tests**

```python
def test_dashboard_contains_document_revision_and_backup_tools(logged_in_client):
    response = logged_in_client.get("/admin/ui")
    assert response.status_code == 200
    assert 'data-document-table' in response.text
    assert 'data-revision-table' in response.text
    assert 'data-create-full-backup' in response.text
    assert 'data-restore-form' in response.text
    assert "Publish" not in response.text
    assert "GitHub" not in response.text


def test_ui_lifecycle_proxies_require_session(client):
    assert client.get("/admin/ui/documents").status_code == 401
    assert client.get("/admin/ui/revisions").status_code == 401
    assert client.get("/admin/ui/backups").status_code == 401


def test_ui_delete_and_rollback_require_confirmation(logged_in_client, document_service):
    document = document_service.add("candidate.md", b"Python")
    assert logged_in_client.delete(
        f"/admin/ui/documents/{document.document_id}", json={"confirm": False}
    ).status_code == 409
    assert logged_in_client.post(
        f"/admin/ui/revisions/{document.commit}/rollback", json={"confirm": False}
    ).status_code == 409
```

- [ ] **Step 2: Verify missing UI workflows**

```bash
uv run --extra dev pytest tests/test_admin_ui.py -q
```

Expected: FAIL for missing dashboard controls/routes.

- [ ] **Step 3: Split HTML rendering from route/auth logic**

Move login/dashboard HTML functions to `admin/templates.py`. Keep signed-cookie helpers and route handlers in `admin/ui.py`. Dashboard is a dense operational layout with:

- compact header, refresh, and logout;
- storage/config/readiness status band;
- source table with replace/delete actions;
- upload and rebuild controls;
- revision table with changed paths and rollback;
- backup list with create/download/delete;
- restore form with explicit confirmation;
- stable result/error areas and 10-second status refresh.

Do not expose secrets, source text, absolute paths, or raw Git errors. Keep controls responsive at 360 px and desktop widths; avoid nested cards and marketing content.

- [ ] **Step 4: Add session-authenticated UI proxies**

Expose `/admin/ui/*` equivalents for documents, rebuild, revisions, rollback, backups, downloads, and restore. Each calls the same service/helper as bearer API routes. Return `401` JSON for invalid AJAX sessions and redirect only full-page dashboard requests.

- [ ] **Step 5: Implement browser confirmation and refresh behavior**

Use `window.confirm()` before delete/rollback/restore, then send `{"confirm": true}` or multipart `confirm=true`. Disable the initiating control while pending, render redacted response detail, and refresh relevant tables only after success.

- [ ] **Step 6: Verify and commit**

```bash
uv run --extra dev pytest tests/test_admin_ui.py tests/test_admin_lifecycle.py tests/test_admin_backup.py -q
```

Expected: PASS.

```bash
git add src/cv_agent/admin src/cv_agent/main.py tests/test_admin_ui.py
git commit -m "feat(admin): manage local CV storage in UI"
```

### Task 5: Explicit Legacy Wiki Migration

**Files:**
- Modify: `src/cv_agent/cli.py`
- Create: `src/cv_agent/knowledge/migrate.py`
- Test: `tests/test_migrate_data.py`
- Modify: `README.md`
- Modify: `docs/deployment.md`

- [ ] **Step 1: Write failing migration tests**

```python
def test_migration_imports_legacy_wiki_into_initial_local_commit(tmp_path):
    legacy = make_legacy_wiki(tmp_path / "legacy")
    destination = tmp_path / "data"
    result = migrate_legacy_wiki(legacy, destination, replace_existing=False)

    assert result.commit
    assert (destination / "repository" / "sources").glob("*.md")
    assert (destination / "repository" / "knowledge" / "index.md").exists()
    assert LocalKnowledgeGit(destination / "repository", "CV Agent", "cv-agent@localhost").remotes() == []


def test_migration_refuses_nonempty_destination(tmp_path):
    destination = tmp_path / "data"
    (destination / "documents").mkdir(parents=True)
    (destination / "documents" / "existing.pdf").write_bytes(b"PDF")
    with pytest.raises(MigrationError, match="destination is not empty"):
        migrate_legacy_wiki(make_legacy_wiki(tmp_path / "legacy"), destination, False)


def test_cli_requires_explicit_replace_flag(tmp_path):
    result = run_cli("migrate-data", "--from-wiki", str(tmp_path / "legacy"),
                     "--to-data-dir", str(tmp_path / "data"))
    assert result.exit_code != 0
```

- [ ] **Step 2: Verify missing command**

```bash
uv run --extra dev pytest tests/test_migrate_data.py -q
```

Expected: FAIL.

- [ ] **Step 3: Implement deterministic migration**

```python
@dataclass(frozen=True)
class MigrationResult:
    commit: str
    source_pages: int
    knowledge_pages: int
    original_documents: int


```

Implement `migrate_legacy_wiki(source: Path, destination: Path, replace_existing: bool) -> MigrationResult`.

Validate source and destination confinement. Refuse non-empty destination unless `--replace-existing` is passed. When replacing, move old destination to a timestamped sibling recovery directory before activation. Copy supported originals to `documents/`, normalize legacy source pages into required identity schema, put other generated Markdown below `knowledge/`, validate, initialize local Git, create one `Migrate legacy CV knowledge` commit, and print counts/commit only.

- [ ] **Step 4: Add exact CLI**

```text
cv-agent migrate-data --from-wiki /old/wiki --to-data-dir /data
cv-agent migrate-data --from-wiki /old/wiki --to-data-dir /data --replace-existing
```

Use `argparse`; return nonzero with concise stderr on failure. Never run migration automatically at startup.

- [ ] **Step 5: Verify and commit**

```bash
uv run --extra dev pytest tests/test_migrate_data.py tests/test_ingest.py tests/test_data_storage.py -q
```

Expected: PASS.

```bash
git add src/cv_agent/cli.py src/cv_agent/knowledge/migrate.py tests/test_migrate_data.py README.md docs/deployment.md
git commit -m "feat(cli): migrate legacy CV knowledge"
```

### Task 6: Documentation, Container, And Final Audit

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/deployment.md`
- Modify: `docs/demo.md`
- Replace: `docs/sample-transcript.md` with synthetic examples
- Delete: all `docs/superpowers/specs/*` and `docs/superpowers/plans/*` after execution; Git history preserves the approved design/plans
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `.gitignore`
- Create: `tests/test_end_to_end_storage.py`

- [ ] **Step 1: Write failing end-to-end test**

```python
def test_empty_upload_query_backup_restore_flow(tmp_path, fake_openai):
    app = create_configured_app(tmp_path, fake_openai)
    client = TestClient(app)
    assert client.get("/readyz").status_code == 503

    uploaded = admin_upload(client, "candidate.md", b"Alex Example builds Python APIs.")
    assert uploaded.status_code == 200
    assert client.get("/readyz").status_code == 200
    answer = client.post("/v1/responses", json={"input": "What does Alex build?"})
    assert answer.status_code == 200

    backup = create_full_backup(client)
    delete_document(client, uploaded.json()["document"]["document_id"])
    restore_full_backup(client, backup)
    assert client.post("/v1/responses", json={"input": "What does Alex build?"}).status_code == 200
```

- [ ] **Step 2: Rewrite active documentation**

Document fork setup, environment variables, mounted disk requirements, empty initialization, admin workflows, local Git semantics, PDF-vs-Markdown versioning, backups, restore, rollback limits, migration, Open Responses registration, and volume snapshots. Use only synthetic names/URLs. Remove all planning/spec documents from the active tree after implementation; Git history preserves them.

- [ ] **Step 3: Finalize container behavior**

Docker image includes code and Git CLI only, never candidate data. Compose mounts `${CV_AGENT_DATA_DIR:-./data}:/data`, sets `DATA_DIR=/data`, and health-checks `/healthz`. `.env.example` contains generic blank values and every supported setting exactly once.

- [ ] **Step 4: Run full verification**

```bash
uv run --extra dev pytest -q
```

Expected: all tests PASS.

```bash
uv run --extra dev pytest tests/test_generic_branding.py -q
```

Expected: no matches in active files.

```bash
find . -path ./.git -prune -o -path ./data -prune -o -type f \( -iname '*.pdf' -o -iname '*.tex' \) -print
```

Expected: no real candidate documents; only explicitly synthetic minimal test fixtures, if any.

```bash
docker build --tag cv-agent:generic .
docker run --rm --env DATA_DIR=/data cv-agent:generic python -c "from cv_agent.main import app; assert app.title == 'CV Agent'"
```

Expected: build and smoke check succeed.

- [ ] **Step 5: Review final diff and commit**

```bash
git status --short
git diff --check
git diff --stat origin/main..HEAD
git add --all
git commit -m "docs: document generic CV agent operations"
```

Expected: no whitespace errors; commit includes only intended genericization/storage work.
