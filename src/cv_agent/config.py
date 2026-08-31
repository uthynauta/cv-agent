from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


GroundingMode = Literal["strict", "inference"]
IngestionMode = Literal["openai", "deterministic"]
RetrievalMode = Literal["lexical", "llm_rerank"]
ContextMode = Literal["excerpt", "page"]
AgentLanguage = Literal["auto", "es", "en"]


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
    admin_ui_password: str | None = Field(default=None, alias="ADMIN_UI_PASSWORD")
    admin_ui_session_secret: str | None = Field(default=None, alias="ADMIN_UI_SESSION_SECRET")
    admin_ui_session_max_age_seconds: int = Field(
        default=12 * 60 * 60,
        gt=0,
        alias="ADMIN_UI_SESSION_MAX_AGE_SECONDS",
    )
    admin_upload_max_bytes: int = Field(
        default=10 * 1024 * 1024,
        gt=0,
        alias="ADMIN_UPLOAD_MAX_BYTES",
    )
    admin_backup_max_bytes: int = Field(
        default=100 * 1024 * 1024,
        gt=0,
        alias="ADMIN_BACKUP_MAX_BYTES",
    )
    backup_retention_count: int = Field(default=10, ge=1, alias="BACKUP_RETENTION_COUNT")
    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    github_repository: str = Field(default="uthynauta/cv-agent", alias="GITHUB_REPOSITORY")
    github_base_branch: str = Field(default="main", alias="GITHUB_BASE_BRANCH")
    github_commit_author_name: str = Field(
        default="Banorte Agent Admin",
        alias="GITHUB_COMMIT_AUTHOR_NAME",
    )
    github_commit_author_email: str | None = Field(
        default=None,
        alias="GITHUB_COMMIT_AUTHOR_EMAIL",
    )
    agent_model_name: str = Field(default="cv-agent", alias="AGENT_MODEL_NAME")
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
    agent_owner_name: str | None = Field(default=None, alias="AGENT_OWNER_NAME")
    agent_display_name: str = Field(default="CV Agent", alias="AGENT_DISPLAY_NAME")
    agent_description: str = Field(
        default="Ask questions about this candidate's CV.", alias="AGENT_DESCRIPTION"
    )
    agent_language: AgentLanguage = Field(default="auto", alias="AGENT_LANGUAGE")
    agent_public_url: str = Field(
        default="https://banorte-cv-agent.onrender.com",
        alias="AGENT_PUBLIC_URL",
    )
    data_git_author_name: str = Field(default="CV Agent", alias="DATA_GIT_AUTHOR_NAME")
    data_git_author_email: str = Field(
        default="cv-agent@localhost", alias="DATA_GIT_AUTHOR_EMAIL"
    )
    public_request_body_limit_bytes: int = Field(
        default=16 * 1024, gt=0, alias="PUBLIC_REQUEST_BODY_LIMIT_BYTES"
    )
    wiki_dir: str = Field(default="wiki", alias="WIKI_DIR")
    otel_enabled: bool = Field(default=False, alias="OTEL_ENABLED")
    otel_service_name: str = Field(default="cv-agent", alias="OTEL_SERVICE_NAME")
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

    @field_validator("data_dir", mode="before")
    @classmethod
    def validate_data_dir(cls, value: str | Path) -> str | Path:
        if not isinstance(value, (str, Path)):
            raise ValueError("data_dir must be a nonblank path")
        normalized = str(value).strip()
        candidate = Path(normalized).expanduser()
        resolved = candidate.resolve()
        if (
            not normalized
            or candidate == Path(".")
            or resolved == Path.cwd().resolve()
            or resolved == Path(resolved.anchor)
        ):
            raise ValueError("data_dir must be a nonblank path other than '.'")
        return normalized

    @field_validator("agent_language", mode="before")
    @classmethod
    def validate_agent_language(cls, value: str) -> str:
        if value in {"auto", "es", "en"}:
            return value
        raise ValueError("agent_language must be 'auto', 'es', or 'en'")

    @field_validator("agent_owner_name", mode="before")
    @classmethod
    def normalize_agent_owner_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("data_git_author_name", "data_git_author_email", mode="before")
    @classmethod
    def normalize_data_git_author(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("data Git author values must be nonblank")
        return value.strip()

    @field_validator("rerank_model", mode="before")
    @classmethod
    def normalize_rerank_model(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        return value

    @field_validator(
        "admin_ui_password",
        "admin_ui_session_secret",
        "github_token",
        "github_commit_author_email",
        mode="before",
    )
    @classmethod
    def normalize_optional_secret(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
