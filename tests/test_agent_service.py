from pathlib import Path

from banorte_agent.agent.service import AgentService
from banorte_agent.config import Settings
from banorte_agent.wiki.repository import WikiRepository
from banorte_agent.wiki.search import WikiSearch


class FakeTextClient:
    def __init__(self) -> None:
        self.instructions = ""
        self.input_text = ""

    def create_response(self, instructions: str, input_text: str) -> str:
        self.instructions = instructions
        self.input_text = input_text
        return "Othon tiene experiencia con FastAPI. Fuentes: [[Python]]"


def test_agent_builds_spanish_grounded_prompt(tmp_path: Path):
    repo = WikiRepository(tmp_path)
    repo.write_page("skills/python.md", "Python", {"kind": "skill"}, "Othon used FastAPI for AI agents.")
    fake = FakeTextClient()
    settings = Settings(openai_api_key="test-key", grounding_mode="strict")
    service = AgentService(settings, WikiSearch(repo), fake)
    answer = service.answer("¿Qué experiencia tiene con FastAPI?")
    assert "Fuentes: [[Python]]" in answer
    assert "Answer in Spanish" in fake.instructions
    assert "strict grounding mode" in fake.instructions
    assert "[[Python]]" in fake.input_text
