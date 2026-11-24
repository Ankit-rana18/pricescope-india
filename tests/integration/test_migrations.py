"""Migrations against a real, throwaway PostgreSQL database."""

from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DataError, IntegrityError

from app.api.v1.health import storage_provider
from app.core.config import Environment, Settings, StorageBackendName
from app.main import create_app
from app.models import Base
from app.storage.sql_store import SqlTableStore

pytestmark = pytest.mark.db

EXPECTED_TABLES = {
    "users",
    "products",
    "product_variants",
    "marketplaces",
    "marketplace_products",
    "product_identifiers",
    "comparisons",
    "comparison_results",
    "price_history",
    "location_checks",
    "delivery_fees",
    "saved_products",
    "price_alerts",
    "integration_credentials",
    "integration_health_logs",
    "pincode_directory",
    "audit_logs",
}


def test_single_migration_head(alembic_config: Config) -> None:
    assert len(ScriptDirectory.from_config(alembic_config).get_heads()) == 1


def test_upgrade_downgrade_roundtrip(alembic_config: Config, pg_engine: Engine) -> None:
    command.upgrade(alembic_config, "head")
    tables = set(inspect(pg_engine).get_table_names())
    assert tables >= EXPECTED_TABLES

    command.downgrade(alembic_config, "base")
    remaining = set(inspect(pg_engine).get_table_names()) - {"alembic_version"}
    assert remaining == set()

    command.upgrade(alembic_config, "head")


def test_models_match_migrations(alembic_config: Config, pg_engine: Engine) -> None:
    """Autogenerate must find no differences: models and migrations are in sync."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    command.upgrade(alembic_config, "head")
    with pg_engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == []


def test_marketplaces_seeded_without_verified_capabilities(
    alembic_config: Config, pg_engine: Engine
) -> None:
    command.upgrade(alembic_config, "head")
    with pg_engine.connect() as conn:
        rows = conn.execute(text("SELECT code, capabilities FROM marketplaces")).all()
    assert {r.code for r in rows} == {"AMAZON_IN", "FLIPKART", "BLINKIT", "ZEPTO", "BIGBASKET"}
    for r in rows:
        for key in ("search_by_gtin", "location", "fees", "coupons"):
            assert r.capabilities[key] == "unverified"


def _mkt_id(conn: sa.Connection) -> object:
    return conn.execute(text("SELECT id FROM marketplaces WHERE code='AMAZON_IN'")).scalar_one()


@pytest.mark.parametrize("pincode", ["012345", "12345", "1234567", "abcdef"])
def test_invalid_pincode_rejected_by_database(
    alembic_config: Config, pg_engine: Engine, pincode: str
) -> None:
    command.upgrade(alembic_config, "head")
    # Too long -> DataError (varchar(6)); wrong format -> IntegrityError (CHECK).
    with pytest.raises((IntegrityError, DataError)), pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO comparisons (source_url, pincode, data_mode) "
                "VALUES ('https://www.amazon.in/dp/B000000000', :p, 'DEMO')"
            ),
            {"p": pincode},
        )


def test_credential_table_only_accepts_references(
    alembic_config: Config, pg_engine: Engine
) -> None:
    command.upgrade(alembic_config, "head")
    insert = text(
        "INSERT INTO integration_credentials (marketplace_id, key_name, secret_ref) "
        "VALUES (:m, :k, :r)"
    )
    with pg_engine.begin() as conn:
        conn.execute(
            insert,
            {"m": _mkt_id(conn), "k": "secret", "r": "env:AMAZON_CREATORS_CREDENTIAL_SECRET"},
        )
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(insert, {"m": _mkt_id(conn), "k": "raw", "r": "sk_live_actual_secret"})


def test_complete_final_price_requires_value(alembic_config: Config, pg_engine: Engine) -> None:
    command.upgrade(alembic_config, "head")
    with pg_engine.begin() as conn:
        cmp_id = conn.execute(
            text(
                "INSERT INTO comparisons (source_url, pincode, data_mode) "
                "VALUES ('https://www.amazon.in/dp/B000000000', '560001', 'DEMO') RETURNING id"
            )
        ).scalar_one()
        mkt = _mkt_id(conn)
        row = conn.execute(
            text(
                "INSERT INTO comparison_results "
                "(comparison_id, marketplace_id, status, item_price) "
                "VALUES (:c, :m, 'OK', :p) RETURNING delivery_fee, delivery_fee_status"
            ),
            {"c": cmp_id, "m": mkt, "p": Decimal("99.00")},
        ).one()
        # Unknown fee is NULL + UNKNOWN, never zero.
        assert row.delivery_fee is None
        assert row.delivery_fee_status == "UNKNOWN"
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(
            text("UPDATE comparison_results SET final_price_complete = true, final_price = NULL")
        )


def test_readiness_reports_postgres_storage_ok(pg_engine: Engine) -> None:
    app = create_app(
        Settings(
            env=Environment.TEST,
            log_level="WARNING",
            storage_backend=StorageBackendName.POSTGRES,
        )
    )
    app.dependency_overrides[storage_provider] = lambda: lambda: SqlTableStore(pg_engine)
    with TestClient(app) as c:
        r = c.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "data_mode": "DEMO",
        "storage_backend": "postgres",
        "checks": {"storage": "ok"},
    }
