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


def test_admin_pdf_upload_keeps_original_outside_markdown_git(tmp_path, monkeypatch):
    settings = mounted_settings(tmp_path, ingestion_mode="deterministic", admin_upload_max_bytes=1024)
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    class Extracted:
        kind = "pdf"
        needs_ocr = False
        text = "Synthetic searchable PDF profile"
        sha256 = "a" * 64

    monkeypatch.setattr("cv_agent.knowledge.ingest.extract_source", lambda path: Extracted())
    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("candidate.pdf", b"synthetic pdf", "application/pdf")},
    )

    assert response.status_code == 200
    document_id = response.json()["document"]["document_id"]
    original = next((tmp_path / "documents").glob(f"{document_id}.pdf"))
    assert original.is_file()
    tracked = app.state.git_store.tracked_paths()
    assert tracked
    assert all(path.startswith(("sources/", "knowledge/")) and path.endswith(".md") for path in tracked)


def test_admin_partial_original_write_is_compensated(tmp_path, monkeypatch):
    settings = mounted_settings(tmp_path, admin_upload_max_bytes=1024)
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    paths = app.state.data_paths

    def partial_write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data[:2])
        raise OSError("simulated document write failure")

    monkeypatch.setattr(admin_module.DocumentService, "_write_exclusive", staticmethod(partial_write))
    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("candidate.md", b"candidate", "text/markdown")},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail.startswith("document mutation failed; operation ")
    assert str(tmp_path) not in response.text
    assert app.state.git_store.head() == ""
    assert [path for path in paths.documents.iterdir() if path.name != "quarantine"] == []
    assert list(paths.sources.iterdir()) == []
    assert list(paths.staging.iterdir()) == []


@pytest.mark.parametrize(
    ("filename", "payload"),
    [("broken.md", b"bad\xff"), ("broken.tex", b"bad\xff"), ("broken.pdf", b"not a PDF")],
)
def test_admin_documents_upload_maps_malformed_files_to_422(tmp_path, filename, payload):
    settings = mounted_settings(tmp_path, admin_upload_max_bytes=1024)
    response = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": (filename, payload, "application/octet-stream")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] in {"document text is invalid", "document PDF is invalid"}


def test_admin_documents_failure_does_not_change_live_state(tmp_path, monkeypatch):
    settings = mounted_settings(tmp_path, admin_upload_max_bytes=1024)
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    paths = app.state.data_paths
    prior_head = app.state.git_store.head()

    monkeypatch.setattr(
        admin_module.DocumentService,
        "add",
        lambda self, original_filename, data, media_type=None: (_ for _ in ()).throw(
            DocumentMutationError("b" * 32, "backend failed")
        ),
    )
    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("candidate.md", b"candidate", "text/markdown")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == f"document mutation failed; operation {'b' * 32}"
    assert str(tmp_path) not in response.text
    assert app.state.git_store.head() == prior_head
    assert [path for path in paths.documents.iterdir() if path.name != "quarantine"] == []
    assert list(paths.sources.iterdir()) == []
    assert list(paths.staging.iterdir()) == []


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
    assert payload["storage"]["writable"] is True
    assert payload["storage"]["document_count"] == 0
    assert payload["knowledge"]["initialized"] is False
    assert payload["knowledge"]["active_commit"] == ""
    assert payload["ingestion"]["mode"] == settings.ingestion_mode
def test_admin_status_payload_helper_reports_local_storage(tmp_path):
    from cv_agent.api.admin import build_admin_status_payload

    settings = Settings(
        _env_file=None,
        admin_api_key="admin-secret",
    )

    payload = build_admin_status_payload(settings)

    assert payload["status"] == "ok"
    assert payload["storage"]["writable"] is True
    assert payload["storage"]["document_count"] == 0
    assert "github" not in payload
