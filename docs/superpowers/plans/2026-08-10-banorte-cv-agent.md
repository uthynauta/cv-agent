# Banorte CV Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Dockerized FastAPI CV agent with an Open Responses-like API, Obsidian-style wiki ingestion, Spanish grounded answers, observability, tests, evals, and demo docs.

**Architecture:** One Python FastAPI service exposes `/v1/responses`, operational endpoints, and a protected ingest endpoint. The agent searches committed Markdown wiki pages, calls OpenAI with English internal prompts, and returns Spanish cited answers. A local CLI ingests `.tex`, `.pdf`, and `.md` files from `wiki/raw/` into generated Obsidian-style Markdown pages.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, OpenAI Python SDK, PyPDF, PyYAML, prometheus-client, OpenTelemetry OTLP/gRPC, pytest, httpx, uv, Docker, Docker Compose.

## Global Constraints

- Public reviewer API is `POST /v1/responses`.
- Reviewer-facing answers are Spanish by default.
- Code, config, tests, prompts, and internal docs are English.
- `GROUNDING_MODE` supports `strict` and `inference`; default is `inference`.
- `AGENT_API_KEY` enables optional bearer auth for public agent requests.
- `ADMIN_API_KEY` protects ingestion API when set.
- `OPENAI_API_KEY` is required for live model calls.
- `OPENAI_MODEL` defaults to `gpt-5.6`.
- Raw files live under `wiki/raw/`.
- `wiki/raw/**/*.tex` can be committed.
- Non-LaTeX raw files under `wiki/raw/` are ignored by Git.
- Generated Markdown wiki pages are committed.
- No vector database for MVP.
- No server-side conversation database for MVP.
- No Kubernetes for MVP.
- Scanned PDFs are marked with `needs_ocr: true` when text extraction is too short.
- Logs must not include API keys or full secret-bearing headers.
- Optional tracing uses OpenTelemetry and is disabled by default with `OTEL_ENABLED=false`.
- OTLP/gRPC tracing must be compatible with Grafana Tempo or an OpenTelemetry Collector.
- Traces must not include API keys, bearer tokens, full prompts, raw documents, or full retrieved context.

---

## File Structure

Create this structure:

```text
.
  pyproject.toml
  uv.lock
  .gitignore
  .env.example
  Dockerfile
  docker-compose.yml
  README.md
  src/
    banorte_agent/
      __init__.py
      main.py
      config.py
      logging.py
      metrics.py
      api/
        __init__.py
        auth.py
        responses.py
        health.py
        admin.py
        models.py
      agent/
        __init__.py
        prompts.py
        service.py
        openai_client.py
      wiki/
        __init__.py
        paths.py
        documents.py
        repository.py
        search.py
        ingest.py
        extractors.py
        frontmatter.py
      cli.py
  tests/
    conftest.py
    test_config.py
    test_health.py
    test_auth.py
    test_response_schema.py
    test_wiki_repository.py
    test_extractors.py
    test_ingest.py
    test_search.py
    test_agent_service.py
    test_metrics.py
  evals/
    questions.yml
    run_eval.py
  docs/
    architecture.md
    deployment.md
    demo.md
    sample-transcript.md
  wiki/
    raw/
      cv/
      documents/
    sources/
    entities/
    concepts/
    projects/
    skills/
    questions/
    index.md
    log.md
```

Responsibility summary:

- `config.py`: environment parsing and settings defaults.
- `logging.py`: JSON logging setup and request ID helpers.
- `metrics.py`: Prometheus counters and histograms.
- `tracing.py`: optional OpenTelemetry setup and safe span helpers.
- `api/*`: HTTP routing, auth, request/response models.
- `agent/*`: prompt assembly, OpenAI client adapter, response generation.
- `wiki/*`: paths, Markdown page model, raw text extraction, ingestion, search.
- `cli.py`: local ingestion and eval commands.
- `evals/run_eval.py`: black-box API eval runner.

---

### Task 1: Project Foundation, Config, Health

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `src/banorte_agent/__init__.py`
- Create: `src/banorte_agent/config.py`
- Create: `src/banorte_agent/main.py`
- Create: `src/banorte_agent/api/__init__.py`
- Create: `src/banorte_agent/api/health.py`
- Create: `tests/test_config.py`
- Create: `tests/test_health.py`
- Create: `tests/conftest.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `banorte_agent.config.Settings`
- Produces: `banorte_agent.config.get_settings() -> Settings`
- Produces: `banorte_agent.main.create_app() -> fastapi.FastAPI`
- Produces: `GET /healthz`
- Produces: `GET /readyz`

- [ ] **Step 1: Write dependency metadata**

Create `pyproject.toml`:

```toml
[project]
name = "banorte-agent"
version = "0.1.0"
description = "Open Responses-compatible CV agent for the Banorte AI challenge"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.116.0",
  "uvicorn[standard]>=0.35.0",
  "pydantic-settings>=2.10.0",
  "openai>=1.99.0",
  "pypdf>=5.9.0",
  "PyYAML>=6.0.2",
  "prometheus-client>=0.22.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.4.0",
  "httpx>=0.28.0",
  "pytest-cov>=6.2.0",
]

[project.scripts]
banorte-agent = "banorte_agent.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Write config tests**

Create `tests/conftest.py`:

```python
import pytest

from banorte_agent.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

Create `tests/test_config.py`:

```python
from banorte_agent.config import Settings


def test_settings_defaults():
    settings = Settings(openai_api_key="test-key")
    assert settings.openai_model == "gpt-5.6"
    assert settings.grounding_mode == "inference"
    assert settings.agent_model_name == "banorte-cv-agent"
    assert settings.wiki_dir == "wiki"


def test_grounding_mode_rejects_invalid_value():
    try:
        Settings(openai_api_key="test-key", grounding_mode="creative")
    except ValueError as exc:
        assert "grounding_mode" in str(exc)
    else:
        raise AssertionError("invalid grounding mode was accepted")
```

- [ ] **Step 3: Write health tests**

Create `tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from banorte_agent.main import create_app


def test_healthz_returns_alive():
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_missing_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(create_app())
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "OPENAI_API_KEY" in response.json()["missing"]
```

- [ ] **Step 4: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_config.py tests/test_health.py -q
```

Expected: FAIL because `banorte_agent.config` and `banorte_agent.main` do not exist.

- [ ] **Step 5: Implement settings and health app**

Create `src/banorte_agent/config.py`:

```python
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


GroundingMode = Literal["strict", "inference"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.6", alias="OPENAI_MODEL")
    grounding_mode: GroundingMode = Field(default="inference", alias="GROUNDING_MODE")
    agent_api_key: str | None = Field(default=None, alias="AGENT_API_KEY")
    admin_api_key: str | None = Field(default=None, alias="ADMIN_API_KEY")
    agent_model_name: str = Field(default="banorte-cv-agent", alias="AGENT_MODEL_NAME")
    wiki_dir: str = Field(default="wiki", alias="WIKI_DIR")

    @field_validator("grounding_mode")
    @classmethod
    def validate_grounding_mode(cls, value: str) -> str:
        if value not in {"strict", "inference"}:
            raise ValueError("grounding_mode must be 'strict' or 'inference'")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Create `src/banorte_agent/api/health.py`:

```python
from pathlib import Path

from fastapi import APIRouter, Response, status

from banorte_agent.config import get_settings

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(response: Response) -> dict[str, object]:
    settings = get_settings()
    missing: list[str] = []
    if not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")
    index_path = Path(settings.wiki_dir) / "index.md"
    if not index_path.exists():
        missing.append("wiki/index.md")
    if missing:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "missing": missing}
    return {"status": "ready", "missing": []}
```

Create `src/banorte_agent/main.py`:

```python
from fastapi import FastAPI

from banorte_agent.api.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="Banorte CV Agent", version="0.1.0")
    app.include_router(health_router)
    return app


app = create_app()
```

Create `src/banorte_agent/__init__.py`:

```python
__all__ = ["__version__"]

__version__ = "0.1.0"
```

Create empty `src/banorte_agent/api/__init__.py`.

- [ ] **Step 6: Add `.env.example`**

Create `.env.example`:

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6
GROUNDING_MODE=inference
AGENT_API_KEY=
ADMIN_API_KEY=
AGENT_MODEL_NAME=banorte-cv-agent
WIKI_DIR=wiki
```

- [ ] **Step 7: Update README foundation section**

Add:

```markdown
## Local Development

```bash
uv run --extra dev pytest
uv run uvicorn banorte_agent.main:app --reload
```

Runtime configuration is read from environment variables. Start from `.env.example` and keep real `.env` files out of Git.
```

- [ ] **Step 8: Run tests to verify pass**

Run:

```bash
uv run --extra dev pytest tests/test_config.py tests/test_health.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .env.example README.md src tests
git commit -m "feat: add FastAPI project foundation"
```

---

### Task 2: Wiki Structure, Frontmatter, Git Ignore Policy

**Files:**
- Create: `.gitignore`
- Create: `src/banorte_agent/wiki/__init__.py`
- Create: `src/banorte_agent/wiki/paths.py`
- Create: `src/banorte_agent/wiki/frontmatter.py`
- Create: `src/banorte_agent/wiki/documents.py`
- Create: `src/banorte_agent/wiki/repository.py`
- Create: `tests/test_wiki_repository.py`
- Create: `wiki/.gitkeep`
- Create: `wiki/raw/cv/.gitkeep`
- Create: `wiki/raw/documents/.gitkeep`
- Create: `wiki/sources/.gitkeep`
- Create: `wiki/entities/.gitkeep`
- Create: `wiki/concepts/.gitkeep`
- Create: `wiki/projects/.gitkeep`
- Create: `wiki/skills/.gitkeep`
- Create: `wiki/questions/.gitkeep`
- Create: `wiki/index.md`
- Create: `wiki/log.md`

**Interfaces:**
- Consumes: `Settings.wiki_dir`
- Produces: `WikiPage(path: Path, title: str, metadata: dict[str, object], body: str)`
- Produces: `dump_frontmatter(metadata: dict[str, object], body: str) -> str`
- Produces: `load_frontmatter(text: str) -> tuple[dict[str, object], str]`
- Produces: `WikiRepository(root: Path)`
- Produces: `WikiRepository.list_pages() -> list[WikiPage]`
- Produces: `WikiRepository.write_page(relative_path: str, title: str, metadata: dict[str, object], body: str) -> Path`

- [ ] **Step 1: Write wiki repository tests**

Create `tests/test_wiki_repository.py`:

```python
from pathlib import Path

from banorte_agent.wiki.frontmatter import dump_frontmatter, load_frontmatter
from banorte_agent.wiki.repository import WikiRepository


def test_frontmatter_round_trip():
    text = dump_frontmatter({"title": "Othon CV", "tags": ["cv", "source"]}, "Body text")
    metadata, body = load_frontmatter(text)
    assert metadata["title"] == "Othon CV"
    assert metadata["tags"] == ["cv", "source"]
    assert body == "Body text"


def test_repository_writes_and_lists_pages(tmp_path: Path):
    repo = WikiRepository(tmp_path)
    written = repo.write_page(
        "sources/othon-cv.md",
        "Othon CV",
        {"kind": "source"},
        "Resumen con link a [[Python]].",
    )
    assert written == tmp_path / "sources" / "othon-cv.md"
    pages = repo.list_pages()
    assert len(pages) == 1
    assert pages[0].title == "Othon CV"
    assert pages[0].metadata["kind"] == "source"
    assert "[[Python]]" in pages[0].body
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_wiki_repository.py -q
```

Expected: FAIL because wiki modules do not exist.

- [ ] **Step 3: Implement wiki modules**

Create `src/banorte_agent/wiki/documents.py`:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WikiPage:
    path: Path
    title: str
    metadata: dict[str, object]
    body: str
```

Create `src/banorte_agent/wiki/frontmatter.py`:

```python
from typing import Any

import yaml


def dump_frontmatter(metadata: dict[str, object], body: str) -> str:
    yaml_text = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{yaml_text}\n---\n\n{body.strip()}\n"


def load_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text.strip()
    _, yaml_text, body = text.split("---", 2)
    metadata = yaml.safe_load(yaml_text) or {}
    return metadata, body.strip()
```

Create `src/banorte_agent/wiki/repository.py`:

```python
from pathlib import Path

from banorte_agent.wiki.documents import WikiPage
from banorte_agent.wiki.frontmatter import dump_frontmatter, load_frontmatter


class WikiRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_pages(self) -> list[WikiPage]:
        pages: list[WikiPage] = []
        if not self.root.exists():
            return pages
        for path in sorted(self.root.rglob("*.md")):
            if any(part == "raw" for part in path.relative_to(self.root).parts):
                continue
            metadata, body = load_frontmatter(path.read_text(encoding="utf-8"))
            title = str(metadata.get("title") or path.stem.replace("-", " ").title())
            pages.append(WikiPage(path=path, title=title, metadata=metadata, body=body))
        return pages

    def write_page(self, relative_path: str, title: str, metadata: dict[str, object], body: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        merged = {"title": title, **metadata}
        path.write_text(dump_frontmatter(merged, body), encoding="utf-8")
        return path
```

Create `src/banorte_agent/wiki/paths.py`:

```python
from pathlib import Path

WIKI_DIRS = [
    "raw/cv",
    "raw/documents",
    "sources",
    "entities",
    "concepts",
    "projects",
    "skills",
    "questions",
]


def ensure_wiki_tree(root: Path) -> None:
    for dirname in WIKI_DIRS:
        (root / dirname).mkdir(parents=True, exist_ok=True)
    (root / "index.md").touch(exist_ok=True)
    (root / "log.md").touch(exist_ok=True)
```

Create empty `src/banorte_agent/wiki/__init__.py`.

- [ ] **Step 4: Create wiki skeleton files**

Create directories and files exactly as listed in the task file list. `wiki/index.md` content:

```markdown
# Wiki Index

## Sources

## Entities

## Concepts

## Projects

## Skills

## Questions
```

`wiki/log.md` content:

```markdown
# Wiki Log
```

- [ ] **Step 5: Add `.gitignore` raw policy**

Create `.gitignore`:

```gitignore
.env
.venv/
__pycache__/
.pytest_cache/
.coverage
htmlcov/
dist/
*.egg-info/

wiki/raw/**
!wiki/raw/
!wiki/raw/**/
!wiki/raw/**/*.tex
!wiki/raw/**/.gitkeep
```

- [ ] **Step 6: Run tests**

Run:

```bash
uv run --extra dev pytest tests/test_wiki_repository.py -q
```

Expected: PASS.

- [ ] **Step 7: Verify Git ignore policy**

Run:

```bash
git check-ignore wiki/raw/documents/example.pdf
```

Expected output includes `wiki/raw/documents/example.pdf`.

Run:

```bash
git check-ignore wiki/raw/cv/example.tex
```

Expected: no output and exit code 1, because `.tex` files are not ignored.

- [ ] **Step 8: Commit**

```bash
git add .gitignore src/banorte_agent/wiki tests/test_wiki_repository.py wiki
git commit -m "feat: add Obsidian-style wiki foundation"
```

---

### Task 3: Raw Text Extractors And Ingestion Pipeline

**Files:**
- Create: `src/banorte_agent/wiki/extractors.py`
- Create: `src/banorte_agent/wiki/ingest.py`
- Create: `src/banorte_agent/cli.py`
- Create: `tests/test_extractors.py`
- Create: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `WikiRepository.write_page(...)`
- Produces: `ExtractedSource(source_path: Path, text: str, kind: str, needs_ocr: bool, sha256: str)`
- Produces: `extract_source(path: Path) -> ExtractedSource`
- Produces: `IngestResult(source_path: Path, source_page: Path, needs_ocr: bool)`
- Produces: `IngestionService(repository: WikiRepository)`
- Produces: `IngestionService.ingest_file(path: Path) -> IngestResult`
- Produces: CLI command `banorte-agent ingest wiki/raw`

- [ ] **Step 1: Write extractor tests**

Create `tests/test_extractors.py`:

```python
from pathlib import Path

from banorte_agent.wiki.extractors import extract_source


def test_extract_markdown(tmp_path: Path):
    path = tmp_path / "profile.md"
    path.write_text("# Perfil\n\nExperiencia con agentes de IA.", encoding="utf-8")
    result = extract_source(path)
    assert result.kind == "markdown"
    assert "Experiencia con agentes" in result.text
    assert result.needs_ocr is False
    assert len(result.sha256) == 64


def test_extract_latex_strips_common_commands(tmp_path: Path):
    path = tmp_path / "cv.tex"
    path.write_text(r"\section{Experience}\textbf{AI Agents}", encoding="utf-8")
    result = extract_source(path)
    assert result.kind == "latex"
    assert "Experience" in result.text
    assert "AI Agents" in result.text
    assert "\\section" not in result.text
```

- [ ] **Step 2: Write ingestion tests**

Create `tests/test_ingest.py`:

```python
from pathlib import Path

from banorte_agent.wiki.ingest import IngestionService
from banorte_agent.wiki.repository import WikiRepository


def test_ingest_file_creates_source_page_and_log(tmp_path: Path):
    raw = tmp_path / "raw" / "cv"
    raw.mkdir(parents=True)
    source = raw / "othon.tex"
    source.write_text(r"\section{Skills} Python, FastAPI, AI agents", encoding="utf-8")
    repo = WikiRepository(tmp_path)
    result = IngestionService(repo).ingest_file(source)
    assert result.source_page == tmp_path / "sources" / "othon.md"
    text = result.source_page.read_text(encoding="utf-8")
    assert "Python, FastAPI, AI agents" in text
    assert "sha256:" in text
    assert "needs_ocr: false" in text
    assert "ingest | othon.tex" in (tmp_path / "log.md").read_text(encoding="utf-8")
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_extractors.py tests/test_ingest.py -q
```

Expected: FAIL because extractor and ingestion modules do not exist.

- [ ] **Step 4: Implement extractors**

Create `src/banorte_agent/wiki/extractors.py`:

```python
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from pypdf import PdfReader


@dataclass(frozen=True)
class ExtractedSource:
    source_path: Path
    text: str
    kind: str
    needs_ocr: bool
    sha256: str


def extract_source(path: Path) -> ExtractedSource:
    suffix = path.suffix.lower()
    raw_bytes = path.read_bytes()
    digest = sha256(raw_bytes).hexdigest()
    if suffix == ".md":
        return ExtractedSource(path, path.read_text(encoding="utf-8"), "markdown", False, digest)
    if suffix == ".tex":
        return ExtractedSource(path, _clean_latex(path.read_text(encoding="utf-8")), "latex", False, digest)
    if suffix == ".pdf":
        text = _extract_pdf_text(path)
        return ExtractedSource(path, text, "pdf", len(text.strip()) < 120, digest)
    raise ValueError(f"unsupported source extension: {suffix}")


def _clean_latex(text: str) -> str:
    text = re.sub(r"%.*", "", text)
    text = re.sub(r"\\(section|subsection|subsubsection|textbf|emph)\{([^}]*)\}", r"\2\n", text)
    text = re.sub(r"\\[a-zA-Z]+(\[[^]]*\])?(\{[^}]*\})?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()
```

- [ ] **Step 5: Implement ingestion service and CLI**

Create `src/banorte_agent/wiki/ingest.py`:

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re

from banorte_agent.wiki.extractors import extract_source
from banorte_agent.wiki.repository import WikiRepository


@dataclass(frozen=True)
class IngestResult:
    source_path: Path
    source_page: Path
    needs_ocr: bool


class IngestionService:
    def __init__(self, repository: WikiRepository) -> None:
        self.repository = repository

    def ingest_file(self, path: Path) -> IngestResult:
        extracted = extract_source(path)
        slug = _slugify(path.stem)
        metadata = {
            "kind": "source",
            "source_file": str(path),
            "source_type": extracted.kind,
            "sha256": extracted.sha256,
            "needs_ocr": extracted.needs_ocr,
            "ingested_at": datetime.now(UTC).date().isoformat(),
            "tags": ["source", extracted.kind],
        }
        body = "\n".join(
            [
                f"# {path.stem}",
                "",
                "## Summary",
                "",
                extracted.text[:2000].strip() or "No selectable text extracted.",
                "",
                "## Extracted Text",
                "",
                extracted.text.strip() or "No selectable text extracted.",
            ]
        )
        source_page = self.repository.write_page(f"sources/{slug}.md", path.stem, metadata, body)
        self._append_log(path)
        self._ensure_index()
        return IngestResult(path, source_page, extracted.needs_ocr)

    def ingest_directory(self, root: Path) -> list[IngestResult]:
        results: list[IngestResult] = []
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() in {".tex", ".pdf", ".md"}:
                results.append(self.ingest_file(path))
        return results

    def _append_log(self, path: Path) -> None:
        log_path = self.repository.root / "log.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not log_path.exists():
            log_path.write_text("# Wiki Log\n", encoding="utf-8")
        today = datetime.now(UTC).date().isoformat()
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## [{today}] ingest | {path.name}\n\n- Source: `{path}`\n")

    def _ensure_index(self) -> None:
        index_path = self.repository.root / "index.md"
        if not index_path.exists():
            index_path.write_text("# Wiki Index\n", encoding="utf-8")


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value or "source"
```

Create `src/banorte_agent/cli.py`:

```python
from pathlib import Path
import argparse

from banorte_agent.config import get_settings
from banorte_agent.wiki.ingest import IngestionService
from banorte_agent.wiki.repository import WikiRepository


def main() -> None:
    parser = argparse.ArgumentParser(prog="banorte-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("path")
    args = parser.parse_args()

    if args.command == "ingest":
        settings = get_settings()
        repo = WikiRepository(Path(settings.wiki_dir))
        service = IngestionService(repo)
        target = Path(args.path)
        results = service.ingest_directory(target) if target.is_dir() else [service.ingest_file(target)]
        for result in results:
            print(f"ingested {result.source_path} -> {result.source_page}")
```

- [ ] **Step 6: Run tests**

Run:

```bash
uv run --extra dev pytest tests/test_extractors.py tests/test_ingest.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/banorte_agent/wiki/extractors.py src/banorte_agent/wiki/ingest.py src/banorte_agent/cli.py tests/test_extractors.py tests/test_ingest.py
git commit -m "feat: add wiki ingestion pipeline"
```

---

### Task 4: Lexical Wiki Search

**Files:**
- Create: `src/banorte_agent/wiki/search.py`
- Create: `tests/test_search.py`

**Interfaces:**
- Consumes: `WikiRepository.list_pages() -> list[WikiPage]`
- Produces: `SearchHit(path: Path, title: str, excerpt: str, score: float)`
- Produces: `WikiSearch(repository: WikiRepository).search(query: str, limit: int = 5) -> list[SearchHit]`

- [ ] **Step 1: Write search tests**

Create `tests/test_search.py`:

```python
from pathlib import Path

from banorte_agent.wiki.repository import WikiRepository
from banorte_agent.wiki.search import WikiSearch


def test_search_ranks_matching_pages(tmp_path: Path):
    repo = WikiRepository(tmp_path)
    repo.write_page("skills/python.md", "Python", {"kind": "skill"}, "Evidence: FastAPI and AI agents.")
    repo.write_page("concepts/cloud.md", "Cloud", {"kind": "concept"}, "Docker Compose deployment.")
    hits = WikiSearch(repo).search("Python FastAPI agents")
    assert hits[0].title == "Python"
    assert hits[0].score > 0
    assert "FastAPI" in hits[0].excerpt


def test_search_returns_empty_for_blank_query(tmp_path: Path):
    repo = WikiRepository(tmp_path)
    repo.write_page("skills/python.md", "Python", {"kind": "skill"}, "Python")
    assert WikiSearch(repo).search("   ") == []
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_search.py -q
```

Expected: FAIL because `banorte_agent.wiki.search` does not exist.

- [ ] **Step 3: Implement search**

Create `src/banorte_agent/wiki/search.py`:

```python
from dataclasses import dataclass
from pathlib import Path
import re

from banorte_agent.wiki.repository import WikiRepository


@dataclass(frozen=True)
class SearchHit:
    path: Path
    title: str
    excerpt: str
    score: float


class WikiSearch:
    def __init__(self, repository: WikiRepository) -> None:
        self.repository = repository

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        terms = _terms(query)
        if not terms:
            return []
        hits: list[SearchHit] = []
        for page in self.repository.list_pages():
            haystack = " ".join([page.title, str(page.metadata), page.body])
            score = _score(haystack, terms)
            if score > 0:
                hits.append(SearchHit(page.path, page.title, _excerpt(page.body, terms), score))
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]


def _terms(query: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9]+", query) if len(term) > 2]


def _score(text: str, terms: list[str]) -> float:
    lowered = text.lower()
    return float(sum(lowered.count(term) for term in terms))


def _excerpt(body: str, terms: list[str]) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", body.replace("\n", " "))
    for sentence in sentences:
        if any(term in sentence.lower() for term in terms):
            return sentence[:500]
    return body.replace("\n", " ")[:500]
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run --extra dev pytest tests/test_search.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/banorte_agent/wiki/search.py tests/test_search.py
git commit -m "feat: add lexical wiki search"
```

---

### Task 5: Agent Service And OpenAI Adapter

**Files:**
- Create: `src/banorte_agent/agent/__init__.py`
- Create: `src/banorte_agent/agent/prompts.py`
- Create: `src/banorte_agent/agent/openai_client.py`
- Create: `src/banorte_agent/agent/service.py`
- Create: `tests/test_agent_service.py`

**Interfaces:**
- Consumes: `WikiSearch.search(query: str, limit: int = 5) -> list[SearchHit]`
- Produces: `OpenAITextClient.create_response(instructions: str, input_text: str) -> str`
- Produces: `AgentService.answer(input_text: str, extra_instructions: str | None = None) -> str`

- [ ] **Step 1: Write agent service tests**

Create `tests/test_agent_service.py`:

```python
from pathlib import Path

from banorte_agent.agent.service import AgentService
from banorte_agent.config import Settings
from banorte_agent.wiki.repository import WikiRepository
from banorte_agent.wiki.search import WikiSearch


class FakeTextClient:
    def __init__(self) -> None:
        self.instructions = ""
        self.input_text = ""

    def create_response(self, instructions: str, input_text: str) -> str:
        self.instructions = instructions
        self.input_text = input_text
        return "Othon tiene experiencia con FastAPI. Fuentes: [[Python]]"


def test_agent_builds_spanish_grounded_prompt(tmp_path: Path):
    repo = WikiRepository(tmp_path)
    repo.write_page("skills/python.md", "Python", {"kind": "skill"}, "Othon used FastAPI for AI agents.")
    fake = FakeTextClient()
    settings = Settings(openai_api_key="test-key", grounding_mode="strict")
    service = AgentService(settings, WikiSearch(repo), fake)
    answer = service.answer("¿Qué experiencia tiene con FastAPI?")
    assert "Fuentes: [[Python]]" in answer
    assert "Answer in Spanish" in fake.instructions
    assert "strict grounding mode" in fake.instructions
    assert "[[Python]]" in fake.input_text
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_agent_service.py -q
```

Expected: FAIL because agent modules do not exist.

- [ ] **Step 3: Implement prompt builder and client adapter**

Create `src/banorte_agent/agent/prompts.py`:

```python
from banorte_agent.config import GroundingMode


def build_instructions(grounding_mode: GroundingMode, extra_instructions: str | None = None) -> str:
    mode_rule = (
        "Use strict grounding mode: answer only from the supplied wiki context and say clearly when information is missing."
        if grounding_mode == "strict"
        else "Use inference grounding mode: answer from supplied wiki facts and label cautious inferences when useful."
    )
    parts = [
        "You are Othon's CV agent for Banorte technical reviewers.",
        "Answer in Spanish by default.",
        "Use clear, concise, natural recruiter-facing Spanish.",
        "Cite visible wiki page names using Obsidian links in a final 'Fuentes:' line.",
        "Do not invent unsupported dates, employers, credentials, or project outcomes.",
        mode_rule,
    ]
    if extra_instructions:
        parts.append(f"Additional request instructions: {extra_instructions}")
    return "\n".join(parts)
```

Create `src/banorte_agent/agent/openai_client.py`:

```python
from openai import OpenAI

from banorte_agent.config import Settings


class OpenAITextClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)

    def create_response(self, instructions: str, input_text: str) -> str:
        response = self.client.responses.create(
            model=self.settings.openai_model,
            instructions=instructions,
            input=input_text,
        )
        return response.output_text
```

- [ ] **Step 4: Implement agent service**

Create `src/banorte_agent/agent/service.py`:

```python
from typing import Protocol

from banorte_agent.agent.prompts import build_instructions
from banorte_agent.config import Settings
from banorte_agent.wiki.search import WikiSearch


class TextClient(Protocol):
    def create_response(self, instructions: str, input_text: str) -> str:
        ...


class AgentService:
    def __init__(self, settings: Settings, search: WikiSearch, text_client: TextClient) -> None:
        self.settings = settings
        self.search = search
        self.text_client = text_client

    def answer(self, input_text: str, extra_instructions: str | None = None) -> str:
        hits = self.search.search(input_text)
        context = "\n\n".join(
            f"Source: [[{hit.title}]]\nPath: {hit.path}\nExcerpt: {hit.excerpt}" for hit in hits
        )
        if not context:
            context = "No relevant wiki context found."
        instructions = build_instructions(self.settings.grounding_mode, extra_instructions)
        model_input = f"Wiki context:\n{context}\n\nReviewer question:\n{input_text}"
        return self.text_client.create_response(instructions, model_input)
```

Create empty `src/banorte_agent/agent/__init__.py`.

- [ ] **Step 5: Run tests**

Run:

```bash
uv run --extra dev pytest tests/test_agent_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/banorte_agent/agent tests/test_agent_service.py
git commit -m "feat: add grounded CV agent service"
```

---

### Task 6: Open Responses-like API, Auth, Admin Ingest

**Files:**
- Create: `src/banorte_agent/api/models.py`
- Create: `src/banorte_agent/api/auth.py`
- Create: `src/banorte_agent/api/responses.py`
- Create: `src/banorte_agent/api/admin.py`
- Modify: `src/banorte_agent/main.py`
- Create: `tests/test_auth.py`
- Create: `tests/test_response_schema.py`

**Interfaces:**
- Consumes: `AgentService.answer(...) -> str`
- Consumes: `IngestionService.ingest_file(...) -> IngestResult`
- Produces: `ResponseRequest(model: str | None, input: str, instructions: str | None)`
- Produces: `POST /v1/responses`
- Produces: `POST /admin/ingest`

- [ ] **Step 1: Write auth and response tests**

Create `tests/test_auth.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from banorte_agent.api.auth import require_bearer


def test_optional_bearer_allows_request_when_key_missing():
    app = FastAPI()

    @app.get("/protected")
    def protected(_: None = require_bearer(None)):
        return {"ok": True}

    assert TestClient(app).get("/protected").status_code == 200


def test_bearer_rejects_wrong_key():
    app = FastAPI()

    @app.get("/protected")
    def protected(_: None = require_bearer("secret")):
        return {"ok": True}

    response = TestClient(app).get("/protected", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401
```

Create `tests/test_response_schema.py`:

```python
from fastapi.testclient import TestClient

from banorte_agent.main import create_app


def test_responses_endpoint_returns_openai_like_shape(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    app = create_app(agent_answerer=lambda text, instructions=None: "Respuesta en español. Fuentes: [[Othon CV]]")
    client = TestClient(app)
    response = client.post("/v1/responses", json={"model": "banorte-cv-agent", "input": "¿Quién es Othon?"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "response"
    assert payload["model"] == "banorte-cv-agent"
    assert payload["output_text"].endswith("Fuentes: [[Othon CV]]")
    assert payload["output"][0]["content"][0]["type"] == "output_text"


def test_responses_endpoint_enforces_agent_key():
    app = create_app(
        settings=__import__("banorte_agent.config", fromlist=["Settings"]).Settings(
            openai_api_key="test-key",
            agent_api_key="agent-secret",
        ),
        agent_answerer=lambda text, instructions=None: "Respuesta. Fuentes: [[Test]]",
    )
    response = TestClient(app).post("/v1/responses", json={"input": "hola"})
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_auth.py tests/test_response_schema.py -q
```

Expected: FAIL because API modules and `create_app(agent_answerer=...)` do not exist.

- [ ] **Step 3: Implement API models**

Create `src/banorte_agent/api/models.py`:

```python
from pydantic import BaseModel, Field


class ResponseRequest(BaseModel):
    model: str | None = None
    input: str = Field(min_length=1)
    instructions: str | None = None


class IngestRequest(BaseModel):
    path: str
```

- [ ] **Step 4: Implement bearer auth**

Create `src/banorte_agent/api/auth.py`:

```python
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status


def require_bearer(expected_key: str | None):
    def dependency(authorization: Annotated[str | None, Header()] = None) -> None:
        if not expected_key:
            return
        if authorization != f"Bearer {expected_key}":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")
    return Depends(dependency)
```

- [ ] **Step 5: Implement responses and admin routers**

Create `src/banorte_agent/api/responses.py`:

```python
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter

from banorte_agent.api.auth import require_bearer
from banorte_agent.api.models import ResponseRequest
from banorte_agent.config import Settings


def build_responses_router(settings: Settings, answerer: Callable[[str, str | None], str]) -> APIRouter:
    router = APIRouter(dependencies=[require_bearer(settings.agent_api_key)])

    @router.post("/v1/responses")
    def create_response(request: ResponseRequest) -> dict[str, object]:
        text = answerer(request.input, request.instructions)
        model = request.model or settings.agent_model_name
        return {
            "id": f"resp_{uuid4().hex}",
            "object": "response",
            "created_at": int(datetime.now(UTC).timestamp()),
            "model": model,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
            "output_text": text,
        }

    return router
```

Create `src/banorte_agent/api/admin.py`:

```python
from pathlib import Path

from fastapi import APIRouter

from banorte_agent.api.auth import require_bearer
from banorte_agent.api.models import IngestRequest
from banorte_agent.config import Settings
from banorte_agent.wiki.ingest import IngestionService


def build_admin_router(settings: Settings, ingestion: IngestionService) -> APIRouter:
    router = APIRouter(dependencies=[require_bearer(settings.admin_api_key)])

    @router.post("/admin/ingest")
    def ingest(request: IngestRequest) -> dict[str, object]:
        path = Path(request.path)
        results = ingestion.ingest_directory(path) if path.is_dir() else [ingestion.ingest_file(path)]
        return {
            "status": "ok",
            "count": len(results),
            "sources": [str(result.source_page) for result in results],
        }

    return router
```

- [ ] **Step 6: Wire app factory with injectable answerer**

Modify `src/banorte_agent/main.py`:

```python
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from banorte_agent.agent.openai_client import OpenAITextClient
from banorte_agent.agent.service import AgentService
from banorte_agent.api.admin import build_admin_router
from banorte_agent.api.health import router as health_router
from banorte_agent.api.responses import build_responses_router
from banorte_agent.config import Settings, get_settings
from banorte_agent.wiki.ingest import IngestionService
from banorte_agent.wiki.repository import WikiRepository
from banorte_agent.wiki.search import WikiSearch


def create_app(
    settings: Settings | None = None,
    agent_answerer: Callable[[str, str | None], str] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Banorte CV Agent", version="0.1.0")
    app.include_router(health_router)
    repository = WikiRepository(Path(settings.wiki_dir))
    if agent_answerer is None:
        def agent_answerer(text: str, instructions: str | None = None) -> str:
            agent = AgentService(settings, WikiSearch(repository), OpenAITextClient(settings))
            return agent.answer(text, instructions)
    app.include_router(build_responses_router(settings, agent_answerer))
    app.include_router(build_admin_router(settings, IngestionService(repository)))
    return app


app = create_app()
```

- [ ] **Step 7: Run tests**

Run:

```bash
uv run --extra dev pytest tests/test_auth.py tests/test_response_schema.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/banorte_agent/api src/banorte_agent/main.py tests/test_auth.py tests/test_response_schema.py
git commit -m "feat: add Open Responses API"
```

---

### Task 7: Observability, Metrics, And Optional Tracing

**Files:**
- Create: `src/banorte_agent/logging.py`
- Create: `src/banorte_agent/metrics.py`
- Create: `src/banorte_agent/tracing.py`
- Modify: `src/banorte_agent/main.py`
- Modify: `src/banorte_agent/api/health.py`
- Modify: `src/banorte_agent/agent/service.py`
- Modify: `src/banorte_agent/agent/openai_client.py`
- Modify: `src/banorte_agent/wiki/search.py`
- Modify: `src/banorte_agent/wiki/ingest.py`
- Create: `tests/test_metrics.py`
- Create: `tests/test_tracing.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`

**Interfaces:**
- Produces: `GET /metrics`
- Produces: request log middleware with `x-request-id`
- Produces: Prometheus metrics text containing `banorte_http_requests_total`
- Produces: `configure_tracing(app: FastAPI, settings: Settings) -> None`
- Produces: optional OTLP/gRPC tracing when `OTEL_ENABLED=true`
- Produces: no-op tracing setup when `OTEL_ENABLED=false`
- Produces: safe spans for agent answer, OpenAI call, wiki search, and ingestion

- [ ] **Step 1: Write metrics test**

Create `tests/test_metrics.py`:

```python
from fastapi.testclient import TestClient

from banorte_agent.main import create_app


def test_metrics_endpoint_exposes_prometheus_text(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    app = create_app(agent_answerer=lambda text, instructions=None: "ok. Fuentes: [[Test]]")
    client = TestClient(app)
    client.get("/healthz")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "banorte_http_requests_total" in response.text


def test_request_id_header_is_returned(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    app = create_app(agent_answerer=lambda text, instructions=None: "ok. Fuentes: [[Test]]")
    response = TestClient(app).get("/healthz", headers={"x-request-id": "req-test"})
    assert response.headers["x-request-id"] == "req-test"
```

Create `tests/test_tracing.py`:

```python
from fastapi import FastAPI

from banorte_agent.config import Settings
from banorte_agent.tracing import configure_tracing, tracing_enabled


def test_tracing_disabled_by_default():
    settings = Settings(openai_api_key="test-key")
    assert tracing_enabled(settings) is False


def test_configure_tracing_noops_when_disabled():
    app = FastAPI()
    settings = Settings(openai_api_key="test-key", otel_enabled=False)
    configure_tracing(app, settings)
    assert app.title == "FastAPI"


def test_safe_span_attributes_exclude_text_payloads():
    from banorte_agent.tracing import safe_count_attribute

    assert safe_count_attribute("query_length", "secret prompt text") == ("query_length", 18)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_metrics.py -q
```

Expected: FAIL because `/metrics`, request ID middleware, and tracing module do not exist.

- [ ] **Step 3: Implement metrics**

Create `src/banorte_agent/metrics.py`:

```python
from prometheus_client import Counter, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "banorte_http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "banorte_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)
OPENAI_CALLS = Counter("banorte_openai_calls_total", "OpenAI calls", ["status"])
INGEST_EVENTS = Counter("banorte_ingest_events_total", "Ingest events", ["status"])


def render_metrics() -> bytes:
    return generate_latest()
```

Create `src/banorte_agent/tracing.py`:

```python
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from banorte_agent.config import Settings


def tracing_enabled(settings: Settings) -> bool:
    return settings.otel_enabled


def configure_tracing(app: FastAPI, settings: Settings) -> None:
    if not tracing_enabled(settings):
        return
    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=settings.otel_exporter_otlp_endpoint,
        insecure=settings.otel_exporter_otlp_insecure,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


def get_tracer():
    return trace.get_tracer("banorte_agent")


def safe_count_attribute(name: str, value: str) -> tuple[str, int]:
    return name, len(value)
```

Create `src/banorte_agent/logging.py`:

```python
from uuid import uuid4
import json
import logging
import time

from fastapi import Request, Response

from banorte_agent.metrics import HTTP_LATENCY, HTTP_REQUESTS

logger = logging.getLogger("banorte_agent")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


async def request_observability_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex}"
    start = time.perf_counter()
    response: Response = await call_next(request)
    elapsed = time.perf_counter() - start
    path = request.url.path
    HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    HTTP_LATENCY.labels(request.method, path).observe(elapsed)
    response.headers["x-request-id"] = request_id
    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "latency_seconds": round(elapsed, 6),
            }
        )
    )
    return response
```

Modify `src/banorte_agent/config.py` to add:

```python
    otel_enabled: bool = Field(default=False, alias="OTEL_ENABLED")
    otel_service_name: str = Field(default="banorte-cv-agent", alias="OTEL_SERVICE_NAME")
    otel_exporter_otlp_endpoint: str = Field(default="http://tempo:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    otel_exporter_otlp_insecure: bool = Field(default=True, alias="OTEL_EXPORTER_OTLP_INSECURE")
    otel_resource_attributes: str | None = Field(default=None, alias="OTEL_RESOURCE_ATTRIBUTES")
```

Modify `pyproject.toml` dependencies to include:

```toml
  "opentelemetry-api>=1.36.0",
  "opentelemetry-sdk>=1.36.0",
  "opentelemetry-exporter-otlp-proto-grpc>=1.36.0",
  "opentelemetry-instrumentation-fastapi>=0.57b0",
```

Modify `.env.example` to include:

```dotenv
OTEL_ENABLED=false
OTEL_SERVICE_NAME=banorte-cv-agent
OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
OTEL_EXPORTER_OTLP_INSECURE=true
OTEL_RESOURCE_ATTRIBUTES=
```

- [ ] **Step 4: Wire middleware and metrics endpoint**

Modify `src/banorte_agent/api/health.py`:

```python
from pathlib import Path

from fastapi import APIRouter, Response, status
from fastapi.responses import PlainTextResponse

from banorte_agent.config import get_settings
from banorte_agent.metrics import render_metrics

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(response: Response) -> dict[str, object]:
    settings = get_settings()
    missing: list[str] = []
    if not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")
    index_path = Path(settings.wiki_dir) / "index.md"
    if not index_path.exists():
        missing.append("wiki/index.md")
    if missing:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "missing": missing}
    return {"status": "ready", "missing": []}


@router.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(render_metrics().decode("utf-8"), media_type="text/plain; version=0.0.4")
```

Modify `src/banorte_agent/main.py` to call:

```python
from banorte_agent.logging import configure_logging, request_observability_middleware
from banorte_agent.tracing import configure_tracing

configure_logging()
configure_tracing(app, settings)
app.middleware("http")(request_observability_middleware)
```

inside `create_app()` before routers are included.

Add safe manual spans:

- In `AgentService.answer`, create span `agent.answer`; set `grounding_mode`, `search.hit_count`, and `input.length`. Do not put full user input, prompt, context, or answer in attributes.
- In `WikiSearch.search`, create span `wiki.search`; set `query.length`, `result.count`, and `result.titles` with only the top titles joined and capped to 200 characters.
- In `OpenAITextClient.create_response`, create span `openai.responses.create`; set `openai.model` and `input.length`; record exception and status on errors; do not put prompt/input text in attributes.
- In `IngestionService.ingest_file`, create span `wiki.ingest_file`; set `source.extension`, `source.needs_ocr`, and `source.page`; do not put raw extracted text in attributes.

- [ ] **Step 5: Run tests**

Run:

```bash
uv run --extra dev pytest tests/test_metrics.py tests/test_tracing.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .env.example src/banorte_agent/logging.py src/banorte_agent/metrics.py src/banorte_agent/tracing.py src/banorte_agent/main.py src/banorte_agent/api/health.py tests/test_metrics.py tests/test_tracing.py
git commit -m "feat: add service observability"
```

---

### Task 8: Docker Compose Deployment

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`
- Create: `docs/deployment.md`
- Modify: `README.md`

**Interfaces:**
- Produces: Docker image that runs `uvicorn banorte_agent.main:app`
- Produces: Compose service `banorte-agent` on port `8000`

- [ ] **Step 1: Write Dockerfile**

Create `Dockerfile`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY README.md ./
COPY src ./src
COPY wiki ./wiki

RUN uv pip install --system .

EXPOSE 8000

CMD ["uvicorn", "banorte_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write Compose config**

Create `docker-compose.yml`:

```yaml
services:
  banorte-agent:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - ./wiki:/app/wiki
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
      interval: 30s
      timeout: 5s
      retries: 3
```

- [ ] **Step 3: Write Docker ignore file**

Create `.dockerignore`:

```dockerignore
.git
.env
.venv
__pycache__
.pytest_cache
htmlcov
dist
*.egg-info
wiki/raw/**/*.pdf
wiki/raw/**/*.docx
wiki/raw/**/*.png
wiki/raw/**/*.jpg
```

- [ ] **Step 4: Write deployment docs**

Create `docs/deployment.md`:

```markdown
# Deployment

## Environment

Copy `.env.example` to `.env` on the server and set:

- `OPENAI_API_KEY`
- `AGENT_API_KEY` if the public endpoint should require bearer auth
- `ADMIN_API_KEY` if `/admin/ingest` is exposed
- `GROUNDING_MODE=inference`
- `OPENAI_MODEL=gpt-5.6`

## Run

```bash
docker compose up -d --build
docker compose logs -f banorte-agent
```

## Checks

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
curl http://localhost:8000/metrics
```

## Banorte Registration

Register the public URL:

```text
https://<host>/v1/responses
```

If `AGENT_API_KEY` is set, register the same value as the endpoint API key in the Banorte platform.
```

- [ ] **Step 5: Update README deployment section**

Add:

```markdown
## Docker

```bash
docker compose up -d --build
curl http://localhost:8000/healthz
```

See [docs/deployment.md](docs/deployment.md).
```

- [ ] **Step 6: Build image**

Run:

```bash
docker compose build
```

Expected: image builds without error.

- [ ] **Step 7: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore docs/deployment.md README.md
git commit -m "feat: add Docker Compose deployment"
```

---

### Task 9: Eval Runner And Demo Docs

**Files:**
- Create: `evals/questions.yml`
- Create: `evals/run_eval.py`
- Create: `docs/architecture.md`
- Create: `docs/demo.md`
- Create: `docs/sample-transcript.md`
- Modify: `README.md`

**Interfaces:**
- Produces: `uv run python evals/run_eval.py --base-url http://localhost:8000`
- Produces: sample transcript Markdown

- [ ] **Step 1: Write eval questions**

Create `evals/questions.yml`:

```yaml
questions:
  - id: profile_summary
    text: "Resume el perfil profesional de Othon."
    require_citation: true
    require_spanish: true
  - id: ai_agents
    text: "¿Qué experiencia tiene Othon construyendo agentes de IA?"
    require_citation: true
    require_spanish: true
  - id: missing_info
    text: "¿Cuál fue el presupuesto exacto del proyecto más grande de Othon?"
    require_citation: true
    require_spanish: true
    expect_missing_info: true
```

- [ ] **Step 2: Write eval runner**

Create `evals/run_eval.py`:

```python
from pathlib import Path
import argparse
import sys

import httpx
import yaml


SPANISH_MARKERS = {" el ", " la ", " de ", " que ", " experiencia ", " fuentes:"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--output", default="docs/sample-transcript.md")
    args = parser.parse_args()

    questions = yaml.safe_load(Path("evals/questions.yml").read_text(encoding="utf-8"))["questions"]
    transcript: list[str] = ["# Sample Transcript", ""]
    failures: list[str] = []
    with httpx.Client(timeout=60) as client:
        for item in questions:
            response = client.post(
                f"{args.base_url.rstrip('/')}/v1/responses",
                json={"model": "banorte-cv-agent", "input": item["text"]},
            )
            if response.status_code != 200:
                failures.append(f"{item['id']}: status {response.status_code}")
                continue
            text = response.json()["output_text"]
            transcript.extend([f"## {item['id']}", "", f"**Q:** {item['text']}", "", f"**A:** {text}", ""])
            lowered = f" {text.lower()} "
            if item.get("require_citation") and "Fuentes:" not in text:
                failures.append(f"{item['id']}: missing Fuentes citation line")
            if item.get("require_spanish") and not any(marker in lowered for marker in SPANISH_MARKERS):
                failures.append(f"{item['id']}: Spanish markers not detected")
            if item.get("expect_missing_info") and not any(phrase in lowered for phrase in ["no tengo", "no se especifica", "no aparece"]):
                failures.append(f"{item['id']}: missing-info behavior not detected")

    Path(args.output).write_text("\n".join(transcript), encoding="utf-8")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"eval passed; transcript written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Write docs**

Create `docs/architecture.md`:

```markdown
# Architecture

The Banorte CV Agent is a Dockerized FastAPI service. It exposes an Open Responses-like `/v1/responses` endpoint, searches a local Obsidian-style Markdown wiki, calls OpenAI, and returns Spanish answers with visible wiki citations.

The system separates raw sources from generated knowledge. LaTeX CV files under `wiki/raw/` can be committed. PDFs and other full documents under `wiki/raw/` are local-only. Generated Markdown pages under `wiki/sources`, `wiki/entities`, `wiki/concepts`, `wiki/projects`, `wiki/skills`, and `wiki/questions` are committed.

MVP retrieval is lexical search over Markdown. This keeps the system transparent and easy to operate for the challenge. The search module has a narrow interface so embeddings can be added after the MVP.
```

Create `docs/demo.md`:

```markdown
# Demo

## What To Show

1. `wiki/` contains generated Obsidian-style Markdown pages.
2. `POST /v1/responses` answers questions in Spanish.
3. Answers include `Fuentes:` with wiki links.
4. `/healthz`, `/readyz`, and `/metrics` show operational readiness.
5. Docker Compose runs the service without Kubernetes.

## Example Questions

- "Resume el perfil profesional de Othon."
- "¿Qué experiencia tiene Othon construyendo agentes de IA?"
- "¿Qué proyectos demuestran criterio técnico?"
- "¿Qué información no está disponible en las fuentes?"
```

Create initial `docs/sample-transcript.md`:

```markdown
# Sample Transcript

Run `uv run python evals/run_eval.py --base-url http://localhost:8000` after starting the service to refresh this transcript.
```

- [ ] **Step 4: Update README**

Add:

```markdown
## Evaluation

```bash
uv run python evals/run_eval.py --base-url http://localhost:8000
```

The eval runner checks Spanish output, visible citations, and missing-information behavior.
```

- [ ] **Step 5: Run static eval script check**

Run:

```bash
uv run python evals/run_eval.py --help
```

Expected: help text prints and exits with status 0.

- [ ] **Step 6: Commit**

```bash
git add evals docs/architecture.md docs/demo.md docs/sample-transcript.md README.md
git commit -m "feat: add eval runner and demo docs"
```

---

### Task 10: Final Verification Pass

**Files:**
- Modify: `README.md`
- Modify: `docs/deployment.md`
- Modify: `docs/demo.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified local test suite and deployable Compose app.

- [ ] **Step 1: Run full test suite**

Run:

```bash
uv run --extra dev pytest
```

Expected: PASS.

- [ ] **Step 2: Run app locally without live OpenAI call**

Run:

```bash
uv run uvicorn banorte_agent.main:app --host 127.0.0.1 --port 8000
```

Expected: server starts. In another terminal:

```bash
curl http://127.0.0.1:8000/healthz
```

Expected:

```json
{"status":"ok"}
```

- [ ] **Step 3: Run Docker build**

Run:

```bash
docker compose build
```

Expected: build completes.

- [ ] **Step 4: Run Docker health check**

Run:

```bash
docker compose up -d
curl http://127.0.0.1:8000/healthz
docker compose down
```

Expected health response:

```json
{"status":"ok"}
```

- [ ] **Step 5: Check docs for challenge completeness**

Verify README includes:

```markdown
- Open Responses-like endpoint
- Docker Compose deployment
- Wiki ingestion
- Observability endpoints
- Eval runner
- Banorte registration URL path
```

- [ ] **Step 6: Commit final docs polish**

If files changed:

```bash
git add README.md docs/deployment.md docs/demo.md .env.example
git commit -m "docs: finalize Banorte agent handoff"
```

If no files changed:

```bash
git status --short
```

Expected: no uncommitted changes.
