"""One behavioural contract, two backends.

Every test runs against the Google Sheets store (in-memory fake spreadsheet) and against
real PostgreSQL (skipped if unreachable), proving the Sheets store enforces the same rules
as the database: types, defaults, unique/foreign keys, CHECK rules and ON DELETE actions.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from support.fake_sheets import FakeSheetClient

from app.models.enums import (
    ChargeStatus,
    ComparisonStatus,
    DataMode,
    MarketplaceCode,
    QuantityUnit,
)
from app.storage.base import TableStore
from app.storage.bootstrap import bootstrap
from app.storage.errors import ConstraintViolation, RowNotFound
from app.storage.sheets.store import SheetsTableStore


@pytest.fixture(params=["sheets", pytest.param("postgres", marks=pytest.mark.db)])
def store(request: pytest.FixtureRequest) -> Iterator[TableStore]:
    if request.param == "sheets":
        client = FakeSheetClient()
        bootstrap(client)
        yield SheetsTableStore(client, cache_ttl_seconds=10)
        return
    from sqlalchemy import create_engine

    from app.storage.sql_store import SqlTableStore

    cfg: Config = request.getfixturevalue("alembic_config")
    command.upgrade(cfg, "head")
    engine = create_engine(request.getfixturevalue("pg_database_url"))
    yield SqlTableStore(engine)
    engine.dispose()


def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _marketplace(store: TableStore, code: MarketplaceCode = MarketplaceCode.AMAZON_IN) -> Any:
    return store.find("marketplaces", {"code": code})[0]["id"]


def _comparison(store: TableStore, **extra: Any) -> dict[str, Any]:
    return store.insert(
        "comparisons",
        {
            "source_url": f"https://www.amazon.in/dp/{_uid()}",
            "pincode": "560001",
            "data_mode": DataMode.DEMO,
            **extra,
        },
    )


def _product_variant(store: TableStore) -> tuple[dict[str, Any], dict[str, Any]]:
    product = store.insert("products", {"slug": f"p-{_uid()}", "title": "Tata Salt 1 kg"})
    variant = store.insert(
        "product_variants",
        {
            "product_id": product["id"],
            "variant_key": "1000g|x1",
            "quantity_value": Decimal("1000"),
            "quantity_unit": "g",
            "attributes": {"iodized": True},
        },
    )
    return product, variant


# ------------------------------------------------------------------ types and defaults


def test_seeded_marketplaces_are_present(store: TableStore) -> None:
    codes = {r["code"] for r in store.find("marketplaces")}
    assert codes == set(MarketplaceCode)


def test_insert_applies_defaults_and_roundtrips_types(store: TableStore) -> None:
    product, variant = _product_variant(store)
    assert isinstance(product["id"], uuid.UUID)
    assert product["created_at"].tzinfo is not None
    assert variant["pack_count"] == 1  # default
    assert variant["quantity_value"] == Decimal("1000.000")
    assert variant["quantity_unit"] is QuantityUnit.GRAM

    again = store.get("product_variants", variant["id"])
    assert again == variant
    assert again["attributes"] == {"iodized": True}


def test_unknown_fees_are_null_with_unknown_status_never_zero(store: TableStore) -> None:
    cmp = _comparison(store)
    assert cmp["status"] is ComparisonStatus.PENDING
    result = store.insert(
        "comparison_results",
        {
            "comparison_id": cmp["id"],
            "marketplace_id": _marketplace(store),
            "status": "OK",
            "item_price": Decimal("99.5"),
        },
    )
    for fee in ("delivery_fee", "handling_fee", "platform_fee", "other_fees"):
        assert result[fee] is None
        assert result[f"{fee}_status"] is ChargeStatus.UNKNOWN
    assert result["item_price"] == Decimal("99.50")
    assert result["final_price_complete"] is False
    assert result["match_reasons"] == []


# ------------------------------------------------------------------ keys


def test_unique_key_enforced(store: TableStore) -> None:
    with pytest.raises(ConstraintViolation):
        store.insert(
            "marketplaces",
            {"code": "AMAZON_IN", "name": "dup", "base_domains": ["amazon.in"]},
        )


def test_composite_unique_key_enforced(store: TableStore) -> None:
    cmp = _comparison(store)
    row = {"comparison_id": cmp["id"], "marketplace_id": _marketplace(store), "status": "OK"}
    store.insert("comparison_results", row)
    with pytest.raises(ConstraintViolation):
        store.insert("comparison_results", row)


def test_case_insensitive_email_is_unique(store: TableStore) -> None:
    email = f"Asha.{_uid()}@Example.test"
    store.insert("users", {"id": uuid.uuid4(), "email": email})
    with pytest.raises(ConstraintViolation):
        store.insert("users", {"id": uuid.uuid4(), "email": email.lower()})


def test_foreign_key_to_missing_parent_rejected(store: TableStore) -> None:
    with pytest.raises(ConstraintViolation):
        store.insert(
            "comparison_results",
            {"comparison_id": uuid.uuid4(), "marketplace_id": _marketplace(store), "status": "OK"},
        )


# ------------------------------------------------------------------ validation


def _bad_rows(store: TableStore) -> list[tuple[str, dict[str, Any]]]:
    mkt = _marketplace(store)
    cmp = _comparison(store)
    product, _ = _product_variant(store)
    url = "https://www.amazon.in/dp/X"
    return [
        ("comparisons", {"source_url": url, "pincode": "012345", "data_mode": "DEMO"}),
        ("comparisons", {"source_url": url, "pincode": "56001", "data_mode": "DEMO"}),
        ("comparisons", {"source_url": url, "pincode": "560001", "data_mode": "MAYBE"}),
        (
            "integration_credentials",
            {"marketplace_id": mkt, "key_name": "k", "secret_ref": "sk_live_raw_secret"},
        ),
        (
            "comparison_results",
            {
                "comparison_id": cmp["id"],
                "marketplace_id": mkt,
                "status": "OK",
                "final_price_complete": True,
            },
        ),
        (
            "comparison_results",
            {
                "comparison_id": cmp["id"],
                "marketplace_id": mkt,
                "status": "OK",
                "item_price": 99.99,  # float money refused
            },
        ),
        (
            "product_variants",
            {"product_id": product["id"], "variant_key": "x", "pack_count": 0},
        ),
        (
            "product_variants",
            {"product_id": product["id"], "variant_key": "y", "quantity_value": Decimal("5")},
        ),
        ("products", {"slug": "s" * 201, "title": "too long slug"}),
        ("products", {"slug": f"ok-{_uid()}", "title": "t", "not_a_column": 1}),
        ("products", {"slug": f"ok-{_uid()}", "title": ""}),  # empty == NULL
    ]


def test_invalid_rows_rejected(store: TableStore) -> None:
    for table, values in _bad_rows(store):
        with pytest.raises(ConstraintViolation):
            store.insert(table, values)


def test_update_revalidates_and_refreshes_updated_at(store: TableStore) -> None:
    cmp = _comparison(store)
    updated = store.update("comparisons", cmp["id"], {"status": ComparisonStatus.COMPLETE})
    assert updated["status"] is ComparisonStatus.COMPLETE
    assert updated["updated_at"] >= cmp["updated_at"]
    assert updated["created_at"] == cmp["created_at"]

    with pytest.raises(ConstraintViolation):
        store.update("comparisons", cmp["id"], {"pincode": "000000"})
    assert store.get("comparisons", cmp["id"])["pincode"] == "560001"

    with pytest.raises(ConstraintViolation):
        store.update("comparisons", cmp["id"], {"id": uuid.uuid4()})


def test_missing_rows(store: TableStore) -> None:
    with pytest.raises(RowNotFound):
        store.get("comparisons", uuid.uuid4())
    with pytest.raises(RowNotFound):
        store.get("comparisons", "not-a-uuid")
    with pytest.raises(RowNotFound):
        store.update("comparisons", uuid.uuid4(), {"status": "RUNNING"})
    with pytest.raises(RowNotFound):
        store.delete("comparisons", uuid.uuid4())


# ------------------------------------------------------------------ deletes


def test_delete_cascades_to_children(store: TableStore) -> None:
    cmp = _comparison(store)
    store.insert(
        "comparison_results",
        {"comparison_id": cmp["id"], "marketplace_id": _marketplace(store), "status": "OK"},
    )
    store.delete("comparisons", cmp["id"])
    assert store.find("comparison_results", {"comparison_id": cmp["id"]}) == []


def test_delete_sets_null_where_declared(store: TableStore) -> None:
    user = store.insert("users", {"id": uuid.uuid4(), "email": f"u{_uid()}@x.test"})
    cmp = _comparison(store, user_id=user["id"])
    store.delete("users", user["id"])
    assert store.get("comparisons", cmp["id"])["user_id"] is None


def test_restricted_delete_refused_and_nothing_removed(store: TableStore) -> None:
    mkt = _marketplace(store, MarketplaceCode.FLIPKART)
    store.insert(
        "integration_health_logs", {"marketplace_id": mkt, "status": "NOT_CONFIGURED"}
    )  # CASCADE child: must survive the refused delete
    store.insert(
        "marketplace_products",
        {"marketplace_id": mkt, "external_id": _uid(), "url": "https://x", "title_raw": "t"},
    )  # RESTRICT child
    with pytest.raises(ConstraintViolation):
        store.delete("marketplaces", mkt)
    assert store.get("marketplaces", mkt)["code"] is MarketplaceCode.FLIPKART
    assert len(store.find("integration_health_logs", {"marketplace_id": mkt})) == 1


# ------------------------------------------------------------------ queries


def test_find_filters_orders_and_limits(store: TableStore) -> None:
    listing = store.insert(
        "marketplace_products",
        {
            "marketplace_id": _marketplace(store, MarketplaceCode.ZEPTO),
            "external_id": _uid(),
            "url": "https://www.zeptonow.com/pn/x",
            "title_raw": "Amul Butter 500 g",
        },
    )
    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    for i, price in enumerate(["270", "265", "275"]):
        store.insert(
            "price_history",
            {
                "marketplace_product_id": listing["id"],
                "item_price": Decimal(price),
                "data_mode": "DEMO",
                "observed_at": t0 + timedelta(days=i),
            },
        )
    rows = store.find(
        "price_history",
        {"marketplace_product_id": listing["id"]},
        order_by="observed_at",
        descending=True,
        limit=2,
    )
    assert [r["item_price"] for r in rows] == [Decimal("275.00"), Decimal("265.00")]


def test_estimated_fee_status_is_storable(store: TableStore) -> None:
    cmp = _comparison(store)
    row = store.insert(
        "comparison_results",
        {
            "comparison_id": cmp["id"],
            "marketplace_id": _marketplace(store),
            "status": "OK",
            "delivery_fee": Decimal("40"),
            "delivery_fee_status": "ESTIMATED",
        },
    )
    assert row["delivery_fee_status"] is ChargeStatus.ESTIMATED
    assert store.get("comparison_results", row["id"])["delivery_fee"] == Decimal("40.00")
