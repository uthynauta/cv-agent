from pathlib import Path
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient
import pytest

import cv_agent.api.admin as admin_module
import cv_agent.main as main_module
from cv_agent.config import Settings
from cv_agent.knowledge.documents_service import DocumentMutationError
from cv_agent.knowledge.ingest import document_id_for_path
from cv_agent.knowledge.storage import ensure_data_storage
from cv_agent.main import create_app


def mounted_settings(tmp_path, **overrides):
    values = {"_env_file": None, "data_dir": tmp_path, "admin_api_key": "admin-secret"}
    values.update(overrides)
    return Settings(**values)


def legacy_upload_app(settings, monkeypatch):
    build_admin_router = main_module.build_admin_router
    build_admin_ui_router = main_module.build_admin_ui_router

    def build_legacy_admin_router(settings_arg, paths, git_store, ingestion, document_service):
        return build_admin_router(settings_arg, paths, git_store, ingestion, None)

    def build_legacy_admin_ui_router(settings_arg, paths, git_store, ingestion, document_service):
        return build_admin_ui_router(settings_arg, paths, git_store, ingestion, None)

    monkeypatch.setattr(main_module, "build_admin_router", build_legacy_admin_router)
    monkeypatch.setattr(main_module, "build_admin_ui_router", build_legacy_admin_ui_router)
    return create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")


def test_admin_ingest_allows_file_inside_documents(tmp_path, monkeypatch):
    source = tmp_path / "documents" / "cv.md"
    source.parent.mkdir()
    source.write_text("# CV", encoding="utf-8")
    settings = mounted_settings(tmp_path)

    class Result:
        source_page = Path("sources/cv.md")

    def ingest_file(self, path: Path, document_id: str):
        assert path == source
        return Result()

    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    monkeypatch.setattr("cv_agent.api.admin.IngestionService.ingest_file", ingest_file)

    response = TestClient(app).post(
        "/admin/ingest",
        headers={"Authorization": "Bearer admin-secret"},
        json={"path": str(source)},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "count": 1,
        "sources": ["sources/cv.md"],
        "revision": {"commit": ""},
    }


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

    assert response.status_code == 400


def test_admin_ingest_relative_data_dir_uses_stable_absolute_roots(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = Path("data/documents/cv.md")
    source.parent.mkdir(parents=True)
    source.write_text("# CV", encoding="utf-8")
    settings = Settings(_env_file=None, data_dir="data", admin_api_key="admin-secret")
    seen: list[tuple[Path, str]] = []

    class Result:
        source_page = Path("sources/cv.md")

    def ingest_file(self, path: Path, document_id: str):
        seen.append((path, document_id))
        return Result()

    monkeypatch.setattr(admin_module.IngestionService, "ingest_file", ingest_file)
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    response = TestClient(app).post(
        "/admin/ingest",
        headers={"Authorization": "Bearer admin-secret"},
        json={"path": str(source)},
    )

    assert response.status_code == 200
    assert seen == [(source.absolute(), document_id_for_path(source.absolute(), (tmp_path / "data" / "documents").absolute()))]


def test_admin_upload_persists_original_under_documents(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    settings = Settings(
        _env_file=None,
        data_dir="data",
        admin_api_key="admin-secret",
        admin_upload_max_bytes=1024,
    )
    app = legacy_upload_app(settings, monkeypatch)
    calls: list[tuple[Path, str]] = []

    class Extracted:
        kind = "markdown"
        needs_ocr = False
        text = "upload text"
        sha256 = "a" * 64

    class Result:
        document_id = "upload-id"
        source_page = Path("sources/upload-id.md")

    monkeypatch.setattr(admin_module, "extract_source", lambda path: Extracted())

    def ingest_file(self, path: Path, document_id: str, original_filename=None):
        calls.append((path, document_id))
        return Result()

    monkeypatch.setattr(admin_module.IngestionService, "ingest_file", ingest_file)
    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("notes.md", b"notes", "text/markdown")},
    )

    assert response.status_code == 200
    relative_path = response.json()["document"]["path"]
    assert relative_path.startswith("documents/")
    assert (tmp_path / "data" / relative_path).is_file()
    assert len(calls) == 1
    assert calls[0][0] == tmp_path / "data" / relative_path


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


def test_admin_ingest_requires_admin_key(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = raw_dir / "cv.md"
    source.write_text("# CV", encoding="utf-8")
    settings = Settings(data_dir=tmp_path, admin_api_key="admin-secret")
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post("/admin/ingest", json={"path": str(source)})

    assert response.status_code == 401


def test_admin_ingest_is_disabled_without_configured_key(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = raw_dir / "cv.md"
    source.write_text("# CV", encoding="utf-8")
    settings = Settings(data_dir=tmp_path, admin_api_key=None)

    response = TestClient(
        create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    ).post("/admin/ingest", json={"path": str(source)})

    assert response.status_code == 503
    assert response.json()["detail"] == "admin ingest is disabled"


def test_admin_document_upload_saves_pdf_and_ingests(tmp_path, monkeypatch):
    settings = mounted_settings(tmp_path, admin_upload_max_bytes=1024)
    app = legacy_upload_app(settings, monkeypatch)

    class Extracted:
        kind = "pdf"
        needs_ocr = False
        text = "retrievable text " * 20
        sha256 = "a" * 64

    class Result:
        source_page = Path("sources/uploaded.md")

    def fake_extract(path: Path):
        assert path.name.endswith(".pdf")
        return Extracted()

    def fake_ingest_file(self, path: Path, document_id: str, original_filename=None):
        assert path.parent == tmp_path / "documents"
        assert path.read_bytes() == b"%PDF-1.4 text"
        return Result()

    monkeypatch.setattr("cv_agent.api.admin.extract_source", fake_extract)
    monkeypatch.setattr("cv_agent.api.admin.IngestionService.ingest_file", fake_ingest_file)

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("Uploaded PDF.pdf", b"%PDF-1.4 text", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["document"]["filename"] == "Uploaded-PDF.pdf"
    assert payload["document"]["kind"] == "pdf"
    assert payload["ingestion"] == {
        "count": 1, "sources": ["sources/uploaded.md"], "generated": []
    }


def test_admin_upload_uses_unique_exclusive_targets_and_ids(tmp_path, monkeypatch):
    settings = mounted_settings(tmp_path, admin_upload_max_bytes=1024)
    app = legacy_upload_app(settings, monkeypatch)

    class Extracted:
        kind = "markdown"
        needs_ocr = False
        text = "upload text"
        sha256 = "a" * 64

    class Result:
        source_page = Path("sources/uploaded.md")

    class Token:
        def __init__(self, value: str) -> None:
            self.hex = value

    tokens = iter(["upload-one", "upload-two"])
    seen: list[tuple[Path, str]] = []

    monkeypatch.setattr(admin_module, "uuid4", lambda: Token(next(tokens)), raising=False)
    monkeypatch.setattr(admin_module, "extract_source", lambda path: Extracted())

    def fake_ingest_file(self, path: Path, document_id: str, original_filename=None):
        seen.append((path, document_id))
        return Result()

    monkeypatch.setattr(admin_module.IngestionService, "ingest_file", fake_ingest_file)
    client = TestClient(app)

    first = client.post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("same.md", b"first", "text/markdown")},
    )
    second = client.post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("same.md", b"second", "text/markdown")},
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["document"]["document_id"] == "upload-one"
    assert second.json()["document"]["document_id"] == "upload-two"
    assert len(seen) == 2
    assert seen[0][0] != seen[1][0]
    assert seen[0][1] == "upload-one"
    assert seen[1][1] == "upload-two"
    assert seen[0][0].read_bytes() == b"first"
    assert seen[1][0].read_bytes() == b"second"


def test_admin_document_upload_saves_markdown_and_ingests(tmp_path, monkeypatch):
    settings = mounted_settings(tmp_path, admin_upload_max_bytes=1024)
    app = legacy_upload_app(settings, monkeypatch)

    class Extracted:
        kind = "markdown"
        needs_ocr = False
        text = "# Profile\n\nMarkdown evidence."
        sha256 = "a" * 64

    class Result:
        source_page = Path("sources/profile.md")

    def fake_extract(path: Path):
        assert path.name.endswith(".md")
        return Extracted()

    def fake_ingest_file(self, path: Path, document_id: str, original_filename=None):
        assert path.parent == tmp_path / "documents"
        assert path.read_text(encoding="utf-8") == "# Profile\n\nMarkdown evidence."
        return Result()

    monkeypatch.setattr("cv_agent.api.admin.extract_source", fake_extract)
    monkeypatch.setattr("cv_agent.api.admin.IngestionService.ingest_file", fake_ingest_file)

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("Profile Notes.md", b"# Profile\n\nMarkdown evidence.", "text/markdown")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["document"]["filename"] == "Profile-Notes.md"
    assert payload["document"]["kind"] == "markdown"
    assert payload["ingestion"] == {
        "count": 1, "sources": ["sources/profile.md"], "generated": []
    }


def test_admin_document_upload_saves_latex_and_ingests(tmp_path, monkeypatch):
    settings = mounted_settings(tmp_path, admin_upload_max_bytes=1024)
    app = legacy_upload_app(settings, monkeypatch)

    class Extracted:
        kind = "latex"
        needs_ocr = False
        text = "Profile latex evidence."
        sha256 = "a" * 64

    class Result:
        source_page = Path("sources/profile-latex.md")

    def fake_extract(path: Path):
        assert path.name.endswith(".tex")
        return Extracted()

    def fake_ingest_file(self, path: Path, document_id: str, original_filename=None):
        assert path.parent == tmp_path / "documents"
        assert path.read_text(encoding="utf-8") == r"\section{Profile} Profile latex evidence."
        return Result()

    monkeypatch.setattr("cv_agent.api.admin.extract_source", fake_extract)
    monkeypatch.setattr("cv_agent.api.admin.IngestionService.ingest_file", fake_ingest_file)

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={
            "file": (
                "Profile Source.tex",
                rb"\section{Profile} Profile latex evidence.",
                "application/x-tex",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["document"]["filename"] == "Profile-Source.tex"
    assert payload["document"]["kind"] == "latex"
    assert payload["ingestion"] == {
        "count": 1, "sources": ["sources/profile-latex.md"], "generated": []
    }


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


def test_admin_document_upload_rejects_low_text_pdf(tmp_path, monkeypatch):
    settings = mounted_settings(tmp_path)
    app = legacy_upload_app(settings, monkeypatch)

    class Extracted:
        kind = "pdf"
        needs_ocr = True
        text = ""
        sha256 = "a" * 64

    monkeypatch.setattr("cv_agent.api.admin.extract_source", lambda path: Extracted())

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("scan.pdf", b"%PDF-1.4 image", "application/pdf")},
    )

    assert response.status_code == 422
    assert "OCR" in response.json()["detail"]


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
