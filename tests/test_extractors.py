from pathlib import Path

import pytest

import banorte_agent.wiki.extractors as extractors
from banorte_agent.wiki.extractors import extract_source


FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_markdown(tmp_path: Path):
    path = tmp_path / "profile.md"
    path.write_text("# Perfil\n\nExperiencia con agentes de IA.", encoding="utf-8")
    result = extract_source(path)
    assert result.kind == "markdown"
    assert "Experiencia con agentes" in result.text
    assert result.needs_ocr is False
    assert len(result.sha256) == 64


def test_extract_latex_strips_common_commands(tmp_path: Path):
    path = tmp_path / "cv.tex"
    path.write_text(r"\section{Experience}\textbf{AI Agents}", encoding="utf-8")
    result = extract_source(path)
    assert result.kind == "latex"
    assert "Experience" in result.text
    assert "AI Agents" in result.text
    assert "\\section" not in result.text


def test_extract_latex_preserves_escaped_percent(tmp_path: Path):
    path = tmp_path / "cv.tex"
    path.write_text(r"Experience with 80\% growth % remove this comment", encoding="utf-8")
    result = extract_source(path)
    assert "80% growth" in result.text
    assert "remove this comment" not in result.text


@pytest.mark.parametrize("fixture_name", ["cv-header-ai.tex", "cv-header-ats.tex"])
def test_extract_actual_cv_headers_preserves_name_and_removes_layout_debris(fixture_name: str):
    result = extract_source(FIXTURES / fixture_name)

    assert "Othón González" in result.text
    assert "Professional Summary" in result.text
    assert "0pt" not in result.text
    assert "LARGE" not in result.text
    assert "textwidth" not in result.text
    assert "center" not in result.text


def test_extract_latex_double_backslash_before_percent_starts_comment(tmp_path: Path):
    path = tmp_path / "cv.tex"
    path.write_text(r"Line break \\% remove this comment", encoding="utf-8")
    result = extract_source(path)
    assert "Line break" in result.text
    assert "remove this comment" not in result.text


@pytest.mark.parametrize(
    ("text", "needs_ocr"),
    [("x" * 119, True), ("x" * 120, False)],
)
def test_extract_pdf_sets_needs_ocr_at_text_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, needs_ocr: bool
):
    path = tmp_path / "cv.pdf"
    path.write_bytes(b"mock pdf")

    class FakePage:
        def extract_text(self) -> str:
            return text

    class FakeReader:
        def __init__(self, _: str) -> None:
            self.pages = [FakePage()]

    monkeypatch.setattr(extractors, "PdfReader", FakeReader)
    result = extract_source(path)
    assert result.kind == "pdf"
    assert result.needs_ocr is needs_ocr
