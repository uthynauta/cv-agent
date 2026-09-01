from pathlib import Path
import urllib.error
from io import BytesIO

from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient
import pytest

import cv_agent.api.admin as admin_module
from cv_agent.config import Settings
from cv_agent.main import create_app


def test_admin_ingest_allows_file_inside_raw(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = raw_dir / "cv.md"
    source.write_text("# CV", encoding="utf-8")
    settings = Settings(wiki_dir=str(tmp_path), admin_api_key="admin-secret")

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
    assert response.json() == {"status": "ok", "count": 1, "sources": ["sources/cv.md"]}


def test_admin_ingest_rejects_path_outside_raw(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    outside = tmp_path / "raw-other"
    outside.mkdir()
    source = outside / "secret.md"
    source.write_text("secret", encoding="utf-8")
    settings = Settings(wiki_dir=str(tmp_path), admin_api_key="admin-secret")
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post(
        "/admin/ingest",
        headers={"Authorization": "Bearer admin-secret"},
        json={"path": str(source)},
    )

    assert response.status_code == 400


def test_admin_ingest_rejects_symlinked_raw_root_without_external_access(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("secret", encoding="utf-8")
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "raw").symlink_to(outside, target_is_directory=True)
    settings = Settings(_env_file=None, wiki_dir=str(wiki), admin_api_key="admin-secret")

    class FakeIngestion:
        def ingest_directory(self, path):
            pytest.fail("symlinked raw root must not be ingested")

        def ingest_file(self, path, document_id):
            pytest.fail("symlinked raw root must not be ingested")

    from cv_agent.api.admin import build_admin_router

    app = FastAPI()
    app.include_router(build_admin_router(settings, FakeIngestion()))
    response = TestClient(app).post(
        "/admin/ingest",
        headers={"Authorization": "Bearer admin-secret"},
        json={"path": str(wiki / "raw")},
    )

    assert response.status_code == 503
    assert secret.read_text(encoding="utf-8") == "secret"


def test_admin_upload_rejects_symlinked_upload_root_without_external_write(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "raw").symlink_to(outside, target_is_directory=True)
    settings = Settings(_env_file=None, wiki_dir=str(wiki), admin_api_key="admin-secret")

    class FakeIngestion:
        def ingest_file(self, path, document_id):
            pytest.fail("symlinked upload root must not be ingested")

    from cv_agent.api.admin import upload_document_payload

    upload = UploadFile(filename="notes.md", file=BytesIO(b"notes"))
    with pytest.raises(Exception) as raised:
        import asyncio
        asyncio.run(upload_document_payload(settings, FakeIngestion(), upload))

    assert getattr(raised.value, "status_code", None) == 503
    assert secret.read_text(encoding="utf-8") == "secret"
    assert not (outside / "uploads").exists()


def test_admin_status_rejects_symlinked_upload_root_without_external_access(tmp_path):
    from fastapi import HTTPException
    from cv_agent.api.admin import build_admin_status_payload

    outside = tmp_path / "outside"
    outside.mkdir()
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "raw").symlink_to(outside, target_is_directory=True)
    settings = Settings(_env_file=None, wiki_dir=str(wiki), admin_api_key="admin-secret")

    with pytest.raises(HTTPException) as raised:
        build_admin_status_payload(settings)

    assert raised.value.status_code == 503
    assert not (outside / "uploads").exists()


def test_admin_ingest_requires_admin_key(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = raw_dir / "cv.md"
    source.write_text("# CV", encoding="utf-8")
    settings = Settings(wiki_dir=str(tmp_path), admin_api_key="admin-secret")
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post("/admin/ingest", json={"path": str(source)})

    assert response.status_code == 401


def test_admin_ingest_is_disabled_without_configured_key(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = raw_dir / "cv.md"
    source.write_text("# CV", encoding="utf-8")
    settings = Settings(wiki_dir=str(tmp_path), admin_api_key=None)

    response = TestClient(
        create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    ).post("/admin/ingest", json={"path": str(source)})

    assert response.status_code == 503
    assert response.json()["detail"] == "admin ingest is disabled"


def test_admin_document_upload_saves_pdf_and_ingests(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        admin_upload_max_bytes=1024,
    )
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

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

    def fake_ingest_file(self, path: Path, document_id: str):
        assert path.parent == tmp_path / "raw" / "uploads"
        assert path.read_bytes() == b"%PDF-1.4 text"
        return Result()

    monkeypatch.setattr("cv_agent.api.admin.extract_source", fake_extract)
    monkeypatch.setattr("cv_agent.api.admin.IngestionService.ingest_file", fake_ingest_file)
    monkeypatch.setattr("cv_agent.api.admin.wiki_has_changes", lambda _: True)

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
    assert payload["ingestion"] == {"count": 1, "sources": ["sources/uploaded.md"]}
    assert payload["publish"] == {"pending": True}


def test_admin_upload_uses_unique_exclusive_targets_and_ids(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        admin_upload_max_bytes=1024,
    )
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

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

    def fake_ingest_file(self, path: Path, document_id: str):
        seen.append((path, document_id))
        return Result()

    monkeypatch.setattr(admin_module.IngestionService, "ingest_file", fake_ingest_file)
    monkeypatch.setattr(admin_module, "wiki_has_changes", lambda _: False)
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
    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        admin_upload_max_bytes=1024,
    )
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

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

    def fake_ingest_file(self, path: Path, document_id: str):
        assert path.parent == tmp_path / "raw" / "uploads"
        assert path.read_text(encoding="utf-8") == "# Profile\n\nMarkdown evidence."
        return Result()

    monkeypatch.setattr("cv_agent.api.admin.extract_source", fake_extract)
    monkeypatch.setattr("cv_agent.api.admin.IngestionService.ingest_file", fake_ingest_file)
    monkeypatch.setattr("cv_agent.api.admin.wiki_has_changes", lambda _: True)

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
    assert payload["ingestion"] == {"count": 1, "sources": ["sources/profile.md"]}
    assert payload["publish"] == {"pending": True}


def test_admin_document_upload_saves_latex_and_ingests(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        admin_upload_max_bytes=1024,
    )
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

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

    def fake_ingest_file(self, path: Path, document_id: str):
        assert path.parent == tmp_path / "raw" / "uploads"
        assert path.read_text(encoding="utf-8") == r"\section{Profile} Profile latex evidence."
        return Result()

    monkeypatch.setattr("cv_agent.api.admin.extract_source", fake_extract)
    monkeypatch.setattr("cv_agent.api.admin.IngestionService.ingest_file", fake_ingest_file)
    monkeypatch.setattr("cv_agent.api.admin.wiki_has_changes", lambda _: True)

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
    assert payload["ingestion"] == {"count": 1, "sources": ["sources/profile-latex.md"]}
    assert payload["publish"] == {"pending": True}


def test_admin_document_upload_rejects_unsupported_extension(tmp_path):
    settings = Settings(_env_file=None, wiki_dir=str(tmp_path), admin_api_key="admin-secret")
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("notes.txt", b"text", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "only .pdf, .md, and .tex uploads are supported"


def test_admin_document_upload_rejects_oversized_file(tmp_path):
    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        admin_upload_max_bytes=4,
    )
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    response = TestClient(app).post(
        "/admin/documents",
        headers={"Authorization": "Bearer admin-secret"},
        files={"file": ("cv.pdf", b"12345", "application/pdf")},
    )

    assert response.status_code == 413


def test_admin_document_upload_rejects_low_text_pdf(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, wiki_dir=str(tmp_path), admin_api_key="admin-secret")
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

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


def test_admin_status_reports_storage_and_github_without_secrets(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        github_token="secret-token",
    )

    class FakeGitHub:
        def __init__(self, settings):
            pass

        def status(self):
            return {
                "configured": True,
                "connected": True,
                "base_branch": "main",
                "pending_wiki_changes": True,
                "error": None,
            }

    monkeypatch.setattr("cv_agent.api.admin.GitHubAdminService", FakeGitHub)
    response = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")).get(
        "/admin/status",
        headers={"Authorization": "Bearer admin-secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["wiki"]["upload_dir"].endswith("raw/uploads")
    assert payload["wiki"]["upload_dir_writable"] is True
    assert payload["ingestion"]["mode"] == settings.ingestion_mode
    assert payload["github"]["connected"] is True
    assert "secret-token" not in str(payload)


def test_admin_publish_returns_noop(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, wiki_dir=str(tmp_path), admin_api_key="admin-secret")

    class FakeGitHub:
        def __init__(self, settings):
            pass

        def publish(self):
            return {"status": "noop", "changed_files": []}

    monkeypatch.setattr("cv_agent.api.admin.GitHubAdminService", FakeGitHub)
    response = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")).post(
        "/admin/publish",
        headers={"Authorization": "Bearer admin-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "noop", "changed_files": []}


def test_admin_publish_redacts_failures(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        github_token="secret-token",
    )

    class FakeGitHub:
        def __init__(self, settings):
            pass

        def publish(self):
            raise RuntimeError("push failed for secret-token")

    monkeypatch.setattr("cv_agent.api.admin.GitHubAdminService", FakeGitHub)
    response = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")).post(
        "/admin/publish",
        headers={"Authorization": "Bearer admin-secret"},
    )

    assert response.status_code == 503
    assert "secret-token" not in response.text


def test_admin_publish_returns_redacted_github_http_errors(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        github_token="secret-token",
    )

    class FakeGitHub:
        def __init__(self, settings):
            pass

        def publish(self):
            raise urllib.error.HTTPError(
                "https://api.github.com/repos/uthynauta/cv-agent/git/refs",
                403,
                "Resource not accessible by personal access token secret-token",
                {},
                None,
            )

    monkeypatch.setattr("cv_agent.api.admin.GitHubAdminService", FakeGitHub)
    response = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")).post(
        "/admin/publish",
        headers={"Authorization": "Bearer admin-secret"},
    )

    assert response.status_code == 502
    assert "GitHub publish failed" in response.json()["detail"]
    assert "secret-token" not in response.text


def test_admin_status_payload_helper_redacts_secrets(tmp_path, monkeypatch):
    from cv_agent.api.admin import build_admin_status_payload

    settings = Settings(
        _env_file=None,
        wiki_dir=str(tmp_path),
        admin_api_key="admin-secret",
        github_token="secret-token",
    )

    class FakeGitHub:
        def __init__(self, settings):
            pass

        def status(self):
            return {
                "configured": True,
                "connected": True,
                "base_branch": "main",
                "pending_wiki_changes": False,
                "error": "failed secret-token",
            }

    monkeypatch.setattr("cv_agent.api.admin.GitHubAdminService", FakeGitHub)

    payload = build_admin_status_payload(settings)

    assert payload["status"] == "ok"
    assert payload["wiki"]["upload_dir"].endswith("raw/uploads")
    assert payload["github"]["connected"] is True
    assert "secret-token" not in str(payload)
