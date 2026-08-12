from typing import Any

from pydantic import BaseModel, Field, field_validator

MAX_INPUT_CHARS = 4000
MAX_INSTRUCTIONS_CHARS = 1000
MAX_MODEL_CHARS = 128


class ResponseRequest(BaseModel):
    model: str | None = Field(default=None, max_length=MAX_MODEL_CHARS)
    input: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)
    instructions: str | None = Field(default=None, max_length=MAX_INSTRUCTIONS_CHARS)

    @field_validator("input", mode="before")
    @classmethod
    def normalize_input(cls, value: Any) -> str:
        text = _extract_input_text(value)
        if text is None:
            return value
        return text


class IngestRequest(BaseModel):
    path: str


def _extract_input_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _extract_input_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts) if parts else None
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        content = value.get("content")
        if content is not None:
            return _extract_input_text(content)
    return None
