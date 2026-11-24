"""Demo adapter: serves the fictional catalog in ``catalog.json``.

Used only when demo mode is on, for every marketplace at once (demo and live data are
never mixed). Everything it returns is marked ``data_source=DEMO`` and has no URL, so the
UI never links to a page that doesn't exist.

Per-product ``behaviour`` simulates real-world failures for testing the pipeline:
``timeout``, ``error`` (upstream 5xx) and ``rate_limited_once`` (first call is throttled,
the retry succeeds).
"""

import json
import random
import threading
import time
from decimal import Decimal
from functools import cache
from importlib import resources
from typing import Any

from pricescope_integrations.base import (
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUpstreamError,
    ListingNotFound,
)
from pricescope_integrations.models import (
    AdapterState,
    AdapterStatus,
    Availability,
    Capabilities,
    CardOffer,
    Charge,
    Coupon,
    DataSource,
    Listing,
    LocationCapability,
    LocationResult,
    LocationVerification,
    Marketplace,
    Offer,
    ProductQuery,
)

DEMO_REASON = "Demo mode: fictional sample data, not real prices, stock, fees or offers."


@cache
def load_catalog() -> dict[str, Any]:
    raw = (
        resources.files("pricescope_integrations.demo")
        .joinpath("catalog.json")
        .read_text(encoding="utf-8")
    )
    catalog: dict[str, Any] = json.loads(raw)
    return catalog


def _charge(spec: dict[str, Any] | None) -> Charge:
    if not spec:
        return Charge.unknown()
    return Charge(
        status=spec["status"],
        amount=Decimal(spec["amount"]) if "amount" in spec else None,
        note=spec.get("note"),
    )


class DemoAdapter:
    def __init__(
        self,
        marketplace: Marketplace,
        *,
        latency_seconds: tuple[float, float] = (0.15, 0.6),
        timeout_seconds: float = 1.5,
    ) -> None:
        self.marketplace = marketplace
        self._latency = latency_seconds
        self._timeout = timeout_seconds
        self._catalog = load_catalog()
        self._throttled_once: set[str] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ helpers

    def _sleep(self) -> None:
        low, high = self._latency
        if high > 0:
            time.sleep(random.uniform(low, high))  # noqa: S311 - simulated latency only

    def _entries(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """(product, listing spec) pairs for this marketplace."""
        return [
            (product, spec)
            for product in self._catalog["products"]
            for spec in product["listings"].get(self.marketplace.value, [])
        ]

    def _listing(self, spec: dict[str, Any]) -> Listing:
        return Listing(
            marketplace=self.marketplace,
            external_id=spec["external_id"],
            title=spec["title"],
            url=None,
            image_url=None,
            brand=spec.get("brand"),
            model=spec.get("model"),
            gtin=spec.get("gtin"),
            attributes=dict(spec.get("attributes", {})),
            data_source=DataSource.DEMO,
        )

    def _behave(self, product: dict[str, Any]) -> None:
        behaviour = product.get("behaviour", {}).get(self.marketplace.value)
        if behaviour == "timeout":
            time.sleep(self._timeout)
            raise AdapterTimeout(f"Demo: {self.marketplace.value} did not respond in time")
        if behaviour == "error":
            raise AdapterUpstreamError(f"Demo: {self.marketplace.value} returned a server error")
        if behaviour == "rate_limited_once":
            with self._lock:
                if product["key"] not in self._throttled_once:
                    self._throttled_once.add(product["key"])
                    raise AdapterRateLimited("Demo: rate limited", retry_after_seconds=0.2)

    def _product_for(self, query: ProductQuery) -> dict[str, Any] | None:
        """The demo product a query refers to: by barcode first, then by brand."""
        brand = (query.brand or "").casefold()
        for product in self._catalog["products"]:
            specs = [s for lst in product["listings"].values() for s in lst]
            if query.gtin and any(s.get("gtin") == query.gtin for s in specs):
                return dict(product)
        for product in self._catalog["products"]:
            specs = [s for lst in product["listings"].values() for s in lst]
            if brand and any((s.get("brand") or "").casefold() == brand for s in specs):
                return dict(product)
        return None

    # ------------------------------------------------------------------ adapter API

    def status(self) -> AdapterStatus:
        return AdapterStatus(
            marketplace=self.marketplace,
            state=AdapterState.DEMO,
            data_source=DataSource.DEMO,
            reason=DEMO_REASON,
            capabilities=Capabilities(
                search_by_gtin=True,
                search_by_text=True,
                location=(
                    LocationCapability.NONE
                    if self.marketplace is Marketplace.FLIPKART
                    else LocationCapability.PINCODE
                ),
                fees=True,
                coupons=True,
            ),
        )

    def get_listing(self, external_id: str) -> Listing:
        self._sleep()
        for _, spec in self._entries():
            if spec["external_id"].casefold() == external_id.casefold():
                return self._listing(spec)
        raise ListingNotFound(f"{external_id} is not in the demo catalog")

    def search(self, query: ProductQuery, limit: int = 5) -> list[Listing]:
        self._sleep()
        product = self._product_for(query)
        if product is None:
            return []
        self._behave(product)
        specs = product["listings"].get(self.marketplace.value, [])
        return [self._listing(s) for s in specs[:limit]]

    def get_offer(self, external_id: str, pincode: str) -> Offer:
        self._sleep()
        for _, spec in self._entries():
            if spec["external_id"].casefold() == external_id.casefold():
                return self._offer(spec["offer"], pincode)
        raise ListingNotFound(f"{external_id} is not in the demo catalog")

    def _offer(self, o: dict[str, Any], pincode: str) -> Offer:
        mode = o.get("location", "unverifiable")
        metro = pincode[:3] in self._catalog["metro_pin_prefixes"]
        eta = o.get("eta")
        if mode == "national":
            location = LocationResult(
                verification=LocationVerification.VERIFIED, serviceable=True, eta_text=eta
            )
        elif mode == "metro":
            location = (
                LocationResult(
                    verification=LocationVerification.VERIFIED, serviceable=True, eta_text=eta
                )
                if metro
                else LocationResult(
                    verification=LocationVerification.UNAVAILABLE, serviceable=False
                )
            )
        elif mode == "precise":
            location = LocationResult(verification=LocationVerification.NEEDS_PRECISE_LOCATION)
        else:
            location = LocationResult(verification=LocationVerification.UNVERIFIABLE)

        return Offer(
            item_price=Decimal(o["item_price"]) if o.get("item_price") else None,
            mrp=Decimal(o["mrp"]) if o.get("mrp") else None,
            delivery_fee=_charge(o.get("delivery_fee")),
            handling_fee=_charge(o.get("handling_fee")),
            platform_fee=_charge(o.get("platform_fee")),
            other_fees=_charge(o.get("other_fees")),
            coupons=tuple(Coupon(**c) for c in o.get("coupons", [])),
            card_offers=tuple(CardOffer(**c) for c in o.get("card_offers", [])),
            availability=Availability(o.get("availability", "UNKNOWN")),
            location=location,
            data_source=DataSource.DEMO,
        )


def demo_source_links() -> list[dict[str, str]]:
    """One pasteable link per demo product, for the 'try a demo product' buttons."""
    from pricescope_integrations.demo.links import canonical_demo_url

    out = []
    for product in load_catalog()["products"]:
        for code in ("AMAZON_IN", "FLIPKART", "BIGBASKET", "BLINKIT", "ZEPTO"):
            specs = product["listings"].get(code) or []
            if specs:
                out.append(
                    {
                        "key": product["key"],
                        "title": specs[0]["title"],
                        "marketplace": code,
                        "url": canonical_demo_url(Marketplace(code), specs[0]["external_id"]),
                    }
                )
                break
    return out
