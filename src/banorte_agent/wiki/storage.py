from pathlib import Path
import re
import shutil
import unicodedata


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
    if suffix != ".pdf":
        raise ValueError("only .pdf uploads are supported")

    stem = Path(name).stem
    normalized = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized)
    normalized = re.sub(r"[-_.]{2,}", "-", normalized).strip("-_.")
    normalized = re.sub(r"^[A-Za-z]{1,2}-", "", normalized)
    if not normalized:
        raise ValueError("filename must contain letters or numbers")
    return f"{normalized}.pdf"
