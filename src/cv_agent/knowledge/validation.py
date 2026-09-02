from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from typing import Any

from cv_agent.knowledge.frontmatter import load_frontmatter
from cv_agent.knowledge.repository import (
    MAX_PATH_DEPTH,
    MAX_PATH_COMPONENT_BYTES,
    MAX_RELATIVE_PATH_BYTES,
    resolve_directory_path,
)


MAX_DOCUMENT_ID_BYTES = 128
_DOCUMENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_EXTRACTED_HEADING_RE = re.compile(r"(?m)^[ \t]*##[ \t]+Extracted Text[ \t]*$")
_NEXT_HEADING_RE = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]+\S.*$")
_SOURCE_LINK_RE = re.compile(r"\[\[([^\]\r\n]+)\]\]")
_PLACEHOLDERS = {
    "no extracted text",
    "no selectable text extracted",
    "no text extracted",
    "no text",
    "none",
    "null",
    "n a",
    "placeholder",
    "tbd",
    "todo",
    "unknown",
}


class KnowledgeValidationError(ValueError):
    """Raised when a staged knowledge tree is not safe or internally valid."""


@dataclass(frozen=True)
class _Page:
    relative_path: str
    metadata: dict[str, Any]
    body: str


def validate_knowledge(root: str | Path) -> None:
    """Validate a staged local ``sources``/``knowledge`` Markdown tree."""

    try:
        candidate = Path(root).expanduser()
        lexical_root = resolve_directory_path(candidate)
    except (OSError, TypeError, ValueError):
        _fail("root", "path", "is unsafe")
    if not lexical_root.exists() or not lexical_root.is_dir():
        _fail("root", "path", "is not a directory")

    pages = _read_pages(lexical_root)
    source_pages = [page for page in pages if page.relative_path.startswith("sources/")]
    generated_pages = [
        page
        for page in pages
        if page.relative_path.startswith("knowledge/")
        and page.relative_path not in {"knowledge/index.md", "knowledge/log.md"}
    ]

    source_ids: set[str] = set()
    for page in source_pages:
        _validate_source_page(page, source_ids)
    for page in generated_pages:
        _validate_generated_page(page, source_ids)


def _read_pages(root: Path) -> list[_Page]:
    pages: list[_Page] = []
    pending: list[tuple[Path, tuple[str, ...]]] = [(root, ())]
    while pending:
        directory, prefix = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError:
            _fail(_relative(prefix), "path", "cannot be inspected")
        for entry in entries:
            relative_parts = prefix + (entry.name,)
            relative = _relative(relative_parts)
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError:
                _fail(relative, "path", "cannot be inspected")
            if stat.S_ISLNK(mode):
                _fail(relative, "path", "uses a symlink")
            if stat.S_ISDIR(mode):
                if len(relative_parts) == 1 and entry.name not in {"sources", "knowledge"}:
                    _fail(relative, "path", "is outside the knowledge scopes")
                if relative_parts[0] not in {"sources", "knowledge"}:
                    _fail(relative, "path", "is outside the knowledge scopes")
                pending.append((Path(entry.path), relative_parts))
                continue
            if not stat.S_ISREG(mode):
                _fail(relative, "path", "is not a regular file")
            if relative_parts[0] not in {"sources", "knowledge"}:
                _fail(relative, "path", "is outside the knowledge scopes")
            if not entry.name.endswith(".md"):
                _fail(relative, "path", "must be Markdown")
            if relative_parts[0] == "sources" and len(relative_parts) != 2:
                _fail(relative, "path", "source pages must be direct children")
            try:
                _validate_path_limits(relative)
                metadata, body = _load_page(entry.path)
            except KnowledgeValidationError:
                raise
            except Exception:
                _fail(relative, "frontmatter", "is invalid")
            pages.append(_Page(relative, metadata, body))
    return pages


def _load_page(path: str) -> tuple[dict[str, Any], str]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            return load_frontmatter(handle.read())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _validate_source_page(page: _Page, source_ids: set[str]) -> None:
    metadata = page.metadata
    if metadata.get("kind") != "source":
        _fail(page.relative_path, "kind", "must be source")
    document_id = metadata.get("document_id")
    if not _is_safe_document_id(document_id):
        _fail(page.relative_path, "document_id", "is invalid")
    assert isinstance(document_id, str)
    filename_id = Path(page.relative_path).stem
    if filename_id != document_id:
        _fail(page.relative_path, "document_id", "does not match the source path")
    if document_id in source_ids:
        _fail(page.relative_path, "document_id", "is duplicated")
    source_ids.add(document_id)

    digest = metadata.get("content_sha256")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        _fail(page.relative_path, "content_sha256", "must be lowercase SHA-256")
    if not _has_meaningful_extracted_text(page.body):
        _fail(page.relative_path, "extracted_text", "is missing or not meaningful")


def _validate_generated_page(page: _Page, source_ids: set[str]) -> None:
    found = False
    for match in _SOURCE_LINK_RE.finditer(page.body):
        raw_target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        if not _looks_like_source_reference(raw_target):
            continue
        if not re.fullmatch(r"sources/[A-Za-z0-9][A-Za-z0-9._-]*\Z", raw_target):
            _fail(page.relative_path, "source_citations", "contains a malformed source reference")
        document_id = raw_target.removeprefix("sources/")
        if document_id.endswith(".md") or document_id not in source_ids:
            _fail(page.relative_path, "source_citations", "contains an unknown source reference")
        found = True
    if not found:
        _fail(page.relative_path, "source_citations", "must cite a source page")


def _looks_like_source_reference(target: str) -> bool:
    return target == "sources" or "sources/" in target


def _has_meaningful_extracted_text(body: str) -> bool:
    heading = _EXTRACTED_HEADING_RE.search(body)
    if heading is None:
        return False
    section = body[heading.end() :]
    next_heading = _NEXT_HEADING_RE.search(section)
    if next_heading is not None:
        section = section[: next_heading.start()]
    section = re.sub(r"<!--.*?-->", " ", section, flags=re.DOTALL)
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    lines = [line for line in lines if not re.match(r"^#{1,6}(?:\s|$)", line)]
    if not lines:
        return False
    normalized = re.sub(r"[^0-9a-z]+", " ", " ".join(lines).casefold()).strip()
    if normalized in _PLACEHOLDERS:
        return False
    return re.search(r"\w", normalized, flags=re.UNICODE) is not None


def _is_safe_document_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value.encode("utf-8")) <= MAX_DOCUMENT_ID_BYTES
        and _DOCUMENT_ID_RE.fullmatch(value) is not None
        and not value.lower().endswith(".md")
    )


def _validate_path_limits(relative: str) -> None:
    encoded_length = len(relative.encode("utf-8"))
    candidate = Path(relative)
    if encoded_length > MAX_RELATIVE_PATH_BYTES:
        _fail(relative, "path", "exceeds the size limit")
    if len(candidate.parts) > MAX_PATH_DEPTH:
        _fail(relative, "path", "exceeds the depth limit")
    if any(len(part.encode("utf-8")) > MAX_PATH_COMPONENT_BYTES for part in candidate.parts):
        _fail(relative, "path", "contains an oversized component")
    if "\\" in relative or ".." in candidate.parts:
        _fail(relative, "path", "is unsafe")


def _relative(parts: tuple[str, ...]) -> str:
    return "/".join(parts) or "root"


def _fail(path: str, field: str, reason: str) -> None:
    bounded_path = path[:240]
    raise KnowledgeValidationError(f"{bounded_path}: {field} {reason}")
