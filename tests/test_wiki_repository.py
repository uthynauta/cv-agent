from pathlib import Path

import pytest

from banorte_agent.wiki.frontmatter import dump_frontmatter, load_frontmatter
from banorte_agent.wiki.repository import WikiRepository


def test_frontmatter_round_trip():
    text = dump_frontmatter({"title": "Othon CV", "tags": ["cv", "source"]}, "Body text")
    metadata, body = load_frontmatter(text)
    assert metadata["title"] == "Othon CV"
    assert metadata["tags"] == ["cv", "source"]
    assert body == "Body text"


def test_repository_writes_and_lists_pages(tmp_path: Path):
    repo = WikiRepository(tmp_path)
    written = repo.write_page(
        "sources/othon-cv.md",
        "Othon CV",
        {"kind": "source"},
        "Resumen con link a [[Python]].",
    )
    assert written == tmp_path / "sources" / "othon-cv.md"
    pages = repo.list_pages()
    assert len(pages) == 1
    assert pages[0].title == "Othon CV"
    assert pages[0].metadata["kind"] == "source"
    assert "[[Python]]" in pages[0].body


@pytest.mark.parametrize("relative_path", ["/outside.md", "../outside.md"])
def test_repository_rejects_paths_outside_root(tmp_path: Path, relative_path: str):
    repo = WikiRepository(tmp_path / "wiki")

    with pytest.raises(ValueError, match="outside wiki root"):
        repo.write_page(relative_path, "Outside", {}, "Should not be written")


@pytest.mark.parametrize("frontmatter", ["- item\n", "value\n"])
def test_load_frontmatter_rejects_non_mapping(frontmatter: str):
    with pytest.raises(ValueError, match="mapping"):
        load_frontmatter(f"---\n{frontmatter}---\n\nBody")
