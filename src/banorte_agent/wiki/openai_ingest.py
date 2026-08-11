import json
from pathlib import Path
from typing import Protocol

from openai import OpenAI

from banorte_agent.config import Settings
from banorte_agent.wiki.extractors import ExtractedSource


ALLOWED_PAGE_ROOTS = {
    "sources",
    "entities",
    "education",
    "concepts",
    "projects",
    "skills",
    "questions",
    "syntheses",
}


class TextClient(Protocol):
    def create_response(self, instructions: str, input_text: str) -> str: ...


class OpenAIWikiIngestionClient:
    def __init__(self, settings: Settings, client: object | None = None) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI ingestion")
        self.settings = settings
        self.client = client or OpenAI(api_key=settings.openai_api_key)

    def create_response(self, instructions: str, input_text: str) -> str:
        response = self.client.responses.create(
            model=self.settings.openai_model,
            instructions=instructions,
            input=input_text,
            max_output_tokens=6000,
            text={"format": _json_schema_format()},
        )
        return response.output_text


def build_openai_wiki_pages(
    settings: Settings,
    source_path: Path,
    extracted: ExtractedSource,
    text_client: TextClient,
) -> list[dict[str, object]]:
    response = text_client.create_response(
        instructions=_instructions(),
        input_text=_input_text(settings, source_path, extracted),
    )
    payload = _parse_json(response)
    pages = payload.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("OpenAI ingestion response must include a non-empty pages list")
    return [_validated_page(page) for page in pages]


def _instructions() -> str:
    return """Return strict JSON for an Obsidian-style CV wiki ingestion.

Return strict JSON with this shape:
{"pages":[{"path":"sources/<slug>.md","title":"...","kind":"source","tags":["source","cv"],"body_lines":["..."]}]}

Rules:
- Write in English because backend wiki material is internal implementation context.
- Use concise, source-grounded claims only.
- Include at least one source page under sources/.
- Create useful pages under projects/, concepts/, entities/, education/, skills/, questions/, or syntheses/ when supported.
- Use Obsidian links between pages.
- Put page Markdown in body_lines, one Markdown line per array item. Do not use a long escaped body string.
- Do not include raw PDF or Markdown full text. LaTeX source can be summarized more richly.
- Do not wrap the JSON in Markdown fences.
"""


def _input_text(settings: Settings, source_path: Path, extracted: ExtractedSource) -> str:
    return "\n".join(
        [
            f"Configured model: {settings.openai_model}",
            f"Source path: {source_path}",
            f"Source kind: {extracted.kind}",
            f"Needs OCR: {extracted.needs_ocr}",
            f"SHA256: {extracted.sha256}",
            "",
            "Extracted source text:",
            extracted.text,
        ]
    )


def _parse_json(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        stripped = stripped.removesuffix("```").strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("OpenAI ingestion response must be a JSON object")
    return parsed


def _validated_page(page: object) -> dict[str, object]:
    if not isinstance(page, dict):
        raise ValueError("OpenAI ingestion page must be an object")
    path = page.get("path")
    title = page.get("title")
    metadata = page.get("metadata")
    kind = page.get("kind")
    tags = page.get("tags")
    body = page.get("body")
    body_lines = page.get("body_lines")
    if not isinstance(path, str) or not _is_allowed_path(path):
        raise ValueError(f"OpenAI ingestion page path is not allowed: {path}")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("OpenAI ingestion page title must be a non-empty string")
    if not isinstance(metadata, dict):
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("OpenAI ingestion page kind must be a non-empty string")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError("OpenAI ingestion page tags must be an array of strings")
        metadata = {"kind": kind, "tags": tags}
    if isinstance(body_lines, list) and all(isinstance(line, str) for line in body_lines):
        body = "\n".join(body_lines)
    if not isinstance(body, str) or not body.strip():
        raise ValueError("OpenAI ingestion page body_lines must contain at least one Markdown line")
    return {"path": path, "title": title, "metadata": metadata, "body": body}


def _is_allowed_path(value: str) -> bool:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.suffix != ".md":
        return False
    return len(path.parts) >= 2 and path.parts[0] in ALLOWED_PAGE_ROOTS


def _json_schema_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "name": "wiki_ingestion",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["pages"],
            "properties": {
                "pages": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["path", "title", "kind", "tags", "body_lines"],
                        "properties": {
                            "path": {"type": "string"},
                            "title": {"type": "string"},
                            "kind": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "body_lines": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string"},
                            },
                        },
                    },
                }
            },
        },
    }
