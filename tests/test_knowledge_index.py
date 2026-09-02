from pathlib import Path

import pytest

from cv_agent.config import Settings
from cv_agent.knowledge.index import ActiveKnowledge, KnowledgeSnapshot
from cv_agent.knowledge.repository import KnowledgeRepository
from cv_agent.main import create_app


def test_disk_change_requires_reload(tmp_path: Path):
    repository = KnowledgeRepository(tmp_path)
    repository.write_page("knowledge/python.md", "Python", {"kind": "skill"}, "FastAPI")
    active = ActiveKnowledge.load(repository)

    repository.write_page("knowledge/rust.md", "Rust", {"kind": "skill"}, "Systems")

    assert active.search("Rust") == []
    active.reload(repository)
    assert [hit.title for hit in active.search("Rust")] == ["Rust"]


def test_failed_reload_keeps_old_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repository = KnowledgeRepository(tmp_path)
    repository.write_page("knowledge/python.md", "Python", {"kind": "skill"}, "FastAPI")
    active = ActiveKnowledge.load(repository)

    monkeypatch.setattr(
        KnowledgeSnapshot,
        "from_repository",
        classmethod(lambda cls, repo: (_ for _ in ()).throw(ValueError("invalid"))),
    )

    with pytest.raises(ValueError):
        active.reload(repository)

    assert active.search("FastAPI")


def test_initialized_requires_usable_evidence(tmp_path: Path):
    repository = KnowledgeRepository(tmp_path)
    repository.write_page("knowledge/index.md", "Index", {}, "# Index")
    repository.write_page("knowledge/log.md", "Log", {}, "# Log")
    repository.write_page("knowledge/heading.md", "Heading", {}, "# Heading")
    active = ActiveKnowledge.load(repository)

    assert active.initialized is False

    repository.write_page("sources/candidate.md", "Candidate", {}, "Usable source content")
    active.reload(repository)

    assert active.initialized is True


def test_create_app_injects_one_active_knowledge_handle(tmp_path: Path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    assert isinstance(app.state.active_knowledge, ActiveKnowledge)
