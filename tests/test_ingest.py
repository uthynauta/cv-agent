from datetime import datetime
import inspect
from pathlib import Path

import pytest

import cv_agent.knowledge.ingest as ingest_module
from cv_agent.config import Settings
from cv_agent.knowledge.extractors import ExtractedSource
from cv_agent.knowledge.frontmatter import load_frontmatter
from cv_agent.knowledge.ingest import IngestionService, document_id_for_path
from cv_agent.knowledge.openai_ingest import OpenAIWikiIngestionClient
from cv_agent.knowledge.repository import KnowledgeRepository


@pytest.mark.parametrize(
    ("suffix", "kind", "media_type"),
    [
        (".pdf", "pdf", "application/pdf"),
        (".md", "markdown", "text/markdown"),
        (".tex", "latex", "application/x-tex"),
    ],
)
def test_ingest_file_writes_complete_versioned_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    kind: str,
    media_type: str,
):
    source = tmp_path / f"approved{suffix}"
    source.write_bytes(b"approved source bytes")
    private_text = "private-start\nconfidential material\nprivate-end"
    extracted = ExtractedSource(source, private_text, kind, suffix == ".pdf", "a" * 64)
    monkeypatch.setattr(ingest_module, "extract_source", lambda path: extracted)

    result = IngestionService(KnowledgeRepository(tmp_path)).ingest_file(source, "doc-123")

    assert result.document_id == "doc-123"
    assert result.source_path == source
    assert result.source_page == tmp_path / "sources" / "doc-123.md"
    assert result.generated_pages == ()
    assert result.needs_ocr is (suffix == ".pdf")
    generated = result.source_page.read_text(encoding="utf-8")
    metadata, body = load_frontmatter(generated)
    assert metadata["title"] == "approved"
    assert metadata["kind"] == "source"
    assert metadata["document_id"] == "doc-123"
    assert metadata["original_filename"] == f"approved{suffix}"
    assert metadata["media_type"] == media_type
    assert metadata["content_sha256"] == "a" * 64
    assert metadata["extractor_version"] == "1"
    assert metadata["needs_ocr"] is (suffix == ".pdf")
    assert metadata["tags"] == ["source", kind]
    datetime.fromisoformat(metadata["uploaded_at"])
    assert "## Extracted Text" in body
    assert private_text in body
    assert not (tmp_path / "index.md").exists()
    assert not (tmp_path / "log.md").exists()
    assert (tmp_path / "knowledge" / "index.md").exists()
    assert (tmp_path / "knowledge" / "log.md").exists()


@pytest.mark.parametrize(
    "document_id",
    ["", ".", "..", "../escape", "/absolute", "nested/id", r"nested\\id", "has space", "ends.md", "bad\nvalue", "é"],
)
def test_ingest_file_rejects_unsafe_document_id(tmp_path: Path, document_id: str):
    source = tmp_path / "source.md"
    source.write_text("source", encoding="utf-8")

    with pytest.raises(ValueError, match="document_id"):
        IngestionService(KnowledgeRepository(tmp_path)).ingest_file(source, document_id)


def test_ingest_file_requires_explicit_document_id():
    parameter = inspect.signature(IngestionService.ingest_file).parameters["document_id"]
    assert parameter.default is inspect.Parameter.empty


def test_document_id_for_path_is_stable_from_declared_relative_root(tmp_path: Path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = first_root / "raw" / "nested" / "cv.md"
    second = second_root / "raw" / "nested" / "cv.md"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("same", encoding="utf-8")
    second.write_text("same", encoding="utf-8")

    assert document_id_for_path(first, first_root) == document_id_for_path(second, second_root)
    assert len(document_id_for_path(first, first_root)) <= 128


def test_document_id_for_path_caps_long_stems(tmp_path: Path):
    source = tmp_path / ("x" * 200 + ".md")
    source.write_text("source", encoding="utf-8")

    document_id = document_id_for_path(source)

    assert len(document_id) <= 128
    assert not document_id.lower().endswith(".md")


def test_openai_ingest_writes_generated_pages_under_knowledge_and_source_is_model_immutable(
    tmp_path: Path,
):
    source = tmp_path / "original-name.tex"
    source.write_text("source", encoding="utf-8")

    class FakeTextClient:
        def create_response(self, instructions: str, input_text: str) -> str:
            assert "knowledge/projects/" in instructions
            assert "optional summary suggestion" in instructions
            assert "at most one optional sources/" in instructions
            assert "it is not required" in instructions
            assert "at least one source page" not in instructions
            assert "original-name.tex" in input_text
            return """
            {
              "pages": [
                {
                  "path": "sources/doc-123.md",
                  "title": "Model Override",
                  "kind": "evil",
                  "tags": ["wrong"],
                  "body_lines": ["Model replaced source"]
                },
                {
                  "path": "knowledge/projects/teradata.md",
                  "title": "Teradata",
                  "kind": "project",
                  "tags": ["project"],
                  "body_lines": ["## Summary", "Project page cites [[sources/doc-123]]."]
                }
              ]
            }
            """

    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        ingestion_mode="openai",
        openai_model="gpt-5.6-luna",
    )
    result = IngestionService(KnowledgeRepository(tmp_path), settings, FakeTextClient()).ingest_file(
        source, "doc-123"
    )

    assert result.source_page == tmp_path / "sources" / "doc-123.md"
    assert result.generated_pages == (tmp_path / "knowledge" / "projects" / "teradata.md",)
    source_text = result.source_page.read_text(encoding="utf-8")
    metadata, body = load_frontmatter(source_text)
    assert metadata["title"] == "original-name"
    assert metadata["kind"] == "source"
    assert metadata["document_id"] == "doc-123"
    assert metadata["tags"] == ["source", "latex"]
    assert "Model replaced source" in body
    assert "source" in body
    assert (tmp_path / "knowledge" / "projects" / "teradata.md").exists()
    assert not (tmp_path / "projects" / "teradata.md").exists()


@pytest.mark.parametrize(
    "response",
    [
        """{"pages": [
          {"path": "knowledge/projects/a.md", "title": "A", "kind": "project", "tags": ["project"], "body_lines": ["A"]},
          {"path": "knowledge/projects/a.md", "title": "A2", "kind": "project", "tags": ["project"], "body_lines": ["A2"]}
        ]}""",
        """{"pages": [
          {"path": "knowledge/projects/a.md", "title": "A", "kind": "project", "tags": ["project"], "body_lines": ["See [[sources/other-doc]]"]}
        ]}""",
        """{"pages": [
          {"path": "sources/other-doc.md", "title": "Wrong", "kind": "source", "tags": ["source"], "body_lines": ["Wrong"]}
        ]}""",
        """{"pages": [
          {"path": "sources/doc-123.md", "title": "One", "kind": "source", "tags": ["source"], "body_lines": ["One"]},
          {"path": "sources/doc-123.md", "title": "Two", "kind": "source", "tags": ["source"], "body_lines": ["Two"]}
        ]}""",
    ],
)
def test_openai_rejects_invalid_pages_before_any_write(tmp_path: Path, response: str):
    source = tmp_path / "source.md"
    source.write_text("source", encoding="utf-8")

    class FakeTextClient:
        def create_response(self, instructions: str, input_text: str) -> str:
            assert "sources/doc-123.md" in instructions
            assert "sources/doc-123.md" in input_text
            return response

    settings = Settings(_env_file=None, openai_api_key="test-key", ingestion_mode="openai")
    with pytest.raises(ValueError):
        IngestionService(KnowledgeRepository(tmp_path), settings, FakeTextClient()).ingest_file(
            source, "doc-123"
        )

    assert not (tmp_path / "sources").exists()
    assert not (tmp_path / "knowledge" / "projects" / "a.md").exists()


def test_openai_allows_generated_pages_without_source_suggestion(tmp_path: Path):
    source = tmp_path / "source.md"
    source.write_text("source", encoding="utf-8")

    class FakeTextClient:
        def create_response(self, instructions: str, input_text: str) -> str:
            return """{"pages": [
              {"path": "knowledge/projects/a.md", "title": "A", "kind": "project", "tags": ["project"], "body_lines": ["A"]}
            ]}"""

    settings = Settings(_env_file=None, openai_api_key="test-key", ingestion_mode="openai")
    result = IngestionService(KnowledgeRepository(tmp_path), settings, FakeTextClient()).ingest_file(
        source, "doc-123"
    )

    assert result.source_page == tmp_path / "sources" / "doc-123.md"
    assert result.generated_pages == (tmp_path / "knowledge" / "projects" / "a.md",)


def test_openai_ingestion_client_requests_json_schema_output():
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        ingestion_mode="openai",
        openai_model="gpt-5.6-luna",
    )

    class FakeResponses:
        def __init__(self) -> None:
            self.kwargs = {}

        def create(self, **kwargs):
            self.kwargs = kwargs

            class Response:
                output_text = '{"pages":[]}'

            return Response()

    responses = FakeResponses()

    class FakeOpenAI:
        def __init__(self) -> None:
            self.responses = responses

    client = OpenAIWikiIngestionClient(settings, FakeOpenAI())
    client.create_response("instructions", "input")

    assert responses.kwargs["model"] == "gpt-5.6-luna"
    assert responses.kwargs["max_output_tokens"] == 6000
    assert responses.kwargs["text"]["format"]["type"] == "json_schema"
    assert responses.kwargs["text"]["format"]["strict"] is True
    page_schema = responses.kwargs["text"]["format"]["schema"]["properties"]["pages"]["items"]
    assert page_schema["required"] == ["path", "title", "kind", "tags", "body_lines"]
    assert "metadata" not in page_schema["properties"]
