from pathlib import Path

from cv_agent.config import Settings
from cv_agent.main import create_app


def test_generic_application_identity(tmp_path: Path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    app = create_app(settings=settings, agent_answerer=lambda text, instructions=None: "ok")
    assert app.title == "CV Agent"
    assert settings.agent_model_name == "cv-agent"
    assert settings.otel_service_name == "cv-agent"
