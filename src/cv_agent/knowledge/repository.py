from pathlib import Path

from cv_agent.knowledge.documents import KnowledgePage
from cv_agent.knowledge.frontmatter import dump_frontmatter, load_frontmatter


MAX_PATH_COMPONENT_BYTES = 255
MAX_RELATIVE_PATH_BYTES = 1024
MAX_PATH_DEPTH = 8


def validate_relative_path_limits(relative_path: str) -> None:
    encoded_length = len(relative_path.encode("utf-8"))
    candidate = Path(relative_path)
    if encoded_length > MAX_RELATIVE_PATH_BYTES:
        raise ValueError(f"page path exceeds {MAX_RELATIVE_PATH_BYTES} bytes: {relative_path}")
    if len(candidate.parts) > MAX_PATH_DEPTH:
        raise ValueError(f"page path exceeds depth {MAX_PATH_DEPTH}: {relative_path}")
    if any(len(part.encode("utf-8")) > MAX_PATH_COMPONENT_BYTES for part in candidate.parts):
        raise ValueError(f"page path component exceeds {MAX_PATH_COMPONENT_BYTES} bytes: {relative_path}")


def resolve_directory_path(path: Path, *, create: bool = False) -> Path:
    """Return a lexical directory path after rejecting symlink/file components."""
    lexical = Path(path).absolute()
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"directory path uses symlink component: {path}")
        if current.exists() and not current.is_dir():
            raise ValueError(f"directory path component is not a directory: {path}")
    if create:
        try:
            lexical.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"directory path is not available: {path}") from exc
    return lexical


class KnowledgeRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_pages(self) -> list[KnowledgePage]:
        pages: list[KnowledgePage] = []
        if self.root.is_symlink() or not self.root.exists() or not self.root.is_dir():
            return pages
        root = self.root.resolve()
        for path in sorted(self.root.rglob("*.md")):
            relative_path = path.relative_to(self.root)
            if self._contains_symlink(relative_path):
                continue
            try:
                resolved = path.resolve()
                relative = resolved.relative_to(root)
            except ValueError:
                continue
            if any(part == "raw" for part in relative.parts):
                continue
            metadata, body = load_frontmatter(path.read_text(encoding="utf-8"))
            title = str(metadata.get("title") or path.stem.replace("-", " ").title())
            pages.append(KnowledgePage(path=path, title=title, metadata=metadata, body=body))
        return pages

    def resolve_write_path(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or "\x00" in relative_path:
            raise ValueError(f"page path is not allowed: {relative_path}")
        candidate = Path(relative_path)
        validate_relative_path_limits(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"page path is outside wiki root: {relative_path}")
        if not candidate.parts or "\\" in relative_path:
            raise ValueError(f"page path is not allowed: {relative_path}")
        lexical_root = resolve_directory_path(self.root)
        root = lexical_root.resolve()
        current = lexical_root
        for index, part in enumerate(candidate.parts):
            current /= part
            if current.is_symlink():
                raise ValueError(f"page path is outside wiki root or uses symlink component: {relative_path}")
            if current.exists() and index < len(candidate.parts) - 1 and not current.is_dir():
                raise ValueError(f"page path component is not a directory: {relative_path}")
        if current.exists() and not current.is_file():
            raise ValueError(f"page path target is not a regular file: {relative_path}")
        path = (lexical_root / candidate).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"page path is outside wiki root: {relative_path}") from exc
        return path

    def write_text(self, relative_path: str, text: str, *, append: bool = False) -> Path:
        path = self.resolve_write_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with path.open(mode, encoding="utf-8") as handle:
            handle.write(text)
        return path

    def write_page(self, relative_path: str, title: str, metadata: dict[str, object], body: str) -> Path:
        path = self.resolve_write_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        merged = {"title": title, **metadata}
        path.write_text(dump_frontmatter(merged, body), encoding="utf-8")
        return path

    def _contains_symlink(self, relative_path: Path) -> bool:
        current = self.root
        for part in relative_path.parts:
            current /= part
            if current.is_symlink():
                return True
        return False
