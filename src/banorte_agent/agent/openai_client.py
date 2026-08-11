from openai import OpenAI
from opentelemetry.trace import Status, StatusCode

from banorte_agent.config import Settings
from banorte_agent.metrics import OPENAI_CALLS
from banorte_agent.tracing import get_tracer, safe_count_attribute


class OpenAITextClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)

    def create_response(self, instructions: str, input_text: str) -> str:
        with get_tracer().start_as_current_span("openai.responses.create") as span:
            span.set_attribute("openai.model", self.settings.openai_model)
            span.set_attribute(*safe_count_attribute("input.length", input_text))
            try:
                response = self.client.responses.create(
                    model=self.settings.openai_model,
                    instructions=instructions,
                    input=input_text,
                )
            except Exception as error:
                OPENAI_CALLS.labels("error").inc()
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR))
                raise
            OPENAI_CALLS.labels("success").inc()
            span.set_status(Status(StatusCode.OK))
            return response.output_text
