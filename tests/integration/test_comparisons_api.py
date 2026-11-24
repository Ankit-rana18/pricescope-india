"""Comparisons end to end through the API, with demo adapters and fake Sheets storage."""

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pricescope_integrations.registry import IntegrationConfig, build_adapters
from pricescope_integrations.runner import RetryPolicy
from support.fake_sheets import FakeSheetClient

from app.api.v1.comparisons import get_comparison_service
from app.api.v1.lookup import get_pincode_directory
from app.core.config import Environment, Settings
from app.main import create_app
from app.models.enums import DataMode
from app.services.comparison.executors import CeleryFetchExecutor, ThreadFetchExecutor
from app.services.comparison.service import ComparisonService
from app.services.pincode import PincodeDirectory
from app.storage.bootstrap import bootstrap
from app.storage.sheets.store import SheetsTableStore

FAST = IntegrationConfig(demo_latency_seconds=(0, 0), demo_timeout_seconds=0.05)
POLICY = RetryPolicy(base_delay_seconds=0.001, max_delay_seconds=0.01)
PHONE = "https://www.amazon.in/Nimbus-X2/dp/DEMO000003?tag=x"
BUTTER = "https://www.amazon.in/dp/DEMO000002"
SALT = "https://www.amazon.in/dp/DEMO000001"


@pytest.fixture
def sheets() -> FakeSheetClient:
    c = FakeSheetClient()
    bootstrap(c)
    return c


def make_service(
    sheets: FakeSheetClient,
    *,
    config: IntegrationConfig = FAST,
    data_mode: DataMode = DataMode.DEMO,
) -> ComparisonService:
    adapters = build_adapters(config)
    return ComparisonService(
        SheetsTableStore(sheets),
        adapters,
        ThreadFetchExecutor(adapters, policy=POLICY),
        data_mode=data_mode,
    )


@pytest.fixture
def service(sheets: FakeSheetClient) -> ComparisonService:
    return make_service(sheets)


def client_for(service: ComparisonService, *, demo: bool = True) -> TestClient:
    app = create_app(Settings(env=Environment.TEST, log_level="WARNING", demo_mode=demo))
    app.dependency_overrides[get_comparison_service] = lambda: service
    app.dependency_overrides[get_pincode_directory] = lambda: PincodeDirectory()
    return TestClient(app)


@pytest.fixture
def client(service: ComparisonService) -> Iterator[TestClient]:
    with client_for(service) as c:
        yield c


def run(
    client: TestClient, service: ComparisonService, url: str, pin: str = "560001"
) -> dict[str, Any]:
    r = client.post("/api/v1/comparisons", json={"url": url, "pincode": pin})
    assert r.status_code == 202, r.text
    started = r.json()
    assert started["status"] == "RUNNING"
    assert {x["status"] for x in started["results"]} == {"PENDING"}
    service.wait(started["id"])
    return client.get(f"/api/v1/comparisons/{started['id']}").json()


def by_marketplace(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["marketplace"]: r for r in view["results"]}


# ------------------------------------------------------------------ outcomes


def test_phone_comparison_ranks_exact_matches_and_card_offers(
    client: TestClient, service: ComparisonService
) -> None:
    view = run(client, service, PHONE)
    assert view["status"] == "PARTIAL"  # BigBasket demo error
    assert view["data_mode"] == "DEMO"
    res = by_marketplace(view)

    amazon, flipkart = res["AMAZON_IN"], res["FLIPKART"]
    assert amazon["is_source"] and amazon["is_cheapest"] and amazon["rank"] == 1
    assert flipkart["match_class"] == "EXACT" and flipkart["rank"] == 2
    assert flipkart["delivery_verified"] is False
    # The blue variant is shown as another listing, rejected.
    assert flipkart["other_candidates"][0]["match_class"] == "MISMATCH"
    assert res["BIGBASKET"]["status"] == "FAILED"
    assert res["BLINKIT"]["status"] == "NOT_FOUND"

    s = view["summary"]
    assert s["cheapest"]["marketplace"] == "AMAZON_IN"
    assert Decimal(s["cheaper_unverified"]["final_price"]) == Decimal("14008.00")
    # Best regular card offer wins over the bigger EMI-only one.
    assert amazon["best_card"]["bank"] == "Demo Bank A"
    assert Decimal(amazon["price_after_best_card"]) == Decimal("13499.10")
    assert s["best_with_card"]["marketplace"] == "FLIPKART"
    assert s["best_with_card"]["delivery_verified"] is False
    # Card offers never change the final price.
    assert Decimal(amazon["price"]["final_price"]) == Decimal("14999.00")


def test_butter_rejects_pack_mismatch_and_skips_out_of_stock(
    client: TestClient, service: ComparisonService
) -> None:
    view = run(client, service, BUTTER)
    res = by_marketplace(view)
    assert res["FLIPKART"]["match_class"] == "MISMATCH"
    assert any("pack count" in r for r in res["FLIPKART"]["match_reasons"])
    assert res["BIGBASKET"]["ranked"] is False
    assert "out of stock" in res["BIGBASKET"]["not_ranked_because"]
    assert res["ZEPTO"]["status"] == "FAILED"  # timeout after retries
    assert res["AMAZON_IN"]["attempts"] >= 3  # rate-limited once, then retried
    assert view["summary"]["cheapest"]["marketplace"] == "BLINKIT"
    assert Decimal(view["summary"]["savings_vs_source"]) == Decimal("26.00")


def test_unknown_fees_and_far_pin_codes(client: TestClient, service: ComparisonService) -> None:
    res = by_marketplace(run(client, service, SALT, pin="799001"))
    assert res["FLIPKART"]["price"]["final_price_complete"] is False
    assert res["FLIPKART"]["price"]["delivery_fee"] == {
        "status": "UNKNOWN",
        "amount": None,
        "note": "Depends on cart value",
    }
    assert "some fees are unknown" in res["FLIPKART"]["not_ranked_because"]
    assert res["BLINKIT"]["location_verification"] == "UNAVAILABLE"
    assert res["BLINKIT"]["ranked"] is False


def test_demo_results_carry_no_links(client: TestClient, service: ComparisonService) -> None:
    view = run(client, service, SALT)
    assert view["source"]["url"] is None
    assert all(r["listing"] is None or r["listing"]["url"] is None for r in view["results"])


# ------------------------------------------------------------------ storage


def test_saved_comparison_rebuilds_identically_after_restart(
    sheets: FakeSheetClient, client: TestClient, service: ComparisonService
) -> None:
    live = run(client, service, PHONE)
    fresh = make_service(sheets)  # new process: empty memory, same spreadsheet
    with client_for(fresh) as c2:
        stored = c2.get(f"/api/v1/comparisons/{live['id']}").json()
    assert stored == live


def test_storage_use_per_comparison_is_small(
    sheets: FakeSheetClient, client: TestClient, service: ComparisonService
) -> None:
    run(client, service, SALT)  # warm marketplace ids
    sheets.calls.clear()
    run(client, service, BUTTER)
    # listings, results, price history, location checks (+ comparison row at start)
    assert sheets.calls["append_rows"] <= 5
    assert sheets.calls["update_row"] == 1


def test_storage_failure_still_shows_results(service: ComparisonService) -> None:
    store = service._store
    real_insert_many = store.insert_many

    def failing(table: str, rows: Any) -> Any:
        if table == "comparison_results":
            raise ConnectionError("sheets down")
        return real_insert_many(table, rows)

    store.insert_many = failing  # type: ignore[method-assign]
    with client_for(service) as c:
        r = c.post("/api/v1/comparisons", json={"url": SALT, "pincode": "560001"})
        service.wait(r.json()["id"])
        view = c.get(f"/api/v1/comparisons/{r.json()['id']}").json()
    assert view["status"] == "COMPLETE"
    assert "couldn't be saved" in view["storage_note"]


def test_identical_request_reuses_finished_comparison(
    client: TestClient, service: ComparisonService
) -> None:
    first = run(client, service, SALT)
    again = client.post("/api/v1/comparisons", json={"url": SALT, "pincode": "560001"})
    assert again.status_code == 200
    assert again.json()["id"] == first["id"] and again.json()["reused"] is True
    other_pin = client.post("/api/v1/comparisons", json={"url": SALT, "pincode": "110001"})
    assert other_pin.status_code == 202


# ------------------------------------------------------------------ errors


def test_invalid_input_reports_fields(client: TestClient) -> None:
    r = client.post("/api/v1/comparisons", json={"url": "https://example.com/x", "pincode": "1"})
    assert r.status_code == 422
    assert {f["field"] for f in r.json()["error"]["details"]["fields"]} == {"url", "pincode"}


def test_unknown_demo_product(client: TestClient) -> None:
    r = client.post(
        "/api/v1/comparisons",
        json={"url": "https://www.amazon.in/dp/B07JGFGW3V", "pincode": "560001"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "source_not_found"
    assert "sample products" in r.json()["error"]["message"]


def test_live_mode_explains_marketplace_is_not_connected(sheets: FakeSheetClient) -> None:
    live = make_service(sheets, config=IntegrationConfig(demo_mode=False), data_mode=DataMode.LIVE)
    with client_for(live, demo=False) as c:
        r = c.post("/api/v1/comparisons", json={"url": SALT, "pincode": "560001"})
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "source_unavailable"
        assert "Amazon India isn't connected yet" in r.json()["error"]["message"]
        assert c.get("/api/v1/demo/products").status_code == 404
        states = {
            m["marketplace"]: m["state"]
            for m in c.get("/api/v1/marketplaces").json()["marketplaces"]
        }
    assert states == {
        "AMAZON_IN": "NOT_CONFIGURED",
        "FLIPKART": "NOT_CONFIGURED",
        "BLINKIT": "UNSUPPORTED",
        "ZEPTO": "UNSUPPORTED",
        "BIGBASKET": "UNSUPPORTED",
    }


def test_unknown_comparison_id(client: TestClient) -> None:
    assert client.get("/api/v1/comparisons/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get("/api/v1/comparisons/not-a-uuid").status_code == 404


def test_demo_products_endpoint(client: TestClient) -> None:
    products = client.get("/api/v1/demo/products").json()
    assert len(products) == 4
    assert all(p["url"].startswith("https://") for p in products)


# ------------------------------------------------------------------ executors


def test_celery_executor_matches_thread_executor(sheets: FakeSheetClient) -> None:
    """Celery in eager mode runs the real task code path without a broker."""
    from pricescope_workers.celery_app import app as celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        adapters = build_adapters(FAST)
        celery_service = ComparisonService(
            SheetsTableStore(sheets),
            adapters,
            CeleryFetchExecutor(FAST),
            data_mode=DataMode.DEMO,
        )
        with client_for(celery_service) as c:
            view = run(c, celery_service, PHONE)
        res = by_marketplace(view)
        assert res["AMAZON_IN"]["is_cheapest"]
        assert res["BIGBASKET"]["status"] == "FAILED"
    finally:
        celery_app.conf.task_always_eager = False


def test_thread_executor_turns_a_hung_marketplace_into_failure() -> None:
    import threading

    from pricescope_integrations.models import ProductQuery

    from app.services.comparison.executors import FetchJob

    release = threading.Event()

    class Hung:
        def __init__(self, inner: Any) -> None:
            self._inner, self.marketplace = inner, inner.marketplace

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def search(self, *a: Any, **k: Any) -> Any:
            release.wait(5)
            return []

    adapters = build_adapters(FAST)
    from pricescope_integrations.models import Marketplace

    adapters[Marketplace.ZEPTO] = Hung(adapters[Marketplace.ZEPTO])  # type: ignore[assignment]
    ex = ThreadFetchExecutor(adapters, policy=POLICY, overall_timeout_seconds=0.5)
    q = ProductQuery(title="Saltwise Iodised Salt, 1 kg", brand="Saltwise", gtin="2000000000015")
    results = {
        r.marketplace: r for r in ex.run([FetchJob(m, q, "560001", None) for m in Marketplace])
    }
    release.set()
    assert results[Marketplace.ZEPTO].error_code == "deadline_exceeded"
    assert results[Marketplace.AMAZON_IN].status.value == "OK"


# ------------------------------------------------------------------ Phase 6: policies + location


def make_phase6_service(sheets: FakeSheetClient) -> ComparisonService:
    from pricescope_integrations.demo.adapter import demo_fee_policies

    from app.services.fee_policies import demo_policies
    from app.services.pincode import PincodeDirectory

    adapters = build_adapters(FAST)
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "pincode_directory_sample.csv"
    return ComparisonService(
        SheetsTableStore(sheets),
        adapters,
        ThreadFetchExecutor(adapters, policy=POLICY),
        data_mode=DataMode.DEMO,
        directory=PincodeDirectory.from_csv(sample),
        policies=demo_policies(demo_fee_policies()),
    )


def test_demo_policy_estimates_unknown_delivery_and_is_ranked_after_verified(
    sheets: FakeSheetClient,
) -> None:
    service = make_phase6_service(sheets)
    with client_for(service) as c:
        view = run(c, service, SALT)
    fk = by_marketplace(view)["FLIPKART"]
    assert fk["price"]["delivery_fee"]["status"] == "ESTIMATED"
    assert Decimal(fk["price"]["delivery_fee"]["amount"]) == Decimal("40.00")
    assert fk["price"]["final_price_estimated"] is True
    assert fk["price_verified"] is False
    assert fk["ranked"] is True  # complete (estimated) prices are ranked ...
    assert view["summary"]["cheapest"]["marketplace"] == "AMAZON_IN"  # ... but never "verified"
    ranks = {r["marketplace"]: r["rank"] for r in view["results"] if r["ranked"]}
    assert ranks["FLIPKART"] > ranks["AMAZON_IN"]


def test_comparison_shows_pin_area_and_saves_location_checks(sheets: FakeSheetClient) -> None:
    service = make_phase6_service(sheets)
    with client_for(service) as c:
        view = run(c, service, SALT, pin="110001")
    assert view["location"] == {
        "postal_region": "Northern",
        "directory_status": "VERIFIED",
        "district": "New Delhi",
        "state": "Delhi",
        "division": "New Delhi GPO Division",
        "circle": "Delhi Circle",
    }
    saved = sheets.column_values("location_checks", "verification")
    assert "VERIFIED" in saved and "UNVERIFIABLE" in saved


def test_estimated_flag_survives_reload(sheets: FakeSheetClient) -> None:
    service = make_phase6_service(sheets)
    with client_for(service) as c:
        live = run(c, service, SALT)
    fresh = make_phase6_service(sheets)
    with client_for(fresh) as c2:
        stored = c2.get(f"/api/v1/comparisons/{live['id']}").json()
    assert stored == live
