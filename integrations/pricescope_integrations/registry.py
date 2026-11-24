"""Build the adapter set from configuration (the single dependency-injection point).

Demo mode -> every marketplace uses the demo adapter. Live mode -> official / licensed
adapters only. Demo and live adapters are never mixed in one set.
"""

from dataclasses import dataclass

from pricescope_integrations.base import MarketplaceAdapter
from pricescope_integrations.demo.adapter import DemoAdapter
from pricescope_integrations.models import Marketplace
from pricescope_integrations.official import LicensedProviderAdapter, OfficialApiAdapter

QUICK_COMMERCE = (Marketplace.BLINKIT, Marketplace.ZEPTO, Marketplace.BIGBASKET)


@dataclass(frozen=True)
class IntegrationConfig:
    demo_mode: bool = True
    demo_latency_seconds: tuple[float, float] = (0.15, 0.6)
    demo_timeout_seconds: float = 1.5
    amazon_credentials_present: bool = False
    flipkart_credentials_present: bool = False
    quick_commerce_provider: str | None = None


def build_adapters(config: IntegrationConfig) -> dict[Marketplace, MarketplaceAdapter]:
    if config.demo_mode:
        return {
            m: DemoAdapter(
                m,
                latency_seconds=config.demo_latency_seconds,
                timeout_seconds=config.demo_timeout_seconds,
            )
            for m in Marketplace
        }
    adapters: dict[Marketplace, MarketplaceAdapter] = {
        Marketplace.AMAZON_IN: OfficialApiAdapter(
            Marketplace.AMAZON_IN, has_credentials=config.amazon_credentials_present
        ),
        Marketplace.FLIPKART: OfficialApiAdapter(
            Marketplace.FLIPKART, has_credentials=config.flipkart_credentials_present
        ),
    }
    for m in QUICK_COMMERCE:
        adapters[m] = LicensedProviderAdapter(m, config.quick_commerce_provider or None)
    return adapters
