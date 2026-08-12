import urllib.error
from pathlib import Path

from banorte_agent.admin.github import GitHubAdminService
from banorte_agent.config import Settings


def test_github_status_reports_unconfigured(tmp_path: Path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    service = GitHubAdminService(Settings(_env_file=None, github_token=None, wiki_dir=str(wiki)))

    status = service.status()

    assert status["configured"] is False
    assert status["connected"] is False
    assert status["base_branch"] == "main"
    assert status["pending_wiki_changes"] is False
    assert "token" in status["error"].lower()


def test_wiki_has_changes_compares_local_blobs_to_base_tree(tmp_path: Path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_text("# Local", encoding="utf-8")

    service = GitHubAdminService(Settings(_env_file=None, github_token="token", wiki_dir=str(wiki)))
    monkeypatch.setattr(
        service,
        "_base_wiki_blobs",
        lambda: {"wiki/index.md": "different-sha"},
    )

    assert service.wiki_has_changes() is True
    assert service.changed_wiki_files() == ["wiki/index.md"]


def test_publish_noops_without_wiki_changes(tmp_path: Path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_text("# Same", encoding="utf-8")
    service = GitHubAdminService(Settings(_env_file=None, github_token="token", wiki_dir=str(wiki)))
    monkeypatch.setattr(
        service,
        "_base_wiki_blobs",
        lambda: {"wiki/index.md": service.git_blob_sha((wiki / "index.md").read_bytes())},
    )

    assert service.publish() == {"status": "noop", "changed_files": []}


def test_status_redacts_github_error(tmp_path: Path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(str(request.full_url), 401, "Bad credentials token-secret", {}, None)

    monkeypatch.setattr("banorte_agent.admin.github.urlopen", fake_urlopen)
    service = GitHubAdminService(Settings(_env_file=None, github_token="token-secret", wiki_dir=str(wiki)))

    status = service.status()

    assert status["configured"] is True
    assert status["connected"] is False
    assert "token-secret" not in status["error"]


def test_publish_creates_blobs_tree_commit_ref_and_pr(tmp_path: Path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_text("# Updated", encoding="utf-8")
    (wiki / "raw").mkdir()
    (wiki / "raw" / "doc.pdf").write_bytes(b"%PDF-1.4")
    service = GitHubAdminService(Settings(_env_file=None, github_token="token", wiki_dir=str(wiki)))
    calls = []

    def fake_github_json(path: str, data=None, method=None):
        calls.append((path, data, method))
        if path == "/git/ref/heads/main":
            return {"object": {"sha": "base-ref-sha"}}
        if path == "/git/commits/base-ref-sha":
            return {"tree": {"sha": "base-tree-sha"}}
        if path == "/git/trees/base-tree-sha?recursive=1":
            return {"tree": []}
        if path == "/git/blobs":
            return {"sha": f"blob-{len([call for call in calls if call[0] == '/git/blobs'])}"}
        if path == "/git/trees":
            return {"sha": "new-tree-sha"}
        if path == "/git/commits":
            return {"sha": "new-commit-sha"}
        if path == "/git/refs":
            return {"ref": "refs/heads/wiki/upload-20260812-000000"}
        if path == "/pulls":
            return {"html_url": "https://github.com/uthynauta/cv-agent/pull/1"}
        raise AssertionError(path)

    monkeypatch.setattr(service, "_github_json", fake_github_json)
    monkeypatch.setattr("banorte_agent.admin.github._branch_suffix", lambda: "20260812-000000")

    result = service.publish()

    assert result["status"] == "ok"
    assert result["branch"] == "wiki/upload-20260812-000000"
    assert result["commit"] == "new-commit-sha"
    assert result["pull_request_url"] == "https://github.com/uthynauta/cv-agent/pull/1"
    assert result["changed_files"] == ["wiki/index.md", "wiki/raw/doc.pdf"]
    tree_call = next(call for call in calls if call[0] == "/git/trees")
    assert tree_call[1]["base_tree"] == "base-tree-sha"
    assert [item["path"] for item in tree_call[1]["tree"]] == ["wiki/index.md", "wiki/raw/doc.pdf"]
