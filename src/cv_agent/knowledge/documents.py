from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping


@dataclass(frozen=True)
class KnowledgePage:
    path: Path
    title: str
    metadata: Mapping[str, object]
    body: str
