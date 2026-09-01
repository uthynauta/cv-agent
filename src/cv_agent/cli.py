from pathlib import Path
import argparse

from cv_agent.config import get_settings
from cv_agent.knowledge.ingest import IngestionService, document_id_for_path
from cv_agent.knowledge.repository import KnowledgeRepository


def main() -> None:
    parser = argparse.ArgumentParser(prog="cv-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("path")
    args = parser.parse_args()

    if args.command == "ingest":
        settings = get_settings()
        repo = KnowledgeRepository(Path(settings.wiki_dir))
        service = IngestionService(repo, settings)
        target = Path(args.path)
        results = (
            service.ingest_directory(target)
            if target.is_dir()
            else [service.ingest_file(target, document_id_for_path(target))]
        )
        for result in results:
            print(f"ingested {result.source_path} -> {result.source_page}")
