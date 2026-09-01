from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from cv_agent.config import Settings
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.storage import ensure_data_storage
from cv_agent.main import create_app


def test_fresh_data_dir_starts_empty_and_admin_remains_available(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, admin_api_key="admin-secret")
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503
    status_response = client.get(
        "/admin/status", headers={"Authorization": "Bearer admin-secret"}
    )
    assert status_response.status_code == 200
    assert status_response.json()["knowledge"]["initialized"] is False


def test_readyz_reports_stable_missing_configuration_order(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        openai_api_key=None,
        openai_model="",
        agent_owner_name=None,
        agent_public_url=None,
    )

    response = TestClient(create_app(settings=settings)).get("/readyz")

    assert response.status_code == 503
    assert response.json()["missing"] == [
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "AGENT_OWNER_NAME",
        "AGENT_PUBLIC_URL",
        "knowledge",
    ]


def test_empty_knowledge_response_does_not_call_answerer(tmp_path):
    called = False

    def answerer(text, instructions=None):
        nonlocal called
        called = True
        return "unexpected"

    settings = Settings(_env_file=None, data_dir=tmp_path, openai_api_key="test-key")
    response = TestClient(create_app(settings=settings, agent_answerer=answerer)).post(
        "/v1/responses", json={"input": "hello"}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "candidate knowledge is not initialized"}
    assert called is False


@pytest.mark.parametrize("child", ["documents", "repository", "backups", "staging", "locks"])
def test_ensure_data_storage_rejects_preexisting_child_symlink(tmp_path, child):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / child).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        ensure_data_storage(tmp_path)

    assert list(outside.iterdir()) == []


def test_ensure_data_storage_rejects_symlinked_mount_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    mounted = tmp_path / "mounted"
    mounted.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        ensure_data_storage(mounted)

    assert list(outside.iterdir()) == []


def test_ensure_data_storage_rejects_preexisting_special_path_component(tmp_path):
    (tmp_path / "documents").write_text("not a directory", encoding="utf-8")

    with pytest.raises(ValueError, match="not a directory"):
        ensure_data_storage(tmp_path)


def test_upload_persists_original_and_commits_only_markdown(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        openai_api_key="test-key",
        admin_api_key="admin-secret",
        ingestion_mode="deterministic",
    )

    class Extracted:
        kind = "pdf"
        needs_ocr = False
        text = "Synthetic candidate profile."
        sha256 = "a" * 64

    monkeypatch.setattr("cv_agent.api.admin.extract_source", lambda path: Extracted())
    monkeypatch.setattr("cv_agent.knowledge.ingest.extract_source", lambda path: Extracted())
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))

    response = client.post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("candidate.pdf", b"%PDF synthetic", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    document_id = payload["document"]["document_id"]
    assert payload["revision"]["commit"]
    assert list((tmp_path / "documents").glob(f"{document_id}.pdf"))
    source_page = tmp_path / "repository" / "sources" / f"{document_id}.md"
    assert "original_filename: candidate.pdf" in source_page.read_text(encoding="utf-8")
    tracked = LocalKnowledgeGit(
        tmp_path / "repository", "CV Agent", "cv-agent@localhost"
    ).tracked_paths()
    assert all(not path.endswith(".pdf") for path in tracked)


def test_upload_cleans_staged_original_and_source_when_commit_fails(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        admin_api_key="admin-secret",
        ingestion_mode="deterministic",
    )

    class Extracted:
        kind = "markdown"
        needs_ocr = False
        text = "Synthetic candidate profile."
        sha256 = "a" * 64

    monkeypatch.setattr("cv_agent.api.admin.extract_source", lambda path: Extracted())
    monkeypatch.setattr(
        "cv_agent.api.admin.LocalKnowledgeGit.commit",
        lambda self, message: (_ for _ in ()).throw(RuntimeError("commit failed")),
    )
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))

    response = client.post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("candidate.md", b"profile", "text/markdown")},
    )

    assert response.status_code == 503
    assert list((tmp_path / "staging").iterdir()) == []
    assert list((tmp_path / "documents").glob("*.md")) == []
    assert list((tmp_path / "repository" / "sources").iterdir()) == []


def test_failed_upload_preserves_unrelated_concurrent_markdown(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        admin_api_key="admin-secret",
        ingestion_mode="deterministic",
    )
    paths = ensure_data_storage(tmp_path)

    class Extracted:
        kind = "markdown"
        needs_ocr = False
        text = "Synthetic candidate profile."
        sha256 = "a" * 64

    class Token:
        hex = "upload-id"

    monkeypatch.setattr("cv_agent.api.admin.uuid4", lambda: Token())
    monkeypatch.setattr("cv_agent.api.admin.extract_source", lambda path: Extracted())

    def failed_ingest(self, path, document_id, original_filename=None):
        source = self.repository.root / "sources" / f"{document_id}.md"
        source.write_text("partial upload", encoding="utf-8")
        (self.repository.root / "knowledge" / "concurrent.md").write_text(
            "unrelated concurrent page", encoding="utf-8"
        )
        raise RuntimeError("ingestion failed")

    monkeypatch.setattr("cv_agent.knowledge.ingest.IngestionService.ingest_file", failed_ingest)
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))

    response = client.post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("candidate.md", b"profile", "text/markdown")},
    )

    assert response.status_code == 503
    assert not (paths.repository / "sources" / "upload-id.md").exists()
    assert (paths.repository / "knowledge" / "concurrent.md").read_text(encoding="utf-8") == (
        "unrelated concurrent page"
    )


def test_failed_upload_restores_preexisting_source_version(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        admin_api_key="admin-secret",
        ingestion_mode="deterministic",
    )
    paths = ensure_data_storage(tmp_path)
    previous = paths.repository / "sources" / "upload-id.md"
    previous.write_text("previous source", encoding="utf-8")

    class Extracted:
        kind = "markdown"
        needs_ocr = False
        text = "Synthetic candidate profile."
        sha256 = "a" * 64

    class Token:
        hex = "upload-id"

    monkeypatch.setattr("cv_agent.api.admin.uuid4", lambda: Token())
    monkeypatch.setattr("cv_agent.api.admin.extract_source", lambda path: Extracted())

    def failed_ingest(self, path, document_id, original_filename=None):
        previous.write_text("overwritten source", encoding="utf-8")
        raise RuntimeError("ingestion failed")

    monkeypatch.setattr("cv_agent.knowledge.ingest.IngestionService.ingest_file", failed_ingest)
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))

    response = client.post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("candidate.md", b"profile", "text/markdown")},
    )

    assert response.status_code == 503
    assert previous.read_text(encoding="utf-8") == "previous source"


def test_upload_collision_preserves_existing_original_and_cleans_staging(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        admin_api_key="admin-secret",
        ingestion_mode="deterministic",
    )
    paths = ensure_data_storage(tmp_path)
    existing = paths.documents / "upload-id.md"
    existing.write_text("pre-existing original", encoding="utf-8")
    unrelated = paths.repository / "knowledge" / "unrelated.md"
    unrelated.write_text("unrelated knowledge", encoding="utf-8")

    class Extracted:
        kind = "markdown"
        needs_ocr = False
        text = "Synthetic candidate profile."
        sha256 = "a" * 64

    class Token:
        hex = "upload-id"

    monkeypatch.setattr("cv_agent.api.admin.uuid4", lambda: Token())
    monkeypatch.setattr("cv_agent.api.admin.extract_source", lambda path: Extracted())
    ingest_called = False

    def ingest_file(self, path, document_id, original_filename=None):
        nonlocal ingest_called
        ingest_called = True
        raise AssertionError("ingestion must not run after original collision")

    monkeypatch.setattr("cv_agent.knowledge.ingest.IngestionService.ingest_file", ingest_file)
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))

    response = client.post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("candidate.md", b"new original", "text/markdown")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "document ingestion is unavailable"
    assert ingest_called is False
    assert existing.read_text(encoding="utf-8") == "pre-existing original"
    assert unrelated.read_text(encoding="utf-8") == "unrelated knowledge"
    assert list(paths.staging.iterdir()) == []
