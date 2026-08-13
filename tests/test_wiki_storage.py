from pathlib import Path

import pytest

from banorte_agent.wiki.storage import (
    ensure_wiki_storage,
    safe_upload_filename,
    upload_directory,
)


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
