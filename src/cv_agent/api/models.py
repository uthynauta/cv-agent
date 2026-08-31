import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

MAX_INPUT_CHARS = 4000
MAX_INSTRUCTIONS_CHARS = 1000
MAX_MODEL_CHARS = 128
MAX_TRANSCRIPT_CONTEXT_CHARS = 1000
MAX_TRANSCRIPT_TURN_CHARS = 220
MAX_PREVIOUS_ASSISTANT_ANSWER_CHARS = 700
SHORT_FOLLOWUP_RE = re.compile(
    r"^\s*(s[ií](?:\s+por\s+favor)?|claro|ok|okay|dale|adelante|por\s+favor|"
    r"por\s+(empresa|proyecto|tecnolog[ií]a|tecnologias|años|fechas|cargo|puesto)s?)"
    r"[.!?¡¿\s]*$",
    re.IGNORECASE,
)


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
        transcript_text = _transcript_input_text(value)
        if transcript_text:
            return transcript_text
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


def _transcript_input_text(items: list[Any]) -> str | None:
    latest_index = _latest_user_message_index(items)
    if latest_index is None:
        return None
    latest_text = _message_content_text(items[latest_index])
    if not latest_text:
        return None
    previous_assistant = _previous_assistant_message(items[:latest_index])
    if previous_assistant and _is_short_followup(latest_text):
        previous_answer = _message_content_text(previous_assistant)
        previous_question = _last_question(previous_answer or "")
        if previous_answer and previous_question:
            context = _truncate_text(previous_answer, MAX_PREVIOUS_ASSISTANT_ANSWER_CHARS)
            return (
                "Previous assistant answer for this follow-up:\n"
                f"{context}\n\n"
                "Previous assistant follow-up question:\n"
                f"{previous_question}\n\n"
                "Latest reviewer request:\n"
                f"{latest_text}\n\n"
                "Interpret the latest reviewer request as confirmation or selection for the previous "
                "assistant follow-up. Answer that follow-up directly using the previous assistant answer "
                "and supplied wiki context."
            )
    context_lines = _transcript_context_lines(items[:latest_index])
    if not context_lines:
        return latest_text
    context = _truncate_text("\n".join(context_lines), MAX_TRANSCRIPT_CONTEXT_CHARS)
    return (
        "Conversation context for resolving follow-up references only; do not re-answer it:\n"
        f"{context}\n\n"
        "Latest reviewer request:\n"
        f"{latest_text}"
    )


def _latest_user_message_index(items: list[Any]) -> int | None:
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in {"user", "developer"}:
            continue
        if _message_content_text(item):
            return index
    return None


def _previous_assistant_message(items: list[Any]) -> dict[str, Any] | None:
    for item in reversed(items):
        if isinstance(item, dict) and item.get("role") == "assistant" and _message_content_text(item):
            return item
    return None


def _transcript_context_lines(items: list[Any]) -> list[str]:
    lines: list[str] = []
    for item in items[-6:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in {"user", "assistant", "developer"}:
            continue
        text = _message_content_text(item)
        if not text:
            continue
        label = {"user": "User", "assistant": "Assistant", "developer": "Developer"}[role]
        lines.append(f"{label}: {_truncate_text(text, MAX_TRANSCRIPT_TURN_CHARS)}")
    return lines


def _message_content_text(message: dict[str, Any]) -> str | None:
    content = message.get("content")
    if content is None:
        return None
    return _extract_input_text(content)


def _is_short_followup(value: str) -> bool:
    normalized = value.strip()
    if len(normalized) > 80:
        return False
    return bool(SHORT_FOLLOWUP_RE.match(normalized))


def _last_question(value: str) -> str | None:
    matches = re.findall(r"¿[^?]*\?|[^.?!¿]*\?", value)
    for match in reversed(matches):
        question = match.strip()
        if question:
            return question
    return None


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    if max_chars <= 1:
        return value[:max_chars]
    return value[: max_chars - 1].rstrip() + "…"
