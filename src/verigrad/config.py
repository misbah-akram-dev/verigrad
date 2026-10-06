"""Application settings, loaded from environment variables and `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings. Every field is optional so the app starts without an API key."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY")
    )
    extract_model: str = Field(
        default="claude-sonnet-5-5", validation_alias=AliasChoices("VERIGRAD_EXTRACT_MODEL")
    )
    compare_model: str = Field(
        default="claude-haiku-4-5", validation_alias=AliasChoices("VERIGRAD_COMPARE_MODEL")
    )
    max_cost_per_job: float = Field(
        default=0.30, ge=0, validation_alias=AliasChoices("VERIGRAD_MAX_COST_PER_JOB")
    )
    llm_timeout_seconds: float = Field(
        default=120.0, gt=0, validation_alias=AliasChoices("VERIGRAD_LLM_TIMEOUT_SECONDS")
    )
    data_dir: Path = Field(
        default=Path("./data"), validation_alias=AliasChoices("VERIGRAD_DATA_DIR")
    )
    db_path: Path = Field(
        default=Path("./data/verigrad.db"), validation_alias=AliasChoices("VERIGRAD_DB_PATH")
    )
    fetch_delay_seconds: float = Field(
        default=3.0, ge=0, validation_alias=AliasChoices("VERIGRAD_FETCH_DELAY_SECONDS")
    )
    fetch_timeout_seconds: float = Field(
        default=45.0, gt=0, validation_alias=AliasChoices("VERIGRAD_FETCH_TIMEOUT_SECONDS")
    )
    timezone: str = Field(
        default="Asia/Karachi", validation_alias=AliasChoices("VERIGRAD_TIMEZONE")
    )

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _blank_key_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("extract_model", "compare_model", mode="before")
    @classmethod
    def _blank_model_uses_default(cls, value: object, info: object) -> object:
        # `.env.example` historically left model IDs blank; treat blank as "use the default".
        if isinstance(value, str) and not value.strip():
            field_name = getattr(info, "field_name", "")
            return cls.model_fields[field_name].default
        return value

    @property
    def has_api_key(self) -> bool:
        return self.anthropic_api_key is not None


@lru_cache
def get_settings() -> Settings:
    return Settings()
