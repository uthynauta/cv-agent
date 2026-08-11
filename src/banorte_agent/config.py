from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


GroundingMode = Literal["strict", "inference"]
IngestionMode = Literal["openai", "deterministic"]
RetrievalMode = Literal["lexical", "llm_rerank"]
ContextMode = Literal["excerpt", "page"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.6", alias="OPENAI_MODEL")
    grounding_mode: GroundingMode = Field(default="inference", alias="GROUNDING_MODE")
    ingestion_mode: IngestionMode = Field(default="openai", alias="INGESTION_MODE")
    retrieval_mode: RetrievalMode = Field(default="lexical", alias="RETRIEVAL_MODE")
    rerank_model: str | None = Field(default=None, alias="RERANK_MODEL")
    rerank_top_k: int = Field(default=20, gt=0, alias="RERANK_TOP_K")
    answer_top_k: int = Field(default=5, gt=0, alias="ANSWER_TOP_K")
    context_mode: ContextMode = Field(default="page", alias="CONTEXT_MODE")
    max_context_chars: int = Field(default=12_000, gt=0, alias="MAX_CONTEXT_CHARS")
    agent_api_key: str | None = Field(default=None, alias="AGENT_API_KEY")
    admin_api_key: str | None = Field(default=None, alias="ADMIN_API_KEY")
    agent_model_name: str = Field(default="banorte-cv-agent", alias="AGENT_MODEL_NAME")
    public_request_body_limit_bytes: int = Field(
        default=16 * 1024, gt=0, alias="PUBLIC_REQUEST_BODY_LIMIT_BYTES"
    )
    wiki_dir: str = Field(default="wiki", alias="WIKI_DIR")
    otel_enabled: bool = Field(default=False, alias="OTEL_ENABLED")
    otel_service_name: str = Field(default="banorte-cv-agent", alias="OTEL_SERVICE_NAME")
    otel_exporter_otlp_endpoint: str = Field(default="http://tempo:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    otel_exporter_otlp_insecure: bool = Field(default=True, alias="OTEL_EXPORTER_OTLP_INSECURE")
    otel_resource_attributes: str | None = Field(default=None, alias="OTEL_RESOURCE_ATTRIBUTES")

    @field_validator("grounding_mode", mode="before")
    @classmethod
    def validate_grounding_mode(cls, value: str) -> str:
        if value not in {"strict", "inference"}:
            raise ValueError("grounding_mode must be 'strict' or 'inference'")
        return value

    @field_validator("ingestion_mode", mode="before")
    @classmethod
    def validate_ingestion_mode(cls, value: str) -> str:
        if value not in {"openai", "deterministic"}:
            raise ValueError("ingestion_mode must be 'openai' or 'deterministic'")
        return value

    @field_validator("retrieval_mode", mode="before")
    @classmethod
    def validate_retrieval_mode(cls, value: str) -> str:
        if value not in {"lexical", "llm_rerank"}:
            raise ValueError("retrieval_mode must be 'lexical' or 'llm_rerank'")
        return value

    @field_validator("context_mode", mode="before")
    @classmethod
    def validate_context_mode(cls, value: str) -> str:
        if value not in {"excerpt", "page"}:
            raise ValueError("context_mode must be 'excerpt' or 'page'")
        return value

    @field_validator("rerank_model", mode="before")
    @classmethod
    def normalize_rerank_model(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
