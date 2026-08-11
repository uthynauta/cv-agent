import json
from typing import Protocol

from banorte_agent.wiki.search import SearchHit


class TextClient(Protocol):
    def create_response(self, instructions: str, input_text: str) -> str: ...


class LLMReranker:
    def __init__(self, text_client: TextClient, answer_top_k: int) -> None:
        self.text_client = text_client
        self.answer_top_k = answer_top_k

    def rerank(self, question: str, hits: list[SearchHit]) -> list[SearchHit]:
        if not hits:
            return []
        output = self.text_client.create_response(_instructions(), _input_text(question, hits))
        selected_paths = _parse_selected_paths(output)
        by_path = {str(hit.path): hit for hit in hits}
        selected = [by_path[path] for path in selected_paths if path in by_path]
        return (selected or hits)[: self.answer_top_k]


def _instructions() -> str:
    return (
        "You are a retrieval reranker for a CV wiki. "
        "Select only passages that directly help answer the reviewer question. "
        "Return JSON only with this shape: {\"selected_paths\":[\"wiki/path.md\"]}. "
        "Use exact candidate paths. Prefer specific evidence pages over index pages."
    )


def _input_text(question: str, hits: list[SearchHit]) -> str:
    candidates = []
    for index, hit in enumerate(hits, start=1):
        candidates.append(
            "\n".join(
                [
                    f"Candidate {index}",
                    f"path: {hit.path}",
                    f"title: {hit.title}",
                    f"excerpt: {hit.excerpt}",
                ]
            )
        )
    candidate_text = "\n\n".join(candidates)
    return (
        f"Question: {question}\n\n"
        "Candidates:\n"
        f"{candidate_text}"
    )


def _parse_selected_paths(output: str) -> list[str]:
    stripped = output.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        stripped = stripped.removesuffix("```").strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    selected = payload.get("selected_paths")
    if not isinstance(selected, list):
        return []
    return [path for path in selected if isinstance(path, str)]
