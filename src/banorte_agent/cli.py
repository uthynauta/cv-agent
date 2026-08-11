from pathlib import Path
import argparse

from banorte_agent.config import get_settings
from banorte_agent.wiki.ingest import IngestionService
from banorte_agent.wiki.repository import WikiRepository


def main() -> None:
    parser = argparse.ArgumentParser(prog="banorte-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("path")
    args = parser.parse_args()

    if args.command == "ingest":
        settings = get_settings()
        repo = WikiRepository(Path(settings.wiki_dir))
        service = IngestionService(repo)
        target = Path(args.path)
        results = service.ingest_directory(target) if target.is_dir() else [service.ingest_file(target)]
        for result in results:
            print(f"ingested {result.source_path} -> {result.source_page}")
