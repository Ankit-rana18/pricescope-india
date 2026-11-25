"""Canonical products: one record per exact variant, linking its listings on every marketplace.

A comparison links the pasted listing and every EXACT match to one canonical
(product, variant), found by identifier (barcode, ASIN, Flipkart FSN, model number) or
created. That gives price history across comparisons and product/category pages.

Pages for products seen only in demo data are never indexable: the API marks them
``indexable: false`` and the sitemap leaves them out, so search engines never see
fictional prices.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from pricescope_integrations.models import Listing, Marketplace

from app.core.errors import NotFoundError
from app.models.enums import DataMode, IdentifierType, MarketplaceCode
from app.services.matching.identifiers import normalize_gtin
from app.services.normalization import normalize_attributes
from app.storage.base import TableStore

log = structlog.get_logger(__name__)

GTIN_TYPES = {
    8: IdentifierType.GTIN8,
    12: IdentifierType.GTIN12,
    13: IdentifierType.GTIN13,
    14: IdentifierType.GTIN14,
}


def slugify(text: str, max_len: int = 70) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return s[:max_len].rstrip("-") or "product"


def identifiers_for(listing: Listing) -> list[tuple[IdentifierType, str]]:
    out: list[tuple[IdentifierType, str]] = []
    gtin14, _ = normalize_gtin(listing.gtin)
    if gtin14:
        digits = "".join(c for c in listing.gtin or "" if c.isdigit())
        out.append((GTIN_TYPES[len(digits)], digits))
    if listing.marketplace is Marketplace.AMAZON_IN:
        out.append((IdentifierType.ASIN, listing.external_id.upper()))
    elif listing.marketplace is Marketplace.FLIPKART and len(listing.external_id) == 16:
        out.append((IdentifierType.FSN, listing.external_id.upper()))
    return out


@dataclass(frozen=True)
class LinkedProduct:
    product_id: Any
    variant_id: Any
    slug: str


class CatalogService:
    def __init__(self, store: TableStore) -> None:
        self._store = store

    # ------------------------------------------------------------------ linking

    def link(self, source: Listing, exact: list[Listing]) -> LinkedProduct:
        """Find or create the canonical variant for ``source`` and its exact matches."""
        idents = list(dict.fromkeys(i for lst in [source, *exact] for i in identifiers_for(lst)))
        variant_id = None
        for id_type, value in idents:
            found = self._store.find("product_identifiers", {"type": id_type, "value": value})
            if found:
                variant_id = found[0]["variant_id"]
                break

        if variant_id is not None:
            variant = self._store.get("product_variants", variant_id)
            product = self._store.get("products", variant["product_id"])
        else:
            product, variant = self._create(source, idents)

        known = {
            (r["type"], r["value"])
            for r in self._store.find("product_identifiers", {"variant_id": variant["id"]})
        }
        new = [
            {"variant_id": variant["id"], "type": t, "value": v}
            for t, v in idents
            if (t, v) not in known
            and not self._store.find("product_identifiers", {"type": t, "value": v})
        ]
        self._store.insert_many("product_identifiers", new)
        return LinkedProduct(product["id"], variant["id"], product["slug"])

    def _create(
        self, source: Listing, idents: list[tuple[IdentifierType, str]]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        n = normalize_attributes(source.title, source.attributes)
        key = (
            f"{idents[0][0]}:{idents[0][1]}"
            if idents
            else f"{source.marketplace}:{source.external_id}"
        )
        slug = f"{slugify(source.title)}-{hashlib.sha1(key.encode()).hexdigest()[:6]}"  # noqa: S324 - not security
        category = source.attributes.get("category")
        product = self._store.insert(
            "products",
            {
                "slug": slug,
                "title": source.title,
                "brand": source.brand,
                "model": source.model,
                "category": str(category) if category else None,
                "image_url": source.image_url,
            },
        )
        variant = self._store.insert(
            "product_variants",
            {
                "product_id": product["id"],
                "variant_key": n.variant_key(),
                "size": str(n.per_unit) if n.per_unit else None,
                "colour": n.colour,
                "quantity_value": n.per_unit.value if n.per_unit else None,
                "quantity_unit": n.per_unit.unit if n.per_unit else None,
                "pack_count": n.pack_count,
                "attributes": {"storage_gb": n.storage_gb, "ram_gb": n.ram_gb},
            },
        )
        return product, variant

    # ------------------------------------------------------------------ reading

    @property
    def store(self) -> TableStore:
        return self._store

    def product_by_slug(self, slug: str) -> dict[str, Any]:
        found = self._store.find("products", {"slug": slug})
        if not found:
            raise NotFoundError("Product not found.")
        return found[0]

    def variant_of(self, product: dict[str, Any]) -> dict[str, Any]:
        variants = self._store.find("product_variants", {"product_id": product["id"]})
        if not variants:
            raise NotFoundError("Product has no variants.")
        return variants[0]

    def listings_of(self, variant_id: Any) -> list[dict[str, Any]]:
        return self._store.find("marketplace_products", {"variant_id": variant_id})

    def data_mode_of(self, listings: list[dict[str, Any]]) -> DataMode:
        """LIVE if any listing came from live data; demo-only products are DEMO."""
        sources = {(r.get("attributes") or {}).get("data_source", "DEMO") for r in listings}
        return DataMode.LIVE if "LIVE" in sources else DataMode.DEMO

    def history(
        self, listings: list[dict[str, Any]], *, pincode: str | None, days: int
    ) -> dict[Any, list[dict[str, Any]]]:
        since = datetime.now(UTC) - timedelta(days=days)
        out: dict[Any, list[dict[str, Any]]] = {}
        for lst in listings:
            where: dict[str, Any] = {"marketplace_product_id": lst["id"]}
            if pincode:
                where["pincode"] = pincode
            rows = self._store.find("price_history", where, order_by="observed_at")
            out[lst["id"]] = [r for r in rows if r["observed_at"] >= since]
        return out

    def categories(self) -> dict[str, list[dict[str, Any]]]:
        by_cat: dict[str, list[dict[str, Any]]] = {}
        for p in self._store.find("products", order_by="title"):
            if p.get("category"):
                by_cat.setdefault(p["category"], []).append(p)
        return by_cat


def marketplace_code(store: TableStore, marketplace_id: Any) -> MarketplaceCode:
    for r in store.find("marketplaces"):
        if r["id"] == marketplace_id:
            return MarketplaceCode(r["code"])
    raise NotFoundError("Unknown marketplace.")
