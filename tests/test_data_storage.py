from pathlib import Path

import pytest

from cv_agent.knowledge.storage import (
    DataPaths,
    ensure_data_storage,
    ensure_wiki_storage,
    safe_upload_filename,
    upload_directory,
)


def test_data_paths_derive_all_runtime_locations(tmp_path: Path):
    paths = DataPaths.from_root(tmp_path / "data")
    root = (tmp_path / "data").resolve()

    assert paths.root == root
    assert paths.documents == root / "documents"
    assert paths.quarantine == root / "documents" / "quarantine"
    assert paths.repository == root / "repository"
    assert paths.sources == root / "repository" / "sources"
    assert paths.knowledge == root / "repository" / "knowledge"
    assert paths.backups == root / "backups"
    assert paths.staging == root / "staging"
    assert paths.locks == root / "locks"


@pytest.mark.parametrize("root", ["", "   ", ".", Path(".")])
def test_data_paths_reject_blank_or_current_directory_root(root):
    with pytest.raises(ValueError, match="data root"):
        DataPaths.from_root(root)


@pytest.mark.parametrize("root_factory", [Path.cwd, lambda: str(Path.cwd())])
def test_data_paths_reject_current_working_directory(root_factory):
    with pytest.raises(ValueError, match="data root"):
        DataPaths.from_root(root_factory())


@pytest.mark.parametrize("root", ["data/..", Path("data/..")])
def test_data_paths_reject_collapsing_root(tmp_path, monkeypatch, root):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="data root"):
        DataPaths.from_root(root)


def test_ensure_data_storage_creates_empty_tree(tmp_path: Path):
    paths = ensure_data_storage(tmp_path / "data")

    for directory in (
        paths.root,
        paths.documents,
        paths.quarantine,
        paths.repository,
        paths.sources,
        paths.knowledge,
        paths.backups,
        paths.staging,
        paths.locks,
    ):
        assert directory.is_dir()
    assert list(paths.knowledge.iterdir()) == []


def test_ensure_data_storage_is_idempotent_and_preserves_knowledge(tmp_path: Path):
    paths = ensure_data_storage(tmp_path / "data")
    sentinel = paths.knowledge / "sentinel.md"
    sentinel.write_text("keep", encoding="utf-8")

    second_paths = ensure_data_storage(tmp_path / "data")

    assert second_paths == paths
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_ensure_wiki_storage_seeds_empty_wiki(tmp_path: Path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "index.md").write_text("# Index", encoding="utf-8")
    (bundled / "raw").mkdir()
    (bundled / "raw" / "cv").mkdir(parents=True)
    (bundled / "raw" / "cv" / "cv.tex").write_text("CV", encoding="utf-8")
    wiki = tmp_path / "persistent" / "wiki"

    ensure_wiki_storage(wiki, bundled)

    assert (wiki / "index.md").read_text(encoding="utf-8") == "# Index"
    assert (wiki / "raw" / "uploads").is_dir()
    assert (wiki / "raw" / "cv" / "cv.tex").read_text(encoding="utf-8") == "CV"


def test_ensure_wiki_storage_does_not_overwrite_existing_wiki(tmp_path: Path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "index.md").write_text("# Bundled", encoding="utf-8")
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_text("# Existing", encoding="utf-8")

    ensure_wiki_storage(wiki, bundled)

    assert (wiki / "index.md").read_text(encoding="utf-8") == "# Existing"
    assert (wiki / "raw" / "uploads").is_dir()


def test_upload_directory_returns_raw_uploads(tmp_path: Path):
    assert upload_directory(tmp_path) == tmp_path / "raw" / "uploads"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Profile PDF.pdf", "Profile-PDF.pdf"),
        ("Profile Notes.md", "Profile-Notes.md"),
        ("Profile Source.tex", "Profile-Source.tex"),
        ("../secret.pdf", "secret.pdf"),
        ("áé resume.pdf", "resume.pdf"),
        ("multi___space.pdf", "multi-space.pdf"),
    ],
)
def test_safe_upload_filename_normalizes_supported_document_names(filename: str, expected: str):
    assert safe_upload_filename(filename) == expected


@pytest.mark.parametrize("filename", ["", ".", "no-extension", "file.txt", "../"])
def test_safe_upload_filename_rejects_invalid_names(filename: str):
    with pytest.raises(ValueError):
        safe_upload_filename(filename)
