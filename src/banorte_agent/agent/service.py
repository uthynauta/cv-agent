from typing import Protocol

from banorte_agent.agent.prompts import build_instructions
from banorte_agent.config import Settings
from banorte_agent.tracing import get_tracer, safe_count_attribute
from banorte_agent.wiki.search import WikiSearch


class TextClient(Protocol):
    def create_response(self, instructions: str, input_text: str) -> str:
        ...


class AgentService:
    def __init__(self, settings: Settings, search: WikiSearch, text_client: TextClient) -> None:
        self.settings = settings
        self.search = search
        self.text_client = text_client

    def answer(self, input_text: str, extra_instructions: str | None = None) -> str:
        with get_tracer().start_as_current_span("agent.answer") as span:
            span.set_attribute("grounding_mode", self.settings.grounding_mode)
            span.set_attribute(*safe_count_attribute("input.length", input_text))
            hits = self.search.search(input_text)
            span.set_attribute("search.hit_count", len(hits))
            context = "\n\n".join(
                f"Source: [[{hit.title}]]\nPath: {hit.path}\nExcerpt: {hit.excerpt}" for hit in hits
            )
            if not context:
                context = "No relevant wiki context found."
            instructions = build_instructions(self.settings.grounding_mode, extra_instructions)
            model_input = f"Wiki context:\n{context}\n\nReviewer question:\n{input_text}"
            return self.text_client.create_response(instructions, model_input)
