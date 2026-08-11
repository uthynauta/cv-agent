from pydantic import BaseModel, Field


class ResponseRequest(BaseModel):
    model: str | None = None
    input: str = Field(min_length=1)
    instructions: str | None = None


class IngestRequest(BaseModel):
    path: str
