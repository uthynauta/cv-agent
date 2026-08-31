# Generic CV Agent Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use $subagent-driven-development (recommended) or $executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the service to a generic `cv_agent`, remove bundled candidate/remote-publishing coupling, and establish empty mounted storage with a local Git-versioned Markdown knowledge repository.

**Architecture:** Keep the existing FastAPI and retrieval flow, but move runtime data behind `DataPaths` and `LocalKnowledgeGit`. Original documents live outside the local Git work tree; extracted source Markdown and generated knowledge live inside it. This plan ends with a generic, working service that can initialize empty storage and ingest new documents; advanced replacement/rollback and backup behavior follow in later plans.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic Settings, stdlib `subprocess`/`pathlib`/`hashlib`/`uuid`, Git CLI, pytest, Docker.

---

## File Structure

- Rename `src/banorte_agent/` to `src/cv_agent/` and update all internal imports.
- Rename `src/cv_agent/wiki/` to `src/cv_agent/knowledge/`; keep extraction/search modules focused on knowledge rather than deployment storage.
- Create `src/cv_agent/knowledge/storage.py`: mounted data path creation and validation.
- Create `src/cv_agent/knowledge/git_store.py`: bounded local Git CLI adapter with no remote support.
- Modify `src/cv_agent/knowledge/ingest.py`: stable source identity Markdown with full normalized extracted text.
- Modify `src/cv_agent/api/admin.py`: basic upload into mounted documents plus one local commit.
- Modify `src/cv_agent/main.py` and `src/cv_agent/api/health.py`: empty-store startup and public readiness.
- Delete `src/cv_agent/admin/github.py` and `tests/test_admin_github.py`.
- Remove tracked `wiki/` candidate content and real candidate fixtures.
- Update packaging, container, Compose, env example, README, and focused tests.

### Task 1: Rename Namespace And Public Branding

**Files:**
- Rename: `src/banorte_agent/` -> `src/cv_agent/`
- Rename: `src/cv_agent/wiki/` -> `src/cv_agent/knowledge/`
- Modify: `pyproject.toml`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: every `tests/test_*.py` and `tests/conftest.py` import
- Modify: `src/cv_agent/main.py`
- Modify: `src/cv_agent/admin/ui.py`
- Test: `tests/test_generic_branding.py`

- [ ] **Step 1: Add a failing generic-branding test**

Create `tests/test_generic_branding.py`:

```python
from pathlib import Path

from cv_agent.config import Settings
from cv_agent.main import create_app


def test_generic_application_identity(tmp_path: Path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    assert app.title == "CV Agent"
    assert settings.agent_model_name == "cv-agent"
    assert settings.otel_service_name == "cv-agent"
```

- [ ] **Step 2: Run the test and verify import failure**

Run:

```bash
uv run --extra dev pytest tests/test_generic_branding.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'cv_agent'`.

- [ ] **Step 3: Perform the mechanical package rename**

Run:

```bash
git mv src/banorte_agent src/cv_agent
git mv src/cv_agent/wiki src/cv_agent/knowledge
```

Update imports to the new namespace and from `.wiki` to `.knowledge` across `src/` and `tests/`. Rename `WikiRepository`, `WikiSearch`, and `WikiPage` consistently to `KnowledgeRepository`, `KnowledgeSearch`, and `KnowledgePage`. Update `pyproject.toml`:

```toml
[project]
name = "cv-agent"
description = "Open Responses-compatible CV retrieval agent"

[project.scripts]
cv-agent = "cv_agent.cli:main"
```

Update application identity and cookie:

```python
# src/cv_agent/main.py
app = FastAPI(title="CV Agent", version="0.3.0")

# src/cv_agent/admin/ui.py
SESSION_COOKIE = "cv_agent_admin_session"
```

Update Docker entrypoint and Compose service:

```dockerfile
CMD ["uvicorn", "cv_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
services:
  cv-agent:
```

- [ ] **Step 4: Update identity assertions and run import-focused tests**

Replace old package names, cookie names, app title, model identifier, and service name in tests. Use synthetic candidate names such as `Alex Example`; do not retain real names or employers.

Run:

```bash
uv run --extra dev pytest tests/test_generic_branding.py tests/test_agent_card.py tests/test_admin_ui.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the namespace rename**

```bash
git add pyproject.toml Dockerfile docker-compose.yml src tests
git commit -m "refactor: rename service to cv-agent"
```

### Task 2: Add Environment Configuration And Mounted Data Paths

**Files:**
- Modify: `src/cv_agent/config.py`
- Create: `src/cv_agent/knowledge/storage.py`
- Delete: `src/cv_agent/knowledge/paths.py`
- Replace: `tests/test_wiki_storage.py` with `tests/test_data_storage.py`
- Modify: `tests/test_config.py`
- Modify: `.env.example`

- [ ] **Step 1: Write failing settings and path tests**

Create `tests/test_data_storage.py`:

```python
from pathlib import Path

from cv_agent.knowledge.storage import DataPaths, ensure_data_storage


def test_data_paths_derive_all_runtime_locations(tmp_path: Path):
    paths = DataPaths.from_root(tmp_path / "data")

    assert paths.documents == tmp_path / "data" / "documents"
    assert paths.quarantine == tmp_path / "data" / "documents" / "quarantine"
    assert paths.repository == tmp_path / "data" / "repository"
    assert paths.sources == paths.repository / "sources"
    assert paths.knowledge == paths.repository / "knowledge"
    assert paths.backups == tmp_path / "data" / "backups"
    assert paths.staging == tmp_path / "data" / "staging"
    assert paths.locks == tmp_path / "data" / "locks"


def test_ensure_data_storage_creates_empty_tree(tmp_path: Path):
    paths = ensure_data_storage(tmp_path / "data")

    assert paths.documents.is_dir()
    assert paths.sources.is_dir()
    assert paths.knowledge.is_dir()
    assert paths.backups.is_dir()
    assert list(paths.knowledge.iterdir()) == []
```

Append to `tests/test_config.py`:

```python
def test_generic_storage_and_identity_defaults(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)

    assert settings.data_dir == tmp_path
    assert settings.agent_owner_name is None
    assert settings.agent_display_name == "CV Agent"
    assert settings.agent_description == "Ask questions about this candidate's CV."
    assert settings.agent_language == "auto"
    assert settings.admin_backup_max_bytes == 100 * 1024 * 1024
    assert settings.backup_retention_count == 10
    assert settings.data_git_author_name == "CV Agent"
    assert settings.data_git_author_email == "cv-agent@localhost"


@pytest.mark.parametrize("value", ["auto", "es", "en"])
def test_agent_language_accepts_supported_values(value):
    assert Settings(_env_file=None, agent_language=value).agent_language == value


@pytest.mark.parametrize("value", ["", "english", "es-MX", "../es"])
def test_agent_language_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, agent_language=value)
```

- [ ] **Step 2: Verify the new tests fail**

Run:

```bash
uv run --extra dev pytest tests/test_config.py tests/test_data_storage.py -q
```

Expected: FAIL because `data_dir`, generic identity settings, and `DataPaths` do not exist.

- [ ] **Step 3: Implement generic settings**

Replace deployment-specific fields in `Settings` with:

```python
data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
agent_owner_name: str | None = Field(default=None, alias="AGENT_OWNER_NAME")
agent_display_name: str = Field(default="CV Agent", alias="AGENT_DISPLAY_NAME")
agent_description: str = Field(
    default="Ask questions about this candidate's CV.", alias="AGENT_DESCRIPTION"
)
agent_language: str = Field(default="auto", alias="AGENT_LANGUAGE")
agent_model_name: str = Field(default="cv-agent", alias="AGENT_MODEL_NAME")
agent_public_url: str | None = Field(default=None, alias="AGENT_PUBLIC_URL")
admin_backup_max_bytes: int = Field(
    default=100 * 1024 * 1024, gt=0, alias="ADMIN_BACKUP_MAX_BYTES"
)
backup_retention_count: int = Field(default=10, ge=1, alias="BACKUP_RETENTION_COUNT")
data_git_author_name: str = Field(default="CV Agent", alias="DATA_GIT_AUTHOR_NAME")
data_git_author_email: str = Field(default="cv-agent@localhost", alias="DATA_GIT_AUTHOR_EMAIL")
otel_service_name: str = Field(default="cv-agent", alias="OTEL_SERVICE_NAME")
```

Add the generic fields without removing `wiki_dir` or `github_*` yet. Those transitional fields still serve the legacy startup/publish paths and are removed with their consumers in Tasks 5 and 6. Add:

```python
@field_validator("agent_language")
@classmethod
def validate_agent_language(cls, value: str) -> str:
    if value in {"auto", "es", "en"}:
        return value
    raise ValueError("agent_language must be 'auto', 'es', or 'en'")
```

- [ ] **Step 4: Implement `DataPaths` and empty initialization**

Create `src/cv_agent/knowledge/storage.py`:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataPaths:
    root: Path
    documents: Path
    quarantine: Path
    repository: Path
    sources: Path
    knowledge: Path
    backups: Path
    staging: Path
    locks: Path

    @classmethod
    def from_root(cls, root: str | Path) -> "DataPaths":
        resolved = Path(root).expanduser().resolve()
        repository = resolved / "repository"
        return cls(
            root=resolved,
            documents=resolved / "documents",
            quarantine=resolved / "documents" / "quarantine",
            repository=repository,
            sources=repository / "sources",
            knowledge=repository / "knowledge",
            backups=resolved / "backups",
            staging=resolved / "staging",
            locks=resolved / "locks",
        )


def ensure_data_storage(root: str | Path) -> DataPaths:
    paths = DataPaths.from_root(root)
    for directory in (
        paths.documents,
        paths.quarantine,
        paths.sources,
        paths.knowledge,
        paths.backups,
        paths.staging,
        paths.locks,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return paths
```

- [ ] **Step 5: Update `.env.example` and run focused tests**

Add the generic storage, identity, backup, and local-Git settings with blank secrets and no personal values. Keep the existing wiki-path and remote-publishing variables temporarily because their runtime consumers remain until Tasks 5 and 6; mark them as transitional in comments rather than presenting them as the new deployment interface.

Run:

```bash
uv run --extra dev pytest tests/test_config.py tests/test_data_storage.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit mounted path configuration**

```bash
git add .env.example src/cv_agent/config.py src/cv_agent/knowledge tests/test_config.py tests/test_data_storage.py
git commit -m "feat(storage): add mounted data layout"
```

### Task 3: Add Local-Only Git Repository Adapter

**Files:**
- Create: `src/cv_agent/knowledge/git_store.py`
- Test: `tests/test_git_store.py`
- Modify: `Dockerfile`

- [ ] **Step 1: Write failing Git-store tests**

Create `tests/test_git_store.py`:

```python
from pathlib import Path
import subprocess

from cv_agent.knowledge.git_store import LocalKnowledgeGit


def test_initialize_creates_local_repo_without_remote(tmp_path: Path):
    store = LocalKnowledgeGit(tmp_path / "repository", "CV Agent", "cv-agent@localhost")
    store.initialize()

    assert (tmp_path / "repository" / ".git").is_dir()
    assert store.remotes() == []


def test_commit_versions_markdown_but_not_external_pdf(tmp_path: Path):
    repository = tmp_path / "repository"
    documents = tmp_path / "documents"
    documents.mkdir()
    store = LocalKnowledgeGit(repository, "CV Agent", "cv-agent@localhost")
    store.initialize()
    (repository / "sources").mkdir()
    (repository / "sources" / "source.md").write_text("# Source\n", encoding="utf-8")
    (documents / "source.pdf").write_bytes(b"%PDF")

    commit = store.commit("Ingest document doc-1")

    assert len(commit) == 40
    assert store.tracked_paths() == ["sources/source.md"]


def test_git_commands_never_accept_remote_configuration(tmp_path: Path):
    store = LocalKnowledgeGit(tmp_path / "repository", "CV Agent", "cv-agent@localhost")
    store.initialize()

    result = subprocess.run(
        ["git", "-C", str(store.root), "remote"], capture_output=True, text=True, check=True
    )
    assert result.stdout == ""
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run --extra dev pytest tests/test_git_store.py -q
```

Expected: FAIL because `LocalKnowledgeGit` is undefined.

- [ ] **Step 3: Implement bounded Git adapter**

Create `src/cv_agent/knowledge/git_store.py` with this interface:

```python
from pathlib import Path
import subprocess


class LocalKnowledgeGit:
    def __init__(self, root: Path, author_name: str, author_email: str) -> None:
        self.root = root.resolve()
        self.author_name = author_name
        self.author_email = author_email

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=check,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").is_dir():
            self._run("init", "--initial-branch=main")
        self._run("config", "user.name", self.author_name)
        self._run("config", "user.email", self.author_email)

    def commit(self, message: str) -> str:
        self._run("add", "--all", "--", "sources", "knowledge")
        staged = self._run("diff", "--cached", "--quiet", check=False)
        if staged.returncode == 0:
            return self.head()
        self._run("commit", "--message", message)
        return self.head()

    def head(self) -> str:
        result = self._run("rev-parse", "HEAD")
        return result.stdout.strip()

    def remotes(self) -> list[str]:
        return [line for line in self._run("remote").stdout.splitlines() if line]

    def tracked_paths(self) -> list[str]:
        return sorted(self._run("ls-files").stdout.splitlines())
```

Handle the unborn-branch `head()` case by returning `""`. Raise a dedicated `GitStoreError` containing only bounded stderr for failed Git operations.

- [ ] **Step 4: Install Git in the runtime image and verify**

Add before installing `uv`:

```dockerfile
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
```

Run:

```bash
uv run --extra dev pytest tests/test_git_store.py -q
docker build --tag cv-agent:foundation .
docker run --rm cv-agent:foundation git --version
```

Expected: tests PASS; image prints a Git version.

- [ ] **Step 5: Commit local Git storage**

```bash
git add Dockerfile src/cv_agent/knowledge/git_store.py tests/test_git_store.py
git commit -m "feat(storage): version knowledge locally"
```

### Task 4: Version Full Source Identity Markdown

**Files:**
- Modify: `src/cv_agent/knowledge/ingest.py`
- Modify: `src/cv_agent/knowledge/openai_ingest.py`
- Modify: `src/cv_agent/knowledge/repository.py`
- Modify: `tests/test_ingest.py`

- [ ] **Step 1: Replace snippet-policy test with failing full-text identity test**

Add to `tests/test_ingest.py`:

```python
def test_pdf_ingest_writes_stable_identity_and_full_text(tmp_path, monkeypatch):
    source = tmp_path / "candidate.pdf"
    source.write_bytes(b"%PDF synthetic")
    extracted = ExtractedSource(
        source,
        "Complete private extracted CV text.",
        "pdf",
        False,
        "a" * 64,
    )
    monkeypatch.setattr(ingest_module, "extract_source", lambda path: extracted)
    repository = KnowledgeRepository(tmp_path / "repository")

    result = IngestionService(repository).ingest_file(source, document_id="doc-123")
    text = result.source_page.read_text(encoding="utf-8")

    assert result.document_id == "doc-123"
    assert "document_id: doc-123" in text
    assert f"content_sha256: {'a' * 64}" in text
    assert "original_filename: candidate.pdf" in text
    assert "## Extracted Text" in text
    assert "Complete private extracted CV text." in text
```

- [ ] **Step 2: Verify failure under snippet-only behavior**

Run:

```bash
uv run --extra dev pytest tests/test_ingest.py::test_pdf_ingest_writes_stable_identity_and_full_text -q
```

Expected: FAIL because `document_id` is unsupported and PDF full text is omitted.

- [ ] **Step 3: Implement stable identity and knowledge paths**

Change the result and public signature:

```python
@dataclass(frozen=True)
class IngestResult:
    document_id: str
    source_path: Path
    source_page: Path
    generated_pages: tuple[Path, ...]
    needs_ocr: bool


def ingest_file(self, path: Path, document_id: str) -> IngestResult:
    return self._ingest_extracted(path, document_id, extract_source(path))
```

Write source pages to `sources/{document_id}.md`. Prefix every non-source model-generated path with `knowledge/`. Source metadata must contain:

```python
metadata = {
    "kind": "source",
    "document_id": document_id,
    "original_filename": path.name,
    "media_type": _media_type(path),
    "uploaded_at": datetime.now(UTC).isoformat(),
    "content_sha256": extracted.sha256,
    "extractor_version": "1",
    "needs_ocr": extracted.needs_ocr,
    "tags": ["source", extracted.kind],
}
```

All source kinds use a body containing `## Extracted Text` and the complete normalized extracted text. Remove `content_policy: snippet_only` behavior.

- [ ] **Step 4: Run ingestion and repository tests**

Run:

```bash
uv run --extra dev pytest tests/test_ingest.py tests/test_wiki_repository.py tests/test_extractors.py -q
```

Expected: PASS after renaming `WikiRepository` tests/imports to `KnowledgeRepository` as needed.

- [ ] **Step 5: Commit source identity Markdown**

```bash
git add src/cv_agent/knowledge tests/test_ingest.py tests/test_wiki_repository.py
git commit -m "feat(ingest): version full source text"
```

### Task 5: Wire Empty Startup, Basic Upload Commit, And Generic Readiness

**Files:**
- Modify: `src/cv_agent/main.py`
- Modify: `src/cv_agent/api/admin.py`
- Modify: `src/cv_agent/api/health.py`
- Modify: `src/cv_agent/api/responses.py`
- Modify: `src/cv_agent/knowledge/storage.py`
- Modify: `tests/test_admin.py`
- Modify: `tests/test_health.py`
- Modify: `tests/test_response_schema.py`

- [ ] **Step 1: Write failing empty-start and committed-upload tests**

Add:

```python
def test_fresh_data_dir_starts_empty_and_admin_remains_available(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, admin_api_key="admin-secret")
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503
    status_response = client.get("/admin/status", headers={"Authorization": "Bearer admin-secret"})
    assert status_response.status_code == 200
    assert status_response.json()["knowledge"]["initialized"] is False


def test_upload_persists_original_and_commits_only_markdown(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, data_dir=tmp_path, admin_api_key="admin-secret")
    monkeypatch.setattr("cv_agent.knowledge.ingest.extract_source", fake_pdf_extractor)
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))

    response = client.post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("candidate.pdf", b"%PDF synthetic", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document"]["document_id"]
    assert payload["revision"]["commit"]
    assert list((tmp_path / "documents").glob("*.pdf"))
    tracked = LocalKnowledgeGit(tmp_path / "repository", "CV Agent", "cv-agent@localhost").tracked_paths()
    assert all(not path.endswith(".pdf") for path in tracked)
```

- [ ] **Step 2: Verify focused failures**

Run:

```bash
uv run --extra dev pytest tests/test_health.py tests/test_admin.py -q
```

Expected: FAIL because startup still seeds bundled wiki and uploads do not use local Git.

- [ ] **Step 3: Wire mounted services in `create_app`**

Initialize once:

```python
paths = ensure_data_storage(settings.data_dir)
git_store = LocalKnowledgeGit(
    paths.repository,
    settings.data_git_author_name,
    settings.data_git_author_email,
)
git_store.initialize()
repository = KnowledgeRepository(paths.repository)
ingestion = IngestionService(repository, settings)
```

Remove bundled-wiki discovery and seeding. Pass `paths`, `git_store`, and `ingestion` to admin router construction. Public answering continues using `KnowledgeSearch(repository)` until the immutable index is introduced in Plan 2.

- [ ] **Step 4: Implement basic committed upload**

In `upload_document_payload`:

1. Read and validate upload.
2. Generate `document_id = uuid.uuid4().hex`.
3. Write a temporary file under `paths.staging`.
4. Extract and reject OCR-required PDF.
5. Copy current original to `paths.documents / f"{document_id}{suffix}"`.
6. Call `ingestion.ingest_file(original, document_id)`.
7. Commit with `git_store.commit(f"Ingest document {document_id}")`.
8. Return `document_id`, source page paths, and commit SHA.

If extraction or ingestion fails, remove the staged/current original and generated source page. Full transactional behavior replaces this basic cleanup in Plan 2.

- [ ] **Step 5: Implement generic readiness and public 503**

Readiness missing values are stable machine-readable strings:

```python
missing = []
if not settings.openai_api_key:
    missing.append("OPENAI_API_KEY")
if not settings.openai_model:
    missing.append("OPENAI_MODEL")
if not settings.agent_owner_name:
    missing.append("AGENT_OWNER_NAME")
if not settings.agent_public_url:
    missing.append("AGENT_PUBLIC_URL")
if not repository.list_pages():
    missing.append("knowledge")
```

The responses route must return `503` with `{"detail": "candidate knowledge is not initialized"}` before invoking the answerer when no usable page exists.

- [ ] **Step 6: Run API/health tests**

Run:

```bash
uv run --extra dev pytest tests/test_health.py tests/test_admin.py tests/test_response_schema.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit startup and upload wiring**

```bash
git add src/cv_agent tests/test_health.py tests/test_admin.py tests/test_response_schema.py
git commit -m "feat(storage): initialize empty CV data"
```

### Task 6: Remove Remote Publishing And Bundled Candidate Corpus

**Files:**
- Delete: `src/cv_agent/admin/github.py`
- Delete: `tests/test_admin_github.py`
- Delete: tracked `wiki/`
- Delete: real candidate fixtures under `tests/fixtures/`
- Modify: `src/cv_agent/api/admin.py`
- Modify: `src/cv_agent/admin/ui.py`
- Modify: `tests/test_admin.py`
- Modify: `tests/test_admin_ui.py`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/deployment.md`
- Modify: `docs/demo.md`
- Modify: `docs/sample-transcript.md`

- [ ] **Step 1: Add failing active-brand/data audit**

Extend `tests/test_generic_branding.py`:

```python
def test_repository_has_no_bundled_candidate_corpus():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "wiki").exists()
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY wiki" not in dockerfile


def test_active_runtime_has_no_remote_publish_route(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, admin_api_key="secret")
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))
    response = client.post("/admin/publish", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 404


def test_active_tree_has_no_legacy_identity_or_deployment_markers():
    root = Path(__file__).resolve().parents[1]
    markers = tuple(
        part.casefold()
        for part in (
            "ban" + "orte",
            "ai " + "reto",
            "ot" + "hon",
            "uthy" + "nauta",
            "onrender" + ".com",
            "tera" + "data",
            "conti" + "nental",
            "centro" + "geo",
        )
    )
    roots = [root / "src", root / "tests", root / "docs", root / "README.md"]
    offenders = []
    for candidate in roots:
        paths = [candidate] if candidate.is_file() else candidate.rglob("*")
        for path in paths:
            if not path.is_file() or "superpowers" in path.parts or path.suffix == ".pyc":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").casefold()
            if any(marker in text for marker in markers):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []
```

- [ ] **Step 2: Verify audit failures**

Run:

```bash
uv run --extra dev pytest tests/test_generic_branding.py -q
```

Expected: FAIL because tracked corpus and publish route still exist.

- [ ] **Step 3: Remove remote publishing and candidate data**

Delete GitHub service/tests and `/admin/publish` plus `/admin/ui/publish`. Replace dashboard publishing tiles/actions with local revision status placeholders that Plan 2 will populate. Remove all tracked corpus files and real candidate fixtures. Remove `COPY wiki ./wiki` and the Compose `./wiki:/app/wiki` volume; mount `${CV_AGENT_DATA_DIR:-./data}:/data` and set `DATA_DIR=/data`.

Update `.gitignore`:

```gitignore
data/
*.cv-agent-backup.tar.gz
*.cv-agent.bundle
```

- [ ] **Step 4: Rewrite active documentation generically**

Document:

- generic local/container startup;
- required `DATA_DIR`, identity, OpenAI, admin, and public URL settings;
- empty deployment initialization through admin upload;
- stateless non-streaming Open Responses endpoint;
- mounted disk persistence and local-only Git;
- no committed candidate data and no remote publishing.

Use only synthetic names and URLs such as `https://cv-agent.example.com`.

- [ ] **Step 5: Run full foundation verification**

Run:

```bash
uv run --extra dev pytest -q
uv run --extra dev pytest tests/test_generic_branding.py -q
docker build --tag cv-agent:foundation .
```

Expected: all tests PASS; `rg` returns no active legacy/personal/deployment matches except historical design documents explicitly excluded or rewritten; Docker build succeeds.

- [ ] **Step 6: Commit generic foundation cleanup**

```bash
git add --all
git commit -m "refactor: remove bundled candidate data"
```
