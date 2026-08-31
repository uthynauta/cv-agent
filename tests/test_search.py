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

    hits = KnowledgeSearch(repo).search("¿Qué hizo Othon en Continental con radares?")

    assert hits[0].title == "Experiencia automotriz"
    assert "Continental" in hits[0].excerpt
    assert "radar" in hits[0].excerpt
    assert KnowledgeSearch(repo).search("¿Qué hizo en con la?") == []


def test_real_cv_query_prefers_continental_radar_evidence():
    wiki_root = Path(__file__).resolve().parents[1] / "wiki"

    hits = KnowledgeSearch(KnowledgeRepository(wiki_root)).search(
        "¿Qué hizo Othon en Continental con radares?"
    )

    assert hits
    assert "continental" in hits[0].excerpt.lower()
    assert "radar" in hits[0].excerpt.lower()


def test_real_cv_spanish_agent_query_retrieves_ai_agent_evidence():
    wiki_root = Path(__file__).resolve().parents[1] / "wiki"

    hits = KnowledgeSearch(KnowledgeRepository(wiki_root)).search(
        "¿Qué experiencia tiene Othon con agentes de IA?"
    )

    assert hits
    combined = " ".join(hit.excerpt.lower() for hit in hits[:2])
    assert "agent" in combined
    assert "llm" in combined or "ai" in combined


def test_real_cv_spanish_education_query_retrieves_formal_degrees():
    wiki_root = Path(__file__).resolve().parents[1] / "wiki"

    hits = KnowledgeSearch(KnowledgeRepository(wiki_root)).search(
        "¿Qué educación formal posee Othón?"
    )

    assert hits
    combined = " ".join(hit.excerpt.lower() for hit in hits[:4])
    assert "phd" in combined or "doctor" in combined
    assert "msc" in combined or "maestr" in combined
    assert "aeronaut" in combined or "engineering" in combined
