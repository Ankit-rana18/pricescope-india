"""Adapter honesty rules, demo data labelling, and the retrying fetch runner."""

import re
import time
from decimal import Decimal

import pytest
from pricescope_integrations.base import AdapterTimeout, AdapterUpstreamError, ListingNotFound
from pricescope_integrations.demo.adapter import DemoAdapter, demo_source_links, load_catalog
from pricescope_integrations.models import (
    AdapterState,
    AdapterStatus,
    DataSource,
    FetchStatus,
    Listing,
    Marketplace,
    Offer,
    ProductQuery,
)
from pricescope_integrations.registry import IntegrationConfig, build_adapters
from pricescope_integrations.runner import RetryPolicy, fetch_marketplace

from app.models.enums import MarketplaceCode
from app.services.url_parser import parse_product_url

FAST = IntegrationConfig(demo_latency_seconds=(0, 0), demo_timeout_seconds=0.05)
NO_WAIT = RetryPolicy(base_delay_seconds=0.001, max_delay_seconds=0.001)


def test_marketplace_codes_match_backend() -> None:
    assert {m.value for m in Marketplace} == {m.value for m in MarketplaceCode}


# ------------------------------------------------------------------ honesty


@pytest.mark.parametrize("creds", [False, True])
def test_official_adapters_are_never_live(creds: bool) -> None:
    adapters = build_adapters(
        IntegrationConfig(
            demo_mode=False,
            amazon_credentials_present=creds,
            flipkart_credentials_present=creds,
            quick_commerce_provider="SomeProvider" if creds else None,
        )
    )
    states = {m: a.status().state for m, a in adapters.items()}
    assert AdapterState.LIVE not in states.values()
    assert AdapterState.DEMO not in states.values()  # never mixed with demo
    assert states[Marketplace.AMAZON_IN] is AdapterState.NOT_CONFIGURED
    expected_qc = AdapterState.NOT_CONFIGURED if creds else AdapterState.UNSUPPORTED
    assert states[Marketplace.BLINKIT] is expected_qc
    for a in adapters.values():
        assert a.status().reason  # always explains why


def test_live_mode_fetch_reports_status_without_calling_anything() -> None:
    adapters = build_adapters(IntegrationConfig(demo_mode=False))
    q = ProductQuery(title="x")
    assert (
        fetch_marketplace(adapters[Marketplace.AMAZON_IN], q, "560001").status
        is FetchStatus.NOT_CONFIGURED
    )
    assert (
        fetch_marketplace(adapters[Marketplace.ZEPTO], q, "560001").status
        is FetchStatus.UNSUPPORTED
    )


def test_demo_mode_is_all_demo() -> None:
    adapters = build_adapters(FAST)
    assert {a.status().state for a in adapters.values()} == {AdapterState.DEMO}


def test_demo_catalog_is_clearly_fictional() -> None:
    catalog = load_catalog()
    assert catalog["notice"].startswith("DEMO DATA")
    for product in catalog["products"]:
        for specs in product["listings"].values():
            for s in specs:
                if s.get("gtin"):
                    # GS1 prefixes 20-29: in-store numbers, never a real trade item.
                    assert re.fullmatch(r"2\d{12}", s["gtin"]), s["gtin"]
                for c in s["offer"].get("card_offers", []):
                    assert c["bank"].startswith("Demo Bank")


def test_demo_listings_have_no_links_and_are_labelled() -> None:
    a = DemoAdapter(Marketplace.AMAZON_IN, latency_seconds=(0, 0))
    listing = a.get_listing("DEMO000003")
    assert listing.url is None and listing.image_url is None
    assert listing.data_source is DataSource.DEMO
    assert a.get_offer("DEMO000003", "560001").data_source is DataSource.DEMO
    with pytest.raises(ListingNotFound):
        a.get_listing("B07JGFGW3V")  # a real-looking ASIN is not in the demo catalog


def test_demo_links_parse_back_to_their_listings() -> None:
    for d in demo_source_links():
        parsed = parse_product_url(d["url"])
        assert parsed.marketplace.value == d["marketplace"]
        adapter = DemoAdapter(Marketplace(d["marketplace"]), latency_seconds=(0, 0))
        assert adapter.get_listing(parsed.external_id).title == d["title"]


def test_quick_commerce_location_depends_on_pin() -> None:
    a = DemoAdapter(Marketplace.BLINKIT, latency_seconds=(0, 0))
    assert a.get_offer("9000001", "560001").location.verification.value == "VERIFIED"
    far = a.get_offer("9000001", "799001").location
    assert (far.verification.value, far.serviceable) == ("UNAVAILABLE", False)


# ------------------------------------------------------------------ runner


class Flaky:
    """Adapter whose search fails ``fail_times`` with ``error`` before succeeding."""

    marketplace = Marketplace.FLIPKART

    def __init__(
        self, error: Exception | None = None, fail_times: int = 0, crash: bool = False
    ) -> None:
        self.error, self.fail_times, self.crash, self.calls = error, fail_times, crash, 0

    def status(self) -> AdapterStatus:
        return AdapterStatus(
            marketplace=self.marketplace,
            state=AdapterState.DEMO,
            data_source=DataSource.DEMO,
            reason="t",
        )

    def get_listing(self, external_id: str) -> Listing:
        raise NotImplementedError

    def search(self, query: ProductQuery, limit: int = 5) -> list[Listing]:
        self.calls += 1
        if self.crash:
            raise RuntimeError("bug")
        if self.calls <= self.fail_times and self.error:
            raise self.error
        return [
            Listing(
                marketplace=self.marketplace,
                external_id="X",
                title="t",
                data_source=DataSource.DEMO,
            )
        ]

    def get_offer(self, external_id: str, pincode: str) -> Offer:
        return Offer(item_price=Decimal("10"), data_source=DataSource.DEMO)


Q = ProductQuery(title="t")


def test_retryable_errors_are_retried_with_backoff() -> None:
    sleeps: list[float] = []
    a = Flaky(AdapterUpstreamError("503"), fail_times=2)
    r = fetch_marketplace(
        a, Q, "560001", policy=RetryPolicy(base_delay_seconds=0.1), sleep=sleeps.append
    )
    assert r.status is FetchStatus.OK
    assert a.calls == 3 and len(sleeps) == 2
    assert all(0 <= s <= 0.2 for s in sleeps)  # full jitter within the exponential cap


def test_gives_up_after_max_attempts() -> None:
    a = Flaky(AdapterTimeout("slow"), fail_times=99)
    r = fetch_marketplace(a, Q, "560001", policy=NO_WAIT, sleep=lambda s: None)
    assert (r.status, r.error_code, a.calls) == (FetchStatus.FAILED, "timeout", 3)


def test_non_retryable_errors_fail_immediately() -> None:
    a = Flaky(ListingNotFound("gone"), fail_times=99)
    r = fetch_marketplace(a, Q, "560001", policy=NO_WAIT, sleep=lambda s: None)
    assert r.status is FetchStatus.FAILED and a.calls == 1


def test_adapter_bug_never_escapes() -> None:
    r = fetch_marketplace(Flaky(crash=True), Q, "560001")
    assert (r.status, r.error_code) == (FetchStatus.FAILED, "adapter_crash")


def test_deadline_stops_retrying() -> None:
    a = Flaky(AdapterTimeout("slow"), fail_times=99)
    policy = RetryPolicy(
        max_attempts=50, base_delay_seconds=5, max_delay_seconds=5, deadline_seconds=0.5
    )
    start = time.monotonic()
    r = fetch_marketplace(a, Q, "560001", policy=policy, sleep=time.sleep)
    assert r.status is FetchStatus.FAILED
    assert time.monotonic() - start < 1


def test_source_listing_is_priced_first_on_its_own_marketplace() -> None:
    a = DemoAdapter(Marketplace.FLIPKART, latency_seconds=(0, 0))
    src = a.get_listing("DEMOPHNE00000003")
    r = fetch_marketplace(
        a, ProductQuery(title=src.title, brand=src.brand, gtin=src.gtin), "560001", source=src
    )
    assert r.candidates[0].listing.external_id == "DEMOPHNE00000003"
