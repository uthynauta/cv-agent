import hashlib
import json
import tarfile
import io

import pytest

from cv_agent.config import Settings
from cv_agent.knowledge.backup import BackupService
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.restore import BackupValidationError, RestoreService
from cv_agent.knowledge.storage import ensure_data_storage


def _services(tmp_path):
    paths = ensure_data_storage(tmp_path)
    settings = Settings(_env_file=None, data_dir=tmp_path, agent_model_name="test-model")
    git = LocalKnowledgeGit(paths.repository, settings.data_git_author_name, settings.data_git_author_email)
    git.initialize()
    (paths.sources / "doc.md").write_text(
        "---\nkind: source\ndocument_id: doc\noriginal_filename: doc.pdf\n"
        "media_type: application/pdf\nuploaded_at: '2026-01-01T00:00:00+00:00'\n"
        f"content_sha256: {hashlib.sha256(b'doc').hexdigest()}\n"
        "extractor_version: '1'\nneeds_ocr: false\ntags: [source, pdf]\n---\n\n"
        "# Doc\n\n## Extracted Text\n\nDocument text.\n",
        encoding="utf-8",
    )
    (paths.knowledge / "index.md").write_text("# Index\n", encoding="utf-8")
    git.commit("seed")
    (paths.documents / "doc.pdf").write_bytes(b"doc")
    return paths, git, settings


def test_full_restore_round_trip_and_file_mode(tmp_path):
    paths, git, settings = _services(tmp_path)
    backup = BackupService(paths, git, settings).create_full_backup()
    (paths.sources / "doc.md").write_text("bad", encoding="utf-8")
    result = RestoreService(paths, git, settings).restore_full(backup.path, confirmed=True)
    assert result.active_commit
    assert (paths.documents / "doc.pdf").read_bytes() == b"doc"
    assert (paths.documents / "doc.pdf").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("field,value", [("format_version", True), ("active_commit", "x" * 40), ("created_at", "yesterday"), ("agent_model", 1)])
def test_manifest_rejects_wrong_types_or_values(tmp_path, field, value):
    paths, git, settings = _services(tmp_path)
    service = RestoreService(paths, git, settings)
    manifest = {"format_version": 1, "created_at": "2026-01-01T00:00:00Z", "active_commit": "a" * 40, "agent_model": "model", "files": {"knowledge.bundle": {"sha256": "a" * 64, "size": 1}}}
    manifest[field] = value
    with pytest.raises(BackupValidationError):
        service._validate_manifest(manifest, {"knowledge.bundle": b"x"})


def test_archive_rejects_links_and_traversal(tmp_path):
    paths, git, settings = _services(tmp_path)
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("../manifest.json"); info.size = 0; tar.addfile(info, io.BytesIO())
    with pytest.raises(BackupValidationError):
        RestoreService(paths, git, settings)._read_archive(archive)
