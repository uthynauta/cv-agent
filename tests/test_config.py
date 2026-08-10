from banorte_agent.config import Settings


def test_settings_defaults():
    settings = Settings(openai_api_key="test-key")
    assert settings.openai_model == "gpt-5.6"
    assert settings.grounding_mode == "inference"
    assert settings.agent_model_name == "banorte-cv-agent"
    assert settings.wiki_dir == "wiki"


def test_grounding_mode_rejects_invalid_value():
    try:
        Settings(openai_api_key="test-key", grounding_mode="creative")
    except ValueError as exc:
        assert "grounding_mode" in str(exc)
    else:
        raise AssertionError("invalid grounding mode was accepted")
