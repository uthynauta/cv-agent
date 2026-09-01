from pathlib import Path

from fastapi.testclient import TestClient

from cv_agent.config import Settings
from cv_agent.main import create_app
from cv_agent.knowledge.storage import DataPaths


def seeded_settings(tmp_path: Path, **overrides) -> Settings:
    data_dir = tmp_path / "data"
    paths = DataPaths.from_root(data_dir)
    paths.sources.mkdir(parents=True)
    (paths.sources / "candidate.md").write_text(
        "# Candidate\n\nUsable source content.", encoding="utf-8"
    )
    values = {
        "_env_file": None,
        "data_dir": data_dir,
        "openai_api_key": "test-key",
        "openai_model": "test-model",
        "agent_owner_name": "Candidate",
        "agent_public_url": "https://example.test",
    }
    values.update(overrides)
    return Settings(**values)


def test_healthz_returns_alive():
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_missing_openai_key(tmp_path):
    settings = seeded_settings(tmp_path, openai_api_key=None)
    response = TestClient(create_app(settings=settings)).get("/readyz")
    assert response.status_code == 503
    assert response.json()["missing"] == ["OPENAI_API_KEY"]


def test_readyz_uses_mounted_knowledge(tmp_path):
    response = TestClient(create_app(settings=seeded_settings(tmp_path))).get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "missing": []}


def test_readyz_requires_usable_source_or_generated_page(tmp_path):
    data_dir = tmp_path / "data"
    paths = DataPaths.from_root(data_dir)
    paths.knowledge.mkdir(parents=True)
    (paths.knowledge / "index.md").write_text("# Index", encoding="utf-8")
    (paths.knowledge / "log.md").write_text("# Log", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        data_dir=data_dir,
        openai_api_key="test-key",
        openai_model="test-model",
        agent_owner_name="Candidate",
        agent_public_url="https://example.test",
    )

    response = TestClient(create_app(settings=settings)).get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "missing": ["knowledge"]}


def test_readyz_reports_stable_missing_configuration_order(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        openai_api_key=None,
        openai_model="",
        agent_owner_name=None,
        agent_public_url=None,
    )

    response = TestClient(create_app(settings=settings)).get("/readyz")

    assert response.status_code == 503
    assert response.json()["missing"] == [
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "AGENT_OWNER_NAME",
        "AGENT_PUBLIC_URL",
        "knowledge",
    ]


def test_create_app_uses_only_data_dir_and_does_not_seed_wiki(tmp_path):
    wiki_dir = tmp_path / "obsolete-wiki"
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", wiki_dir=str(wiki_dir))

    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")

    assert app.title == "CV Agent"
    assert not wiki_dir.exists()
    assert app.state.data_paths.root == (tmp_path / "data").resolve()


def test_readyz_does_not_require_github(tmp_path):
    settings = seeded_settings(tmp_path, github_token=None)
    response = TestClient(create_app(settings=settings)).get("/readyz")
    assert response.status_code == 200
