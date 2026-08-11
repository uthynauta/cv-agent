from pathlib import Path

import pytest

from banorte_agent.config import Settings
import banorte_agent.wiki.ingest as ingest_module
from banorte_agent.wiki.extractors import ExtractedSource
from banorte_agent.wiki.ingest import IngestionService
from banorte_agent.wiki.openai_ingest import OpenAIWikiIngestionClient
from banorte_agent.wiki.repository import WikiRepository


def test_ingest_file_creates_source_page_and_log(tmp_path: Path):
    raw = tmp_path / "raw" / "cv"
    raw.mkdir(parents=True)
    source = raw / "othon.tex"
    source.write_text(r"\section{Skills} Python, FastAPI, AI agents", encoding="utf-8")
    repo = WikiRepository(tmp_path)
    result = IngestionService(repo).ingest_file(source)
    assert result.source_page == tmp_path / "sources" / "othon.md"
    text = result.source_page.read_text(encoding="utf-8")
    assert "Python, FastAPI, AI agents" in text
    assert "sha256:" in text
    assert "needs_ocr: false" in text
    assert "## Extracted Text" in text
    assert "ingest | othon.tex" in (tmp_path / "log.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(("suffix", "kind"), [(".md", "markdown"), (".pdf", "pdf")])
def test_non_latex_ingest_does_not_copy_full_source_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str, kind: str
):
    raw = tmp_path / "raw" / "documents"
    raw.mkdir(parents=True)
    source = raw / f"private{suffix}"
    source.write_bytes(b"placeholder")
    private_text = "private-start " + ("confidential material " * 200) + " private-end"
    extracted = ExtractedSource(source, private_text, kind, False, "a" * 64)
    monkeypatch.setattr(ingest_module, "extract_source", lambda path: extracted)

    result = IngestionService(WikiRepository(tmp_path)).ingest_file(source)
    generated = result.source_page.read_text(encoding="utf-8")

    assert "content_policy: snippet_only" in generated
    assert "## Extracted Text" not in generated
    assert private_text not in generated
    assert "private-end" not in generated


def test_openai_ingest_writes_structured_wiki_pages(tmp_path: Path):
    raw = tmp_path / "raw" / "cv"
    raw.mkdir(parents=True)
    source = raw / "othon.tex"
    source.write_text(
        r"\section{Experience} Teradata Agentic AI platform \section{Teaching} Developed and taught undergraduate and graduate courses",
        encoding="utf-8",
    )

    class FakeTextClient:
        def create_response(self, instructions: str, input_text: str) -> str:
            assert "Return strict JSON" in instructions
            assert "Teradata Agentic AI platform" in input_text
            assert "Developed and taught undergraduate and graduate courses" in input_text
            return """
            {
              "pages": [
                {
                  "path": "sources/model-picked-wrong-slug.md",
                  "title": "Othon CV",
                  "metadata": {"kind": "source", "tags": ["source", "cv"]},
                  "body_lines": [
                    "## Summary",
                    "Othon worked on [[../projects/teradata-agentic-ai-platform|Teradata Agentic AI Platform]]."
                  ]
                },
                {
                  "path": "projects/teradata-agentic-ai-platform.md",
                  "title": "Teradata Agentic AI Platform",
                  "metadata": {"kind": "project", "tags": ["project", "agentic-ai"]},
                  "body_lines": ["## Summary", "Enterprise agentic AI platform."]
                },
                {
                  "path": "education/advanced-technology-degree.md",
                  "title": "Advanced Technology Degree",
                  "metadata": {"kind": "education", "tags": ["education"]},
                  "body_lines": ["## Summary", "PhD in Advanced Technology."]
                },
                {
                  "path": "experience/teaching.md",
                  "title": "Teaching Experience",
                  "metadata": {"kind": "experience", "tags": ["experience", "teaching"]},
                  "body_lines": ["## Summary", "Developed and taught undergraduate and graduate courses."]
                },
                {
                  "path": "credentials/llm-course.md",
                  "title": "LLM Course",
                  "metadata": {"kind": "credential", "tags": ["credential", "llm"]},
                  "body_lines": ["## Summary", "Completed LLM coursework."]
                },
                {
                  "path": "publications/image-captioning-metrics.md",
                  "title": "Image Captioning Metrics Paper",
                  "metadata": {"kind": "publication", "tags": ["publication"]},
                  "body_lines": ["## Summary", "Peer-reviewed publication."]
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
    result = IngestionService(WikiRepository(tmp_path), settings, FakeTextClient()).ingest_file(source)

    assert result.source_page == tmp_path / "sources" / "othon.md"
    assert not (tmp_path / "sources" / "model-picked-wrong-slug.md").exists()
    source_text = result.source_page.read_text(encoding="utf-8")
    assert "Teradata Agentic AI Platform" in source_text
    assert "## Extracted Text" in source_text
    assert "Developed and taught undergraduate and graduate courses" in source_text
    assert (tmp_path / "projects" / "teradata-agentic-ai-platform.md").exists()
    assert (tmp_path / "education" / "advanced-technology-degree.md").exists()
    assert (tmp_path / "experience" / "teaching.md").exists()
    assert (tmp_path / "credentials" / "llm-course.md").exists()
    assert (tmp_path / "publications" / "image-captioning-metrics.md").exists()
    index_text = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "[[sources/othon|Othon CV]]" in index_text
    assert "kind: source" in index_text
    assert "tags: source, cv" in index_text
    assert "mode: openai" in (tmp_path / "log.md").read_text(encoding="utf-8")


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
