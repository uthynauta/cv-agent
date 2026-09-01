import os
from pathlib import Path
from typing import Annotated, cast
from urllib.error import HTTPError, URLError
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status

from cv_agent.admin.github import GitHubAdminService
from cv_agent.api.models import IngestRequest
from cv_agent.config import Settings
from cv_agent.knowledge.extractors import extract_source
from cv_agent.knowledge.ingest import IngestionService, document_id_for_path
from cv_agent.knowledge import ingest as ingest_module
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.repository import KnowledgeRepository, resolve_directory_path
from cv_agent.knowledge.storage import DataPaths, ensure_data_storage, safe_upload_filename


_DEFAULT_EXTRACT_SOURCE = extract_source


def _extract_upload(path: Path):
    # Keep upload tests and callers able to patch either the public admin helper
    # or the extractor used by IngestionService.
    extractor = extract_source if extract_source is not _DEFAULT_EXTRACT_SOURCE else ingest_module.extract_source
    return extractor(path)


def wiki_has_changes(settings: Settings) -> bool:
    return GitHubAdminService(settings).wiki_has_changes()


def _redact_detail(detail: str, settings: Settings) -> str:
    if settings.github_token:
        detail = detail.replace(settings.github_token, "[redacted]")
    return detail


def _github_http_error_detail(exc: HTTPError, settings: Settings) -> str:
    reason = exc.reason or str(exc)
    return _redact_detail(f"GitHub publish failed: {exc.code} {reason}", settings)


def _redact_payload_secrets(value: object, settings: Settings) -> object:
    if isinstance(value, str):
        return _redact_detail(value, settings)
    if isinstance(value, dict):
        return {key: _redact_payload_secrets(item, settings) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_payload_secrets(item, settings) for item in value]
    return value


def _knowledge_initialized(repository: KnowledgeRepository) -> bool:
    from cv_agent.api.health import knowledge_is_initialized

    return knowledge_is_initialized(repository)


def build_admin_status_payload(
    settings: Settings,
    paths: DataPaths | None = None,
    git_store: LocalKnowledgeGit | None = None,
    repository: KnowledgeRepository | None = None,
) -> dict[str, object]:
    paths = paths or ensure_data_storage(settings.data_dir)
    if git_store is None:
        git_store = LocalKnowledgeGit(
            paths.repository, settings.data_git_author_name, settings.data_git_author_email
        )
        git_store.initialize()
    if repository is None:
        repository = KnowledgeRepository(paths.repository)
    try:
        documents = resolve_directory_path(paths.documents)
        head = git_store.head()
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="upload storage is unavailable",
        ) from exc
    return {
        "status": "ok",
        "admin": {"enabled": bool(settings.admin_api_key)},
        "wiki": {
            "dir": settings.wiki_dir,
            "upload_dir": str(documents),
            "upload_dir_writable": documents.exists() and os.access(documents, os.W_OK),
        },
        "ingestion": {"mode": settings.ingestion_mode},
        "knowledge": {
            "initialized": _knowledge_initialized(repository),
            "repository_head": head,
        },
        "repository": {"head": head},
        "paths": {
            "root": str(paths.root),
            "documents": str(paths.documents),
            "repository": str(paths.repository),
            "sources": str(paths.sources),
            "knowledge": str(paths.knowledge),
            "staging": str(paths.staging),
        },
        "github": _redact_payload_secrets(GitHubAdminService(settings).status(), settings),
    }


def publish_wiki_payload(settings: Settings) -> dict[str, object]:
    try:
        return cast(dict[str, object], _redact_payload_secrets(GitHubAdminService(settings).publish(), settings))
    except RuntimeError as exc:
        detail = _redact_detail(str(exc), settings)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc
    except HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_github_http_error_detail(exc, settings)) from exc
    except (URLError, OSError) as exc:
        detail = _redact_detail(f"GitHub publish failed: {exc}", settings)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc


async def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="upload is too large")
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="upload is empty")
    return data


def _markdown_paths(repository: KnowledgeRepository) -> set[Path]:
    root = repository.root
    try:
        return {
            path.resolve()
            for scope in (root / "sources", root / "knowledge")
            for path in scope.rglob("*.md")
            if path.is_file() and not path.is_symlink()
        }
    except OSError:
        return set()


def _markdown_state(repository: KnowledgeRepository, paths: set[Path]) -> dict[Path, bytes]:
    state: dict[Path, bytes] = {}
    for path in paths:
        try:
            state[path] = path.read_bytes()
        except OSError:
            continue
    return state


def _resolved_repository_path(repository_root: Path, path: Path | str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = repository_root / candidate
    return candidate.resolve()


def _cleanup_upload(
    repository: KnowledgeRepository,
    before_markdown: set[Path],
    before_state: dict[Path, bytes],
    document_id: str,
    staging_path: Path,
    original_path: Path,
    original_created: bool,
    generated_paths: tuple[Path, ...] = (),
) -> None:
    paths_to_remove = (staging_path, original_path) if original_created else (staging_path,)
    for path in paths_to_remove:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    repository_root = repository.root.resolve()
    transaction_paths = {
        repository_root / "sources" / f"{document_id}.md",
        repository_root / "knowledge" / "index.md",
        repository_root / "knowledge" / "log.md",
        *(_resolved_repository_path(repository_root, path) for path in generated_paths),
    }
    # OpenAI-generated pages may be written before ingestion raises. Identify
    # only new pages citing this document; unrelated concurrent pages survive.
    for path in _markdown_paths(repository) - before_markdown:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if f"[[sources/{document_id}]]" in text or f"document_id: {document_id}" in text:
            transaction_paths.add(path)
    for path in transaction_paths:
        previous = before_state.get(path)
        try:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(previous)
        except OSError:
            pass


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


async def upload_document_payload(
    settings: Settings,
    paths: DataPaths,
    git_store: LocalKnowledgeGit,
    ingestion: IngestionService,
    file: UploadFile,
) -> dict[str, object]:
    try:
        filename = safe_upload_filename(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    data = await _read_upload(file, settings.admin_upload_max_bytes)
    try:
        staging_dir = resolve_directory_path(paths.staging, create=True)
        documents_dir = resolve_directory_path(paths.documents, create=True)
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="upload storage is unavailable",
        ) from exc
    document_id = uuid4().hex
    staging_path = staging_dir / f"{document_id}-{filename}"
    original_path = documents_dir / f"{document_id}{Path(filename).suffix.lower()}"
    staging_created = False
    try:
        handle = staging_path.open("xb")
        staging_created = True
        with handle:
            handle.write(data)
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="upload ID collision") from exc
    except OSError as exc:
        if staging_created:
            try:
                staging_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="upload storage is unavailable",
        ) from exc

    repository = ingestion.repository
    before_markdown = _markdown_paths(repository)
    repository_root = repository.root.resolve()
    before_state = _markdown_state(repository, before_markdown)
    before_state.update(
        _markdown_state(
            repository,
            {
                repository_root / "sources" / f"{document_id}.md",
                repository_root / "knowledge" / "index.md",
                repository_root / "knowledge" / "log.md",
            },
        )
    )
    try:
        extracted = _extract_upload(staging_path)
    except Exception as exc:
        _cleanup_upload(
            repository,
            before_markdown,
            before_state,
            document_id,
            staging_path,
            original_path,
            False,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="document is unreadable") from exc
    if extracted.needs_ocr:
        _cleanup_upload(
            repository,
            before_markdown,
            before_state,
            document_id,
            staging_path,
            original_path,
            False,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="PDF requires OCR before upload",
        )

    result = None
    original_created = False
    try:
        handle = original_path.open("xb")
        # Exclusive open creates the transaction-owned file before write starts.
        original_created = True
        with handle:
            handle.write(data)
        result = ingestion.ingest_file(original_path, document_id, filename)
        commit = git_store.commit(f"Ingest document {document_id}")
    except HTTPException:
        _cleanup_upload(
            repository,
            before_markdown,
            before_state,
            document_id,
            staging_path,
            original_path,
            original_created,
            tuple(getattr(result, "generated_pages", ())) if result is not None else (),
        )
        raise
    except Exception as exc:
        _cleanup_upload(
            repository,
            before_markdown,
            before_state,
            document_id,
            staging_path,
            original_path,
            original_created,
            tuple(getattr(result, "generated_pages", ())) if result is not None else (),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="document ingestion is unavailable",
        ) from exc
    try:
        staging_path.unlink(missing_ok=True)
    except OSError:
        # Commit already succeeded; leave the artifact for a later bounded cleanup.
        pass
    source_path = str(result.source_page)
    generated_paths = [str(path) for path in getattr(result, "generated_pages", ())]
    return {
        "status": "ok",
        "document": {
            "document_id": getattr(result, "document_id", document_id),
            "filename": filename,
            "path": str(original_path.relative_to(paths.root)),
            "kind": extracted.kind,
            "source": source_path,
            "generated": generated_paths,
        },
        "ingestion": {
            "count": 1,
            "sources": [source_path],
            "generated": generated_paths,
        },
        "revision": {"commit": commit},
        "publish": {
            "pending": wiki_has_changes(settings),
        },
    }


def build_admin_router(
    settings: Settings,
    paths: DataPaths,
    git_store: LocalKnowledgeGit,
    ingestion: IngestionService,
) -> APIRouter:
    def require_admin_key(authorization: Annotated[str | None, Header()] = None) -> None:
        if not settings.admin_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="admin ingest is disabled",
            )
        if authorization != f"Bearer {settings.admin_api_key}":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")

    router = APIRouter(dependencies=[Depends(require_admin_key)])
    @router.post("/admin/ingest")
    def ingest(request: IngestRequest) -> dict[str, object]:
        try:
            requested = Path(request.path).absolute()
            resolve_directory_path(requested.parent)
            path = requested.resolve()
            path.relative_to(paths.root.resolve())
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="data storage is unavailable",
            ) from exc
        allowed_roots = (paths.documents.resolve(), paths.staging.resolve())
        allowed_root = next((root for root in allowed_roots if _is_relative_to(path, root)), None)
        if allowed_root is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="path must be within the mounted data directory",
            )
        results = (
            ingestion.ingest_directory(path)
            if path.is_dir()
            else [ingestion.ingest_file(path, document_id_for_path(path, allowed_root))]
        )
        commit = git_store.commit("Ingest legacy document")
        return {
            "status": "ok",
            "count": len(results),
            "sources": [str(result.source_page) for result in results],
            "revision": {"commit": commit},
        }

    @router.post("/admin/documents")
    async def upload_document(file: UploadFile = File(...)) -> dict[str, object]:
        return await upload_document_payload(settings, paths, git_store, ingestion, file)

    @router.get("/admin/status")
    def admin_status() -> dict[str, object]:
        return build_admin_status_payload(settings, paths, git_store, ingestion.repository)

    @router.post("/admin/publish")
    def publish_wiki() -> dict[str, object]:
        return publish_wiki_payload(settings)

    return router
