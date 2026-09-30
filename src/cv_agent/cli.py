from pathlib import Path
import argparse

from cv_agent.config import get_settings
from cv_agent.knowledge.ingest import IngestionService, document_id_for_path
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.migrate import MigrationError, migrate_legacy_wiki
from cv_agent.knowledge.repository import KnowledgeRepository
from cv_agent.knowledge.storage import ensure_data_storage


def _resolve_ingest_target(parser: argparse.ArgumentParser, raw_path: str, documents: Path) -> Path:
    requested = Path(raw_path).expanduser().absolute()
    try:
        relative = requested.relative_to(documents)
    except ValueError:
        parser.error("ingestion path must be inside DATA_DIR/documents and contain no symlink components")

    current = documents
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            parser.error("ingestion path must be inside DATA_DIR/documents and contain no symlink components")

    target = requested.resolve()
    try:
        target.relative_to(documents)
    except ValueError:
        parser.error("ingestion path must be inside DATA_DIR/documents and contain no symlink components")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(prog="cv-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("path")
    migrate_parser = subparsers.add_parser("migrate-data")
    migrate_parser.add_argument("--from-wiki", required=True)
    migrate_parser.add_argument("--to-data-dir", required=True)
    migrate_parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args()

    if args.command == "migrate-data":
        try:
            result = migrate_legacy_wiki(args.from_wiki, args.to_data_dir, args.replace_existing)
        except MigrationError as exc:
            parser.exit(2, f"error: {exc}\n")
        print(f"source_pages={result.source_pages} knowledge_pages={result.knowledge_pages} originals={result.original_documents}")
        print(f"commit={result.commit}")
        return

    if args.command == "ingest":
        settings = get_settings()
        paths = ensure_data_storage(settings.data_dir)
        target = _resolve_ingest_target(parser, args.path, paths.documents)
        git_store = LocalKnowledgeGit(
            paths.repository,
            settings.data_git_author_name,
            settings.data_git_author_email,
        )
        git_store.initialize()
        repo = KnowledgeRepository(paths.repository)
        service = IngestionService(repo, settings)
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


if __name__ == "__main__":
    main()
