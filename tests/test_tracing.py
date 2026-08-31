from fastapi import FastAPI

import cv_agent.tracing as tracing
from cv_agent.config import Settings
from cv_agent.tracing import configure_tracing, tracing_enabled


def test_tracing_disabled_by_default():
    settings = Settings(openai_api_key="test-key")
    assert tracing_enabled(settings) is False


def test_configure_tracing_noops_when_disabled():
    app = FastAPI()
    settings = Settings(openai_api_key="test-key", otel_enabled=False)
    configure_tracing(app, settings)
    assert app.title == "FastAPI"


def test_safe_span_attributes_exclude_text_payloads():
    from cv_agent.tracing import safe_count_attribute

    assert safe_count_attribute("query_length", "secret prompt text") == ("query_length", 18)


def test_resource_attributes_apply_configured_otel_values():
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        otel_resource_attributes="deployment.environment=review,service.version=1%2E0",
    )

    assert tracing.resource_attributes(settings) == {
        "service.name": "cv-agent",
        "deployment.environment": "review",
        "service.version": "1.0",
    }
