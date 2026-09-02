from __future__ import annotations

from dataclasses import dataclass
import errno
import html
import os
from pathlib import Path
import re
import stat
from typing import Any
import unicodedata

from cv_agent.knowledge.frontmatter import load_frontmatter
from cv_agent.knowledge.repository import (
    MAX_PATH_DEPTH,
    MAX_PATH_COMPONENT_BYTES,
    MAX_RELATIVE_PATH_BYTES,
)


MAX_DOCUMENT_ID_BYTES = 128
_DOCUMENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_EXTRACTED_HEADING_RE = re.compile(r"(?m)^[ \t]*##[ \t]+Extracted Text[ \t]*$")
_SOURCE_LINK_RE = re.compile(r"\[\[([^\]\r\n]+)\]\]")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_TAG_RE = re.compile(
    r"</?(?:a|abbr|article|aside|b|blockquote|br|code|div|em|figcaption|figure|footer|"
    r"h[1-6]|header|hr|i|li|main|nav|ol|p|pre|section|small|span|strong|sub|sup|"
    r"table|tbody|td|th|thead|tr|ul)(?:\s+[^<>]*)?/?>",
    re.IGNORECASE,
)
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
MAX_VALIDATION_ENTRIES = 10_000
MAX_VALIDATION_PAGES = 8_000
MAX_VALIDATION_DIRECTORIES = 2_000
MAX_MARKDOWN_BYTES = 16 * 1024 * 1024
MAX_TOTAL_MARKDOWN_BYTES = 128 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024


class KnowledgeValidationError(ValueError):
    """Raised when a staged knowledge tree is not safe or internally valid."""


@dataclass(frozen=True)
class _Page:
    relative_path: str
    metadata: dict[str, Any]
    body: str


@dataclass
class _ValidationBudget:
    entries: int = 0
    pages: int = 0
    directories: int = 0
    markdown_bytes: int = 0


def validate_knowledge(root: str | Path) -> None:
    """Validate a staged local ``sources``/``knowledge`` Markdown tree."""

    try:
        candidate = Path(root).expanduser()
        lexical_root = candidate.absolute()
        root_fd = _open_directory_path(lexical_root)
    except (OSError, TypeError, ValueError, KnowledgeValidationError):
        _fail("root", "path", "is unsafe")

    pages = _read_pages(root_fd)
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


def _read_pages(root_fd: int) -> list[_Page]:
    pages: list[_Page] = []
    budget = _ValidationBudget()
    try:
        _read_directory(root_fd, (), pages, budget)
    finally:
        try:
            os.close(root_fd)
        except OSError:
            pass
    return pages


def _read_directory(
    directory_fd: int,
    prefix: tuple[str, ...],
    pages: list[_Page],
    budget: _ValidationBudget,
) -> None:
    try:
        with os.scandir(directory_fd) as scanner:
            entries = sorted(scanner, key=lambda entry: entry.name)
    except OSError:
        _fail(_relative(prefix), "path", "cannot be inspected")
    for entry in entries:
        relative_parts = prefix + (entry.name,)
        relative = _relative(relative_parts)
        _validate_path_limits(relative)
        budget.entries += 1
        if budget.entries > MAX_VALIDATION_ENTRIES:
            _fail(relative, "resource", "entry limit exceeded")
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
            budget.directories += 1
            if budget.directories > MAX_VALIDATION_DIRECTORIES:
                _fail(relative, "resource", "directory limit exceeded")
            child_fd = _open_directory_at(directory_fd, entry.name, relative)
            try:
                _read_directory(child_fd, relative_parts, pages, budget)
            finally:
                try:
                    os.close(child_fd)
                except OSError:
                    pass
            continue
        if not stat.S_ISREG(mode):
            _fail(relative, "path", "is not a regular file")
        if relative_parts[0] not in {"sources", "knowledge"}:
            _fail(relative, "path", "is outside the knowledge scopes")
        if not entry.name.endswith(".md"):
            _fail(relative, "path", "must be Markdown")
        if relative_parts[0] == "sources" and len(relative_parts) != 2:
            _fail(relative, "path", "source pages must be direct children")
        budget.pages += 1
        if budget.pages > MAX_VALIDATION_PAGES:
            _fail(relative, "resource", "page limit exceeded")
        raw_text = _load_page(directory_fd, entry.name, relative)
        budget.markdown_bytes += len(raw_text)
        if budget.markdown_bytes > MAX_TOTAL_MARKDOWN_BYTES:
            _fail(relative, "resource", "total Markdown size exceeded")
        try:
            metadata, body = load_frontmatter(raw_text.decode("utf-8"))
        except Exception:
            _fail(relative, "frontmatter", "is invalid")
        pages.append(_Page(relative, metadata, body))


def _directory_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _open_directory_path(path: Path) -> int:
    if path.anchor != "/" or ".." in path.parts:
        raise KnowledgeValidationError("root: path is unsafe")
    current = os.open("/", _directory_flags())
    try:
        for component in path.parts[1:]:
            child = _open_directory_at(current, component, "root")
            os.close(current)
            current = child
        return current
    except Exception:
        try:
            os.close(current)
        except OSError:
            pass
        raise


def _open_directory_at(parent_fd: int, name: str, relative: str) -> int:
    try:
        descriptor = os.open(name, _directory_flags(), dir_fd=parent_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            _fail(relative, "path", "uses a symlink")
        _fail(relative, "path", "is not a local directory")
    try:
        mode = os.fstat(descriptor).st_mode
    except OSError:
        os.close(descriptor)
        _fail(relative, "path", "cannot be inspected")
    if not stat.S_ISDIR(mode):
        os.close(descriptor)
        _fail(relative, "path", "is not a local directory")
    return descriptor


def _load_page(directory_fd: int, name: str, relative: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            _fail(relative, "path", "uses a symlink")
        _fail(relative, "path", "cannot be opened")
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            _fail(relative, "path", "is not a regular file")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            data = bytearray()
            while len(data) <= MAX_MARKDOWN_BYTES:
                chunk = handle.read(min(_READ_CHUNK_BYTES, MAX_MARKDOWN_BYTES + 1 - len(data)))
                if not chunk:
                    return bytes(data)
                data.extend(chunk)
            _fail(relative, "resource", "Markdown size exceeded")
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
    for _ in range(3):
        cleaned = _HTML_COMMENT_RE.sub(" ", section)
        cleaned = _HTML_TAG_RE.sub(" ", cleaned)
        decoded = html.unescape(cleaned)
        section = decoded
        if decoded == cleaned:
            break
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    lines = [line for line in lines if not re.match(r"^#{1,6}(?:\s|$)", line)]
    if not lines:
        return False
    evidence = " ".join(lines)
    evidence = "".join(" " if char.isspace() else char for char in evidence)
    normalized = unicodedata.normalize("NFKD", evidence).casefold()
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).strip()
    if normalized in _PLACEHOLDERS:
        return False
    return any(char.isalnum() for char in evidence)


def _is_safe_document_id(value: object) -> bool:
    if not isinstance(value, str) or not bool(value.strip()):
        return False
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return False
    return (
        encoded_length <= MAX_DOCUMENT_ID_BYTES
        and _DOCUMENT_ID_RE.fullmatch(value) is not None
        and not value.lower().endswith(".md")
    )


def _validate_path_limits(relative: str) -> None:
    try:
        encoded_length = len(relative.encode("utf-8"))
        candidate = Path(relative)
        component_lengths = [len(part.encode("utf-8")) for part in candidate.parts]
    except (UnicodeError, ValueError):
        _fail(relative, "path", "contains invalid characters")
    if encoded_length > MAX_RELATIVE_PATH_BYTES:
        _fail(relative, "path", "exceeds the size limit")
    if len(candidate.parts) > MAX_PATH_DEPTH:
        _fail(relative, "path", "exceeds the depth limit")
    if any(length > MAX_PATH_COMPONENT_BYTES for length in component_lengths):
        _fail(relative, "path", "contains an oversized component")
    if "\\" in relative or ".." in candidate.parts:
        _fail(relative, "path", "is unsafe")


def _relative(parts: tuple[str, ...]) -> str:
    return "/".join(parts) or "root"


def _fail(path: str, field: str, reason: str) -> None:
    try:
        bounded_path = path.encode("utf-8", "backslashreplace").decode("utf-8")[:220]
    except (UnicodeError, AttributeError):
        bounded_path = repr(path)[:220]
    raise KnowledgeValidationError(f"{bounded_path}: {field} {reason}") from None
