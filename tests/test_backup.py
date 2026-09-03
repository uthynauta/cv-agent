import json
import os
import subprocess
import tarfile
import pytest

from cv_agent.config import Settings
from cv_agent.knowledge.backup import BackupService
from cv_agent.knowledge.git_store import GitStoreError, LocalKnowledgeGit
from cv_agent.knowledge.storage import ensure_data_storage
from cv_agent.knowledge.backup import BackupError, BackupNotFoundError, BackupTooLargeError


def _service(tmp_path):
    paths = ensure_data_storage(tmp_path)
    git = LocalKnowledgeGit(paths.repository, "Test", "test@example.com")
    git.initialize()
    (paths.sources / "doc-1.md").write_text(
        "---\ndocument_id: doc-1\noriginal_filename: doc-1.pdf\nmedia_type: application/pdf\ncontent_sha256: 068f7e8f5e0a1c9f7f9f9d2d6f2f4f0c16e6e1f4f6f6f8c2c8e0e7d3a4e6b5b1\n---\n\n# Doc\n",
        encoding="utf-8",
    )
    (paths.knowledge / "index.md").write_text("# Index\n", encoding="utf-8")
    git.commit("seed")
    (paths.documents / "doc-1.pdf").write_bytes(b"original")
    import hashlib
    source = paths.sources / "doc-1.md"
    source.write_text(source.read_text(encoding="utf-8").replace("068f7e8f5e0a1c9f7f9f9d2d6f2f4f0c16e6e1f4f6f6f8c2c8e0e7d3a4e6b5b1", hashlib.sha256(b"original").hexdigest()), encoding="utf-8")
    return BackupService(paths, git, Settings(_env_file=None, data_dir=tmp_path, agent_model_name="test-model"))


def test_knowledge_backup_is_valid_git_bundle(tmp_path):
    service = _service(tmp_path)
    result = service.create_knowledge_bundle()
    completed = subprocess.run(["git", "bundle", "verify", str(result.path)], capture_output=True, text=True)
    assert completed.returncode == 0
    assert result.path.suffix == ".bundle"


def test_full_backup_contains_bundle_originals_and_checksums(tmp_path):
    service = _service(tmp_path)
    result = service.create_full_backup()
    with tarfile.open(result.path, "r:gz") as archive:
        names = set(archive.getnames())
        manifest = json.load(archive.extractfile("manifest.json"))
    assert "knowledge.bundle" in names
    assert "documents/doc-1.pdf" in names
    assert manifest["format_version"] == 1
    assert manifest["active_commit"]
    assert manifest["files"]["documents/doc-1.pdf"]["sha256"]


def test_retention_removes_only_old_managed_backups(tmp_path):
    service = _service(tmp_path)
    for _ in range(4):
        service.create_knowledge_bundle()
    service.retention_count = 2
    service.prune()
    assert len(service.list()) == 2


@pytest.mark.parametrize("name", [
    "knowledge-20260101T000000Z-aaaaaaaaaaaaaaaa.tar.gz",
    "full-20260101T000000Z-aaaaaaaaaaaaaaaa.bundle",
    "../knowledge-20260101T000000Z-aaaaaaaaaaaaaaa.bundle",
])
def test_backup_name_requires_kind_specific_suffix(tmp_path, name):
    service = _service(tmp_path)
    with pytest.raises(BackupNotFoundError):
        service.resolve_download(name)


def test_malformed_source_metadata_is_backup_error(tmp_path):
    service = _service(tmp_path)
    (service.paths.sources / "broken.md").write_text("---\n[not: valid\n---\n", encoding="utf-8")
    with pytest.raises(BackupError):
        service.create_full_backup()


def test_download_rejects_oversize_before_digest(tmp_path, monkeypatch):
    service = _service(tmp_path)
    service.max_bytes = 1
    result = service.paths.backups / "knowledge-20260101T000000Z-aaaaaaaaaaaaaaaa.bundle"
    result.write_bytes(b"too large")
    monkeypatch.setattr(service, "_digest", lambda _path: (_ for _ in ()).throw(AssertionError("hashed")))
    with pytest.raises(BackupTooLargeError):
        service.open_download(result.name)


def test_knowledge_create_rejects_oversize_during_bundle_stream(tmp_path):
    service = _service(tmp_path)
    service.max_bytes = 1
    with pytest.raises(BackupTooLargeError):
        service.create_knowledge_bundle()
    assert not service.list()


def test_open_download_does_not_leak_directory_descriptors(tmp_path):
    service = _service(tmp_path)
    result = service.create_knowledge_bundle()
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(20):
        record, handle = service.open_download(result.name)
        handle.close()
        assert record.name == result.name
    after = len(os.listdir("/proc/self/fd"))
    assert after <= before + 1


def test_list_rejects_symlinked_backup_root(tmp_path):
    service = _service(tmp_path)
    real = service.paths.backups
    moved = tmp_path / "real-backups"
    real.rename(moved)
    real.symlink_to(moved, target_is_directory=True)
    with pytest.raises(BackupError):
        service.list()


def test_full_backup_verifies_digest_of_staged_original(tmp_path, monkeypatch):
    service = _service(tmp_path)
    original_snapshot = service._snapshot

    def corrupt_after_snapshot(source, destination, **kwargs):
        original_snapshot(source, destination, **kwargs)
        destination.write_bytes(b"changed")

    monkeypatch.setattr(service, "_snapshot", corrupt_after_snapshot)
    with pytest.raises(BackupError, match="document changed"):
        service.create_full_backup()
    assert not list(service.paths.backups.iterdir())
    assert not list(service.paths.staging.iterdir())


def test_oversized_source_metadata_fails_before_parsing(tmp_path):
    service = _service(tmp_path)
    service.max_bytes = 16
    (service.paths.sources / "oversized.md").write_text("x" * 17, encoding="utf-8")
    with pytest.raises(BackupTooLargeError):
        service.create_full_backup()


def test_git_head_failure_is_a_backup_error(tmp_path, monkeypatch):
    service = _service(tmp_path)
    monkeypatch.setattr(service.git, "head", lambda: (_ for _ in ()).throw(GitStoreError("bad")))
    with pytest.raises(BackupError):
        service.create_knowledge_bundle()
