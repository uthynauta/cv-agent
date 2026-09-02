from fastapi.testclient import TestClient

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
