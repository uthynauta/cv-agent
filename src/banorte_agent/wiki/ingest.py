from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re

from banorte_agent.wiki.extractors import extract_source
from banorte_agent.metrics import INGEST_EVENTS
from banorte_agent.wiki.repository import WikiRepository
from banorte_agent.tracing import get_tracer


@dataclass(frozen=True)
class IngestResult:
    source_path: Path
    source_page: Path
    needs_ocr: bool


class IngestionService:
    def __init__(self, repository: WikiRepository) -> None:
        self.repository = repository

    def ingest_file(self, path: Path) -> IngestResult:
        with get_tracer().start_as_current_span("wiki.ingest_file") as span:
            span.set_attribute("source.extension", path.suffix.lower())
            try:
                extracted = extract_source(path)
                span.set_attribute("source.needs_ocr", extracted.needs_ocr)
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
                span.set_attribute("source.page", str(source_page))
                INGEST_EVENTS.labels("success").inc()
                return IngestResult(path, source_page, extracted.needs_ocr)
            except Exception:
                INGEST_EVENTS.labels("error").inc()
                raise

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
