from openai import OpenAI

from banorte_agent.config import Settings


class OpenAITextClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)

    def create_response(self, instructions: str, input_text: str) -> str:
        response = self.client.responses.create(
            model=self.settings.openai_model,
            instructions=instructions,
            input=input_text,
        )
        return response.output_text
