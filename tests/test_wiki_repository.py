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


def test_repository_list_pages_ignores_symlinked_root(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    wiki_root = tmp_path / "wiki"
    wiki_root.symlink_to(outside, target_is_directory=True)

    assert KnowledgeRepository(wiki_root).list_pages() == []


def test_repository_rejects_internal_symlink_alias_without_overwrite(tmp_path: Path):
    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir()
    sources = wiki_root / "sources"
    sources.mkdir()
    sentinel = sources / "sentinel.md"
    sentinel.write_text("original", encoding="utf-8")
    (wiki_root / "knowledge").mkdir()
    (wiki_root / "knowledge" / "projects").symlink_to(sources, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        KnowledgeRepository(wiki_root).write_page("knowledge/projects/sentinel.md", "Changed", {}, "bad")

    assert sentinel.read_text(encoding="utf-8") == "original"


def test_repository_rejects_overlong_path_component_before_write(tmp_path: Path):
    with pytest.raises(ValueError, match="path"):
        KnowledgeRepository(tmp_path).write_page(
            f"knowledge/projects/{'x' * 256}.md", "Long", {}, "body"
        )


def test_repository_rejects_existing_directory_target_before_write(tmp_path: Path):
    target = tmp_path / "knowledge" / "projects" / "existing.md"
    target.mkdir(parents=True)

    with pytest.raises(ValueError, match="regular file"):
        KnowledgeRepository(tmp_path).write_page("knowledge/projects/existing.md", "Changed", {}, "body")

    assert target.is_dir()


def test_repository_rejects_regular_file_parent_before_write(tmp_path: Path):
    parent = tmp_path / "knowledge" / "projects"
    parent.parent.mkdir(parents=True)
    parent.write_text("sentinel", encoding="utf-8")

    with pytest.raises(ValueError, match="directory"):
        KnowledgeRepository(tmp_path).write_page("knowledge/projects/new.md", "New", {}, "body")

    assert parent.read_text(encoding="utf-8") == "sentinel"


@pytest.mark.parametrize("frontmatter", ["- item\n", "value\n"])
def test_load_frontmatter_rejects_non_mapping(frontmatter: str):
    with pytest.raises(ValueError, match="mapping"):
        load_frontmatter(f"---\n{frontmatter}---\n\nBody")
