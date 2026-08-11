from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re

from banorte_agent.config import Settings
from banorte_agent.wiki.extractors import extract_source
from banorte_agent.metrics import INGEST_EVENTS
from banorte_agent.wiki.openai_ingest import OpenAIWikiIngestionClient, TextClient, build_openai_wiki_pages
from banorte_agent.wiki.repository import WikiRepository
from banorte_agent.tracing import get_tracer


@dataclass(frozen=True)
class IngestResult:
    source_path: Path
    source_page: Path
    needs_ocr: bool


class IngestionService:
    def __init__(
        self,
        repository: WikiRepository,
        settings: Settings | None = None,
        text_client: TextClient | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.text_client = text_client

    def ingest_file(self, path: Path) -> IngestResult:
        with get_tracer().start_as_current_span("wiki.ingest_file") as span:
            span.set_attribute("source.extension", path.suffix.lower())
            try:
                extracted = extract_source(path)
                span.set_attribute("source.needs_ocr", extracted.needs_ocr)
                slug = _slugify(path.stem)
                if self._mode == "openai":
                    source_page = self._ingest_with_openai(path, extracted, slug)
                else:
                    source_page = self._ingest_deterministic(path, extracted, slug)
                self._append_log(path, self._mode)
                self._write_index()
                span.set_attribute("source.page", str(source_page))
                INGEST_EVENTS.labels("success").inc()
                return IngestResult(path, source_page, extracted.needs_ocr)
            except Exception:
                INGEST_EVENTS.labels("error").inc()
                raise

    def _source_reference(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.repository.root.resolve()))
        except ValueError:
            return path.name

    @property
    def _mode(self) -> str:
        return self.settings.ingestion_mode if self.settings else "deterministic"

    def _ingest_with_openai(self, path: Path, extracted: object, slug: str) -> Path:
        if not self.settings:
            raise ValueError("settings are required for OpenAI ingestion")
        text_client = self.text_client or OpenAIWikiIngestionClient(self.settings)
        pages = build_openai_wiki_pages(self.settings, path, extracted, text_client)
        source_page: Path | None = None
        for page in pages:
            relative_path = str(page["path"])
            metadata = dict(page["metadata"])
            if relative_path.startswith("sources/"):
                relative_path = f"sources/{slug}.md"
                metadata = {
                    "kind": "source",
                    "source_file": self._source_reference(path),
                    "source_type": extracted.kind,
                    "sha256": extracted.sha256,
                    "needs_ocr": extracted.needs_ocr,
                    "content_policy": "full_text" if extracted.kind == "latex" else "snippet_only",
                    "extracted_characters": len(extracted.text),
                    "ingested_at": datetime.now(UTC).date().isoformat(),
                    **metadata,
                }
            written = self.repository.write_page(
                relative_path,
                str(page["title"]),
                metadata,
                str(page["body"]),
            )
            if written.parent.name == "sources" and source_page is None:
                source_page = written
        return source_page or self.repository.root / "sources" / f"{slug}.md"

    def _ingest_deterministic(self, path: Path, extracted: object, slug: str) -> Path:
        metadata = {
            "kind": "source",
            "source_file": self._source_reference(path),
            "source_type": extracted.kind,
            "sha256": extracted.sha256,
            "needs_ocr": extracted.needs_ocr,
            "content_policy": "full_text" if extracted.kind == "latex" else "snippet_only",
            "extracted_characters": len(extracted.text),
            "ingested_at": datetime.now(UTC).date().isoformat(),
            "tags": ["source", extracted.kind],
        }
        body = _source_page_body(path, extracted.kind, extracted.text)
        return self.repository.write_page(f"sources/{slug}.md", path.stem, metadata, body)

    def ingest_directory(self, root: Path) -> list[IngestResult]:
        results: list[IngestResult] = []
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() in {".tex", ".pdf", ".md"}:
                results.append(self.ingest_file(path))
        return results

    def _append_log(self, path: Path, mode: str) -> None:
        log_path = self.repository.root / "log.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not log_path.exists():
            log_path.write_text("# Wiki Log\n", encoding="utf-8")
        today = datetime.now(UTC).date().isoformat()
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## [{today}] ingest | {path.name}\n\n- Source: `{path}`\n- mode: {mode}\n")

    def _write_index(self) -> None:
        index_path = self.repository.root / "index.md"
        lines = ["# Wiki Index", ""]
        for page in self.repository.list_pages():
            relative = page.path.relative_to(self.repository.root).with_suffix("")
            if page.path.name in {"index.md", "log.md"}:
                continue
            lines.append(f"- [[{relative.as_posix()}|{page.title}]]")
        index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value or "source"


def _source_page_body(path: Path, kind: str, text: str) -> str:
    extracted = text.strip() or "No selectable text extracted."
    parts = [f"# {path.stem}", "", "## Summary", ""]
    if kind == "latex":
        parts.extend([extracted[:2000].rstrip(), "", "## Extracted Text", "", extracted])
    else:
        snippet = re.sub(r"\s+", " ", extracted)[:600].strip()
        parts.extend(
            [
                snippet,
                "",
                "Full extracted text is intentionally omitted for non-LaTeX sources.",
            ]
        )
    return "\n".join(parts)
