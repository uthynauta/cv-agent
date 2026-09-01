from importlib.metadata import version
from pathlib import Path

from fastapi.testclient import TestClient

from cv_agent.config import Settings
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
        part.casefold()
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
            text = path.read_text(encoding="utf-8", errors="ignore").casefold()
            if any(marker in text for marker in markers):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []
