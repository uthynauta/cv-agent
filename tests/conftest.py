import pytest

from cv_agent.config import get_settings
from cv_agent.knowledge.storage import ensure_data_storage


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def seed_response_knowledge(request, tmp_path, monkeypatch):
    """Give response protocol tests a minimal mounted source without corpus data."""
    if request.node.path.name == "test_response_schema.py":
        monkeypatch.chdir(tmp_path)
        paths = ensure_data_storage("data")
        (paths.sources / "synthetic.md").write_text(
            "# Synthetic Candidate\n\nSynthetic profile evidence for protocol tests.",
            encoding="utf-8",
        )
    yield
