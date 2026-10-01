"""Resolve cited wiki titles to verified originals from one knowledge revision."""

import re

from cv_agent.knowledge.documents import KnowledgePage
from cv_agent.knowledge.public_pdfs import ProcessedPdfCatalog


_CITATION_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
_SOURCES_LABEL_RE = re.compile(
    r"^(?:\*{1,2}\s*)?(?:Fuentes|Sources)(?:\s*\*{1,2}\s*)?:(?:\*{1,2})?"
)
_SOURCE_REFERENCE_RE = re.compile(r"\[\[([^\]\r\n]+)\]\]")


def resolve_source_documents(
    answer: str, pages: list[KnowledgePage], catalog: ProcessedPdfCatalog
) -> list[dict[str, object]]:
    lines = [line.strip() for line in answer.splitlines() if line.strip()]
    if not lines:
        return []
    label = _SOURCES_LABEL_RE.match(lines[-1])
    if label is None:
        return []
    titles = dict.fromkeys(_CITATION_RE.findall(lines[-1][label.end():]))
    pages_by_title: dict[str, list[KnowledgePage]] = {}
    for page in pages:
        pages_by_title.setdefault(page.title, []).append(page)

    descriptions: dict[str, dict[str, str] | None] = {}
    result: list[dict[str, object]] = []
    for title in titles:
        documents: list[dict[str, str]] = []
        matches = pages_by_title.get(title, [])
        if len(matches) == 1:
            page = matches[0]
            if page.metadata.get("kind") == "source":
                document_id = page.metadata.get("document_id")
                document_ids = (
                    [document_id]
                    if isinstance(document_id, str)
                    and page.path == catalog.paths.sources / f"{document_id}.md"
                    else []
                )
            else:
                document_ids = []
                for reference in _SOURCE_REFERENCE_RE.findall(page.body):
                    target = reference.split("|", 1)[0].split("#", 1)[0].strip()
                    if re.fullmatch(r"sources/[A-Za-z0-9][A-Za-z0-9._-]*", target):
                        document_ids.append(target.removeprefix("sources/"))
            for document_id in dict.fromkeys(document_ids):
                if document_id not in descriptions:
                    descriptions[document_id] = catalog.describe_pdf(document_id, pages)
                description = descriptions[document_id]
                if description is not None:
                    documents.append(dict(description))
        result.append({"title": title, "documents": documents})
    return result
