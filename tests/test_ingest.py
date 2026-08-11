from pathlib import Path

import pytest

import banorte_agent.wiki.ingest as ingest_module
from banorte_agent.wiki.extractors import ExtractedSource
from banorte_agent.wiki.ingest import IngestionService
from banorte_agent.wiki.repository import WikiRepository


def test_ingest_file_creates_source_page_and_log(tmp_path: Path):
    raw = tmp_path / "raw" / "cv"
    raw.mkdir(parents=True)
    source = raw / "othon.tex"
    source.write_text(r"\section{Skills} Python, FastAPI, AI agents", encoding="utf-8")
    repo = WikiRepository(tmp_path)
    result = IngestionService(repo).ingest_file(source)
    assert result.source_page == tmp_path / "sources" / "othon.md"
    text = result.source_page.read_text(encoding="utf-8")
    assert "Python, FastAPI, AI agents" in text
    assert "sha256:" in text
    assert "needs_ocr: false" in text
    assert "## Extracted Text" in text
    assert "ingest | othon.tex" in (tmp_path / "log.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(("suffix", "kind"), [(".md", "markdown"), (".pdf", "pdf")])
def test_non_latex_ingest_does_not_copy_full_source_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str, kind: str
):
    raw = tmp_path / "raw" / "documents"
    raw.mkdir(parents=True)
    source = raw / f"private{suffix}"
    source.write_bytes(b"placeholder")
    private_text = "private-start " + ("confidential material " * 200) + " private-end"
    extracted = ExtractedSource(source, private_text, kind, False, "a" * 64)
    monkeypatch.setattr(ingest_module, "extract_source", lambda path: extracted)

    result = IngestionService(WikiRepository(tmp_path)).ingest_file(source)
    generated = result.source_page.read_text(encoding="utf-8")

    assert "content_policy: snippet_only" in generated
    assert "## Extracted Text" not in generated
    assert private_text not in generated
    assert "private-end" not in generated
