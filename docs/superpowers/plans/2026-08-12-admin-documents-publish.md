# Admin Documents And Wiki Publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use $subagent-driven-development (recommended) or $executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add protected admin APIs for PDF upload+ingest, admin-only storage/GitHub status, and manual PR publishing of updated wiki files.

**Architecture:** Keep the existing FastAPI admin router and `ADMIN_API_KEY` dependency. Add small service modules for durable wiki storage setup and GitHub API publishing so API code stays thin. Use Render Persistent Disk by pointing `WIKI_DIR` at `/app/data/wiki`; seed it from bundled `/app/wiki` only when empty.

**Tech Stack:** FastAPI, Pydantic Settings, pypdf, stdlib `urllib.request`, pytest, FastAPI `TestClient`.

---

## File Structure

- Modify `pyproject.toml`: add `python-multipart`, required by FastAPI for multipart uploads.
- Modify `src/banorte_agent/config.py`: add upload and GitHub settings.
- Modify `src/banorte_agent/api/admin.py`: keep existing ingest endpoint, add upload/status/publish endpoints and reusable admin auth.
- Modify `src/banorte_agent/main.py`: initialize persistent wiki directories before creating repository/search services.
- Create `src/banorte_agent/wiki/storage.py`: seed persistent `WIKI_DIR`, ensure upload dir, normalize uploaded filenames.
- Create `src/banorte_agent/admin/github.py`: compare local `WIKI_DIR` files with the GitHub base branch wiki tree, create a tree/commit/ref/PR via GitHub API.
- Modify `tests/test_admin.py`: cover upload, status, publish API behavior with monkeypatched services.
- Create `tests/test_wiki_storage.py`: cover seeding and filename/path safety.
- Create `tests/test_admin_github.py`: cover GitHub API status, local wiki comparison, no-op, and publish behavior with mocks.
- Modify `.env.example`, `README.md`, and `docs/deployment.md`: document Render disk, upload, status, publish, and GitHub env vars.

## Task 1: Settings And Multipart Dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/banorte_agent/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Append to `tests/test_config.py`:

```python
def test_admin_upload_and_github_defaults():
    settings = Settings(_env_file=None, openai_api_key="test-key")

    assert settings.admin_upload_max_bytes == 10 * 1024 * 1024
    assert settings.github_token is None
    assert settings.github_repository == "uthynauta/cv-agent"
    assert settings.github_base_branch == "main"
    assert settings.github_commit_author_name == "Banorte Agent Admin"
    assert settings.github_commit_author_email is None


def test_blank_github_values_normalize_to_none():
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        github_token="",
        github_commit_author_email="",
    )

    assert settings.github_token is None
    assert settings.github_commit_author_email is None
```

- [ ] **Step 2: Run failing config tests**

Run:

```bash
uv run --extra dev pytest tests/test_config.py -q
```

Expected: fail because the new settings do not exist.

- [ ] **Step 3: Add dependency and settings**

In `pyproject.toml`, add the dependency:

```toml
  "python-multipart>=0.0.20",
```

In `src/banorte_agent/config.py`, add fields to `Settings` after `admin_api_key`:

```python
    admin_upload_max_bytes: int = Field(
        default=10 * 1024 * 1024,
        gt=0,
        alias="ADMIN_UPLOAD_MAX_BYTES",
    )
    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    github_repository: str = Field(default="uthynauta/cv-agent", alias="GITHUB_REPOSITORY")
    github_base_branch: str = Field(default="main", alias="GITHUB_BASE_BRANCH")
    github_commit_author_name: str = Field(
        default="Banorte Agent Admin",
        alias="GITHUB_COMMIT_AUTHOR_NAME",
    )
    github_commit_author_email: str | None = Field(
        default=None,
        alias="GITHUB_COMMIT_AUTHOR_EMAIL",
    )
```

Add a shared normalizer near `normalize_rerank_model`:

```python
    @field_validator("github_token", "github_commit_author_email", mode="before")
    @classmethod
    def normalize_optional_secret(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        return value
```

Append to `.env.example` after `ADMIN_API_KEY=`:

```dotenv
ADMIN_UPLOAD_MAX_BYTES=10485760
GITHUB_TOKEN=
GITHUB_REPOSITORY=uthynauta/cv-agent
GITHUB_BASE_BRANCH=main
GITHUB_COMMIT_AUTHOR_NAME=Banorte Agent Admin
GITHUB_COMMIT_AUTHOR_EMAIL=
```

- [ ] **Step 4: Verify config tests pass**

Run:

```bash
uv run --extra dev pytest tests/test_config.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add pyproject.toml uv.lock src/banorte_agent/config.py .env.example tests/test_config.py
git commit -m "feat: add admin upload settings"
```

If `uv.lock` changed after dependency resolution, include it. If it did not change, do not stage it.

## Task 2: Persistent Wiki Storage Helpers

**Files:**
- Create: `src/banorte_agent/wiki/storage.py`
- Test: `tests/test_wiki_storage.py`

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_wiki_storage.py`:

```python
from pathlib import Path

import pytest

from banorte_agent.wiki.storage import (
    ensure_wiki_storage,
    safe_upload_filename,
    upload_directory,
)


def test_ensure_wiki_storage_seeds_empty_wiki(tmp_path: Path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "index.md").write_text("# Index", encoding="utf-8")
    (bundled / "raw").mkdir()
    (bundled / "raw" / "cv").mkdir(parents=True)
    (bundled / "raw" / "cv" / "cv.tex").write_text("CV", encoding="utf-8")
    wiki = tmp_path / "persistent" / "wiki"

    ensure_wiki_storage(wiki, bundled)

    assert (wiki / "index.md").read_text(encoding="utf-8") == "# Index"
    assert (wiki / "raw" / "uploads").is_dir()
    assert (wiki / "raw" / "cv" / "cv.tex").read_text(encoding="utf-8") == "CV"


def test_ensure_wiki_storage_does_not_overwrite_existing_wiki(tmp_path: Path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "index.md").write_text("# Bundled", encoding="utf-8")
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_text("# Existing", encoding="utf-8")

    ensure_wiki_storage(wiki, bundled)

    assert (wiki / "index.md").read_text(encoding="utf-8") == "# Existing"
    assert (wiki / "raw" / "uploads").is_dir()


def test_upload_directory_returns_raw_uploads(tmp_path: Path):
    assert upload_directory(tmp_path) == tmp_path / "raw" / "uploads"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Profile PDF.pdf", "Profile-PDF.pdf"),
        ("../secret.pdf", "secret.pdf"),
        ("áé resume.pdf", "resume.pdf"),
        ("multi___space.pdf", "multi-space.pdf"),
    ],
)
def test_safe_upload_filename_normalizes_pdf_names(filename: str, expected: str):
    assert safe_upload_filename(filename) == expected


@pytest.mark.parametrize("filename", ["", ".", "no-extension", "file.txt", "../"])
def test_safe_upload_filename_rejects_invalid_names(filename: str):
    with pytest.raises(ValueError):
        safe_upload_filename(filename)
```

- [ ] **Step 2: Run failing storage tests**

Run:

```bash
uv run --extra dev pytest tests/test_wiki_storage.py -q
```

Expected: fail because `banorte_agent.wiki.storage` does not exist.

- [ ] **Step 3: Implement storage helpers**

Create `src/banorte_agent/wiki/storage.py`:

```python
from pathlib import Path
import re
import shutil
import unicodedata


def upload_directory(wiki_dir: str | Path) -> Path:
    return Path(wiki_dir) / "raw" / "uploads"


def ensure_wiki_storage(wiki_dir: str | Path, bundled_wiki_dir: str | Path | None = None) -> None:
    wiki_path = Path(wiki_dir)
    bundled_path = Path(bundled_wiki_dir) if bundled_wiki_dir else None

    if not wiki_path.exists():
        if bundled_path and bundled_path.exists():
            shutil.copytree(bundled_path, wiki_path)
        else:
            wiki_path.mkdir(parents=True)

    upload_directory(wiki_path).mkdir(parents=True, exist_ok=True)


def safe_upload_filename(filename: str) -> str:
    name = Path(filename).name
    if not name or name in {".", ".."}:
        raise ValueError("filename is required")
    suffix = Path(name).suffix.lower()
    if suffix != ".pdf":
        raise ValueError("only .pdf uploads are supported")

    stem = Path(name).stem
    normalized = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized)
    normalized = re.sub(r"[-_.]{2,}", "-", normalized).strip("-_.")
    if not normalized:
        raise ValueError("filename must contain letters or numbers")
    return f"{normalized}.pdf"
```

- [ ] **Step 4: Verify storage tests pass**

Run:

```bash
uv run --extra dev pytest tests/test_wiki_storage.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/banorte_agent/wiki/storage.py tests/test_wiki_storage.py
git commit -m "feat: add wiki storage helpers"
```

## Task 3: Startup Wiki Seeding

**Files:**
- Modify: `src/banorte_agent/main.py`
- Test: `tests/test_health.py`

- [ ] **Step 1: Write failing startup seed test**

Append to `tests/test_health.py`:

```python
def test_create_app_seeds_empty_configured_wiki(tmp_path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "index.md").write_text("# Bundled", encoding="utf-8")
    target = tmp_path / "data" / "wiki"
    settings = Settings(_env_file=None, openai_api_key="test-key", wiki_dir=str(target))

    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    assert app.title == "Banorte CV Agent"
    assert (target / "raw" / "uploads").is_dir()
```

This test validates directory creation only. It does not need to monkeypatch bundled wiki path.

- [ ] **Step 2: Run failing startup seed test**

Run:

```bash
uv run --extra dev pytest tests/test_health.py::test_create_app_seeds_empty_configured_wiki -q
```

Expected: fail because `raw/uploads` is not created by app startup.

- [ ] **Step 3: Wire storage setup in app startup**

In `src/banorte_agent/main.py`, import helper:

```python
from banorte_agent.wiki.storage import ensure_wiki_storage
```

Inside `create_app`, before `repository = WikiRepository(Path(settings.wiki_dir))`, add:

```python
    bundled_wiki_dir = Path(__file__).resolve().parents[2] / "wiki"
    ensure_wiki_storage(settings.wiki_dir, bundled_wiki_dir)
```

- [ ] **Step 4: Verify startup seed test passes**

Run:

```bash
uv run --extra dev pytest tests/test_health.py::test_create_app_seeds_empty_configured_wiki -q
```

Expected: pass.

- [ ] **Step 5: Run focused health tests**

Run:

```bash
uv run --extra dev pytest tests/test_health.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/banorte_agent/main.py tests/test_health.py
git commit -m "feat: initialize wiki storage"
```

## Task 4: Upload And Immediate Ingest Endpoint

**Files:**
- Modify: `src/banorte_agent/api/admin.py`
- Modify: `src/banorte_agent/api/models.py`
- Test: `tests/test_admin.py`

- [ ] **Step 1: Write failing upload success test**

Append to `tests/test_admin.py`:

```python
def test_admin_document_upload_saves_pdf_and_ingests(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        admin_upload_max_bytes=1024,
    )
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    class Extracted:
        kind = "pdf"
        needs_ocr = False
        text = "retrievable text " * 20
        sha256 = "a" * 64

    class Result:
        source_page = Path("sources/uploaded.md")

    def fake_extract(path: Path):
        assert path.name.endswith(".pdf")
        return Extracted()

    def fake_ingest_file(self, path: Path):
        assert path.parent == tmp_path / "raw" / "uploads"
        assert path.read_bytes() == b"%PDF-1.4 text"
        return Result()

    monkeypatch.setattr("banorte_agent.api.admin.extract_source", fake_extract)
    monkeypatch.setattr("banorte_agent.api.admin.IngestionService.ingest_file", fake_ingest_file)
    monkeypatch.setattr("banorte_agent.api.admin.wiki_has_changes", lambda _: True)

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("Uploaded PDF.pdf", b"%PDF-1.4 text", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["document"]["filename"] == "Uploaded-PDF.pdf"
    assert payload["document"]["kind"] == "pdf"
    assert payload["ingestion"] == {"count": 1, "sources": ["sources/uploaded.md"]}
    assert payload["publish"] == {"pending": True}
```

- [ ] **Step 2: Write failing upload validation tests**

Append to `tests/test_admin.py`:

```python
def test_admin_document_upload_rejects_non_pdf(tmp_path):
    settings = Settings(_env_file=None, wiki_dir=str(tmp_path), admin_api_key="admin-secret")
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("notes.txt", b"text", "text/plain")},
    )

    assert response.status_code == 400


def test_admin_document_upload_rejects_oversized_file(tmp_path):
    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        admin_upload_max_bytes=4,
    )
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("cv.pdf", b"12345", "application/pdf")},
    )

    assert response.status_code == 413


def test_admin_document_upload_rejects_low_text_pdf(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, wiki_dir=str(tmp_path), admin_api_key="admin-secret")
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    class Extracted:
        kind = "pdf"
        needs_ocr = True
        text = ""
        sha256 = "a" * 64

    monkeypatch.setattr("banorte_agent.api.admin.extract_source", lambda path: Extracted())

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("scan.pdf", b"%PDF-1.4 image", "application/pdf")},
    )

    assert response.status_code == 422
    assert "OCR" in response.json()["detail"]
```

- [ ] **Step 3: Run failing upload tests**

Run:

```bash
uv run --extra dev pytest tests/test_admin.py::test_admin_document_upload_saves_pdf_and_ingests tests/test_admin.py::test_admin_document_upload_rejects_non_pdf tests/test_admin.py::test_admin_document_upload_rejects_oversized_file tests/test_admin.py::test_admin_document_upload_rejects_low_text_pdf -q
```

Expected: fail because `/admin/documents` does not exist.

- [ ] **Step 4: Implement upload endpoint**

In `src/banorte_agent/api/admin.py`, extend imports:

```python
from datetime import UTC, datetime
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from banorte_agent.wiki.extractors import extract_source
from banorte_agent.wiki.storage import safe_upload_filename, upload_directory
```

Add helper functions above `build_admin_router`:

```python
def wiki_has_changes(settings: Settings) -> bool:
    return False


async def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="upload is too large")
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="upload is empty")
    return data
```

Inside `build_admin_router`, after existing `/admin/ingest`, add:

```python
    @router.post("/admin/documents")
    async def upload_document(file: UploadFile = File(...)) -> dict[str, object]:
        try:
            filename = safe_upload_filename(file.filename or "")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        data = await _read_upload(file, settings.admin_upload_max_bytes)
        target_dir = upload_directory(settings.wiki_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        target = target_dir / f"{timestamp}-{filename}"
        target.write_bytes(data)

        try:
            extracted = extract_source(target)
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PDF is unreadable") from exc
        if extracted.needs_ocr:
            target.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="PDF requires OCR before upload",
            )

        result = ingestion.ingest_file(target)
        return {
            "status": "ok",
            "document": {
                "filename": filename,
                "path": str(target.relative_to(Path(settings.wiki_dir))),
                "kind": extracted.kind,
            },
            "ingestion": {
                "count": 1,
                "sources": [str(result.source_page)],
            },
            "publish": {
                "pending": wiki_has_changes(settings),
            },
        }
```

- [ ] **Step 5: Verify upload tests pass**

Run:

```bash
uv run --extra dev pytest tests/test_admin.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/banorte_agent/api/admin.py tests/test_admin.py
git commit -m "feat: upload and ingest admin PDFs"
```

## Task 5: GitHub Admin Service

**Files:**
- Create: `src/banorte_agent/admin/__init__.py`
- Create: `src/banorte_agent/admin/github.py`
- Test: `tests/test_admin_github.py`

- [ ] **Step 1: Write failing GitHub service tests**

Create `tests/test_admin_github.py`:

```python
import urllib.error
from pathlib import Path

from banorte_agent.admin.github import GitHubAdminService
from banorte_agent.config import Settings


def test_github_status_reports_unconfigured(tmp_path: Path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    service = GitHubAdminService(Settings(_env_file=None, github_token=None, wiki_dir=str(wiki)))

    status = service.status()

    assert status["configured"] is False
    assert status["connected"] is False
    assert "token" in status["error"].lower()


def test_wiki_has_changes_compares_local_blobs_to_base_tree(tmp_path: Path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_text("# Local", encoding="utf-8")

    service = GitHubAdminService(Settings(_env_file=None, github_token="token", wiki_dir=str(wiki)))
    monkeypatch.setattr(
        service,
        "_base_wiki_blobs",
        lambda: {"wiki/index.md": "different-sha"},
    )

    assert service.wiki_has_changes() is True
    assert service.changed_wiki_files() == ["wiki/index.md"]


def test_publish_noops_without_wiki_changes(tmp_path: Path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_text("# Same", encoding="utf-8")
    service = GitHubAdminService(Settings(_env_file=None, github_token="token", wiki_dir=str(wiki)))
    monkeypatch.setattr(
        service,
        "_base_wiki_blobs",
        lambda: {"wiki/index.md": service.git_blob_sha((wiki / "index.md").read_bytes())},
    )

    assert service.publish() == {"status": "noop", "changed_files": []}


def test_status_redacts_github_error(tmp_path: Path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(str(request.full_url), 401, "Bad credentials token-secret", {}, None)

    monkeypatch.setattr("banorte_agent.admin.github.urlopen", fake_urlopen)
    service = GitHubAdminService(Settings(_env_file=None, github_token="token-secret", wiki_dir=str(wiki)))

    status = service.status()

    assert status["configured"] is True
    assert status["connected"] is False
    assert "token-secret" not in status["error"]


def test_publish_creates_tree_commit_ref_and_pr(tmp_path: Path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_text("# Updated", encoding="utf-8")
    service = GitHubAdminService(Settings(_env_file=None, github_token="token", wiki_dir=str(wiki)))
    calls = []

    def fake_github_json(path: str, data=None, method=None):
        calls.append((path, data, method))
        if path == "/git/ref/heads/main":
            return {"object": {"sha": "base-ref-sha"}}
        if path == "/git/commits/base-ref-sha":
            return {"tree": {"sha": "base-tree-sha"}}
        if path == "/git/trees/base-tree-sha?recursive=1":
            return {"tree": []}
        if path == "/git/trees":
            return {"sha": "new-tree-sha"}
        if path == "/git/commits":
            return {"sha": "new-commit-sha"}
        if path == "/git/refs":
            return {"ref": "refs/heads/wiki/upload-20260812-000000"}
        if path == "/pulls":
            return {"html_url": "https://github.com/uthynauta/cv-agent/pull/1"}
        raise AssertionError(path)

    monkeypatch.setattr(service, "_github_json", fake_github_json)
    monkeypatch.setattr("banorte_agent.admin.github._branch_suffix", lambda: "20260812-000000")

    result = service.publish()

    assert result["status"] == "ok"
    assert result["branch"] == "wiki/upload-20260812-000000"
    assert result["commit"] == "new-commit-sha"
    assert result["pull_request_url"] == "https://github.com/uthynauta/cv-agent/pull/1"
    assert result["changed_files"] == ["wiki/index.md"]
    assert any(call[0] == "/git/trees" for call in calls)
```

- [ ] **Step 2: Run failing GitHub service tests**

Run:

```bash
uv run --extra dev pytest tests/test_admin_github.py -q
```

Expected: fail because `banorte_agent.admin.github` does not exist.

- [ ] **Step 3: Implement GitHub service skeleton**

Create `src/banorte_agent/admin/__init__.py`:

```python
"""Admin service helpers."""
```

Create `src/banorte_agent/admin/github.py`:

```python
from base64 import b64encode
from datetime import UTC, datetime
from hashlib import sha1
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from banorte_agent.config import Settings


class GitHubAdminService:
    def __init__(self, settings: Settings, repo_root: Path | None = None) -> None:
        self.settings = settings
        self.repo_root = repo_root or Path.cwd()
        self.wiki_dir = Path(settings.wiki_dir)

    def status(self) -> dict[str, object]:
        if not self.settings.github_token:
            return {
                "configured": False,
                "connected": False,
                "base_branch": self.settings.github_base_branch,
                "pending_wiki_changes": False,
                "error": "GITHUB_TOKEN is not configured",
            }
        try:
            self._github_json("")
            pending = self.wiki_has_changes()
        except (HTTPError, URLError, OSError) as exc:
            return {
                "configured": True,
                "connected": False,
                "base_branch": self.settings.github_base_branch,
                "pending_wiki_changes": False,
                "error": self._redact(str(exc)),
            }
        return {
            "configured": True,
            "connected": True,
            "base_branch": self.settings.github_base_branch,
            "pending_wiki_changes": pending,
            "error": None,
        }

    def wiki_has_changes(self) -> bool:
        return bool(self.changed_wiki_files())

    def changed_wiki_files(self) -> list[str]:
        base = self._base_wiki_blobs()
        changed: list[str] = []
        for relative_path, data in self._local_wiki_files().items():
            repo_path = f"wiki/{relative_path}"
            if base.get(repo_path) != self.git_blob_sha(data):
                changed.append(repo_path)
        return sorted(changed)

    def publish(self) -> dict[str, object]:
        changed_files = self.changed_wiki_files()
        if not changed_files:
            return {"status": "noop", "changed_files": []}
        if not self.settings.github_token:
            raise RuntimeError("GITHUB_TOKEN is not configured")
        branch = f"wiki/upload-{_branch_suffix()}"
        base_ref = self._github_json(f"/git/ref/heads/{self.settings.github_base_branch}")
        base_sha = str(base_ref["object"]["sha"])
        base_commit = self._github_json(f"/git/commits/{base_sha}")
        base_tree_sha = str(base_commit["tree"]["sha"])
        tree_items = self._tree_items(changed_files)
        tree = self._github_json(
            "/git/trees",
            data={"base_tree": base_tree_sha, "tree": tree_items},
        )
        commit = self._github_json(
            "/git/commits",
            data={
                "message": "docs: ingest uploaded wiki documents",
                "tree": tree["sha"],
                "parents": [base_sha],
                "author": self._commit_author(),
            },
        )
        commit_sha = str(commit["sha"])
        self._github_json("/git/refs", data={"ref": f"refs/heads/{branch}", "sha": commit_sha})
        pr = self._create_pull_request(branch)
        return {
            "status": "ok",
            "branch": branch,
            "commit": commit_sha,
            "pull_request_url": pr.get("html_url"),
            "changed_files": changed_files,
        }

    def _create_pull_request(self, branch: str) -> dict[str, object]:
        return self._github_json(
            "/pulls",
            data={
                "title": "Ingest uploaded wiki documents",
                "head": branch,
                "base": self.settings.github_base_branch,
                "body": "Generated by the Banorte Agent admin publish endpoint.",
            },
        )

    def _base_wiki_blobs(self) -> dict[str, str]:
        ref = self._github_json(f"/git/ref/heads/{self.settings.github_base_branch}")
        commit = self._github_json(f"/git/commits/{ref['object']['sha']}")
        tree = self._github_json(f"/git/trees/{commit['tree']['sha']}?recursive=1")
        blobs: dict[str, str] = {}
        for item in tree.get("tree", []):
            if item.get("type") == "blob" and str(item.get("path", "")).startswith("wiki/"):
                blobs[str(item["path"])] = str(item["sha"])
        return blobs

    def _local_wiki_files(self) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        for path in sorted(self.wiki_dir.rglob("*")):
            if path.is_file():
                files[path.relative_to(self.wiki_dir).as_posix()] = path.read_bytes()
        return files

    def _tree_items(self, changed_files: list[str]) -> list[dict[str, object]]:
        local = self._local_wiki_files()
        items: list[dict[str, object]] = []
        for repo_path in changed_files:
            relative_path = repo_path.removeprefix("wiki/")
            data = local[relative_path]
            items.append(
                {
                    "path": repo_path,
                    "mode": "100644",
                    "type": "blob",
                    "content": data.decode("utf-8") if self._is_text_file(repo_path, data) else None,
                    "encoding": None if self._is_text_file(repo_path, data) else "base64",
                    "content_base64": b64encode(data).decode("ascii")
                    if not self._is_text_file(repo_path, data)
                    else None,
                }
            )
        for item in items:
            if item.get("encoding") == "base64":
                item["content"] = item.pop("content_base64")
            else:
                item.pop("encoding", None)
                item.pop("content_base64", None)
        return items

    def _commit_author(self) -> dict[str, str] | None:
        if not self.settings.github_commit_author_email:
            return None
        return {
            "name": self.settings.github_commit_author_name,
            "email": self.settings.github_commit_author_email,
        }

    def _github_json(self, path: str, data: dict[str, object] | None = None) -> dict[str, object]:
        body = None if data is None else json.dumps(data).encode("utf-8")
        url = f"https://api.github.com/repos/{self.settings.github_repository}{path}"
        request = Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.settings.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
            method="GET" if data is None else "POST",
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _redact(self, value: str) -> str:
        token = self.settings.github_token
        if token:
            value = value.replace(token, "[redacted]")
        return value

    def _is_text_file(self, repo_path: str, data: bytes) -> bool:
        if Path(repo_path).suffix.lower() in {".md", ".tex", ".txt", ".yml", ".yaml"}:
            return True
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True

    @staticmethod
    def git_blob_sha(data: bytes) -> str:
        return sha1(f"blob {len(data)}\0".encode("utf-8") + data).hexdigest()


def _branch_suffix() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
```

- [ ] **Step 4: Verify GitHub service tests pass**

Run:

```bash
uv run --extra dev pytest tests/test_admin_github.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/banorte_agent/admin tests/test_admin_github.py
git commit -m "feat: add github admin service"
```

## Task 6: Admin Status And Publish Endpoints

**Files:**
- Modify: `src/banorte_agent/api/admin.py`
- Test: `tests/test_admin.py`
- Test: `tests/test_health.py`

- [ ] **Step 1: Write failing status endpoint test**

Append to `tests/test_admin.py`:

```python
def test_admin_status_reports_storage_and_github_without_secrets(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        github_token="secret-token",
    )

    class FakeGitHub:
        def __init__(self, settings):
            pass

        def status(self):
            return {
                "configured": True,
                "connected": True,
                "branch": "main",
                "pending_wiki_changes": True,
                "error": None,
            }

    monkeypatch.setattr("banorte_agent.api.admin.GitHubAdminService", FakeGitHub)
    response = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")).get(
        "/admin/status",
        headers={"Authorization": "Bearer admin-secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["wiki"]["upload_dir"].endswith("raw/uploads")
    assert payload["wiki"]["upload_dir_writable"] is True
    assert payload["ingestion"]["mode"] == settings.ingestion_mode
    assert payload["github"]["connected"] is True
    assert "secret-token" not in str(payload)
```

- [ ] **Step 2: Write failing publish endpoint tests**

Append to `tests/test_admin.py`:

```python
def test_admin_publish_returns_noop(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, wiki_dir=str(tmp_path), admin_api_key="admin-secret")

    class FakeGitHub:
        def __init__(self, settings):
            pass

        def publish(self):
            return {"status": "noop", "changed_files": []}

    monkeypatch.setattr("banorte_agent.api.admin.GitHubAdminService", FakeGitHub)
    response = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")).post(
        "/admin/publish",
        headers={"Authorization": "Bearer admin-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "noop", "changed_files": []}


def test_admin_publish_redacts_failures(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        github_token="secret-token",
    )

    class FakeGitHub:
        def __init__(self, settings):
            pass

        def publish(self):
            raise RuntimeError("push failed for secret-token")

    monkeypatch.setattr("banorte_agent.api.admin.GitHubAdminService", FakeGitHub)
    response = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")).post(
        "/admin/publish",
        headers={"Authorization": "Bearer admin-secret"},
    )

    assert response.status_code == 503
    assert "secret-token" not in response.text
```

- [ ] **Step 3: Write readiness isolation test**

Append to `tests/test_health.py`:

```python
def test_readyz_does_not_require_github(tmp_path):
    (tmp_path / "index.md").write_text("# Index\n\n- [[sources/cv]]", encoding="utf-8")
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "cv.md").write_text("# CV\n\nusable page content", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        wiki_dir=str(tmp_path),
        github_token=None,
    )

    response = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")).get(
        "/readyz"
    )

    assert response.status_code == 200
```

- [ ] **Step 4: Run failing endpoint tests**

Run:

```bash
uv run --extra dev pytest tests/test_admin.py::test_admin_status_reports_storage_and_github_without_secrets tests/test_admin.py::test_admin_publish_returns_noop tests/test_admin.py::test_admin_publish_redacts_failures tests/test_health.py::test_readyz_does_not_require_github -q
```

Expected: admin endpoint tests fail because routes do not exist; readiness test should pass or continue passing after implementation.

- [ ] **Step 5: Implement endpoints**

In `src/banorte_agent/api/admin.py`, import:

```python
from banorte_agent.admin.github import GitHubAdminService
from banorte_agent.wiki.storage import safe_upload_filename, upload_directory
```

Replace `wiki_has_changes` helper from Task 4:

```python
def wiki_has_changes(settings: Settings) -> bool:
    return GitHubAdminService(settings).wiki_has_changes()
```

Inside `build_admin_router`, add:

```python
    @router.get("/admin/status")
    def admin_status() -> dict[str, object]:
        uploads = upload_directory(settings.wiki_dir)
        uploads.mkdir(parents=True, exist_ok=True)
        github = GitHubAdminService(settings).status()
        return {
            "status": "ok",
            "admin": {"enabled": bool(settings.admin_api_key)},
            "wiki": {
                "dir": settings.wiki_dir,
                "upload_dir": str(uploads),
                "upload_dir_writable": uploads.exists() and os.access(uploads, os.W_OK),
            },
            "ingestion": {"mode": settings.ingestion_mode},
            "github": github,
        }

    @router.post("/admin/publish")
    def publish_wiki() -> dict[str, object]:
        try:
            return GitHubAdminService(settings).publish()
        except RuntimeError as exc:
            detail = str(exc)
            if settings.github_token:
                detail = detail.replace(settings.github_token, "[redacted]")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc
```

Also import `os`.

- [ ] **Step 6: Verify admin and health tests pass**

Run:

```bash
uv run --extra dev pytest tests/test_admin.py tests/test_health.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/banorte_agent/api/admin.py tests/test_admin.py tests/test_health.py
git commit -m "feat: add admin status and publish endpoints"
```

## Task 7: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/deployment.md`

- [ ] **Step 1: Update README ingestion/admin docs**

In `README.md`, extend the `## Ingestion` section after the existing `/admin/ingest` curl example:

```markdown
For runtime PDF uploads, configure `ADMIN_API_KEY` and use the admin documents endpoint:

```bash
curl -sS http://localhost:8000/admin/documents \
  -H 'Authorization: Bearer YOUR_ADMIN_API_KEY' \
  -F 'file=@/path/to/text-retrievable.pdf'
```

The endpoint accepts text-retrievable PDFs only, saves them under `wiki/raw/uploads`, and ingests them immediately. Image-only scanned PDFs must be OCR-processed before upload.

Admin status is available without exposing secrets:

```bash
curl -sS http://localhost:8000/admin/status \
  -H 'Authorization: Bearer YOUR_ADMIN_API_KEY'
```

Publishing updated wiki files to GitHub is manual:

```bash
curl -sS -X POST http://localhost:8000/admin/publish \
  -H 'Authorization: Bearer YOUR_ADMIN_API_KEY'
```
```

- [ ] **Step 2: Update deployment docs**

In `docs/deployment.md`, add a `## Persistent Wiki Storage` section after the Render settings:

```markdown
## Persistent Wiki Storage

Render's default filesystem is ephemeral. To keep uploaded PDFs and generated wiki pages across deploys, attach a Render Persistent Disk to the web service.

Recommended settings:

- Disk mount path: `/app/data`
- Environment variable after storage seeding support is deployed: `WIKI_DIR=/app/data/wiki`
- Upload limit: `ADMIN_UPLOAD_MAX_BYTES=10485760`

Do not switch `WIKI_DIR` to `/app/data/wiki` before deploying the storage seeding code, because an empty wiki can make readiness fail. Creating the disk earlier is safe if `WIKI_DIR` remains `wiki`.

GitHub publishing uses these Render environment variables:

- `GITHUB_TOKEN`
- `GITHUB_REPOSITORY=uthynauta/cv-agent`
- `GITHUB_BASE_BRANCH=main`
- `GITHUB_COMMIT_AUTHOR_NAME`
- `GITHUB_COMMIT_AUTHOR_EMAIL`

Manage these values in the Render Dashboard. The admin API reports GitHub status but never returns secret values.
```

- [ ] **Step 3: Verify docs grep**

Run:

```bash
rg -n "admin/documents|admin/status|admin/publish|WIKI_DIR=/app/data/wiki|GITHUB_TOKEN" README.md docs/deployment.md
```

Expected: all new admin and persistent storage references appear.

- [ ] **Step 4: Commit**

Run:

```bash
git add README.md docs/deployment.md
git commit -m "docs: document admin document uploads"
```

## Task 8: Final Verification

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run full test suite**

Run:

```bash
uv run --extra dev pytest
```

Expected: all tests pass.

- [ ] **Step 2: Run import check**

Run:

```bash
uv run python -c "from banorte_agent.main import create_app; app = create_app(); print(app.title)"
```

Expected output includes:

```text
Banorte CV Agent
```

- [ ] **Step 3: Inspect final diff**

Run:

```bash
git status --short
git log --oneline -5
```

Expected: working tree clean after the task commits; latest commits correspond to this plan.

## Self-Review

Spec coverage:

- PDF upload and immediate ingestion: Task 4.
- Persistent Render disk and wiki seeding: Tasks 2, 3, 7.
- Admin-only status: Tasks 5, 6.
- Manual GitHub PR publishing: Tasks 5, 6.
- Secrets managed through Render env vars, never API mutation: Tasks 1, 5, 6, 7.
- Public readiness independent of GitHub: Task 6.
- Docs and verification: Tasks 7, 8.

Placeholder scan:

- No incomplete implementation gaps remain.
- The only conditional note is about whether `uv.lock` changes after dependency resolution; that is an execution-time file staging condition, not missing design.

Type consistency:

- `GitHubAdminService.status()`, `publish()`, `wiki_has_changes()`, and `changed_wiki_files()` are defined before endpoint use.
- `ensure_wiki_storage()`, `upload_directory()`, and `safe_upload_filename()` are defined before app/admin use.
- New `Settings` names match `.env.example`, tests, and endpoint code.
