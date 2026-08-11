from pathlib import Path

WIKI_DIRS = [
    "raw/cv",
    "raw/documents",
    "sources",
    "entities",
    "concepts",
    "projects",
    "skills",
    "questions",
]


def ensure_wiki_tree(root: Path) -> None:
    for dirname in WIKI_DIRS:
        (root / dirname).mkdir(parents=True, exist_ok=True)
    (root / "index.md").touch(exist_ok=True)
    (root / "log.md").touch(exist_ok=True)
