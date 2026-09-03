"""Bounded language selection and response policy for the agent."""

import re
import unicodedata
from typing import Literal

Language = Literal["es", "en"]
ConfiguredLanguage = Literal["auto", "es", "en"]

_CITATION_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
_SPANISH_WORDS = {
    "ademas", "con", "como", "cuenta", "de", "del", "donde", "el", "en", "es",
    "experiencia", "hay", "la", "las", "los", "para", "por", "que", "qué", "sobre",
    "formacion", "fuentes", "habilidades", "informacion", "ingenieria", "lidero",
    "posee", "publicaciones", "respuesta", "respaldada", "sobre", "tiene", "trabajo",
    "una", "y", "¿qué",
}
_ENGLISH_WORDS = {
    "a", "about", "an", "and", "are", "can", "does", "for", "has", "have", "how",
    "in", "is", "of", "on", "or", "tell", "the", "this", "to", "used", "what", "with",
}


class LanguagePolicy:
    def __init__(self, configured: ConfiguredLanguage | str) -> None:
        if configured not in {"auto", "es", "en"}:
            raise ValueError("agent_language must be 'auto', 'es', or 'en'")
        self.configured: ConfiguredLanguage = configured  # type: ignore[assignment]

    def effective_language(self, question: str) -> Language:
        if self.configured != "auto":
            return self.configured
        normalized = _normalize(question)
        tokens = set(re.findall(r"[a-z]+", normalized))
        spanish_score = len(tokens & _SPANISH_WORDS)
        english_score = len(tokens & _ENGLISH_WORDS)
        if re.search(r"[¿¡áéíóúüñ]", question.casefold()):
            spanish_score += 2
        return "es" if spanish_score > english_score else "en"

    @staticmethod
    def instruction(effective: Language) -> str:
        if effective == "es":
            return "Answer in Spanish. Use clear, concise, natural language."
        return "Answer in English. Use clear, concise, natural language."

    @staticmethod
    def sources_label(effective: Language) -> str:
        return "Fuentes:" if effective == "es" else "Sources:"

    def validate(self, answer: str, effective: Language) -> bool:
        lines = [line.strip() for line in answer.strip().splitlines() if line.strip()]
        if not lines or not _is_sources_line(lines[-1], effective):
            return False
        body = _CITATION_RE.sub("", " ".join(lines[:-1]))
        if not body.strip() or not _looks_like(body, effective):
            return False
        return bool(_CITATION_RE.findall(lines[-1]))

    def fallback(self, effective: Language, source_titles: list[str]) -> str:
        label = self.sources_label(effective)
        if not source_titles:
            if effective == "es":
                return f"No pude generar una respuesta respaldada por la base de conocimiento.\n{label} ninguna."
            return f"I could not generate a grounded answer from the knowledge base.\n{label} none."
        citations = ", ".join(f"[[{title}]]" for title in source_titles)
        if effective == "es":
            message = "No pude generar una respuesta respaldada por las fuentes recuperadas. La información disponible no permite responder con seguridad."
        else:
            message = "I could not generate a grounded answer from the retrieved sources. The available information is insufficient to answer safely."
        return f"{message}\n{label} {citations}"


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _looks_like(value: str, language: Language) -> bool:
    normalized = _normalize(value)
    tokens = set(re.findall(r"[a-z]+", normalized))
    markers = _SPANISH_WORDS if language == "es" else _ENGLISH_WORDS
    other = _ENGLISH_WORDS if language == "es" else _SPANISH_WORDS
    marker_count = len(tokens & markers)
    if language == "es" and re.search(r"[áéíóúüñ]", value.casefold()):
        marker_count = max(marker_count, 1)
    required = 1 if language == "es" and re.search(r"[áéíóúüñ]", value.casefold()) else (2 if language == "es" else 1)
    return marker_count >= required


def _is_sources_line(line: str, effective: Language) -> bool:
    normalized = re.sub(r"^\*{1,2}\s*", "", line.strip())
    normalized = re.sub(r"\s*\*{1,2}\s*:", ":", normalized)
    return normalized.startswith(LanguagePolicy.sources_label(effective))
