from hashlib import sha256

from fastapi.testclient import TestClient
import pytest

from cv_agent.config import Settings
from cv_agent.knowledge.frontmatter import dump_frontmatter
from cv_agent.knowledge.storage import ensure_data_storage
from cv_agent.main import create_app


DOCUMENT_ID = "candidate-123"
PDF_BYTES = b"%PDF-1.4\nSynthetic processed profile\n%%EOF\n"
EXTRACTED_BODY = "# Candidate\n\n## Extracted Text\n\nCandidate has Python experience."
ROUTE = f"/v1/documents/{DOCUMENT_ID}/original"


def seeded_app(tmp_path, *, metadata=None, body=EXTRACTED_BODY, payload=PDF_BYTES):
    paths = ensure_data_storage(tmp_path / "data")
    record = {
        "kind": "source",
        "document_id": DOCUMENT_ID,
        "original_filename": "Candidate.pdf",
        "media_type": "application/pdf",
        "content_sha256": sha256(payload).hexdigest(),
    }
    record.update(metadata or {})
    source = paths.sources / f"{DOCUMENT_ID}.md"
    source.write_text(dump_frontmatter(record, body), encoding="utf-8")
    (paths.documents / f"{DOCUMENT_ID}.pdf").write_bytes(payload)
    app = create_app(
        Settings(_env_file=None, data_dir=paths.root, agent_api_key="private-answer-key"),
        agent_answerer=lambda text, instructions=None: "ok",
    )
    return app, source


def test_processed_pdf_is_public_with_inline_safe_headers(tmp_path):
    app, _ = seeded_app(tmp_path)

    response = TestClient(app).get(ROUTE)

    assert response.status_code == 200
    assert response.content == PDF_BYTES
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'inline; filename="Candidate.pdf"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert str(tmp_path) not in str(response.headers)


@pytest.mark.parametrize("media_type", [None, "application/pdf"])
def test_legacy_pdf_with_optional_media_type_is_public(tmp_path, media_type):
    app, _ = seeded_app(tmp_path, metadata={"media_type": media_type})
    assert TestClient(app).get(ROUTE).status_code == 200


def test_download_filename_cannot_inject_headers_or_paths(tmp_path):
    app, _ = seeded_app(
        tmp_path, metadata={"original_filename": '../../Résumé"\r\nX-Evil: yes.pdf'}
    )
    response = TestClient(app).get(ROUTE)

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'inline; filename="Resume-X-Evil-yes.pdf"'
    assert "x-evil" not in response.headers


@pytest.mark.parametrize(
    "metadata",
    [
        {"original_filename": "Candidate.md", "media_type": "text/markdown"},
        {"original_filename": "Candidate.tex", "media_type": "application/x-tex"},
        {"original_filename": None},
        {"media_type": "text/html"},
        {"media_type": ""},
        {"media_type": ["application/pdf"]},
        {"kind": "page"},
        {"document_id": "other-candidate"},
        {"content_sha256": "a" * 64},
        {"content_sha256": "invalid-digest"},
    ],
)
def test_ineligible_source_metadata_is_not_public(tmp_path, metadata):
    app, _ = seeded_app(tmp_path, metadata=metadata)
    response = TestClient(app).get(ROUTE)
    assert response.status_code == 404
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize(
    "body",
    [
        "# Candidate\n\nA summary without extracted text.",
        "## Extracted Text\n\nNo selectable text extracted.",
        "## Extracted Text\n\n<!-- hidden text -->",
        "## Extracted Text\n\n## Empty heading",
    ],
)
def test_source_without_meaningful_extracted_text_is_not_public(tmp_path, body):
    app, _ = seeded_app(tmp_path, body=body)
    assert TestClient(app).get(ROUTE).status_code == 404


def test_unprocessed_original_without_source_is_not_public(tmp_path):
    paths = ensure_data_storage(tmp_path / "data")
    (paths.documents / f"{DOCUMENT_ID}.pdf").write_bytes(PDF_BYTES)
    app = create_app(Settings(_env_file=None, data_dir=paths.root), agent_answerer=lambda *args: "ok")
    assert TestClient(app).get(ROUTE).status_code == 404


def test_generated_page_cannot_publish_an_original(tmp_path):
    app, source = seeded_app(tmp_path)
    source.rename(app.state.data_paths.knowledge / source.name)
    app.state.active_knowledge.reload(app.state.repository)
    assert TestClient(app).get(ROUTE).status_code == 404


def test_nested_source_page_is_not_canonical(tmp_path):
    app, source = seeded_app(tmp_path)
    nested = source.parent / "nested"
    nested.mkdir()
    source.rename(nested / source.name)
    app.state.active_knowledge.reload(app.state.repository)
    assert TestClient(app).get(ROUTE).status_code == 404


@pytest.mark.parametrize("action", ["missing", "symlink", "directory", "fifo", "changed"])
def test_original_must_still_be_the_verified_regular_pdf(tmp_path, action):
    app, _ = seeded_app(tmp_path)
    original = app.state.data_paths.documents / f"{DOCUMENT_ID}.pdf"
    original.unlink()
    if action == "symlink":
        outside = tmp_path / "outside.pdf"
        outside.write_bytes(PDF_BYTES)
        original.symlink_to(outside)
    elif action == "directory":
        original.mkdir()
    elif action == "fifo":
        import os
        os.mkfifo(original)
    elif action == "changed":
        original.write_bytes(b"%PDF-1.4\nUnprocessed replacement\n%%EOF\n")

    assert TestClient(app).get(ROUTE).status_code == 404


def test_documents_directory_symlink_is_rejected_after_startup(tmp_path):
    app, _ = seeded_app(tmp_path)
    documents = app.state.data_paths.documents
    outside = tmp_path / "outside"
    documents.rename(outside)
    documents.symlink_to(outside, target_is_directory=True)
    assert TestClient(app).get(ROUTE).status_code == 404


def test_matching_digest_without_pdf_signature_is_not_public(tmp_path):
    app, _ = seeded_app(tmp_path, payload=b"An uploaded file that is not PDF bytes.")
    assert TestClient(app).get(ROUTE).status_code == 404


@pytest.mark.parametrize("document_id", ["bad%5Cname", "%00", "candidate.md", "a" * 129, "../secret"])
def test_malformed_ids_return_not_found(tmp_path, document_id):
    app, _ = seeded_app(tmp_path)
    response = TestClient(app).get(f"/v1/documents/{document_id}/original")
    assert response.status_code == 404
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize("action", ["delete", "replace"])
def test_deleted_or_replaced_active_source_is_unavailable_immediately(tmp_path, action):
    app, source = seeded_app(tmp_path)
    client = TestClient(app)
    assert client.get(ROUTE).status_code == 200

    if action == "delete":
        source.unlink()
    else:
        source.write_text(
            dump_frontmatter(
                {"kind": "source", "document_id": DOCUMENT_ID,
                 "original_filename": "Candidate.md", "content_sha256": sha256(PDF_BYTES).hexdigest()},
                EXTRACTED_BODY,
            ),
            encoding="utf-8",
        )
    app.state.active_knowledge.reload(app.state.repository)

    assert client.get(ROUTE).status_code == 404


def test_route_streams_verified_descriptor_after_original_path_is_swapped(tmp_path, monkeypatch):
    from cv_agent.knowledge.public_pdfs import ProcessedPdfCatalog

    app, _ = seeded_app(tmp_path)
    original = app.state.data_paths.documents / f"{DOCUMENT_ID}.pdf"
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4\nPrivate unprocessed bytes\n%%EOF\n")
    open_pdf = ProcessedPdfCatalog.open_pdf
    opened = []

    def open_then_swap(self, document_id):
        verified = open_pdf(self, document_id)
        assert verified is not None
        opened.append(verified)
        original.unlink()
        original.symlink_to(outside)
        return verified

    monkeypatch.setattr(ProcessedPdfCatalog, "open_pdf", open_then_swap)
    response = TestClient(app).get(ROUTE)

    assert response.status_code == 200
    assert response.content == PDF_BYTES
    assert opened[0].handle.closed


def test_route_preserves_verified_bytes_after_in_place_original_overwrite(tmp_path, monkeypatch):
    from cv_agent.knowledge.public_pdfs import ProcessedPdfCatalog

    app, _ = seeded_app(tmp_path)
    original = app.state.data_paths.documents / f"{DOCUMENT_ID}.pdf"
    original_inode = original.stat().st_ino
    open_pdf = ProcessedPdfCatalog.open_pdf
    opened = []

    def open_then_overwrite(self, document_id):
        verified = open_pdf(self, document_id)
        assert verified is not None
        opened.append(verified)
        original.write_bytes(b"%PDF-1.4\nUnprocessed in-place replacement\n%%EOF\n")
        assert original.stat().st_ino == original_inode
        return verified

    monkeypatch.setattr(ProcessedPdfCatalog, "open_pdf", open_then_overwrite)
    response = TestClient(app).get(ROUTE)

    assert response.status_code == 200
    assert response.content == PDF_BYTES
    assert opened[0].handle.closed


def test_verified_snapshot_descriptor_rejects_in_place_writes(tmp_path):
    import os
    from cv_agent.knowledge.public_pdfs import ProcessedPdfCatalog

    app, _ = seeded_app(tmp_path)
    catalog = ProcessedPdfCatalog(app.state.data_paths, app.state.active_knowledge)
    verified = catalog.open_pdf(DOCUMENT_ID)
    assert verified is not None
    writable = os.open(f"/proc/self/fd/{verified.handle.fileno()}", os.O_RDWR)
    try:
        with pytest.raises(PermissionError):
            os.pwrite(writable, b"Unprocessed replacement", 0)
        assert b"".join(verified.iter_bytes()) == PDF_BYTES
    finally:
        os.close(writable)
        verified.close()


@pytest.mark.parametrize(("extra_bytes", "status"), [(0, 200), (1, 404)])
def test_public_pdf_snapshot_size_boundary(tmp_path, extra_bytes, status):
    payload = PDF_BYTES + b"\0" * (16 * 1024 * 1024 + extra_bytes - len(PDF_BYTES))
    app, _ = seeded_app(tmp_path, payload=payload)

    response = TestClient(app).get(ROUTE)

    assert response.status_code == status
    if status == 200:
        assert response.content == payload
    else:
        assert response.json() == {"detail": "document not found"}


def test_describe_pdf_uses_pinned_pages_and_only_returns_public_metadata(tmp_path):
    from cv_agent.knowledge.public_pdfs import ProcessedPdfCatalog

    app, source = seeded_app(tmp_path)
    active = app.state.active_knowledge
    pinned = active.list_pages()
    source.unlink()
    active.reload(app.state.repository)
    catalog = ProcessedPdfCatalog(app.state.data_paths, active)

    assert catalog.describe_pdf(DOCUMENT_ID, pinned) == {"filename": "Candidate.pdf", "path": ROUTE}
    assert catalog.describe_pdf(DOCUMENT_ID, active.list_pages()) is None
    assert catalog.open_pdf(DOCUMENT_ID) is None


def test_describe_pdf_rejects_missing_or_changed_original_even_with_pinned_pages(tmp_path):
    from cv_agent.knowledge.public_pdfs import ProcessedPdfCatalog

    app, _ = seeded_app(tmp_path)
    pinned = app.state.active_knowledge.list_pages()
    catalog = ProcessedPdfCatalog(app.state.data_paths, app.state.active_knowledge)
    original = app.state.data_paths.documents / f"{DOCUMENT_ID}.pdf"
    original.write_bytes(b"%PDF-1.4\nNew content\n")
    assert catalog.describe_pdf(DOCUMENT_ID, pinned) is None
    original.unlink()
    assert catalog.describe_pdf(DOCUMENT_ID, pinned) is None
