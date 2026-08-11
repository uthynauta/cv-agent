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
