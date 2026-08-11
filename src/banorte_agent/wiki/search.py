from dataclasses import dataclass
from pathlib import Path
import re

from banorte_agent.wiki.repository import WikiRepository


@dataclass(frozen=True)
class SearchHit:
    path: Path
    title: str
    excerpt: str
    score: float


class WikiSearch:
    def __init__(self, repository: WikiRepository) -> None:
        self.repository = repository

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        terms = _terms(query)
        if not terms:
            return []
        hits: list[SearchHit] = []
        for page in self.repository.list_pages():
            haystack = " ".join([page.title, str(page.metadata), page.body])
            score = _score(haystack, terms)
            if score > 0:
                hits.append(SearchHit(page.path, page.title, _excerpt(page.body, terms), score))
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]


def _terms(query: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9]+", query) if len(term) > 2]


def _score(text: str, terms: list[str]) -> float:
    lowered = text.lower()
    return float(sum(lowered.count(term) for term in terms))


def _excerpt(body: str, terms: list[str]) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", body.replace("\n", " "))
    for sentence in sentences:
        if any(term in sentence.lower() for term in terms):
            return sentence[:500]
    return body.replace("\n", " ")[:500]
