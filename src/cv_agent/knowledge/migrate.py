from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shutil
from uuid import uuid4

from cv_agent.knowledge.frontmatter import dump_frontmatter, load_frontmatter
from cv_agent.knowledge.git_store import GitStoreError, LocalKnowledgeGit
from cv_agent.knowledge.storage import SUPPORTED_UPLOAD_EXTENSIONS
from cv_agent.knowledge.validation import KnowledgeValidationError, validate_knowledge


class MigrationError(ValueError):
    """Raised for an unsafe or invalid legacy wiki migration."""


@dataclass(frozen=True)
class MigrationResult:
    commit: str
    source_pages: int
    knowledge_pages: int
    original_documents: int


_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")
_TITLE_SLUG = re.compile(r"[^a-z0-9]+")
_SOURCE_LINK = re.compile(r"\[\[(sources/([^|#\]]+))([^\]]*)\]\]")


def _safe_id(value: str, fallback: str = "document") -> str:
    result = _SAFE_ID.sub("-", value).strip("-_.") or fallback
    return result[:120]


def _source_aliases(title: str) -> set[str]:
    slug = _TITLE_SLUG.sub("-", title.lower()).strip("-")
    return {slug, slug.removesuffix("-source")}


def _canonical_source_id(reference: str, source_ids: list[str], aliases: dict[str, set[str]]) -> str:
    if reference in source_ids:
        return reference
    exact = aliases.get(reference, set())
    if len(exact) == 1:
        return next(iter(exact))
    if not exact and reference.count("-") >= 2:
        # Old wiki pages occasionally have a one-character typo in a source filename.
        exact = {
            source_id for source_id in source_ids
            if len(reference) == len(source_id)
            and sum(left != right for left, right in zip(reference, source_id)) == 1
        }
    if len(exact) == 1:
        return next(iter(exact))
    raise MigrationError(f"unknown source reference: sources/{reference}")


def _resolve_source_links(body: str, source_ids: list[str], aliases: dict[str, set[str]]) -> str:
    def replace(match: re.Match[str]) -> str:
        reference = match.group(2)
        canonical = _canonical_source_id(reference, source_ids, aliases)
        return f"[[sources/{canonical}{match.group(3)}]]"

    return _SOURCE_LINK.sub(replace, body)


def _check_tree(root: Path, label: str) -> Path:
    if not root.is_absolute():
        root = root.absolute()
    if root == Path(root.anchor) or root == Path.cwd().absolute():
        raise MigrationError(f"{label} path is unsafe")
    current = Path(root.anchor)
    for component in root.parts[1:]:
        current /= component
        if current.is_symlink():
            raise MigrationError(f"{label} path contains a symlink")
        if current.exists() and not current.is_dir():
            raise MigrationError(f"{label} must be a local directory")
    return root


def _files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise MigrationError("source tree contains a symlink")
        if path.is_file():
            yield path
        elif not path.is_dir():
            raise MigrationError("source tree contains a special file")


def _matching_original(source: Path, metadata: dict, page: Path) -> Path | None:
    legacy_source_file = metadata.get("source_file")
    if legacy_source_file is not None:
        if not isinstance(legacy_source_file, str) or not legacy_source_file:
            raise MigrationError("source_file must be a relative path to a supported original")
        relative = Path(legacy_source_file)
        if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
            raise MigrationError("source_file must stay within the source wiki")
        candidate = source
        for component in relative.parts:
            candidate /= component
            if candidate.is_symlink():
                raise MigrationError("source_file path contains a symlink")
        if candidate.suffix.lower() not in SUPPORTED_UPLOAD_EXTENSIONS or not candidate.is_file():
            raise MigrationError("source_file must point to a supported original")
        return candidate

    requested = metadata.get("original_filename")
    names = [str(requested)] if isinstance(requested, str) and requested else [page.stem + suffix for suffix in SUPPORTED_UPLOAD_EXTENSIONS]
    candidates = [source / "documents" / name for name in names]
    candidates += [source / name for name in names]
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def migrate_legacy_wiki(source: str | Path, destination: str | Path, replace_existing: bool = False) -> MigrationResult:
    source_root = _check_tree(Path(source).expanduser(), "source")
    if not source_root.exists():
        raise MigrationError("source wiki does not exist")
    destination_root = _check_tree(Path(destination).expanduser(), "destination")
    if destination_root.exists() and any(destination_root.iterdir()) and not replace_existing:
        raise MigrationError("destination is not empty; use --replace-existing")
    if source_root == destination_root or destination_root in source_root.parents:
        raise MigrationError("destination must not contain the source wiki")

    staging = destination_root.parent / f".{destination_root.name}.migration-{uuid4().hex}"
    if staging.exists():
        raise MigrationError("migration staging path already exists")
    staging.mkdir(parents=True)
    try:
        documents = staging / "documents"
        repository = staging / "repository"
        sources_dir = repository / "sources"
        knowledge_dir = repository / "knowledge"
        documents.mkdir()
        sources_dir.mkdir(parents=True)
        knowledge_dir.mkdir(parents=True)

        markdown = [p for p in _files(source_root) if p.suffix.lower() == ".md"]
        source_pages = [p for p in markdown if "sources" in p.relative_to(source_root).parts]
        source_ids: list[str] = []
        source_aliases: dict[str, set[str]] = {}
        originals: dict[str, Path] = {}
        for page in source_pages:
            metadata, body = load_frontmatter(page.read_text(encoding="utf-8"))
            base = _safe_id(str(metadata.get("document_id") or page.stem))
            document_id = base
            if document_id in source_ids:
                document_id = f"{base}-{hashlib.sha256(str(page).encode()).hexdigest()[:8]}"
            source_ids.append(document_id)
            for alias in _source_aliases(str(metadata.get("title") or page.stem)):
                source_aliases.setdefault(alias, set()).add(document_id)
            original = _matching_original(source_root, metadata, page)
            if original is not None:
                destination_name = f"{document_id}{original.suffix.lower()}"
                shutil.copyfile(original, documents / destination_name)
                digest = hashlib.sha256(original.read_bytes()).hexdigest()
                originals[document_id] = original
            else:
                digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            metadata = {
                "title": str(metadata.get("title") or page.stem),
                **metadata,
                "kind": "source",
                "document_id": document_id,
                "original_filename": str(metadata.get("original_filename") or (original.name if original else page.name)),
                "content_sha256": digest,
            }
            if "## Extracted Text" not in body:
                body = "## Extracted Text\n\n" + body
            (sources_dir / f"{document_id}.md").write_text(dump_frontmatter(metadata, body), encoding="utf-8")

        # Preserve supported originals that are not referenced by a source page.
        copied_names = {path.name for path in documents.iterdir()}
        copied_originals = {path.resolve() for path in originals.values()}
        for original in _files(source_root):
            if original.suffix.lower() not in SUPPORTED_UPLOAD_EXTENSIONS:
                continue
            if original.resolve() in copied_originals:
                continue
            name = f"{_safe_id(original.stem)}{original.suffix.lower()}"
            if name in copied_names:
                name = f"{_safe_id(original.stem)}-{hashlib.sha256(str(original).encode()).hexdigest()[:8]}{original.suffix.lower()}"
            shutil.copyfile(original, documents / name)
            copied_names.add(name)

        for path in markdown:
            if path in source_pages:
                continue
            relative = path.relative_to(source_root)
            if relative.parts and relative.parts[0] == "knowledge":
                target_relative = Path(*relative.parts[1:])
            else:
                target_relative = relative
            if not target_relative.name:
                continue
            target = knowledge_dir / target_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            metadata, body = load_frontmatter(path.read_text(encoding="utf-8"))
            body = _resolve_source_links(body, source_ids, source_aliases)
            if not any(f"sources/{source_id}" in body for source_id in source_ids) and source_ids:
                body = body.rstrip() + f"\n\nSource: [[sources/{source_ids[0]}]]\n"
            target.write_text(dump_frontmatter(metadata, body), encoding="utf-8")

        if not (knowledge_dir / "index.md").exists():
            (knowledge_dir / "index.md").write_text("# Wiki Index\n", encoding="utf-8")
        if not (knowledge_dir / "log.md").exists():
            (knowledge_dir / "log.md").write_text("# Wiki Log\n", encoding="utf-8")
        validate_knowledge(repository)
        git = LocalKnowledgeGit(repository, "CV Agent", "cv-agent@localhost")
        git.initialize()
        commit = git.commit("Migrate legacy CV knowledge")

        recovery = None
        if destination_root.exists() and any(destination_root.iterdir()):
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            recovery = destination_root.parent / f"{destination_root.name}.recovery-{stamp}"
            while recovery.exists():
                recovery = destination_root.parent / f"{destination_root.name}.recovery-{stamp}-{uuid4().hex[:6]}"
            destination_root.rename(recovery)
        staging.rename(destination_root)
        return MigrationResult(commit, len(source_pages), len(markdown) - len(source_pages), len(originals))
    except (OSError, UnicodeError, ValueError, GitStoreError, KnowledgeValidationError) as exc:
        raise MigrationError(str(exc)) from None
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
