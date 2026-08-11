from pathlib import Path

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
    assert "ingest | othon.tex" in (tmp_path / "log.md").read_text(encoding="utf-8")
