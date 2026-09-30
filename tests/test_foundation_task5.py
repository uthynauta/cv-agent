from fastapi.testclient import TestClient
import pytest

from cv_agent.config import Settings
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


def test_heading_only_knowledge_is_not_initialized(tmp_path):
    paths = ensure_data_storage(tmp_path)
    (paths.knowledge / "index.md").write_text("# Index", encoding="utf-8")
    (paths.knowledge / "log.md").write_text("# Log", encoding="utf-8")
    (paths.sources / "empty.md").write_text("---\ntitle: Empty\n---\n\n#", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        openai_api_key="test-key",
        openai_model="test-model",
        agent_owner_name="Candidate",
        agent_public_url="https://example.test",
    )
    called = False

    def answerer(text, instructions=None):
        nonlocal called
        called = True
        return "unexpected"

    client = TestClient(create_app(settings=settings, agent_answerer=answerer))

    assert client.get("/readyz").status_code == 503
    response = client.post("/v1/responses", json={"input": "hello"})
    assert response.status_code == 503
    assert response.json() == {"detail": "candidate knowledge is not initialized"}
    assert called is False


def test_admin_ingest_staging_path_is_unavailable(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, admin_api_key="admin-secret")
    paths = ensure_data_storage(tmp_path)
    source = paths.staging / "candidate.md"
    source.write_text("# Candidate\n\nUsable profile.", encoding="utf-8")
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))

    response = client.post(
        "/admin/ingest",
        headers={"Authorization": "Bearer admin-secret"},
        json={"path": str(source)},
    )

    assert response.status_code == 404
