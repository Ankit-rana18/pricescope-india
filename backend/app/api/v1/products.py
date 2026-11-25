"""Public product, price-history, category and sitemap endpoints (read-only)."""

from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.core.errors import ErrorResponse, NotFoundError
from app.models.enums import DataMode, MarketplaceCode
from app.schemas.products import (
    CategoryProductsView,
    CategoryView,
    PriceHistoryView,
    PricePoint,
    PriceSeries,
    ProductListingView,
    ProductSummary,
    ProductView,
    SitemapEntry,
    SitemapView,
    VariantView,
)
from app.services.catalog import CatalogService, slugify
from app.services.comparison.evaluate import name_of
from app.services.pincode import PINCODE_RE
from app.storage.factory import get_store

router = APIRouter(tags=["products"])
_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}


@lru_cache
def get_catalog() -> CatalogService:
    return CatalogService(get_store())


Catalog = Annotated[CatalogService, Depends(get_catalog)]


def _codes(catalog: CatalogService) -> dict[Any, MarketplaceCode]:
    return {r["id"]: MarketplaceCode(r["code"]) for r in catalog.store.find("marketplaces")}


def _point(row: dict[str, Any]) -> PricePoint:
    return PricePoint(
        observed_at=row["observed_at"],
        pincode=row.get("pincode"),
        item_price=row.get("item_price"),
        final_price=row.get("final_price"),
        final_price_complete=bool(row.get("final_price_complete")),
        final_price_estimated=bool(row.get("final_price_estimated")),
    )


def _pincode(value: str | None) -> str | None:
    if value is not None and not PINCODE_RE.fullmatch(value):
        raise NotFoundError("Unknown PIN code filter.")
    return value


@router.get(
    "/products/{slug}",
    response_model=ProductView,
    summary="A canonical product with its listings and latest prices",
    responses=_NOT_FOUND,
)
def get_product(
    slug: str, catalog: Catalog, pincode: Annotated[str | None, Query()] = None
) -> ProductView:
    pin = _pincode(pincode)
    product = catalog.product_by_slug(slug)
    variant = catalog.variant_of(product)
    listings = catalog.listings_of(variant["id"])
    mode = catalog.data_mode_of(listings)
    history = catalog.history(listings, pincode=pin, days=3650)
    codes = _codes(catalog)
    identifiers = [
        {"type": str(r["type"].value), "value": r["value"]}
        for r in catalog.store.find("product_identifiers", {"variant_id": variant["id"]})
    ]
    attrs = variant.get("attributes") or {}
    return ProductView(
        slug=product["slug"],
        title=product["title"],
        brand=product.get("brand"),
        model=product.get("model"),
        category=product.get("category"),
        category_slug=slugify(product["category"]) if product.get("category") else None,
        data_mode=mode,
        indexable=mode is DataMode.LIVE,
        variant=VariantView(
            size=variant.get("size"),
            pack_count=variant.get("pack_count") or 1,
            colour=variant.get("colour"),
            storage_gb=attrs.get("storage_gb"),
            ram_gb=attrs.get("ram_gb"),
        ),
        identifiers=identifiers,
        listings=[
            ProductListingView(
                marketplace=codes[lst["marketplace_id"]],
                marketplace_name=name_of(codes[lst["marketplace_id"]]),
                title=lst["title_raw"],
                url=lst.get("url") if mode is DataMode.LIVE else None,
                latest=_point(history[lst["id"]][-1]) if history[lst["id"]] else None,
            )
            for lst in sorted(listings, key=lambda r: name_of(codes[r["marketplace_id"]]))
        ],
    )


@router.get(
    "/products/{slug}/price-history",
    response_model=PriceHistoryView,
    summary="Observed prices per marketplace over time",
    responses=_NOT_FOUND,
)
def get_price_history(
    slug: str,
    catalog: Catalog,
    pincode: Annotated[str | None, Query(description="Only prices checked for this PIN")] = None,
    days: Annotated[int, Query(ge=1, le=365)] = 90,
) -> PriceHistoryView:
    pin = _pincode(pincode)
    product = catalog.product_by_slug(slug)
    listings = catalog.listings_of(catalog.variant_of(product)["id"])
    history = catalog.history(listings, pincode=pin, days=days)
    codes = _codes(catalog)
    series = [
        PriceSeries(
            marketplace=codes[lst["marketplace_id"]],
            marketplace_name=name_of(codes[lst["marketplace_id"]]),
            points=[_point(r) for r in history[lst["id"]]],
        )
        for lst in listings
        if history[lst["id"]]
    ]
    return PriceHistoryView(
        product_slug=slug,
        pincode=pin,
        days=days,
        data_mode=catalog.data_mode_of(listings),
        series=sorted(series, key=lambda s: s.marketplace_name),
    )


def _category_views(
    catalog: CatalogService,
) -> dict[str, tuple[CategoryView, list[dict[str, Any]]]]:
    out = {}
    for name, products in catalog.categories().items():
        indexable_count = sum(1 for p in products if _product_indexable(catalog, p))
        view = CategoryView(
            slug=slugify(name),
            name=name,
            product_count=len(products),
            indexable=indexable_count > 0,
        )
        out[view.slug] = (view, products)
    return out


def _product_indexable(catalog: CatalogService, product: dict[str, Any]) -> bool:
    try:
        listings = catalog.listings_of(catalog.variant_of(product)["id"])
    except NotFoundError:
        return False
    return catalog.data_mode_of(listings) is DataMode.LIVE


@router.get("/categories", response_model=list[CategoryView], summary="Product categories")
def list_categories(catalog: Catalog) -> list[CategoryView]:
    return sorted((v for v, _ in _category_views(catalog).values()), key=lambda c: c.name)


@router.get(
    "/categories/{slug}/products",
    response_model=CategoryProductsView,
    summary="Products in a category (paginated)",
    responses=_NOT_FOUND,
)
def category_products(
    slug: str,
    catalog: Catalog,
    cursor: Annotated[str | None, Query(pattern=r"^\d{1,6}$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> CategoryProductsView:
    views = _category_views(catalog)
    if slug not in views:
        raise NotFoundError("Category not found.")
    view, products = views[slug]
    start = int(cursor or 0)
    page = products[start : start + limit]
    nxt = start + limit
    return CategoryProductsView(
        category=view,
        products=[
            ProductSummary(
                slug=p["slug"],
                title=p["title"],
                brand=p.get("brand"),
                indexable=_product_indexable(catalog, p),
            )
            for p in page
        ],
        next_cursor=str(nxt) if nxt < len(products) else None,
    )


@router.get(
    "/seo/sitemap",
    response_model=SitemapView,
    tags=["seo"],
    summary="Indexable pages only (never demo data)",
)
def sitemap(catalog: Catalog) -> SitemapView:
    entries = [SitemapEntry(path="/")]
    for view, _ in _category_views(catalog).values():
        if view.indexable:
            entries.append(SitemapEntry(path=f"/categories/{view.slug}"))
    for p in catalog.store.find("products", order_by="slug"):
        if _product_indexable(catalog, p):
            entries.append(SitemapEntry(path=f"/products/{p['slug']}", lastmod=p.get("updated_at")))
    return SitemapView(entries=entries)
