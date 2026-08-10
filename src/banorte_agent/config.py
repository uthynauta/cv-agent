from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


GroundingMode = Literal["strict", "inference"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.6", alias="OPENAI_MODEL")
    grounding_mode: GroundingMode = Field(default="inference", alias="GROUNDING_MODE")
    agent_api_key: str | None = Field(default=None, alias="AGENT_API_KEY")
    admin_api_key: str | None = Field(default=None, alias="ADMIN_API_KEY")
    agent_model_name: str = Field(default="banorte-cv-agent", alias="AGENT_MODEL_NAME")
    wiki_dir: str = Field(default="wiki", alias="WIKI_DIR")

    @field_validator("grounding_mode", mode="before")
    @classmethod
    def validate_grounding_mode(cls, value: str) -> str:
        if value not in {"strict", "inference"}:
            raise ValueError("grounding_mode must be 'strict' or 'inference'")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
