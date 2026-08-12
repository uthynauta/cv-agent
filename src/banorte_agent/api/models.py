from typing import Any

from pydantic import BaseModel, Field, field_validator

MAX_INPUT_CHARS = 4000
MAX_INSTRUCTIONS_CHARS = 1000
MAX_MODEL_CHARS = 128


class ResponseRequest(BaseModel):
    model: str | None = None
    input: str = Field(min_length=1)
    instructions: str | None = None

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = _extract_input_text(value) or str(value)
        return text[:MAX_MODEL_CHARS]

    @field_validator("input", mode="before")
    @classmethod
    def normalize_input(cls, value: Any) -> str:
        text = _extract_input_text(value)
        if text is None:
            return value
        return text[:MAX_INPUT_CHARS]

    @field_validator("instructions", mode="before")
    @classmethod
    def normalize_instructions(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = _extract_input_text(value)
        if text is None:
            return str(value)[:MAX_INSTRUCTIONS_CHARS]
        return text[:MAX_INSTRUCTIONS_CHARS]


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
