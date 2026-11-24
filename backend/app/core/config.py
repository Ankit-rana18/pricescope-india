"""Application settings, loaded from environment variables (never hard-coded secrets)."""

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pricescope_integrations.registry import IntegrationConfig
from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class AuthMode(StrEnum):
    SUPABASE = "supabase"
    # Local-only, clearly labelled development auth. Refused in production.
    DEV = "dev"


class StorageBackendName(StrEnum):
    # Interim primary store: one tab per table in a Google spreadsheet.
    SHEETS = "sheets"
    POSTGRES = "postgres"


class TaskExecutor(StrEnum):
    THREADS = "threads"  # in-process thread pool; no Redis needed
    CELERY = "celery"  # Celery workers via Redis


def _secret(name: str) -> SecretStr | None:
    """Marketplace credentials use their vendor-style names (no PRICESCOPE_ prefix)."""
    return Field(default=None, validation_alias=AliasChoices(name))


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

    storage_backend: StorageBackendName = StorageBackendName.SHEETS
    google_sheets_spreadsheet_id: str = ""
    # Service-account credentials: a file path (local dev) or the JSON itself (hosted envs).
    google_service_account_file: str = ""
    google_service_account_json: SecretStr | None = None
    # How long a tab's contents are reused before re-reading (own writes invalidate at once).
    sheets_cache_ttl_seconds: float = Field(default=10.0, ge=0, le=300)

    # India Post PIN directory CSV (open data). Empty = existence check unavailable.
    pincode_directory_file: str = ""

    task_executor: TaskExecutor = TaskExecutor.THREADS
    # Presence of approved credentials only; adapters still report NOT_CONFIGURED until a
    # verified live client exists.
    amazon_creators_credential_id: SecretStr | None = _secret("AMAZON_CREATORS_CREDENTIAL_ID")
    amazon_creators_credential_secret: SecretStr | None = _secret(
        "AMAZON_CREATORS_CREDENTIAL_SECRET"
    )
    flipkart_affiliate_id: SecretStr | None = _secret("FLIPKART_AFFILIATE_ID")
    flipkart_affiliate_token: SecretStr | None = _secret("FLIPKART_AFFILIATE_TOKEN")
    quick_commerce_provider: str | None = Field(
        default=None, validation_alias=AliasChoices("QUICK_COMMERCE_PROVIDER")
    )

    auth_mode: AuthMode = AuthMode.DEV
    supabase_url: str = ""
    supabase_jwt_audience: str = "authenticated"

    # Optional AI review of ambiguous matches (Claude API). Off by default; costs tokens.
    llm_review_enabled: bool = False
    llm_review_model: str = "claude-opus-5-5"
    llm_review_max_per_comparison: int = Field(default=6, ge=0, le=50)
    llm_review_timeout_seconds: float = Field(default=12.0, gt=0, le=60)

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
            if self.storage_backend is StorageBackendName.SHEETS and not self.sheets_configured:
                raise ValueError(
                    "Google Sheets storage needs PRICESCOPE_GOOGLE_SHEETS_SPREADSHEET_ID and "
                    "service-account credentials in production"
                )
        return self

    @property
    def is_production(self) -> bool:
        return self.env is Environment.PRODUCTION

    def integration_config(self) -> IntegrationConfig:
        def present(*values: SecretStr | None) -> bool:
            return all(v is not None and v.get_secret_value().strip() for v in values)

        return IntegrationConfig(
            demo_mode=self.demo_mode,
            amazon_credentials_present=present(
                self.amazon_creators_credential_id, self.amazon_creators_credential_secret
            ),
            flipkart_credentials_present=present(
                self.flipkart_affiliate_id, self.flipkart_affiliate_token
            ),
            quick_commerce_provider=(self.quick_commerce_provider or "").strip() or None,
        )

    @property
    def sheets_configured(self) -> bool:
        has_credentials = bool(self.google_service_account_file) or bool(
            self.google_service_account_json and self.google_service_account_json.get_secret_value()
        )
        return bool(self.google_sheets_spreadsheet_id) and has_credentials


@lru_cache
def get_settings() -> Settings:
    return Settings()
