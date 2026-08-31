from pathlib import Path

import pytest

from cv_agent.config import AgentLanguage, Settings


def test_settings_defaults():
    settings = Settings(_env_file=None, openai_api_key="test-key")
    assert settings.openai_model == "gpt-5.6"
    assert settings.grounding_mode == "inference"
    assert settings.ingestion_mode == "openai"
    assert settings.retrieval_mode == "lexical"
    assert settings.rerank_model is None
    assert settings.rerank_top_k == 20
    assert settings.answer_top_k == 5
    assert settings.context_mode == "page"
    assert settings.max_context_chars == 12000
    assert settings.agent_model_name == "cv-agent"
    assert settings.wiki_dir == "wiki"
    assert settings.data_dir == Path("data")
    assert settings.agent_owner_name is None
    assert settings.agent_display_name == "CV Agent"
    assert settings.agent_description == "Ask questions about this candidate's CV."
    assert settings.agent_language == "auto"
    assert settings.admin_backup_max_bytes == 100 * 1024 * 1024
    assert settings.backup_retention_count == 10
    assert settings.data_git_author_name == "CV Agent"
    assert settings.data_git_author_email == "cv-agent@localhost"


def test_generic_storage_and_identity_settings(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        agent_owner_name="Candidate Owner",
    )

    assert settings.data_dir == tmp_path
    assert settings.agent_owner_name == "Candidate Owner"


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_agent_owner_name_normalizes_to_none(value):
    assert Settings(_env_file=None, agent_owner_name=value).agent_owner_name is None


def test_agent_owner_name_is_stripped():
    assert Settings(_env_file=None, agent_owner_name="  Alex  ").agent_owner_name == "Alex"


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_data_dir_from_environment_is_rejected(monkeypatch, value):
    monkeypatch.setenv("DATA_DIR", value)

    with pytest.raises(ValueError, match="data_dir"):
        Settings(_env_file=None)


@pytest.mark.parametrize("value", ["", "   ", "."])
def test_blank_or_current_directory_data_dir_is_rejected(value):
    with pytest.raises(ValueError, match="data_dir"):
        Settings(_env_file=None, data_dir=value)


@pytest.mark.parametrize("value_factory", [Path.cwd, lambda: str(Path.cwd())])
def test_current_working_directory_data_dir_is_rejected(value_factory):
    with pytest.raises(ValueError, match="data_dir"):
        Settings(_env_file=None, data_dir=value_factory())


@pytest.mark.parametrize("value", [Path("/"), "/"])
def test_filesystem_root_data_dir_is_rejected(value):
    with pytest.raises(ValueError, match="data_dir"):
        Settings(_env_file=None, data_dir=value)


@pytest.mark.parametrize("value", ["data/..", Path("data/..")])
def test_collapsing_data_dir_is_rejected(tmp_path, monkeypatch, value):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="data_dir"):
        Settings(_env_file=None, data_dir=value)


@pytest.mark.parametrize("field", ["data_git_author_name", "data_git_author_email"])
@pytest.mark.parametrize("value", ["", "   "])
def test_blank_data_git_author_values_are_rejected(field, value):
    with pytest.raises(ValueError, match="nonblank"):
        Settings(_env_file=None, **{field: value})


def test_data_git_author_values_are_stripped():
    settings = Settings(
        _env_file=None,
        data_git_author_name="  CV Agent  ",
        data_git_author_email="  cv-agent@localhost  ",
    )

    assert settings.data_git_author_name == "CV Agent"
    assert settings.data_git_author_email == "cv-agent@localhost"


@pytest.mark.parametrize("value", ["auto", "es", "en"])
def test_agent_language_accepts_supported_values(value):
    assert Settings(_env_file=None, agent_language=value).agent_language == value


def test_agent_language_uses_supported_literal_type():
    assert Settings.model_fields["agent_language"].annotation is AgentLanguage


@pytest.mark.parametrize("value", ["", "english", "es-MX", "../es"])
def test_agent_language_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, agent_language=value)


@pytest.mark.parametrize(
    ("field", "value"),
    [("admin_backup_max_bytes", 0), ("admin_backup_max_bytes", -1), ("backup_retention_count", 0)],
)
def test_backup_limits_reject_non_positive_values(field, value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: value})


def test_grounding_mode_rejects_invalid_value():
    try:
        Settings(_env_file=None, openai_api_key="test-key", grounding_mode="creative")
    except ValueError as exc:
        assert "grounding_mode" in str(exc)
    else:
        raise AssertionError("invalid grounding mode was accepted")


def test_ingestion_mode_rejects_invalid_value():
    try:
        Settings(_env_file=None, openai_api_key="test-key", ingestion_mode="manual")
    except ValueError as exc:
        assert "ingestion_mode" in str(exc)
    else:
        raise AssertionError("invalid ingestion mode was accepted")


def test_retrieval_mode_rejects_invalid_value():
    try:
        Settings(_env_file=None, openai_api_key="test-key", retrieval_mode="vector")
    except ValueError as exc:
        assert "retrieval_mode" in str(exc)
    else:
        raise AssertionError("invalid retrieval mode was accepted")


def test_context_mode_rejects_invalid_value():
    try:
        Settings(_env_file=None, openai_api_key="test-key", context_mode="raw")
    except ValueError as exc:
        assert "context_mode" in str(exc)
    else:
        raise AssertionError("invalid context mode was accepted")


def test_admin_upload_and_github_defaults():
    settings = Settings(_env_file=None, openai_api_key="test-key")

    assert settings.admin_upload_max_bytes == 10 * 1024 * 1024
    assert settings.github_token is None
    assert settings.github_repository == "uthynauta/cv-agent"
    assert settings.github_base_branch == "main"
    assert settings.github_commit_author_name == "Banorte Agent Admin"
    assert settings.github_commit_author_email is None


def test_blank_github_values_normalize_to_none():
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        github_token="",
        github_commit_author_email="",
    )

    assert settings.github_token is None
    assert settings.github_commit_author_email is None


def test_admin_ui_defaults():
    settings = Settings(_env_file=None, openai_api_key="test-key")

    assert settings.admin_ui_password is None
    assert settings.admin_ui_session_secret is None
    assert settings.admin_ui_session_max_age_seconds == 12 * 60 * 60


def test_blank_admin_ui_secrets_normalize_to_none():
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        admin_ui_password="",
        admin_ui_session_secret="",
    )

    assert settings.admin_ui_password is None
    assert settings.admin_ui_session_secret is None
