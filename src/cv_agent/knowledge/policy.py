from pathlib import Path
import re
from collections.abc import Iterable

from cv_agent.knowledge.documents import KnowledgePage


def has_usable_evidence(body: str) -> bool:
    """Ignore Markdown structure and extractor placeholders when checking content."""
    placeholders = {
        "no selectable text extracted",
        "no text extracted",
        "ocr required",
    }
    evidence_lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        normalized = re.sub(r"[^\w\s]", " ", stripped, flags=re.UNICODE)
        normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
        if not normalized or normalized in placeholders:
            continue
        evidence_lines.append(normalized)
    return bool(re.search(r"[^\W_]{2,}", " ".join(evidence_lines), flags=re.UNICODE))


def has_initialized_knowledge(
    pages: Iterable[KnowledgePage], repository_root: Path | None = None
) -> bool:
    for page in pages:
        relative = page.path
        if repository_root is not None:
            try:
                relative = page.path.resolve().relative_to(repository_root.resolve())
            except (OSError, ValueError):
                pass
        if relative.as_posix() in {"knowledge/index.md", "knowledge/log.md"}:
            continue
        if relative.parts and relative.parts[0] in {"sources", "knowledge"}:
            if has_usable_evidence(page.body):
                return True
    return False
