from pathlib import Path

from cv_agent.knowledge.repository import KnowledgeRepository
from cv_agent.knowledge.search import KnowledgeSearch


def test_search_ranks_matching_pages(tmp_path: Path):
    repo = KnowledgeRepository(tmp_path)
    repo.write_page("skills/python.md", "Python", {"kind": "skill"}, "Evidence: FastAPI and AI agents.")
    repo.write_page("concepts/cloud.md", "Cloud", {"kind": "concept"}, "Docker Compose deployment.")
    hits = KnowledgeSearch(repo).search("Python FastAPI agents")
    assert hits[0].title == "Python"
    assert hits[0].score > 0
    assert "FastAPI" in hits[0].excerpt


def test_search_returns_empty_for_blank_query(tmp_path: Path):
    repo = KnowledgeRepository(tmp_path)
    repo.write_page("skills/python.md", "Python", {"kind": "skill"}, "Python")
    assert KnowledgeSearch(repo).search("   ") == []


def test_search_uses_spanish_stopwords_token_boundaries_and_matching_passages(tmp_path: Path):
    repo = KnowledgeRepository(tmp_path)
    repo.write_page(
        "entities/profile.md",
        "Perfil de Candidate",
        {"kind": "entity"},
        "Candidate es ingeniero con experiencia profesional diversa.",
    )
    repo.write_page(
        "projects/example-mobility.md",
        "Experiencia automotriz",
        {"kind": "project"},
        "# Example Mobility\n\nDesarrolló virtualización de radar para validar modelos de percepción.",
    )
    repo.write_page(
        "concepts/noise.md",
        "Ruido",
        {"kind": "concept"},
        "La palabra contradar no debe contar como radar.",
    )

    hits = KnowledgeSearch(repo).search("¿Qué hizo Candidate en Example Mobility con radares?")

    assert hits[0].title == "Experiencia automotriz"
    assert "Example Mobility" in hits[0].excerpt
    assert "radar" in hits[0].excerpt
    assert KnowledgeSearch(repo).search("¿Qué hizo en con la?") == []
