from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.migrate import MigrationError, migrate_legacy_wiki
from cv_agent.knowledge.validation import validate_knowledge


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
