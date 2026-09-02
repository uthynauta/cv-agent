from __future__ import annotations

from dataclasses import dataclass
import errno
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
    pending: list[tuple[int, tuple[str, ...]]] = [(root_fd, ())]
    open_fds = {root_fd}
    try:
        while pending:
            directory_fd, prefix = pending.pop()
            try:
                with os.scandir(directory_fd) as scanner:
                    entries = sorted(scanner, key=lambda entry: entry.name)
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
                    child_fd = _open_directory_at(directory_fd, entry.name, relative)
                    open_fds.add(child_fd)
                    pending.append((child_fd, relative_parts))
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
                    metadata, body = _load_page(directory_fd, entry.name, relative)
                except KnowledgeValidationError:
                    raise
                except Exception:
                    _fail(relative, "frontmatter", "is invalid")
                pages.append(_Page(relative, metadata, body))
    finally:
        for descriptor in open_fds:
            try:
                os.close(descriptor)
            except OSError:
                pass
    return pages


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


def _load_page(directory_fd: int, name: str, relative: str) -> tuple[dict[str, Any], str]:
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
    normalized = unicodedata.normalize("NFKD", " ".join(lines)).casefold()
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).strip()
    if normalized in _PLACEHOLDERS:
        return False
    return any(char.isalnum() for char in " ".join(lines))


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
