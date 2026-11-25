"""Signed-in user's own data: profile, card banks, history, saved products, price alerts.

Every query is filtered by the signed-in user's id: nobody can read or change another
user's records (other users' ids answer 404, the same as missing ones).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator

from app.api.v1.products import get_catalog
from app.core.auth import User, to_current_user
from app.core.errors import ErrorResponse, NotFoundError
from app.models.enums import UserRole
from app.services.catalog import CatalogService
from app.services.comparison.evaluate import name_of
from app.services.pincode import PincodeError, normalize_pincode
from app.storage.errors import ConstraintViolation, RowNotFound

router = APIRouter(tags=["account"])
Catalog = Annotated[CatalogService, Depends(get_catalog)]
_404: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}


# ------------------------------------------------------------------ profile


class Preferences(BaseModel):
    card_banks: list[str] = Field(default_factory=list, max_length=20)
    card_types: list[Literal["CREDIT", "DEBIT"]] = Field(default_factory=list)

    @field_validator("card_banks")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for bank in v:
            b = " ".join(bank.split())[:60]
            if b and b.casefold() not in {x.casefold() for x in out}:
                out.append(b)
        return out


class MeView(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    role: UserRole
    default_pincode: str | None
    preferences: Preferences


class MeUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=120)
    default_pincode: str | None = Field(None, max_length=16)
    preferences: Preferences | None = None


def _me(row: dict[str, Any]) -> MeView:
    u = to_current_user(row)
    return MeView(
        id=u.id,
        email=u.email,
        display_name=u.display_name,
        role=u.role,
        default_pincode=u.default_pincode,
        preferences=Preferences.model_validate(u.preferences),
    )


@router.get("/me", response_model=MeView, summary="Your profile")
def get_me(user: User, catalog: Catalog) -> MeView:
    return _me(catalog.store.get("users", user.id))


@router.patch("/me", response_model=MeView, summary="Update your profile and saved cards")
def update_me(body: MeUpdate, user: User, catalog: Catalog) -> MeView:
    changes: dict[str, Any] = {}
    fields = body.model_fields_set
    if "display_name" in fields:
        changes["display_name"] = (body.display_name or "").strip() or None
    if "default_pincode" in fields:
        if body.default_pincode:
            try:
                changes["default_pincode"] = normalize_pincode(body.default_pincode)
            except PincodeError as exc:
                raise ConstraintViolation("users", "pincode_format", exc.message) from None
        else:
            changes["default_pincode"] = None
    if body.preferences is not None:
        changes["preferences"] = body.preferences.model_dump()
    row = (
        catalog.store.update("users", user.id, changes)
        if changes
        else catalog.store.get("users", user.id)
    )
    return _me(row)


# ------------------------------------------------------------------ history


class HistoryItem(BaseModel):
    comparison_id: str
    created_at: datetime
    pincode: str
    status: str
    title: str | None
    marketplace: str | None


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    next_cursor: str | None


@router.get("/search/history", response_model=HistoryPage, summary="Your past comparisons")
def search_history(
    user: User,
    catalog: Catalog,
    cursor: Annotated[str | None, Query(pattern=r"^\d{1,6}$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> HistoryPage:
    rows = catalog.store.find(
        "comparisons", {"user_id": user.id}, order_by="created_at", descending=True
    )
    start = int(cursor or 0)
    page = rows[start : start + limit]
    codes = {r["id"]: r["code"] for r in catalog.store.find("marketplaces")}
    items = []
    for r in page:
        title = marketplace = None
        if r.get("source_marketplace_product_id"):
            try:
                listing = catalog.store.get(
                    "marketplace_products", r["source_marketplace_product_id"]
                )
                title = listing["title_raw"]
                marketplace = name_of(codes[listing["marketplace_id"]])
            except RowNotFound:
                pass
        items.append(
            HistoryItem(
                comparison_id=str(r["id"]),
                created_at=r["created_at"],
                pincode=r["pincode"],
                status=str(r["status"].value),
                title=title,
                marketplace=marketplace,
            )
        )
    nxt = start + limit
    return HistoryPage(items=items, next_cursor=str(nxt) if nxt < len(rows) else None)


# ------------------------------------------------------------------ saved products


class SavedCreate(BaseModel):
    product_slug: str = Field(max_length=200)
    note: str | None = Field(None, max_length=500)


class SavedView(BaseModel):
    id: uuid.UUID
    product_slug: str
    title: str
    note: str | None
    created_at: datetime


def _variant_for(catalog: CatalogService, slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    product = catalog.product_by_slug(slug)
    return product, catalog.variant_of(product)


def _product_of_variant(catalog: CatalogService, variant_id: Any) -> dict[str, Any]:
    variant = catalog.store.get("product_variants", variant_id)
    return catalog.store.get("products", variant["product_id"])


def _owned(
    catalog: CatalogService, table: str, row_id: uuid.UUID, user_id: uuid.UUID
) -> dict[str, Any]:
    try:
        row = catalog.store.get(table, row_id)
    except RowNotFound:
        raise NotFoundError("Not found.") from None
    if row["user_id"] != user_id:
        raise NotFoundError("Not found.")
    return row


@router.get("/saved-products", response_model=list[SavedView], summary="Your saved products")
def list_saved(user: User, catalog: Catalog) -> list[SavedView]:
    out = []
    for r in catalog.store.find(
        "saved_products", {"user_id": user.id}, order_by="created_at", descending=True
    ):
        p = _product_of_variant(catalog, r["variant_id"])
        out.append(
            SavedView(
                id=r["id"],
                product_slug=p["slug"],
                title=p["title"],
                note=r.get("note"),
                created_at=r["created_at"],
            )
        )
    return out


@router.post(
    "/saved-products",
    response_model=SavedView,
    status_code=201,
    summary="Save a product",
    responses=_404,
)
def save_product(body: SavedCreate, response: Response, user: User, catalog: Catalog) -> SavedView:
    product, variant = _variant_for(catalog, body.product_slug)
    existing = catalog.store.find(
        "saved_products", {"user_id": user.id, "variant_id": variant["id"]}
    )
    if existing:
        response.status_code = 200  # idempotent: saving twice is fine
        row = existing[0]
    else:
        row = catalog.store.insert(
            "saved_products", {"user_id": user.id, "variant_id": variant["id"], "note": body.note}
        )
    return SavedView(
        id=row["id"],
        product_slug=product["slug"],
        title=product["title"],
        note=row.get("note"),
        created_at=row["created_at"],
    )


@router.delete(
    "/saved-products/{saved_id}", status_code=204, summary="Remove a saved product", responses=_404
)
def delete_saved(saved_id: uuid.UUID, user: User, catalog: Catalog) -> Response:
    _owned(catalog, "saved_products", saved_id, user.id)
    catalog.store.delete("saved_products", saved_id)
    return Response(status_code=204)


# ------------------------------------------------------------------ price alerts


class AlertCreate(BaseModel):
    product_slug: str = Field(max_length=200)
    pincode: str = Field(max_length=16)
    target_price: Decimal = Field(gt=0, le=Decimal("10000000"), decimal_places=2)


class AlertUpdate(BaseModel):
    target_price: Decimal | None = Field(None, gt=0, le=Decimal("10000000"), decimal_places=2)
    is_active: bool | None = None


class AlertView(BaseModel):
    id: uuid.UUID
    product_slug: str
    title: str
    pincode: str
    target_price: Decimal
    is_active: bool
    last_triggered_at: datetime | None
    last_triggered_price: Decimal | None
    last_triggered_marketplace: str | None
    created_at: datetime


def _alert_view(catalog: CatalogService, r: dict[str, Any]) -> AlertView:
    p = _product_of_variant(catalog, r["variant_id"])
    mp = r.get("last_triggered_marketplace")
    return AlertView(
        id=r["id"],
        product_slug=p["slug"],
        title=p["title"],
        pincode=r["pincode"],
        target_price=r["target_price"],
        is_active=r["is_active"],
        last_triggered_at=r.get("last_triggered_at"),
        last_triggered_price=r.get("last_triggered_price"),
        last_triggered_marketplace=name_of(mp) if mp else None,
        created_at=r["created_at"],
    )


@router.get("/alerts", response_model=list[AlertView], summary="Your price-drop alerts")
def list_alerts(user: User, catalog: Catalog) -> list[AlertView]:
    rows = catalog.store.find(
        "price_alerts", {"user_id": user.id}, order_by="created_at", descending=True
    )
    return [_alert_view(catalog, r) for r in rows]


@router.post(
    "/alerts",
    response_model=AlertView,
    status_code=201,
    summary="Create a price-drop alert",
    responses=_404,
)
def create_alert(body: AlertCreate, user: User, catalog: Catalog) -> AlertView:
    try:
        pincode = normalize_pincode(body.pincode)
    except PincodeError as exc:
        raise ConstraintViolation("price_alerts", "pincode_format", exc.message) from None
    _, variant = _variant_for(catalog, body.product_slug)
    row = catalog.store.insert(
        "price_alerts",
        {
            "user_id": user.id,
            "variant_id": variant["id"],
            "pincode": pincode,
            "target_price": body.target_price,
        },
    )
    return _alert_view(catalog, row)


@router.patch(
    "/alerts/{alert_id}",
    response_model=AlertView,
    summary="Change or pause an alert",
    responses=_404,
)
def update_alert(alert_id: uuid.UUID, body: AlertUpdate, user: User, catalog: Catalog) -> AlertView:
    _owned(catalog, "price_alerts", alert_id, user.id)
    changes = body.model_dump(exclude_none=True)
    row = (
        catalog.store.update("price_alerts", alert_id, changes)
        if changes
        else catalog.store.get("price_alerts", alert_id)
    )
    return _alert_view(catalog, row)


@router.delete("/alerts/{alert_id}", status_code=204, summary="Delete an alert", responses=_404)
def delete_alert(alert_id: uuid.UUID, user: User, catalog: Catalog) -> Response:
    _owned(catalog, "price_alerts", alert_id, user.id)
    catalog.store.delete("price_alerts", alert_id)
    return Response(status_code=204)
