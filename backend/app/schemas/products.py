"""Public product, price-history, category and sitemap views."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import DataMode, MarketplaceCode


class VariantView(BaseModel):
    size: str | None = None
    pack_count: int = 1
    colour: str | None = None
    storage_gb: int | None = None
    ram_gb: int | None = None


class PricePoint(BaseModel):
    observed_at: datetime
    pincode: str | None
    item_price: Decimal | None
    final_price: Decimal | None
    final_price_complete: bool
    final_price_estimated: bool = False


class ProductListingView(BaseModel):
    marketplace: MarketplaceCode
    marketplace_name: str
    title: str
    url: str | None = Field(None, description="Real product page; null for demo data.")
    latest: PricePoint | None = None


class ProductView(BaseModel):
    slug: str
    title: str
    brand: str | None
    model: str | None
    category: str | None
    category_slug: str | None
    data_mode: DataMode
    indexable: bool = Field(
        description="False for demo-only products: never shown to search engines."
    )
    variant: VariantView
    identifiers: list[dict[str, str]]
    listings: list[ProductListingView]


class PriceSeries(BaseModel):
    marketplace: MarketplaceCode
    marketplace_name: str
    points: list[PricePoint]


class PriceHistoryView(BaseModel):
    product_slug: str
    pincode: str | None
    days: int
    data_mode: DataMode
    series: list[PriceSeries]


class ProductSummary(BaseModel):
    slug: str
    title: str
    brand: str | None
    indexable: bool


class CategoryView(BaseModel):
    slug: str
    name: str
    product_count: int
    indexable: bool


class CategoryProductsView(BaseModel):
    category: CategoryView
    products: list[ProductSummary]
    next_cursor: str | None = None


class SitemapEntry(BaseModel):
    path: str
    lastmod: datetime | None = None


class SitemapView(BaseModel):
    entries: list[SitemapEntry]
