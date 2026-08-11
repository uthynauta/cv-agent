from pathlib import Path

from banorte_agent.wiki.repository import WikiRepository
from banorte_agent.wiki.search import WikiSearch


def test_search_ranks_matching_pages(tmp_path: Path):
    repo = WikiRepository(tmp_path)
    repo.write_page("skills/python.md", "Python", {"kind": "skill"}, "Evidence: FastAPI and AI agents.")
    repo.write_page("concepts/cloud.md", "Cloud", {"kind": "concept"}, "Docker Compose deployment.")
    hits = WikiSearch(repo).search("Python FastAPI agents")
    assert hits[0].title == "Python"
    assert hits[0].score > 0
    assert "FastAPI" in hits[0].excerpt


def test_search_returns_empty_for_blank_query(tmp_path: Path):
    repo = WikiRepository(tmp_path)
    repo.write_page("skills/python.md", "Python", {"kind": "skill"}, "Python")
    assert WikiSearch(repo).search("   ") == []


def test_search_uses_spanish_stopwords_token_boundaries_and_matching_passages(tmp_path: Path):
    repo = WikiRepository(tmp_path)
    repo.write_page(
        "entities/profile.md",
        "Perfil de Othon",
        {"kind": "entity"},
        "Othon es ingeniero con experiencia profesional diversa.",
    )
    repo.write_page(
        "projects/continental.md",
        "Experiencia automotriz",
        {"kind": "project"},
        "# Continental\n\nDesarrolló virtualización de radar para validar modelos de percepción.",
    )
    repo.write_page(
        "concepts/noise.md",
        "Ruido",
        {"kind": "concept"},
        "La palabra contradar no debe contar como radar.",
    )

    hits = WikiSearch(repo).search("¿Qué hizo Othon en Continental con radares?")

    assert hits[0].title == "Experiencia automotriz"
    assert "Continental" in hits[0].excerpt
    assert "radar" in hits[0].excerpt
    assert WikiSearch(repo).search("¿Qué hizo en con la?") == []


def test_real_cv_query_prefers_continental_radar_evidence():
    wiki_root = Path(__file__).resolve().parents[1] / "wiki"

    hits = WikiSearch(WikiRepository(wiki_root)).search(
        "¿Qué hizo Othon en Continental con radares?"
    )

    assert hits
    assert "continental" in hits[0].excerpt.lower()
    assert "radar" in hits[0].excerpt.lower()
