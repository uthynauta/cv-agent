from pathlib import Path
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient
import pytest

import cv_agent.api.admin as admin_module
from cv_agent.config import Settings
from cv_agent.knowledge.documents_service import DocumentMutationError, DocumentValidationError
from cv_agent.knowledge.storage import ensure_data_storage
from cv_agent.main import create_app


def mounted_settings(tmp_path, **overrides):
    values = {"_env_file": None, "data_dir": tmp_path, "admin_api_key": "admin-secret"}
    values.update(overrides)
    return Settings(**values)


def test_admin_ingest_route_is_unavailable(tmp_path):
    source = tmp_path / "documents" / "cv.md"
    source.parent.mkdir()
    source.write_text("# CV", encoding="utf-8")
    settings = mounted_settings(tmp_path)

    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post(
        "/admin/ingest",
        headers={"Authorization": "Bearer admin-secret"},
        json={"path": str(source)},
    )

    assert response.status_code == 404


def test_admin_ingest_rejects_path_outside_mounted_data_roots(tmp_path):
    ensure_data_storage(tmp_path)
    outside = tmp_path / "other"
    outside.mkdir()
    source = outside / "secret.md"
    source.write_text("secret", encoding="utf-8")
    settings = mounted_settings(tmp_path)
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post(
        "/admin/ingest",
        headers={"Authorization": "Bearer admin-secret"},
        json={"path": str(source)},
    )

    assert response.status_code == 404


def test_admin_ingest_relative_data_dir_uses_stable_absolute_roots(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = Path("data/documents/cv.md")
    source.parent.mkdir(parents=True)
    source.write_text("# CV", encoding="utf-8")
    settings = Settings(_env_file=None, data_dir="data", admin_api_key="admin-secret")
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    response = TestClient(app).post(
        "/admin/ingest",
        headers={"Authorization": "Bearer admin-secret"},
        json={"path": str(source)},
    )

    assert response.status_code == 404


def test_admin_documents_upload_remains_available_after_legacy_ingest_removal(tmp_path):
    settings = mounted_settings(tmp_path, ingestion_mode="deterministic", admin_upload_max_bytes=1024)
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))

    unavailable = client.post(
        "/admin/ingest",
        headers={"Authorization": "Bearer admin-secret"},
        json={"path": str(tmp_path / "documents" / "candidate.md")},
    )
    available = client.post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("candidate.md", b"# Candidate\n\nPython", "text/markdown")},
    )

    assert unavailable.status_code == 404
    assert available.status_code == 200
    assert available.json()["document"]["filename"] == "candidate.md"


@pytest.mark.parametrize(
    ("filename", "media_type", "payload", "kind"),
    [
        ("candidate.md", "text/markdown", b"# Candidate\n\nPython", "markdown"),
        ("candidate.tex", "application/x-tex", rb"\\section{Candidate} Python", "latex"),
        ("candidate.pdf", "application/pdf", b"synthetic pdf", "pdf"),
    ],
)
def test_admin_documents_upload_supported_formats_use_document_service(
    tmp_path, monkeypatch, filename, media_type, payload, kind
):
    settings = mounted_settings(tmp_path, ingestion_mode="deterministic", admin_upload_max_bytes=1024)

    class Extracted:
        needs_ocr = False
        text = "Candidate profile text"
        sha256 = "a" * 64

        def __init__(self, source_kind):
            self.kind = source_kind

    monkeypatch.setattr(
        "cv_agent.knowledge.ingest.extract_source",
        lambda path: Extracted(kind),
    )
    response = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": (filename, payload, media_type)},
    )

    assert response.status_code == 200
    assert response.json()["document"]["kind"] == kind
    document_id = response.json()["document"]["document_id"]
    assert list((tmp_path / "documents").glob(f"{document_id}.*"))


def test_admin_upload_does_not_bypass_document_service_when_ingestion_is_patched(
    tmp_path, monkeypatch
):
    settings = mounted_settings(tmp_path, admin_upload_max_bytes=1024)
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    def fail_legacy_ingest(self, path, document_id, original_filename=None):
        raise AssertionError("legacy ingestion path was used")

    def fail_document_add(self, original_filename, data, media_type=None):
        raise DocumentMutationError("a" * 32)

    monkeypatch.setattr(admin_module.IngestionService, "ingest_file", fail_legacy_ingest)
    monkeypatch.setattr(admin_module.DocumentService, "add", fail_document_add)

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("notes.md", b"notes", "text/markdown")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == f"document mutation failed; operation {'a' * 32}"


def test_admin_upload_maps_document_validation_to_422(tmp_path, monkeypatch):
    settings = mounted_settings(tmp_path, admin_upload_max_bytes=1024)
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    monkeypatch.setattr(
        admin_module.DocumentService,
        "add",
        lambda self, original_filename, data, media_type=None: (_ for _ in ()).throw(
            DocumentValidationError("a" * 32, "document requires OCR")
        ),
    )

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("scan.pdf", b"%PDF-1.4 image", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "document requires OCR"


def test_admin_ingest_rejects_symlinked_data_root_without_external_access(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("secret", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "documents").symlink_to(outside, target_is_directory=True)
    settings = mounted_settings(data_dir)

    with pytest.raises(ValueError, match="symlink"):
        create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    assert secret.read_text(encoding="utf-8") == "secret"


def test_admin_upload_rejects_symlinked_documents_root_without_external_write(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "documents").symlink_to(outside, target_is_directory=True)
    settings = mounted_settings(data_dir)

    with pytest.raises(ValueError, match="symlink"):
        create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    assert secret.read_text(encoding="utf-8") == "secret"
    assert not (outside / "uploads").exists()


def test_admin_status_rejects_symlinked_data_root_without_external_access(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "documents").symlink_to(outside, target_is_directory=True)
    settings = mounted_settings(data_dir)

    with pytest.raises(ValueError, match="symlink"):
        create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    assert not (outside / "uploads").exists()


def test_admin_ingest_route_is_unavailable_without_admin_key(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = raw_dir / "cv.md"
    source.write_text("# CV", encoding="utf-8")
    settings = Settings(data_dir=tmp_path, admin_api_key="admin-secret")
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post("/admin/ingest", json={"path": str(source)})

    assert response.status_code == 404


def test_admin_ingest_route_is_unavailable_when_admin_is_disabled(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = raw_dir / "cv.md"
    source.write_text("# CV", encoding="utf-8")
    settings = Settings(data_dir=tmp_path, admin_api_key=None)

    response = TestClient(
        create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    ).post("/admin/ingest", json={"path": str(source)})

    assert response.status_code == 404


def test_admin_document_upload_rejects_unsupported_extension(tmp_path):
    settings = mounted_settings(tmp_path)
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("notes.txt", b"text", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "only .pdf, .md, and .tex uploads are supported"


def test_admin_document_upload_rejects_oversized_file(tmp_path):
    settings = mounted_settings(tmp_path, admin_upload_max_bytes=4)
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("cv.pdf", b"12345", "application/pdf")},
    )

    assert response.status_code == 413


def test_admin_status_reports_storage_and_local_repository(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        admin_api_key="admin-secret",
    )
    response = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")).get(
        "/admin/status",
        headers={"Authorization": "Bearer admin-secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["storage"]["documents_dir"].endswith("documents")
    assert payload["storage"]["documents_dir_writable"] is True
    assert payload["knowledge"]["initialized"] is False
    assert payload["repository"]["head"] == ""
    assert payload["ingestion"]["mode"] == settings.ingestion_mode
def test_admin_status_payload_helper_reports_local_storage(tmp_path):
    from cv_agent.api.admin import build_admin_status_payload

    settings = Settings(
        _env_file=None,
        admin_api_key="admin-secret",
    )

    payload = build_admin_status_payload(settings)

    assert payload["status"] == "ok"
    assert payload["storage"]["documents_dir"].endswith("documents")
    assert "github" not in payload
