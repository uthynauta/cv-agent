from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

from banorte_agent.metrics import SEARCH_HITS
from banorte_agent.wiki.repository import WikiRepository
from banorte_agent.tracing import get_tracer, safe_count_attribute


SPANISH_STOPWORDS = {
    "a", "al", "algo", "como", "con", "cual", "cuando", "de", "del", "donde",
    "el", "ella", "en", "entre", "era", "es", "esta", "este", "fue", "ha", "hace",
    "hizo", "la", "las", "lo", "los", "mas", "para", "por", "que", "quien", "se",
    "sin", "sobre", "su", "sus", "un", "una", "y",
}
QUERY_SYNONYMS = {
    "agente": ["agent", "agentic", "agents"],
    "agent": ["agentic", "agents"],
    "experiencia": ["experience", "experienced"],
    "ia": ["ai"],
    "perfil": ["profile", "summary"],
    "profesional": ["professional"],
    "resumen": ["summary"],
}
SHORT_SIGNAL_TERMS = {"ia", "ai"}


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
        with get_tracer().start_as_current_span("wiki.search") as span:
            span.set_attribute(*safe_count_attribute("query.length", query))
            terms = _terms(query)
            if not terms:
                span.set_attribute("result.count", 0)
                span.set_attribute("result.titles", "")
                SEARCH_HITS.observe(0)
                return []
            hits: list[SearchHit] = []
            for page in self.repository.list_pages():
                passages = _passages(page.body)
                best_passage, passage_score = max(
                    ((passage, _score(passage, terms)) for passage in passages),
                    key=lambda item: item[1],
                    default=("", 0.0),
                )
                title_score = _score(page.title, terms) * 0.35
                metadata_score = _score(" ".join(map(str, page.metadata.values())), terms) * 0.1
                score = passage_score + title_score + metadata_score
                if score > 0:
                    hits.append(SearchHit(page.path, page.title, _excerpt(best_passage), score))
            results = sorted(hits, key=lambda hit: (-hit.score, hit.title.casefold()))[:limit]
            span.set_attribute("result.count", len(results))
            span.set_attribute("result.titles", ", ".join(hit.title for hit in results)[:200])
            SEARCH_HITS.observe(len(results))
            return results


def _terms(query: str) -> list[str]:
    terms: list[str] = []
    for token in _tokens(query):
        if token in SPANISH_STOPWORDS:
            continue
        if len(token) <= 2 and token not in SHORT_SIGNAL_TERMS:
            continue
        terms.append(token)
        terms.extend(QUERY_SYNONYMS.get(token, []))
    return list(dict.fromkeys(terms))


def _score(text: str, terms: list[str]) -> float:
    tokens = _tokens(text)
    counts = {term: tokens.count(term) for term in set(terms)}
    matched = sum(1 for term in set(terms) if counts[term])
    if not matched:
        return 0.0
    frequency = sum(min(counts[term], 3) for term in set(terms))
    coverage = matched / len(set(terms))
    return float(frequency + coverage * 8)


def _tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    return [_stem(token) for token in re.findall(r"[a-z0-9]+", normalized)]


def _stem(token: str) -> str:
    if len(token) > 5 and token.endswith("ces"):
        return token[:-3] + "z"
    if len(token) > 5 and token.endswith("es") and token[-3] not in "aeiou":
        return token[:-2]
    if len(token) > 4 and token.endswith("s") and token[-2] in "aeiou":
        return token[:-1]
    return token


def _passages(body: str) -> list[str]:
    sections: list[tuple[str, list[str]]] = []
    heading = ""
    blocks: list[str] = []

    def flush() -> None:
        if heading or blocks:
            sections.append((heading, blocks.copy()))

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip()
            blocks = []
        else:
            blocks.append(line.lstrip("- "))
    flush()
    if not sections:
        sections = [("", [body])]

    passages: list[str] = []
    for section_heading, section_blocks in sections:
        if not section_blocks:
            passages.append(section_heading)
            continue
        for index in range(len(section_blocks)):
            window = section_blocks[index : index + 3]
            passages.append(". ".join(part for part in [section_heading, *window] if part))
    return passages


def _excerpt(passage: str) -> str:
    return re.sub(r"\s+", " ", passage).strip()[:500]
