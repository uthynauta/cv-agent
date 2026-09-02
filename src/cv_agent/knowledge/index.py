from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from cv_agent.knowledge.documents import KnowledgePage
from cv_agent.knowledge.policy import has_initialized_knowledge
from cv_agent.knowledge.repository import KnowledgeRepository
from cv_agent.knowledge.search import KnowledgeSearch, PageSource, SearchHit


@dataclass(frozen=True)
class KnowledgeSnapshot:
    pages: tuple[KnowledgePage, ...]
    repository_root: Path | None = None

    @classmethod
    def from_repository(cls, repository: KnowledgeRepository) -> "KnowledgeSnapshot":
        return cls(tuple(repository.list_pages()), repository.root)

    def list_pages(self) -> list[KnowledgePage]:
        return list(self.pages)


class ActiveKnowledge(PageSource):
    def __init__(self, snapshot: KnowledgeSnapshot) -> None:
        self._snapshot = snapshot
        self._lock = Lock()

    @classmethod
    def load(cls, repository: KnowledgeRepository) -> "ActiveKnowledge":
        return cls(KnowledgeSnapshot.from_repository(repository))

    def reload(self, repository: KnowledgeRepository) -> None:
        candidate = KnowledgeSnapshot.from_repository(repository)
        with self._lock:
            self._snapshot = candidate

    def list_pages(self) -> list[KnowledgePage]:
        with self._lock:
            snapshot = self._snapshot
        return snapshot.list_pages()

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        with self._lock:
            snapshot = self._snapshot
        return KnowledgeSearch(snapshot).search(query, limit)

    @property
    def initialized(self) -> bool:
        with self._lock:
            snapshot = self._snapshot
        return has_initialized_knowledge(snapshot.pages, snapshot.repository_root)
