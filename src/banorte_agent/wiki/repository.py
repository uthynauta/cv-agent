from pathlib import Path

from banorte_agent.wiki.documents import WikiPage
from banorte_agent.wiki.frontmatter import dump_frontmatter, load_frontmatter


class WikiRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_pages(self) -> list[WikiPage]:
        pages: list[WikiPage] = []
        if not self.root.exists():
            return pages
        for path in sorted(self.root.rglob("*.md")):
            if any(part == "raw" for part in path.relative_to(self.root).parts):
                continue
            metadata, body = load_frontmatter(path.read_text(encoding="utf-8"))
            title = str(metadata.get("title") or path.stem.replace("-", " ").title())
            pages.append(WikiPage(path=path, title=title, metadata=metadata, body=body))
        return pages

    def write_page(self, relative_path: str, title: str, metadata: dict[str, object], body: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        merged = {"title": title, **metadata}
        path.write_text(dump_frontmatter(merged, body), encoding="utf-8")
        return path
