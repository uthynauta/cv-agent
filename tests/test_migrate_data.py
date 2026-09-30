from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.migrate import MigrationError, migrate_legacy_wiki


def make_legacy_wiki(root: Path) -> Path:
    (root / "sources").mkdir(parents=True)
    (root / "knowledge" / "topics").mkdir(parents=True)
    (root / "documents").mkdir()
    (root / "documents" / "candidate.pdf").write_bytes(b"legacy pdf")
    (root / "sources" / "candidate.md").write_text(
        "---\ntitle: Candidate\noriginal_filename: candidate.pdf\n---\n\n"
        "## Extracted Text\n\nPython and Rust experience.\n",
        encoding="utf-8",
    )
    (root / "knowledge" / "topics" / "rust.md").write_text(
        "---\ntitle: Rust\nkind: skill\n---\n\nRust experience.\n", encoding="utf-8"
    )
    return root


def test_migration_imports_legacy_wiki_into_initial_local_commit(tmp_path: Path):
    destination = tmp_path / "data"
    result = migrate_legacy_wiki(make_legacy_wiki(tmp_path / "legacy"), destination, False)

    assert result.commit
    assert result.source_pages == 1
    assert result.knowledge_pages == 1
    assert result.original_documents == 1
    assert list((destination / "repository" / "sources").glob("*.md"))
    assert (destination / "repository" / "knowledge" / "index.md").exists()
    assert LocalKnowledgeGit(destination / "repository", "CV Agent", "cv-agent@localhost").remotes() == []


def test_migration_resolves_legacy_source_aliases_without_changing_originals(tmp_path: Path):
    legacy = make_legacy_wiki(tmp_path / "legacy")
    (legacy / "sources" / "20260812-certificateofcompletion-building-tools-with-python.md").write_text(
        "---\ntitle: 'Certificate: Building Tools with Python'\n---\n\n"
        "## Extracted Text\n\nCompleted Building Tools with Python.\n", encoding="utf-8"
    )
    (legacy / "sources" / "cv-ogc-ai.md").write_text(
        "---\ntitle: CV AI\n---\n\n## Extracted Text\n\nAI experience.\n", encoding="utf-8"
    )
    page = legacy / "knowledge" / "topics" / "rust.md"
    original = (
        "---\ntitle: Rust\n---\n\n"
        "[[sources/certificate-building-tools-with-python|Course certificate]] and "
        "[[sources/cv-ogh-ai|AI CV]] describe this skill.\n"
    )
    page.write_text(original, encoding="utf-8")

    destination = tmp_path / "data"
    result = migrate_legacy_wiki(legacy, destination)

    migrated = (destination / "repository" / "knowledge" / "topics" / "rust.md").read_text(encoding="utf-8")
    assert result.source_pages == 3
    assert "[[sources/20260812-certificateofcompletion-building-tools-with-python|Course certificate]]" in migrated
    assert "[[sources/cv-ogc-ai|AI CV]]" in migrated
    assert page.read_text(encoding="utf-8") == original


def test_migration_preserves_existing_legacy_index_and_log(tmp_path: Path):
    legacy = make_legacy_wiki(tmp_path / "legacy")
    (legacy / "index.md").write_text("# Original index\n\nSource: [[sources/candidate]]\n", encoding="utf-8")
    (legacy / "log.md").write_text("# Original log\n\nFirst ingestion.\n", encoding="utf-8")

    destination = tmp_path / "data"
    migrate_legacy_wiki(legacy, destination)

    assert "# Original index" in (destination / "repository" / "knowledge" / "index.md").read_text(encoding="utf-8")
    assert "First ingestion." in (destination / "repository" / "knowledge" / "log.md").read_text(encoding="utf-8")
    assert "# Original index" in (legacy / "index.md").read_text(encoding="utf-8")


def test_migration_rejects_ambiguous_legacy_source_alias_and_preserves_destination(tmp_path: Path):
    legacy = make_legacy_wiki(tmp_path / "legacy")
    for document_id in ("cv-ogc-ai", "cv-ogh-ai"):
        (legacy / "sources" / f"{document_id}.md").write_text(
            f"---\ntitle: {document_id}\n---\n\n## Extracted Text\n\nReal source.\n", encoding="utf-8"
        )
    page = legacy / "knowledge" / "topics" / "rust.md"
    page.write_text("[[sources/cv-ogx-ai]]", encoding="utf-8")
    destination = tmp_path / "data"
    destination.mkdir()
    (destination / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(MigrationError, match="unknown source reference"):
        migrate_legacy_wiki(legacy, destination, True)

    assert (destination / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert page.read_text(encoding="utf-8") == "[[sources/cv-ogx-ai]]"


def test_migration_refuses_nonempty_destination(tmp_path: Path):
    destination = tmp_path / "data"
    (destination / "documents").mkdir(parents=True)
    (destination / "documents" / "existing.pdf").write_bytes(b"PDF")
    with pytest.raises(MigrationError, match="destination is not empty"):
        migrate_legacy_wiki(make_legacy_wiki(tmp_path / "legacy"), destination, False)


def test_replacement_moves_old_destination_to_recovery_sibling(tmp_path: Path):
    legacy = make_legacy_wiki(tmp_path / "legacy")
    destination = tmp_path / "data"
    destination.mkdir()
    (destination / "old.txt").write_text("keep me", encoding="utf-8")

    migrate_legacy_wiki(legacy, destination, True)

    recovery = list(tmp_path.glob("data.recovery-*"))
    assert len(recovery) == 1
    assert (recovery[0] / "old.txt").read_text(encoding="utf-8") == "keep me"
    assert not (destination / "old.txt").exists()


def test_cli_requires_explicit_replace_flag(tmp_path: Path):
    legacy = make_legacy_wiki(tmp_path / "legacy")
    destination = tmp_path / "data"
    destination.mkdir()
    (destination / "existing").write_text("x", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "cv_agent.cli", "migrate-data", "--from-wiki", str(legacy), "--to-data-dir", str(destination)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "destination is not empty" in result.stderr
    assert result.stdout == ""
