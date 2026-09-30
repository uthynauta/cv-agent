from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

from cv_agent.knowledge.repository import resolve_directory_path


SUPPORTED_UPLOAD_EXTENSIONS = {".pdf", ".md", ".tex"}
SUPPORTED_UPLOAD_EXTENSIONS_MESSAGE = "only .pdf, .md, and .tex uploads are supported"


def _normalize_data_root(root: str | Path) -> Path:
    if not isinstance(root, (str, Path)):
        raise ValueError("data root must be a nonblank path")
    normalized = str(root).strip()
    candidate = Path(normalized).expanduser()
    resolved = candidate.resolve()
    if (
        not normalized
        or candidate == Path(".")
        or resolved == Path.cwd().resolve()
        or resolved == Path(resolved.anchor)
    ):
        raise ValueError("data root must be a nonblank path other than '.'")
    return candidate


@dataclass(frozen=True)
class DataPaths:
    root: Path
    documents: Path
    quarantine: Path
    repository: Path
    sources: Path
    knowledge: Path
    backups: Path
    staging: Path
    locks: Path

    @classmethod
    def from_root(cls, root: str | Path) -> "DataPaths":
        resolved = _normalize_data_root(root).expanduser().resolve()
        repository = resolved / "repository"
        return cls(
            root=resolved,
            documents=resolved / "documents",
            quarantine=resolved / "documents" / "quarantine",
            repository=repository,
            sources=repository / "sources",
            knowledge=repository / "knowledge",
            backups=resolved / "backups",
            staging=resolved / "staging",
            locks=resolved / "locks",
        )


def ensure_data_storage(root: str | Path) -> DataPaths:
    # Validate the lexical mount path before resolving it.  Path.resolve() would
    # otherwise hide a pre-existing symlink and let mkdir operate outside DATA_DIR.
    resolve_directory_path(Path(root).expanduser())
    paths = DataPaths.from_root(root)
    for directory in (
        paths.documents,
        paths.quarantine,
        paths.sources,
        paths.knowledge,
        paths.backups,
        paths.staging,
        paths.locks,
    ):
        resolve_directory_path(directory, create=True)
    return paths


def safe_upload_filename(filename: str) -> str:
    name = Path(filename).name
    if not name or name in {".", ".."}:
        raise ValueError("filename is required")
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise ValueError(SUPPORTED_UPLOAD_EXTENSIONS_MESSAGE)

    stem = Path(name).stem
    normalized = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized)
    normalized = re.sub(r"[-_.]{2,}", "-", normalized).strip("-_.")
    normalized = re.sub(r"^[A-Za-z]{1,2}-", "", normalized)
    if not normalized:
        raise ValueError("filename must contain letters or numbers")
    return f"{normalized}{suffix}"
