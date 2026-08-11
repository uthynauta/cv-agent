from fastapi import FastAPI

from banorte_agent.config import Settings
from banorte_agent.tracing import configure_tracing, tracing_enabled


def test_tracing_disabled_by_default():
    settings = Settings(openai_api_key="test-key")
    assert tracing_enabled(settings) is False


def test_configure_tracing_noops_when_disabled():
    app = FastAPI()
    settings = Settings(openai_api_key="test-key", otel_enabled=False)
    configure_tracing(app, settings)
    assert app.title == "FastAPI"


def test_safe_span_attributes_exclude_text_payloads():
    from banorte_agent.tracing import safe_count_attribute

    assert safe_count_attribute("query_length", "secret prompt text") == ("query_length", 18)
