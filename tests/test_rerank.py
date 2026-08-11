from pathlib import Path

from banorte_agent.agent.rerank import LLMReranker
from banorte_agent.wiki.search import SearchHit


class FakeTextClient:
    def __init__(self, output: str) -> None:
        self.instructions = ""
        self.input_text = ""
        self.output = output

    def create_response(self, instructions: str, input_text: str) -> str:
        self.instructions = instructions
        self.input_text = input_text
        return self.output


def test_llm_reranker_selects_hits_by_path():
    hits = [
        SearchHit(Path("wiki/skills/python.md"), "Python", "FastAPI", 1.0),
        SearchHit(Path("wiki/education/phd.md"), "PhD", "Doctoral degree", 1.0),
        SearchHit(Path("wiki/projects/agentic.md"), "Agentic AI", "Agents", 1.0),
    ]
    client = FakeTextClient('{"selected_paths":["wiki/education/phd.md","wiki/projects/agentic.md"]}')
    reranker = LLMReranker(client, answer_top_k=2)

    selected = reranker.rerank("¿Qué educación formal posee Othón?", hits)

    assert [hit.title for hit in selected] == ["PhD", "Agentic AI"]
    assert "selected_paths" in client.instructions
    assert "wiki/education/phd.md" in client.input_text


def test_llm_reranker_falls_back_to_original_hits_on_invalid_json():
    hits = [
        SearchHit(Path("wiki/skills/python.md"), "Python", "FastAPI", 1.0),
        SearchHit(Path("wiki/education/phd.md"), "PhD", "Doctoral degree", 1.0),
    ]
    reranker = LLMReranker(FakeTextClient("not json"), answer_top_k=1)

    assert reranker.rerank("question", hits) == hits[:1]
