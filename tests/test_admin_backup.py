from fastapi.testclient import TestClient

from cv_agent.config import Settings
from cv_agent.main import create_app


def test_backup_routes_require_admin_auth(tmp_path):
    app = create_app(settings=Settings(_env_file=None, data_dir=tmp_path, admin_api_key="secret"), agent_answerer=lambda *_: "ok")
    assert TestClient(app).get("/admin/backups").status_code == 401


def test_backup_list_and_delete_are_authenticated(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, admin_api_key="secret")
    app = create_app(settings=settings, agent_answerer=lambda *_: "ok")
    client = TestClient(app)
    headers = {"Authorization": "Bearer secret"}
    service = app.state.backup_service
    service.paths.backups.joinpath("knowledge-20260101T000000Z-aaaaaaaaaaaaaaaa.bundle").write_bytes(b"x")
    listed = client.get("/admin/backups", headers=headers)
    assert listed.status_code == 200
    name = listed.json()["backups"][0]["name"]
    assert client.delete(f"/admin/backups/{name}", headers=headers).status_code == 409
    assert client.request("DELETE", f"/admin/backups/{name}", headers=headers, json={"confirm": True}).status_code == 200


def test_restore_requires_confirmation_and_rejects_invalid_archive(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, admin_api_key="secret")
    client = TestClient(create_app(settings=settings, agent_answerer=lambda *_: "ok"))
    headers = {"Authorization": "Bearer secret"}

    unconfirmed = client.post(
        "/admin/restore",
        headers=headers,
        files={"file": ("backup.tar.gz", b"invalid", "application/gzip")},
    )
    invalid = client.post(
        "/admin/restore",
        headers=headers,
        files={"file": ("backup.tar.gz", b"invalid", "application/gzip")},
        data={"confirm": "true"},
    )

    assert unconfirmed.status_code == 409
    assert invalid.status_code == 422
