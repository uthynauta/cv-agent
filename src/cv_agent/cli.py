from pathlib import Path
import argparse

from cv_agent.config import get_settings
from cv_agent.knowledge.ingest import IngestionService, document_id_for_path
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.repository import KnowledgeRepository
from cv_agent.knowledge.storage import ensure_data_storage


def main() -> None:
    parser = argparse.ArgumentParser(prog="cv-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("path")
    args = parser.parse_args()

    if args.command == "ingest":
        settings = get_settings()
        paths = ensure_data_storage(settings.data_dir)
        git_store = LocalKnowledgeGit(
            paths.repository,
            settings.data_git_author_name,
            settings.data_git_author_email,
        )
        git_store.initialize()
        repo = KnowledgeRepository(paths.repository)
        service = IngestionService(repo, settings)
        target = Path(args.path).expanduser().resolve()
        results = (
            service.ingest_directory(target)
            if target.is_dir()
            else [service.ingest_file(target, document_id_for_path(target, target.parent))]
        )
        commit = git_store.commit("Ingest documents")
        for result in results:
            print(f"ingested {result.source_path} -> {result.source_page}")
        if commit:
            print(f"committed {commit}")
