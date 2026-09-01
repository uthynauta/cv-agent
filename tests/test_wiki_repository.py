from pathlib import Path

import pytest

from cv_agent.knowledge.frontmatter import dump_frontmatter, load_frontmatter
from cv_agent.knowledge.repository import KnowledgeRepository


def test_frontmatter_round_trip():
    text = dump_frontmatter({"title": "Othon CV", "tags": ["cv", "source"]}, "Body text")
    metadata, body = load_frontmatter(text)
    assert metadata["title"] == "Othon CV"
    assert metadata["tags"] == ["cv", "source"]
    assert body == "Body text"


def test_repository_writes_and_lists_pages(tmp_path: Path):
    repo = KnowledgeRepository(tmp_path)
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
    repo = KnowledgeRepository(tmp_path / "wiki")

    with pytest.raises(ValueError, match="outside wiki root"):
        repo.write_page(relative_path, "Outside", {}, "Should not be written")


def test_repository_rejects_symlink_escape(tmp_path: Path):
    wiki_root = tmp_path / "wiki"
    outside = tmp_path / "outside"
    wiki_root.mkdir()
    outside.mkdir()
    (wiki_root / "knowledge").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="outside wiki root"):
        KnowledgeRepository(wiki_root).write_page("knowledge/escaped.md", "Escaped", {}, "secret")

    assert not (outside / "escaped.md").exists()


@pytest.mark.parametrize("frontmatter", ["- item\n", "value\n"])
def test_load_frontmatter_rejects_non_mapping(frontmatter: str):
    with pytest.raises(ValueError, match="mapping"):
        load_frontmatter(f"---\n{frontmatter}---\n\nBody")
