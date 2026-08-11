from pydantic import BaseModel, Field

MAX_INPUT_CHARS = 4000
MAX_INSTRUCTIONS_CHARS = 1000
MAX_MODEL_CHARS = 128


class ResponseRequest(BaseModel):
    model: str | None = Field(default=None, max_length=MAX_MODEL_CHARS)
    input: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)
    instructions: str | None = Field(default=None, max_length=MAX_INSTRUCTIONS_CHARS)


class IngestRequest(BaseModel):
    path: str
