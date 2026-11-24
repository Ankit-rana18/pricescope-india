"""Shared fixtures.

Tests marked ``db`` run against a real PostgreSQL. They create and drop a throwaway
database (``<name>_test_<random>``) so the development database is never touched, and
are skipped when PostgreSQL is not reachable.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from app.core.config import Environment, Settings
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"


@pytest.fixture
def settings() -> Settings:
    return Settings(env=Environment.TEST, demo_mode=True, log_level="WARNING")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


def _admin_url() -> str:
    base = os.environ.get("PRICESCOPE_DATABASE_URL") or Settings().database_url.get_secret_value()
    return base


@pytest.fixture(scope="session")
def pg_database_url() -> Iterator[str]:
    """Create an isolated, empty database for the test session."""
    admin_url = make_url(_admin_url())
    admin = create_engine(
        admin_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )
    try:
        with admin.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL not reachable: {type(exc).__name__}")

    name = f"{admin_url.database}_test_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield admin_url.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def alembic_config(pg_database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = pg_database_url
    return cfg


@pytest.fixture
def pg_engine(pg_database_url: str) -> Iterator[Engine]:
    engine = create_engine(pg_database_url)
    yield engine
    engine.dispose()
