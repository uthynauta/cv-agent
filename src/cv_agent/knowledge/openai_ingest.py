import json
from pathlib import Path
import re
from typing import Protocol

from openai import OpenAI

from cv_agent.config import Settings
from cv_agent.knowledge.extractors import ExtractedSource
from cv_agent.knowledge.repository import validate_relative_path_limits


MAX_MODEL_PAGE_COMPONENT_BYTES = 128


ALLOWED_PAGE_ROOTS = {
    "entities",
    "education",
    "credentials",
    "concepts",
    "experience",
    "projects",
    "publications",
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
    document_id: str,
) -> list[dict[str, object]]:
    canonical_source_path = f"sources/{document_id}.md"
    response = text_client.create_response(
        instructions=_instructions(canonical_source_path),
        input_text=_input_text(settings, source_path, extracted, document_id, canonical_source_path),
    )
    payload = _parse_json(response)
    pages = payload.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("OpenAI ingestion response must include a non-empty pages list")
    validated = [_validated_page(page) for page in pages]
    _validate_page_set(validated, canonical_source_path)
    return validated


def _instructions(canonical_source_path: str) -> str:
    canonical_source_stem = canonical_source_path.removesuffix(".md")
    return f"""Return strict JSON for an Obsidian-style CV wiki ingestion.

Return strict JSON with this shape:
{{"pages":[{{"path":"sources/<model-suggestion>.md","title":"...","kind":"source","tags":["source","cv"],"body_lines":["..."]}}]}}

Rules:
- Write in English because backend wiki material is internal implementation context.
- Use concise, source-grounded claims only.
- Include at most one optional sources/ page as a summary suggestion; if included, use exactly `{canonical_source_path}`; it is not required.
- Create useful pages under knowledge/projects/, knowledge/concepts/, knowledge/entities/, knowledge/education/, knowledge/credentials/, knowledge/experience/, knowledge/publications/, knowledge/skills/, knowledge/questions/, or knowledge/syntheses/ when supported.
- Use Obsidian links between pages.
- Any Obsidian link targeting sources/ must use `{canonical_source_stem}`.
- Every non-source generated page must contain [[{canonical_source_stem}]] as a citation.
- Put page Markdown in body_lines, one Markdown line per array item. Do not use a long escaped body string.
- The source page is only an optional summary suggestion; its path must be exactly `{canonical_source_path}`. Its title, metadata, and extracted text are controlled by the ingestion service.
- Do not include raw extracted source text in generated pages.
- Do not wrap the JSON in Markdown fences.
"""


def _input_text(
    settings: Settings,
    source_path: Path,
    extracted: ExtractedSource,
    document_id: str,
    canonical_source_path: str,
) -> str:
    return "\n".join(
        [
            f"Configured model: {settings.openai_model}",
            f"Source path: {source_path}",
            f"Source kind: {extracted.kind}",
            f"Needs OCR: {extracted.needs_ocr}",
            f"SHA256: {extracted.sha256}",
            f"Document ID: {document_id}",
            f"Canonical source page: {canonical_source_path}",
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
    if "\\" in value or "\x00" in value:
        return False
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.suffix != ".md" or path.as_posix() != value:
        return False
    try:
        validate_relative_path_limits(value)
    except ValueError:
        return False
    if path.parts[:1] == ("sources",):
        return len(path.parts) == 2
    if any(len(part.encode("utf-8")) > MAX_MODEL_PAGE_COMPONENT_BYTES for part in path.parts):
        return False
    return len(path.parts) >= 3 and path.parts[0] == "knowledge" and path.parts[1] in ALLOWED_PAGE_ROOTS


def _validate_page_set(pages: list[dict[str, object]], canonical_source_path: str) -> None:
    paths: set[str] = set()
    source_count = 0
    for page in pages:
        path = str(page["path"])
        if path in paths:
            raise ValueError(f"OpenAI ingestion page path is duplicated: {path}")
        paths.add(path)
        if path.startswith("sources/"):
            source_count += 1
            if source_count > 1:
                raise ValueError("OpenAI ingestion response may include at most one source suggestion")
            if path != canonical_source_path:
                raise ValueError(f"OpenAI source suggestion must use canonical path: {canonical_source_path}")
        has_source_link = _validate_source_links(str(page["body"]), canonical_source_path)
        if not path.startswith("sources/") and not has_source_link:
            raise ValueError(f"OpenAI generated page must cite {canonical_source_path.removesuffix('.md')}: {path}")


def _validate_source_links(body: str, canonical_source_path: str) -> bool:
    canonical_stem = canonical_source_path.removesuffix(".md")
    found = False
    for match in re.finditer(r"\[\[([^\]]+)\]\]", body):
        target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        if target in {canonical_source_path, canonical_stem}:
            found = True
        if "sources/" in target and target not in {canonical_source_path, canonical_stem}:
            raise ValueError(f"OpenAI source link must target {canonical_stem}: {target}")
    return found


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
