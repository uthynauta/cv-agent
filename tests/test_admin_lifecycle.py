from fastapi.testclient import TestClient
import pytest

from cv_agent.config import Settings
from cv_agent.main import create_app


def client(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, admin_api_key="admin-secret", ingestion_mode="deterministic")
    return TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))


def auth(client):
    return {"Authorization": "Bearer admin-secret"}


def test_document_crud_and_rebuild(tmp_path):
    api = client(tmp_path)
    created = api.post("/admin/documents", headers=auth(api), files={"file": ("candidate.md", b"Python", "text/markdown")})
    assert created.status_code == 200
    document_id = created.json()["document"]["document_id"]
    assert api.get("/admin/documents", headers=auth(api)).json()["documents"][0]["document_id"] == document_id
    replaced = api.put(f"/admin/documents/{document_id}", headers=auth(api), files={"file": ("candidate.md", b"Rust", "text/markdown")})
    assert replaced.status_code == 200
    assert api.post("/admin/rebuild", headers=auth(api)).status_code == 200
    assert api.request("DELETE", f"/admin/documents/{document_id}", headers=auth(api), json={"confirm": True}).status_code == 200


def test_rollback_requires_confirmation(tmp_path):
    api = client(tmp_path)
    commit = api.post("/admin/documents", headers=auth(api), files={"file": ("candidate.md", b"Python", "text/markdown")}).json()["revision"]["commit"]
    response = api.post(f"/admin/revisions/{commit}/rollback", headers=auth(api), json={"confirm": False})
    assert response.status_code == 409


def test_status_and_documents_do_not_expose_paths_or_text(tmp_path):
    api = client(tmp_path)
    api.post("/admin/documents", headers=auth(api), files={"file": ("candidate.md", b"SECRET TEXT", "text/markdown")})
    status = api.get("/admin/status", headers=auth(api))
    assert status.status_code == 200
    payload = status.json()
    assert payload["storage"]["document_count"] == 1
    assert payload["knowledge"]["active_commit"]
    assert str(tmp_path) not in status.text
    assert "SECRET TEXT" not in status.text
    assert str(tmp_path) not in api.get("/admin/documents", headers=auth(api)).text


def test_malformed_source_keeps_status_redacted(tmp_path):
    api = client(tmp_path)
    paths = api.app.state.paths
    (paths.sources / "broken.md").write_text("---\n[broken\n---\n", encoding="utf-8")
    response = api.get("/admin/status", headers=auth(api))
    assert response.status_code == 200
    assert response.json()["storage"]["document_count"] == 0
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize("payload", [b"---\n[broken\n---\n", b"---\nname: bad\n---\n\xff"])
def test_documents_list_maps_malformed_sources_to_redacted_503(tmp_path, payload):
    api = client(tmp_path)
    paths = api.app.state.paths
    (paths.sources / "broken.md").write_bytes(payload)

    response = api.get("/admin/documents", headers=auth(api))

    assert response.status_code == 503
    assert response.json()["detail"].startswith("document read failed; operation ")
    assert str(tmp_path) not in response.text
    assert payload.decode("utf-8", errors="ignore") not in response.text


def test_status_document_count_rejects_sources_symlink_without_reading_external_files(tmp_path, monkeypatch):
    api = client(tmp_path)
    paths = api.app.state.paths
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_bytes(b"\xff external secret")
    paths.sources.rmdir()
    paths.sources.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(
        "cv_agent.api.admin.load_frontmatter",
        lambda text: (_ for _ in ()).throw(AssertionError("external source was read")),
    )

    response = api.get("/admin/status", headers=auth(api))

    assert response.status_code == 200
    assert response.json()["storage"]["document_count"] == 0
    assert "external secret" not in response.text


def test_invalid_and_unreachable_rollback_targets_are_not_found(tmp_path):
    api = client(tmp_path)
    for commit in ("A" * 40, "f" * 40):
        response = api.post(
            f"/admin/revisions/{commit}/rollback", headers=auth(api), json={"confirm": True}
        )
        assert response.status_code == 404


def test_admin_lifecycle_routes_all_require_bearer_auth(tmp_path):
    api = client(tmp_path)
    routes = [
        ("get", "/admin/status"), ("get", "/admin/documents"),
        ("post", "/admin/rebuild"), ("get", "/admin/revisions"),
    ]
    for method, route in routes:
        assert getattr(api, method)(route).status_code == 401
