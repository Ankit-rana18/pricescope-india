"""Retry, refresh, canonical products, price history, categories and the sitemap."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pricescope_integrations.models import (
    AdapterState,
    AdapterStatus,
    DataSource,
    Listing,
    Marketplace,
)
from pricescope_integrations.registry import IntegrationConfig, build_adapters
from pricescope_integrations.runner import RetryPolicy
from support.fake_sheets import FakeSheetClient

from app.api.v1.comparisons import get_comparison_service
from app.api.v1.lookup import get_pincode_directory
from app.api.v1.products import get_catalog
from app.core.config import Environment, Settings
from app.main import create_app
from app.models.enums import DataMode
from app.services.catalog import CatalogService
from app.services.comparison.executors import ThreadFetchExecutor
from app.services.comparison.service import ComparisonService
from app.services.pincode import PincodeDirectory
from app.storage.bootstrap import bootstrap
from app.storage.sheets.store import SheetsTableStore

FAST = IntegrationConfig(demo_latency_seconds=(0, 0), demo_timeout_seconds=0.05)
POLICY = RetryPolicy(base_delay_seconds=0.001, max_delay_seconds=0.01)
PHONE = "https://www.amazon.in/dp/DEMO000003"
SALT = "https://www.amazon.in/dp/DEMO000001"


class Env:
    def __init__(self) -> None:
        self.sheets = FakeSheetClient()
        bootstrap(self.sheets)
        self.store = SheetsTableStore(self.sheets)
        self.adapters = build_adapters(FAST)
        self.service = ComparisonService(
            self.store,
            self.adapters,
            ThreadFetchExecutor(self.adapters, policy=POLICY),
            data_mode=DataMode.DEMO,
        )
        self.catalog = CatalogService(self.store)
        app = create_app(Settings(env=Environment.TEST, log_level="WARNING"))
        app.dependency_overrides[get_comparison_service] = lambda: self.service
        app.dependency_overrides[get_catalog] = lambda: self.catalog
        app.dependency_overrides[get_pincode_directory] = lambda: PincodeDirectory()
        self.client = TestClient(app)

    def run(self, url: str, pin: str = "560001") -> dict[str, Any]:
        r = self.client.post("/api/v1/comparisons", json={"url": url, "pincode": pin})
        assert r.status_code in (200, 202), r.text
        self.service.wait(r.json()["id"])
        return self.client.get(f"/api/v1/comparisons/{r.json()['id']}").json()


@pytest.fixture
def env() -> Iterator[Env]:
    e = Env()
    with e.client:
        yield e


class RecoveredAdapter:
    marketplace = Marketplace.BIGBASKET

    def status(self) -> AdapterStatus:
        return AdapterStatus(
            marketplace=self.marketplace,
            state=AdapterState.DEMO,
            data_source=DataSource.DEMO,
            reason="test",
        )

    def search(self, query: Any, limit: int = 5) -> list[Listing]:
        return []


def by_mp(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["marketplace"]: r for r in view["results"]}


# ------------------------------------------------------------------ retry / refresh


def test_retry_rechecks_only_failed_marketplaces_and_updates_saved_rows(env: Env) -> None:
    view = env.run(PHONE)
    assert by_mp(view)["BIGBASKET"]["status"] == "FAILED"
    amazon_checked = by_mp(view)["AMAZON_IN"]["checked_at"]

    # BigBasket "recovers": swap its failing demo adapter for one that answers (no listing).
    env.adapters[Marketplace.BIGBASKET] = RecoveredAdapter()  # type: ignore[assignment]
    r = env.client.post(f"/api/v1/comparisons/{view['id']}/retry")
    assert r.status_code == 202
    assert r.json()["status"] == "RUNNING"
    assert by_mp(r.json())["BIGBASKET"]["status"] == "PENDING"
    env.service.wait(view["id"])
    after = env.client.get(f"/api/v1/comparisons/{view['id']}").json()

    assert after["status"] == "COMPLETE"
    assert by_mp(after)["BIGBASKET"]["status"] == "NOT_FOUND"  # phone isn't sold there
    assert by_mp(after)["AMAZON_IN"]["checked_at"] == amazon_checked  # untouched
    # Saved rows were updated in place, not duplicated.
    assert len(env.store.find("comparison_results", {"comparison_id": view["id"]})) == 5
    fresh = ComparisonService(
        env.store, env.adapters, ThreadFetchExecutor(env.adapters), data_mode=DataMode.DEMO
    )
    assert (
        by_mp(fresh.get(view["id"]).model_dump(mode="json"))["BIGBASKET"]["status"] == "NOT_FOUND"
    )


def test_retry_with_nothing_failed_is_refused(env: Env) -> None:
    view = env.run(SALT)
    r = env.client.post(f"/api/v1/comparisons/{view['id']}/retry")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "nothing_to_retry"


def test_refresh_starts_a_new_comparison(env: Env) -> None:
    first = env.run(SALT)
    again = env.client.post("/api/v1/comparisons", json={"url": SALT, "pincode": "560001"})
    assert again.json()["reused"] is True  # normal request reuses ...
    r = env.client.post(f"/api/v1/comparisons/{first['id']}/refresh")
    assert r.status_code == 202
    assert r.json()["id"] != first["id"]  # ... refresh never does
    assert r.json()["reused"] is False


def test_unknown_comparison_retry_is_404(env: Env) -> None:
    r = env.client.post("/api/v1/comparisons/00000000-0000-0000-0000-000000000000/retry")
    assert r.status_code == 404


# ------------------------------------------------------------------ canonical products


def test_comparison_links_exact_listings_to_one_product(env: Env) -> None:
    view = env.run(PHONE)
    slug = view["product_slug"]
    assert slug and slug.startswith("nimbus-x2-5g-midnight-black")
    p = env.client.get(f"/api/v1/products/{slug}").json()
    assert p["category"] == "Mobiles" and p["category_slug"] == "mobiles"
    assert {lst["marketplace"] for lst in p["listings"]} == {"AMAZON_IN", "FLIPKART"}  # exact only
    assert {i["type"] for i in p["identifiers"]} >= {"GTIN13", "ASIN", "FSN"}
    assert p["variant"] == {
        "size": None,
        "pack_count": 1,
        "colour": "midnight black",
        "storage_gb": 128,
        "ram_gb": 8,
    }
    # Demo-only product: never indexable, never links anywhere.
    assert p["data_mode"] == "DEMO" and p["indexable"] is False
    assert all(lst["url"] is None for lst in p["listings"])


def test_same_product_from_another_marketplace_reuses_the_product(env: Env) -> None:
    a = env.run(PHONE)
    b = env.run("https://www.flipkart.com/demo-product/p/itmdemophne03?pid=DEMOPHNE00000003")
    assert a["product_slug"] == b["product_slug"]
    assert len(env.store.find("products")) == 1


def test_price_history_accumulates_and_filters_by_pin(env: Env) -> None:
    first = env.run(SALT)
    env.client.post(f"/api/v1/comparisons/{first['id']}/refresh")
    env.service.wait(
        env.store.find("comparisons", order_by="created_at", descending=True)[0]["id"].__str__()
    )
    env.run(SALT, pin="110001")
    slug = first["product_slug"]

    h = env.client.get(f"/api/v1/products/{slug}/price-history").json()
    amazon = next(s for s in h["series"] if s["marketplace"] == "AMAZON_IN")
    assert len(amazon["points"]) == 3
    only_560 = env.client.get(f"/api/v1/products/{slug}/price-history?pincode=560001").json()
    assert (
        len(next(s for s in only_560["series"] if s["marketplace"] == "AMAZON_IN")["points"]) == 2
    )
    assert env.client.get(f"/api/v1/products/{slug}/price-history?pincode=12").status_code == 404


def test_unknown_product_is_404(env: Env) -> None:
    assert env.client.get("/api/v1/products/no-such-thing").status_code == 404


# ------------------------------------------------------------------ categories + sitemap


def test_categories_list_and_paginate(env: Env) -> None:
    env.run(PHONE)
    env.run(SALT)
    cats = {c["slug"]: c for c in env.client.get("/api/v1/categories").json()}
    assert set(cats) == {"mobiles", "grocery-staples"}
    assert cats["mobiles"]["indexable"] is False
    page = env.client.get("/api/v1/categories/mobiles/products?limit=1").json()
    assert len(page["products"]) == 1 and page["next_cursor"] is None
    assert env.client.get("/api/v1/categories/nope/products").status_code == 404


def test_sitemap_never_lists_demo_pages_but_lists_live_ones(env: Env) -> None:
    env.run(PHONE)
    assert env.client.get("/api/v1/seo/sitemap").json()["entries"] == [
        {"path": "/", "lastmod": None}
    ]

    live = Listing(
        marketplace=Marketplace.AMAZON_IN,
        external_id="B0LIVE0001",
        title="Real Brand Tea 250 g",
        brand="Real Brand",
        attributes={"category": "Beverages"},
        data_source=DataSource.LIVE,
    )
    linked = env.catalog.link(live, [])
    mid = env.store.find("marketplaces", {"code": "AMAZON_IN"})[0]["id"]
    env.store.insert(
        "marketplace_products",
        {
            "marketplace_id": mid,
            "external_id": "B0LIVE0001",
            "title_raw": live.title,
            "variant_id": linked.variant_id,
            "attributes": {"data_source": "LIVE"},
        },
    )
    paths = [e["path"] for e in env.client.get("/api/v1/seo/sitemap").json()["entries"]]
    assert f"/products/{linked.slug}" in paths
    assert "/categories/beverages" in paths
    assert not any("nimbus" in p for p in paths)
