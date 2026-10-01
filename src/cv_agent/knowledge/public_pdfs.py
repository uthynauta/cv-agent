from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
from typing import BinaryIO

from cv_agent.knowledge.documents import KnowledgePage
from cv_agent.knowledge.index import ActiveKnowledge
from cv_agent.knowledge.ingest import validate_document_id
from cv_agent.knowledge.storage import DataPaths, safe_upload_filename
from cv_agent.knowledge.validation import _has_meaningful_extracted_text, _open_directory_path


_CHUNK_BYTES = 64 * 1024


@dataclass
class VerifiedPdf:
    """Own the descriptor whose bytes were checked against the processed source."""

    handle: BinaryIO
    filename: str

    def close(self) -> None:
        self.handle.close()

    def iter_bytes(self) -> Iterator[bytes]:
        try:
            while chunk := self.handle.read(_CHUNK_BYTES):
                yield chunk
        finally:
            self.close()


class ProcessedPdfCatalog:
    def __init__(self, paths: DataPaths, active: ActiveKnowledge) -> None:
        self.paths = paths
        self.active = active

    def open_pdf(self, document_id: str) -> VerifiedPdf | None:
        return self._open_pdf(document_id, self.active.list_pages())

    def describe_pdf(
        self, document_id: str, pages: list[KnowledgePage]
    ) -> dict[str, str] | None:
        verified = self._open_pdf(document_id, pages)
        if verified is None:
            return None
        try:
            return {
                "filename": verified.filename,
                "path": f"/v1/documents/{document_id}/original",
            }
        finally:
            verified.close()

    def _open_pdf(
        self, document_id: str, pages: list[KnowledgePage]
    ) -> VerifiedPdf | None:
        try:
            validate_document_id(document_id)
        except (ValueError, UnicodeError):
            return None
        canonical = self.paths.sources / f"{document_id}.md"
        sources = [page for page in pages if page.path == canonical]
        if len(sources) != 1:
            return None
        page = sources[0]
        metadata = page.metadata
        filename = metadata.get("original_filename")
        digest = metadata.get("content_sha256")
        if (
            metadata.get("kind") != "source"
            or metadata.get("document_id") != document_id
            or not isinstance(filename, str)
            or Path(filename).suffix.lower() != ".pdf"
            or metadata.get("media_type") not in (None, "application/pdf")
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not _has_meaningful_extracted_text(page.body)
        ):
            return None
        try:
            safe_filename = safe_upload_filename(filename)
        except ValueError:
            safe_filename = "document.pdf"
        safe_filename = f"{Path(safe_filename).stem[:180]}.pdf"

        directory_fd = None
        descriptor = None
        handle = None
        try:
            # Pin each directory component with O_NOFOLLOW, then open the exact
            # canonical filename relative to that directory descriptor.
            directory_fd = _open_directory_path(self.paths.documents)
            descriptor = os.open(
                f"{document_id}.pdf",
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                return None
            handle = os.fdopen(descriptor, "rb")
            descriptor = None
            signature = handle.read(5)
            if signature != b"%PDF-":
                return None
            actual_digest = sha256(signature)
            while chunk := handle.read(_CHUNK_BYTES):
                actual_digest.update(chunk)
            after = os.fstat(handle.fileno())
            if (
                actual_digest.hexdigest() != digest
                or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            ):
                return None
            handle.seek(0)
            verified = VerifiedPdf(handle, safe_filename)
            handle = None
            return verified
        except (OSError, ValueError):
            return None
        finally:
            if handle is not None:
                handle.close()
            if descriptor is not None:
                os.close(descriptor)
            if directory_fd is not None:
                os.close(directory_fd)
