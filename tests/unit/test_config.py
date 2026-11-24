import pytest
from pydantic import ValidationError

from app.core.config import AuthMode, Environment, Settings


def test_cors_origins_parsed_from_comma_string() -> None:
    s = Settings(cors_origins="http://a.test, https://b.test ,")  # type: ignore[arg-type]
    assert s.cors_origins == ["http://a.test", "https://b.test"]


def test_dev_auth_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE=dev"):
        Settings(env=Environment.PRODUCTION, auth_mode=AuthMode.DEV, supabase_url="https://x")


def test_production_requires_supabase_url() -> None:
    with pytest.raises(ValidationError, match="SUPABASE_URL"):
        Settings(env=Environment.PRODUCTION, auth_mode=AuthMode.SUPABASE)


def test_wildcard_cors_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="Wildcard"):
        Settings(
            env=Environment.PRODUCTION,
            auth_mode=AuthMode.SUPABASE,
            supabase_url="https://x.supabase.co",
            cors_origins=["*"],
        )


def test_secrets_not_leaked_in_repr() -> None:
    s = Settings(database_url="postgresql+psycopg://u:topsecret@h/db")  # type: ignore[arg-type]
    assert "topsecret" not in repr(s)
