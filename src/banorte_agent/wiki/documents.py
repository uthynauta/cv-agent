from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WikiPage:
    path: Path
    title: str
    metadata: dict[str, object]
    body: str
