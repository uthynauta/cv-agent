from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
import re

from cv_agent.config import Settings
from cv_agent.knowledge.extractors import extract_source
from cv_agent.metrics import INGEST_EVENTS
from cv_agent.knowledge.openai_ingest import OpenAIWikiIngestionClient, TextClient, build_openai_wiki_pages
from cv_agent.knowledge.repository import KnowledgeRepository
from cv_agent.tracing import get_tracer


MAX_DOCUMENT_ID_BYTES = 128
_DOCUMENT_ID_DIGEST_HEX_LENGTH = 12


@dataclass(frozen=True)
class IngestResult:
    document_id: str
    source_path: Path
    source_page: Path
    generated_pages: tuple[Path, ...]
    needs_ocr: bool


class IngestionService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        settings: Settings | None = None,
        text_client: TextClient | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.text_client = text_client

    def ingest_file(self, path: Path, document_id: str) -> IngestResult:
        with get_tracer().start_as_current_span("wiki.ingest_file") as span:
            span.set_attribute("source.extension", path.suffix.lower())
            try:
                _validate_document_id(document_id)
                extracted = extract_source(path)
                span.set_attribute("source.needs_ocr", extracted.needs_ocr)
                if self._mode == "openai":
                    source_page, generated_pages = self._ingest_with_openai(path, extracted, document_id)
                else:
                    source_page = self._ingest_deterministic(path, extracted, document_id)
                    generated_pages = ()
                self._append_log(path, self._mode)
                self._write_index()
                span.set_attribute("source.page", str(source_page))
                INGEST_EVENTS.labels("success").inc()
                return IngestResult(document_id, path, source_page, tuple(generated_pages), extracted.needs_ocr)
            except Exception:
                INGEST_EVENTS.labels("error").inc()
                raise

    @property
    def _mode(self) -> str:
        return self.settings.ingestion_mode if self.settings else "deterministic"

    def _ingest_with_openai(
        self, path: Path, extracted: object, document_id: str
    ) -> tuple[Path, tuple[Path, ...]]:
        if not self.settings:
            raise ValueError("settings are required for OpenAI ingestion")
        text_client = self.text_client or OpenAIWikiIngestionClient(self.settings)
        pages = build_openai_wiki_pages(self.settings, path, extracted, text_client, document_id)
        summary = ""
        generated_pages: list[Path] = []
        for page in pages:
            relative_path = str(page["path"])
            if relative_path.startswith("sources/"):
                summary = str(page["body"])
                continue
            generated_pages.append(
                self.repository.write_page(
                    relative_path,
                    str(page["title"]),
                    dict(page["metadata"]),
                    str(page["body"]),
                )
            )
        source_page = self._write_source_page(path, extracted, document_id, summary)
        return source_page, tuple(generated_pages)

    def _ingest_deterministic(self, path: Path, extracted: object, document_id: str) -> Path:
        return self._write_source_page(path, extracted, document_id)

    def _write_source_page(
        self,
        path: Path,
        extracted: object,
        document_id: str,
        summary: str = "",
    ) -> Path:
        metadata = {
            "kind": "source",
            "document_id": document_id,
            "original_filename": path.name,
            "media_type": _media_type(extracted.kind),
            "uploaded_at": datetime.now(UTC).isoformat(),
            "content_sha256": extracted.sha256,
            "extractor_version": "1",
            "needs_ocr": extracted.needs_ocr,
            "tags": ["source", extracted.kind],
        }
        body = _source_page_body(path, extracted.text, summary)
        return self.repository.write_page(f"sources/{document_id}.md", path.stem, metadata, body)

    def ingest_directory(self, root: Path) -> list[IngestResult]:
        results: list[IngestResult] = []
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() in {".tex", ".pdf", ".md"}:
                results.append(self.ingest_file(path, document_id_for_path(path, root)))
        return results

    def _append_log(self, path: Path, mode: str) -> None:
        log_path = self.repository.resolve_write_path("knowledge/log.md")
        if not log_path.exists():
            self.repository.write_text("knowledge/log.md", "# Wiki Log\n")
        today = datetime.now(UTC).date().isoformat()
        self.repository.write_text(
            "knowledge/log.md",
            f"\n## [{today}] ingest | {path.name}\n\n- Source: `{path}`\n- mode: {mode}\n",
            append=True,
        )

    def _write_index(self) -> None:
        lines = ["# Wiki Index", ""]
        for page in self.repository.list_pages():
            relative_page = page.path.relative_to(self.repository.root)
            if relative_page.as_posix() in {"knowledge/index.md", "knowledge/log.md"}:
                continue
            relative = relative_page.with_suffix("")
            kind = str(page.metadata.get("kind", "page"))
            tags = page.metadata.get("tags", [])
            tag_text = ", ".join(map(str, tags)) if isinstance(tags, list) else str(tags)
            summary = _one_line_summary(page.body)
            lines.append(
                f"- [[{relative.as_posix()}|{page.title}]] — kind: {kind}; tags: {tag_text}; {summary}"
            )
        self.repository.write_text("knowledge/index.md", "\n".join(lines).rstrip() + "\n")


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value or "source"


def _source_page_body(path: Path, text: str, summary: str = "") -> str:
    extracted = _normalize_extracted_text(text) or "No selectable text extracted."
    parts = [f"# {path.stem}"]
    if summary.strip():
        parts.extend(["", "## LLM Summary", "", summary.strip()])
    parts.extend(["", "## Extracted Text", "", extracted])
    return "\n".join(parts)


def _normalize_extracted_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()


def _media_type(kind: str) -> str:
    return {
        "pdf": "application/pdf",
        "markdown": "text/markdown",
        "latex": "application/x-tex",
    }.get(kind, "application/octet-stream")


def _validate_document_id(document_id: str) -> None:
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-empty path-safe identifier")
    if len(document_id.encode("utf-8")) > MAX_DOCUMENT_ID_BYTES:
        raise ValueError(f"document_id length exceeds {MAX_DOCUMENT_ID_BYTES} bytes")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", document_id):
        raise ValueError("document_id must contain only ASCII letters, digits, '.', '_' or '-'")
    if document_id.lower().endswith(".md"):
        raise ValueError("document_id must not end with .md")


def document_id_for_path(path: Path, declared_root: Path | None = None) -> str:
    """Derive a collision-resistant ID for legacy directory/caller flows."""
    candidate = _slugify(path.stem)
    if declared_root is None:
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        path_digest = digest.hexdigest()[:_DOCUMENT_ID_DIGEST_HEX_LENGTH]
    else:
        identity = path.relative_to(declared_root).as_posix().encode("utf-8")
        path_digest = sha256(identity).hexdigest()[:_DOCUMENT_ID_DIGEST_HEX_LENGTH]
    prefix_budget = MAX_DOCUMENT_ID_BYTES - _DOCUMENT_ID_DIGEST_HEX_LENGTH - 1
    prefix = candidate[:prefix_budget].rstrip("._-") or "source"
    return f"{prefix}-{path_digest}"


def _one_line_summary(body: str) -> str:
    for raw_line in body.splitlines():
        line = raw_line.strip().lstrip("- ").strip()
        if not line or line.startswith("#"):
            continue
        return re.sub(r"\s+", " ", line)[:180]
    return "No summary available."
