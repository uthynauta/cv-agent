from banorte_agent.config import Settings


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
    assert settings.agent_model_name == "banorte-cv-agent"
    assert settings.wiki_dir == "wiki"


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
