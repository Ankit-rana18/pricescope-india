"""Reference data every storage backend starts with.

The PostgreSQL seed migration keeps its own frozen copy (migrations must not change when
application code does); `tests/unit/test_storage_seed.py` checks the two stay in sync.
"""

from typing import Any

from app.models.enums import MarketplaceCode
from app.storage.base import TableStore

# Every capability is "unverified" until an adapter health probe proves it with real,
# authorized credentials and real API calls.
UNVERIFIED_CAPABILITIES = {
    "search_by_gtin": "unverified",
    "search_by_text": "unverified",
    "location": "unverified",
    "fees": "unverified",
    "coupons": "unverified",
}

_QUICK_COMMERCE = "No public API; licensed data provider or partnership required"

MARKETPLACES: list[dict[str, Any]] = [
    {
        "code": MarketplaceCode.AMAZON_IN,
        "name": "Amazon India",
        "base_domains": ["amazon.in", "www.amazon.in", "amzn.in", "amzn.to"],
        "logo_path": "/marketplaces/amazon.svg",
        "integration": "Amazon Creators API (Associates eligibility required)",
    },
    {
        "code": MarketplaceCode.FLIPKART,
        "name": "Flipkart",
        "base_domains": ["flipkart.com", "www.flipkart.com", "dl.flipkart.com"],
        "logo_path": "/marketplaces/flipkart.svg",
        "integration": "Flipkart Affiliate API / product feeds (approval required)",
    },
    {
        "code": MarketplaceCode.BLINKIT,
        "name": "Blinkit",
        "base_domains": ["blinkit.com", "www.blinkit.com"],
        "logo_path": "/marketplaces/blinkit.svg",
        "integration": _QUICK_COMMERCE,
    },
    {
        "code": MarketplaceCode.ZEPTO,
        "name": "Zepto",
        "base_domains": ["zeptonow.com", "www.zeptonow.com"],
        "logo_path": "/marketplaces/zepto.svg",
        "integration": _QUICK_COMMERCE,
    },
    {
        "code": MarketplaceCode.BIGBASKET,
        "name": "BigBasket",
        "base_domains": ["bigbasket.com", "www.bigbasket.com"],
        "logo_path": "/marketplaces/bigbasket.svg",
        "integration": _QUICK_COMMERCE,
    },
]


def seed_marketplaces(store: TableStore) -> int:
    """Insert missing marketplaces; never overwrites existing rows. Returns rows added."""
    existing = {r["code"] for r in store.find("marketplaces")}
    added = 0
    for m in MARKETPLACES:
        if m["code"] in existing:
            continue
        store.insert(
            "marketplaces",
            {
                "code": m["code"],
                "name": m["name"],
                "base_domains": m["base_domains"],
                "logo_path": m["logo_path"],
                "capabilities": {"integration": m["integration"], **UNVERIFIED_CAPABILITIES},
            },
        )
        added += 1
    return added
