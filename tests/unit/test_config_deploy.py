"""Settings behaviour that matters on hosted deploys."""

import pytest

from app.core.config import Environment, Settings


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p@db.internal:5432/pricescope",
        "postgresql://u:p@db.internal:5432/pricescope",
        "postgresql+psycopg://u:p@db.internal:5432/pricescope",
    ],
)
def test_hosted_database_urls_use_the_psycopg_driver(url: str) -> None:
    s = Settings(env=Environment.TEST, database_url=url)  # type: ignore[arg-type]
    assert (
        s.database_url.get_secret_value() == "postgresql+psycopg://u:p@db.internal:5432/pricescope"
    )


def test_rate_limit_defaults_match_the_plan() -> None:
    s = Settings(env=Environment.TEST)
    assert (s.rate_limit_compare_anon, s.rate_limit_compare_user) == (10, 30)
    assert s.trusted_proxy_hops == 0  # X-Forwarded-For is ignored unless configured
