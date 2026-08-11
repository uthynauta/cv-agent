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
