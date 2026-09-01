from pathlib import Path

from cv_agent.knowledge.documents import KnowledgePage
from cv_agent.knowledge.frontmatter import dump_frontmatter, load_frontmatter


class KnowledgeRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_pages(self) -> list[KnowledgePage]:
        pages: list[KnowledgePage] = []
        if not self.root.exists():
            return pages
        root = self.root.resolve()
        for path in sorted(self.root.rglob("*.md")):
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

    def write_page(self, relative_path: str, title: str, metadata: dict[str, object], body: str) -> Path:
        root = self.root.resolve()
        if not isinstance(relative_path, str) or "\x00" in relative_path:
            raise ValueError(f"page path is not allowed: {relative_path}")
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"page path is outside wiki root: {relative_path}")
        if not candidate.parts or "\\" in relative_path:
            raise ValueError(f"page path is not allowed: {relative_path}")
        path = (root / candidate).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"page path is outside wiki root: {relative_path}") from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        merged = {"title": title, **metadata}
        path.write_text(dump_frontmatter(merged, body), encoding="utf-8")
        return path
