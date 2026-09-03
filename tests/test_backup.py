import json
import subprocess
import tarfile

from cv_agent.config import Settings
from cv_agent.knowledge.backup import BackupService
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.storage import ensure_data_storage


def _service(tmp_path):
    paths = ensure_data_storage(tmp_path)
    git = LocalKnowledgeGit(paths.repository, "Test", "test@example.com")
    git.initialize()
    (paths.sources / "doc-1.md").write_text("# Doc\n", encoding="utf-8")
    (paths.knowledge / "index.md").write_text("# Index\n", encoding="utf-8")
    git.commit("seed")
    (paths.documents / "doc-1.pdf").write_bytes(b"original")
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
