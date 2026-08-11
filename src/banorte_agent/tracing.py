from urllib.parse import unquote

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from banorte_agent.config import Settings


def tracing_enabled(settings: Settings) -> bool:
    return settings.otel_enabled


def configure_tracing(app: FastAPI, settings: Settings) -> None:
    if not tracing_enabled(settings):
        return
    resource = Resource.create(resource_attributes(settings))
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=settings.otel_exporter_otlp_endpoint,
        insecure=settings.otel_exporter_otlp_insecure,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


def get_tracer():
    return trace.get_tracer("banorte_agent")


def resource_attributes(settings: Settings) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for pair in (settings.otel_resource_attributes or "").split(","):
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key = unquote(key.strip())
        value = unquote(value.strip())
        if key and value:
            attributes[key] = value
    attributes["service.name"] = settings.otel_service_name
    return attributes


def safe_count_attribute(name: str, value: str) -> tuple[str, int]:
    return name, len(value)
