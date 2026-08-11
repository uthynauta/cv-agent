from pathlib import Path

from banorte_agent.wiki.extractors import extract_source


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
