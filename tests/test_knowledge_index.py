from pathlib import Path
from threading import Event, Thread

import pytest

from cv_agent.config import Settings
from cv_agent.knowledge.documents import KnowledgePage
from cv_agent.knowledge.index import ActiveKnowledge, KnowledgeSnapshot
from cv_agent.knowledge.repository import KnowledgeRepository
from cv_agent.main import create_app
from fastapi.testclient import TestClient


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


def test_snapshot_copies_source_metadata_and_page_views(tmp_path: Path):
    repository = KnowledgeRepository(tmp_path)
    repository.write_page(
        "knowledge/python.md", "Python", {"kind": "skill", "alias": "FastAPI"}, "Runtime"
    )
    active = ActiveKnowledge.load(repository)

    repository_page = repository.list_pages()[0]
    repository_page.metadata["alias"] = "Rust"
    returned_page = active.list_pages()[0]
    returned_page.metadata["alias"] = "Rust"

    assert active.search("Rust") == []
    assert active.list_pages()[0].metadata["alias"] == "FastAPI"


def test_snapshot_copies_metadata_supplied_to_constructor():
    metadata = {"alias": "FastAPI"}
    page = KnowledgePage(Path("knowledge/python.md"), "Python", metadata, "Runtime")
    snapshot = KnowledgeSnapshot((page,))
    metadata["alias"] = "Rust"

    assert snapshot.list_pages()[0].metadata == {"alias": "FastAPI"}


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


def test_malformed_startup_keeps_health_and_admin_available(tmp_path: Path):
    data_dir = tmp_path / "data"
    repository_root = data_dir / "repository" / "knowledge"
    repository_root.mkdir(parents=True)
    (repository_root / "broken.md").write_text(
        "---\nsecret: [unclosed\n---\n\nnot usable", encoding="utf-8"
    )
    settings = Settings(
        _env_file=None,
        data_dir=data_dir,
        admin_api_key="admin-secret",
        openai_api_key="test-key",
        openai_model="test-model",
        agent_owner_name="Candidate",
        agent_public_url="https://example.test",
    )

    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))

    assert client.get("/healthz").status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready", "missing": ["knowledge"]}
    admin = client.get("/admin/status", headers={"Authorization": "Bearer admin-secret"})
    assert admin.status_code == 200
    assert admin.json()["knowledge"]["initialized"] is False
    assert "secret" not in admin.text


def test_reload_serializes_candidate_build_and_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repository = KnowledgeRepository(tmp_path / "initial")
    repository.write_page("knowledge/initial.md", "Initial", {}, "initial")
    active = ActiveKnowledge.load(repository)
    first_repository = KnowledgeRepository(tmp_path / "first")
    first_repository.write_page("knowledge/first.md", "First", {}, "first")
    second_repository = KnowledgeRepository(tmp_path / "second")
    second_repository.write_page("knowledge/second.md", "Second", {}, "second")
    first_started = Event()
    release_first = Event()
    second_started = Event()
    original = KnowledgeSnapshot.from_repository.__func__
    calls = 0

    def from_repository(cls, repo):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            assert release_first.wait(2)
        elif calls == 2:
            second_started.set()
        return original(cls, repo)

    monkeypatch.setattr(KnowledgeSnapshot, "from_repository", classmethod(from_repository))
    first = Thread(target=active.reload, args=(first_repository,))
    second = Thread(target=active.reload, args=(second_repository,))
    first.start()
    assert first_started.wait(2)
    second.start()
    assert not second_started.wait(0.1)
    release_first.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert [hit.title for hit in active.search("Second")] == ["Second"]
    assert active.search("First") == []
