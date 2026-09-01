from importlib.metadata import version
from pathlib import Path
import subprocess
import sys
import unicodedata

import pytest
from fastapi.testclient import TestClient

from cv_agent.config import Settings
from cv_agent.config import get_settings
from cv_agent.cli import main as cli_main
from cv_agent.main import create_app


def test_generic_application_identity(tmp_path: Path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    assert app.title == "CV Agent"
    assert settings.agent_model_name == "cv-agent"
    assert settings.otel_service_name == "cv-agent"
    assert version("cv-agent") == "0.3.0"


def test_repository_has_no_bundled_candidate_corpus():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "wiki").exists()
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY wiki" not in dockerfile


def test_active_runtime_has_no_remote_publish_route(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, admin_api_key="secret")
    client = TestClient(create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok"))
    response = client.post("/admin/publish", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 404


def test_active_tree_has_no_legacy_identity_or_deployment_markers():
    root = Path(__file__).resolve().parents[1]
    markers = tuple(
        _normalize_audit_text(part)
        for part in (
            "ban" + "orte",
            "ai " + "reto",
            "ot" + "hon",
            "uthy" + "nauta",
            "onrender" + ".com",
            "tera" + "data",
            "conti" + "nental",
            "centro" + "geo",
        )
    )
    roots = [root / "src", root / "tests", root / "docs", root / "README.md"]
    offenders = []
    for candidate in roots:
        paths = [candidate] if candidate.is_file() else candidate.rglob("*")
        for path in paths:
            if not path.is_file() or "superpowers" in path.parts or path.suffix == ".pyc":
                continue
            text = _normalize_audit_text(path.read_text(encoding="utf-8", errors="ignore"))
            if any(marker in text for marker in markers):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []


def _normalize_audit_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(character for character in decomposed if not unicodedata.combining(character))
    return without_marks.casefold()


def test_cli_rejects_documents_outside_data_dir_without_repo_mutation(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data"
    documents = data_dir / "documents"
    documents.mkdir(parents=True)
    external = tmp_path / "external.md"
    original = "# External document\n"
    external.write_text(original, encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("INGESTION_MODE", "deterministic")
    monkeypatch.setattr(sys, "argv", ["cv-agent", "ingest", str(external)])
    get_settings.cache_clear()

    try:
        with pytest.raises(SystemExit) as error:
            cli_main()
    finally:
        get_settings.cache_clear()

    assert error.value.code == 2
    assert "inside DATA_DIR/documents" in capsys.readouterr().err
    assert not (data_dir / "repository" / ".git").exists()
    assert external.read_text(encoding="utf-8") == original


def test_cli_rejects_symlinked_documents_target_without_repo_mutation(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data"
    documents = data_dir / "documents"
    documents.mkdir(parents=True)
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    external = external_dir / "candidate.md"
    original = "# External document through symlink\n"
    external.write_text(original, encoding="utf-8")
    symlink = documents / "external"
    symlink.symlink_to(external_dir, target_is_directory=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("INGESTION_MODE", "deterministic")
    monkeypatch.setattr(sys, "argv", ["cv-agent", "ingest", str(symlink)])
    get_settings.cache_clear()

    try:
        with pytest.raises(SystemExit) as error:
            cli_main()
    finally:
        get_settings.cache_clear()

    assert error.value.code == 2
    assert "inside DATA_DIR/documents" in capsys.readouterr().err
    assert not (data_dir / "repository" / ".git").exists()
    assert external.read_text(encoding="utf-8") == original


def test_cli_ingest_commits_versioned_knowledge_without_tracking_originals(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    documents = data_dir / "documents"
    documents.mkdir(parents=True)
    source = documents / "candidate.md"
    source.write_text("# Example Candidate\n\nPython experience.", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("INGESTION_MODE", "deterministic")
    monkeypatch.setattr(sys, "argv", ["cv-agent", "ingest", str(documents)])
    get_settings.cache_clear()

    try:
        cli_main()
    finally:
        get_settings.cache_clear()

    repository = data_dir / "repository"
    assert (repository / ".git").is_dir()
    head = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head
    tracked = subprocess.run(
        ["git", "-C", str(repository), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert any(path.startswith("sources/candidate-") and path.endswith(".md") for path in tracked)
    assert "knowledge/index.md" in tracked
    assert all(not path.startswith("documents/") for path in tracked)
    assert source.exists()


def test_compose_uses_generic_runtime_defaults():
    root = Path(__file__).resolve().parents[1]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (root / ".env.example").read_text(encoding="utf-8")
    assert "AGENT_PUBLIC_URL: ${AGENT_PUBLIC_URL:-}" in compose
    assert "AGENT_MODEL_NAME: ${AGENT_MODEL_NAME:-cv-agent}" in compose
    assert "OTEL_SERVICE_NAME: ${OTEL_SERVICE_NAME:-cv-agent}" in compose
    assert "PUBLIC_REQUEST_BODY_LIMIT_BYTES=16384" in env_example
