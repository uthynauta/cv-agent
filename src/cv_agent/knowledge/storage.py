from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import unicodedata


SUPPORTED_UPLOAD_EXTENSIONS = {".pdf", ".md", ".tex"}
SUPPORTED_UPLOAD_EXTENSIONS_MESSAGE = "only .pdf, .md, and .tex uploads are supported"


def _normalize_data_root(root: str | Path) -> Path:
    if not isinstance(root, (str, Path)):
        raise ValueError("data root must be a nonblank path")
    normalized = str(root).strip()
    candidate = Path(normalized).expanduser()
    resolved = candidate.resolve()
    if not normalized or candidate == Path(".") or resolved == Path(resolved.anchor):
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
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def upload_directory(wiki_dir: str | Path) -> Path:
    return Path(wiki_dir) / "raw" / "uploads"


def ensure_wiki_storage(wiki_dir: str | Path, bundled_wiki_dir: str | Path | None = None) -> None:
    wiki_path = Path(wiki_dir)
    bundled_path = Path(bundled_wiki_dir) if bundled_wiki_dir else None

    if not wiki_path.exists():
        if bundled_path and bundled_path.exists():
            shutil.copytree(bundled_path, wiki_path)
        else:
            wiki_path.mkdir(parents=True)

    upload_directory(wiki_path).mkdir(parents=True, exist_ok=True)


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
