"""Adapters for the official / licensed integration routes.

None of these makes a network call yet. No live client is written until its endpoints,
request signing and terms have been confirmed against documentation the account holder
has access to, and a real call has succeeded. Until then each adapter reports exactly why
it can't be used, and the UI shows that status instead of prices.
"""

from dataclasses import dataclass

from pricescope_integrations.base import AdapterNotConfigured, AdapterUnsupported
from pricescope_integrations.models import (
    AdapterState,
    AdapterStatus,
    Capabilities,
    Listing,
    LocationCapability,
    Marketplace,
    Offer,
    ProductQuery,
)


@dataclass(frozen=True)
class OfficialRoute:
    marketplace: Marketplace
    channel: str
    missing_message: str
    capabilities: Capabilities


ROUTES = {
    Marketplace.AMAZON_IN: OfficialRoute(
        Marketplace.AMAZON_IN,
        "Amazon Creators API",
        "Add approved Amazon Creators API credentials (Associates eligibility required).",
        # Location-specific pricing is not assumed; verified once the API is in use.
        Capabilities(search_by_gtin=True, search_by_text=True),
    ),
    Marketplace.FLIPKART: OfficialRoute(
        Marketplace.FLIPKART,
        "Flipkart Affiliate API",
        "Add approved Flipkart Affiliate API credentials.",
        # Affiliate feeds are not location-aware: PIN-specific data cannot be verified.
        Capabilities(search_by_text=True, location=LocationCapability.NONE),
    ),
}


class OfficialApiAdapter:
    """Amazon / Flipkart. NOT_CONFIGURED until a verified live client exists."""

    def __init__(self, marketplace: Marketplace, *, has_credentials: bool) -> None:
        self.marketplace = marketplace
        self._route = ROUTES[marketplace]
        self._has_credentials = has_credentials

    def _reason(self) -> str:
        if not self._has_credentials:
            return self._route.missing_message
        return (
            f"Credentials are present, but the {self._route.channel} client is not built yet. "
            "It will be implemented against the official documentation and only marked live "
            "after a real call succeeds."
        )

    def status(self) -> AdapterStatus:
        return AdapterStatus(
            marketplace=self.marketplace,
            state=AdapterState.NOT_CONFIGURED,
            data_source=None,
            reason=self._reason(),
            capabilities=self._route.capabilities,
        )

    def _refuse(self) -> AdapterNotConfigured:
        return AdapterNotConfigured(self._reason())

    def get_listing(self, external_id: str) -> Listing:
        raise self._refuse()

    def search(self, query: ProductQuery, limit: int = 5) -> list[Listing]:
        raise self._refuse()

    def get_offer(self, external_id: str, pincode: str) -> Offer:
        raise self._refuse()


class LicensedProviderAdapter:
    """Blinkit / Zepto / BigBasket: no public API. Needs a licensed data provider."""

    def __init__(self, marketplace: Marketplace, provider: str | None = None) -> None:
        self.marketplace = marketplace
        self._provider = provider

    def _reason(self) -> str:
        if self._provider:
            return (
                f"Provider {self._provider!r} is configured, but its client is not built yet. "
                "It will only be marked live after its licence and a real call are verified."
            )
        return "No public API. Choose a licensed data provider or partnership to enable it."

    def status(self) -> AdapterStatus:
        return AdapterStatus(
            marketplace=self.marketplace,
            state=AdapterState.UNSUPPORTED if not self._provider else AdapterState.NOT_CONFIGURED,
            data_source=None,
            reason=self._reason(),
        )

    def _refuse(self) -> AdapterUnsupported | AdapterNotConfigured:
        if self._provider:
            return AdapterNotConfigured(self._reason())
        return AdapterUnsupported(self._reason())

    def get_listing(self, external_id: str) -> Listing:
        raise self._refuse()

    def search(self, query: ProductQuery, limit: int = 5) -> list[Listing]:
        raise self._refuse()

    def get_offer(self, external_id: str, pincode: str) -> Offer:
        raise self._refuse()
