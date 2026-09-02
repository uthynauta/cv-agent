from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from types import MappingProxyType
from collections.abc import Mapping

from cv_agent.knowledge.documents import KnowledgePage
from cv_agent.knowledge.policy import has_initialized_knowledge
from cv_agent.knowledge.repository import KnowledgeRepository
from cv_agent.knowledge.search import KnowledgeSearch, PageSource, SearchHit


@dataclass(frozen=True)
class KnowledgeSnapshot:
    pages: tuple[KnowledgePage, ...]
    repository_root: Path | None = None

    def __post_init__(self) -> None:
        # Keep the active revision independent from repository-owned pages and
        # nested mutable metadata values.
        pages = tuple(
            KnowledgePage(
                path=page.path,
                title=page.title,
                metadata=_freeze_metadata(page.metadata),
                body=page.body,
            )
            for page in self.pages
        )
        object.__setattr__(self, "pages", pages)

    @classmethod
    def from_repository(cls, repository: KnowledgeRepository) -> "KnowledgeSnapshot":
        return cls(tuple(repository.list_pages()), repository.root)

    def list_pages(self) -> list[KnowledgePage]:
        return [_copy_page(page) for page in self.pages]


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


def _freeze_metadata(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_metadata(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_metadata(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_metadata(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_metadata(item) for item in value)
    return value


def _copy_metadata(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _copy_metadata(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_copy_metadata(item) for item in value]
    if isinstance(value, frozenset):
        return {_copy_metadata(item) for item in value}
    return value


def _copy_page(page: KnowledgePage) -> KnowledgePage:
    return KnowledgePage(
        path=page.path,
        title=page.title,
        metadata=_copy_metadata(page.metadata),
        body=page.body,
    )
