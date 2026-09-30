from fastapi.testclient import TestClient

from cv_agent.config import Settings
from cv_agent.main import create_app


def test_storage_lifecycle_upload_query_backup_delete_restore_query(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        admin_api_key="admin-secret",
        ingestion_mode="deterministic",
        openai_api_key="test-key",
        openai_model="test-model",
        agent_owner_name="Example Candidate",
        agent_public_url="https://cv-agent.example.test",
        agent_model_name="test-agent",
    )
    app = create_app(
        settings=settings,
        agent_answerer=lambda *_: "Respuesta basada en el perfil.\nFuentes: [[Candidate Profile]]",
    )
    client = TestClient(app)
    admin = {"Authorization": "Bearer admin-secret"}

    assert client.get("/readyz").status_code == 503

    uploaded = client.post(
        "/admin/documents",
        headers=admin,
        files={"file": ("candidate.md", b"# Candidate Profile\n\nPython engineer.", "text/markdown")},
    )
    assert uploaded.status_code == 200
    document_id = uploaded.json()["document"]["document_id"]
    assert client.get("/readyz").status_code == 200

    queried = client.post(
        "/v1/responses",
        json={"input": "Resume el perfil."},
    )
    assert queried.status_code == 200
    assert "Candidate Profile" in queried.json()["output_text"]

    created_backup = client.post("/admin/backups/full", headers=admin)
    assert created_backup.status_code == 200
    backup_name = created_backup.json()["backup"]["name"]
    backup_bytes = client.get(f"/admin/backups/{backup_name}", headers=admin).content
    assert backup_bytes

    deleted = client.request(
        "DELETE",
        f"/admin/documents/{document_id}",
        headers=admin,
        json={"confirm": True},
    )
    assert deleted.status_code == 200
    assert client.get("/readyz").status_code == 503

    restored = client.post(
        "/admin/restore",
        headers=admin,
        files={"file": (backup_name, backup_bytes, "application/gzip")},
        data={"confirm": "true"},
    )
    assert restored.status_code == 200
    assert client.get("/readyz").status_code == 200

    queried_again = client.post(
        "/v1/responses",
        json={"input": "Resume el perfil otra vez."},
    )
    assert queried_again.status_code == 200
    assert "Candidate Profile" in queried_again.json()["output_text"]
