"""Application settings, loaded from environment variables (never hard-coded secrets)."""

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class AuthMode(StrEnum):
    SUPABASE = "supabase"
    # Local-only, clearly labelled development auth. Refused in production.
    DEV = "dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PRICESCOPE_",
        env_file=(".env", "../.env"),
        extra="ignore",
    )

    env: Environment = Environment.DEVELOPMENT
    demo_mode: bool = True
    log_level: str = "INFO"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://pricescope:change-me-local-only@127.0.0.1:5432/pricescope"
    )
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")

    auth_mode: AuthMode = AuthMode.DEV
    supabase_url: str = ""
    supabase_jwt_audience: str = "authenticated"

    llm_review_enabled: bool = False

    @model_validator(mode="before")
    @classmethod
    def _split_cors(cls, data: object) -> object:
        if isinstance(data, dict):
            raw = data.get("cors_origins")
            if isinstance(raw, str):
                data["cors_origins"] = [o.strip() for o in raw.split(",") if o.strip()]
        return data

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.env is Environment.PRODUCTION:
            if self.auth_mode is AuthMode.DEV:
                raise ValueError("PRICESCOPE_AUTH_MODE=dev is not allowed in production")
            if not self.supabase_url:
                raise ValueError("PRICESCOPE_SUPABASE_URL is required in production")
            if "*" in self.cors_origins:
                raise ValueError("Wildcard CORS origin is not allowed in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.env is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()
