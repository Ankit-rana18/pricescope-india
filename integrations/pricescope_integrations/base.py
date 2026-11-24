"""The adapter contract and its error hierarchy.

An adapter talks to exactly one marketplace through an *authorized* channel. It must never
scrape pages, bypass access controls, or invent prices, stock or fees. If it cannot get a
value through its authorized channel, it reports that value as unknown.
"""

from typing import Protocol

from pricescope_integrations.models import AdapterStatus, Listing, Marketplace, Offer, ProductQuery


class AdapterError(Exception):
    code = "adapter_error"
    retryable = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AdapterNotConfigured(AdapterError):
    code = "not_configured"


class AdapterUnsupported(AdapterError):
    code = "unsupported"


class AdapterAuthError(AdapterError):
    code = "auth_error"


class ListingNotFound(AdapterError):
    code = "listing_not_found"


class AdapterTimeout(AdapterError):
    code = "timeout"
    retryable = True


class AdapterRateLimited(AdapterError):
    code = "rate_limited"
    retryable = True

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class AdapterUpstreamError(AdapterError):
    code = "upstream_error"
    retryable = True


class MarketplaceAdapter(Protocol):
    marketplace: Marketplace

    def status(self) -> AdapterStatus:
        """Current state. LIVE only after real credentials + a verified live call."""

    def get_listing(self, external_id: str) -> Listing:
        """Product details for one listing (the product the user pasted)."""

    def search(self, query: ProductQuery, limit: int = 5) -> list[Listing]:
        """Candidate listings that may be the same product."""

    def get_offer(self, external_id: str, pincode: str) -> Offer:
        """Price, fees, stock and location result for one listing at one PIN code."""
