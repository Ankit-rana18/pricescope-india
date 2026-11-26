"""Admin dashboard API. Every endpoint requires an admin (role stored in our users table)."""

import uuid
from collections import Counter, defaultdict
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.api.v1.comparisons import Service
from app.api.v1.products import get_catalog
from app.core.auth import Admin
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorResponse, NotFoundError
from app.core.ratelimit import client_ip
from app.models.enums import UserRole
from app.services.audit import audit
from app.services.catalog import CatalogService
from app.services.comparison.evaluate import name_of
from app.storage.errors import RowNotFound

router = APIRouter(prefix="/admin", tags=["admin"])
Catalog = Annotated[CatalogService, Depends(get_catalog)]
_ERR: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}


def _since(hours: int) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


# ------------------------------------------------------------------ overview / health


class Overview(BaseModel):
    storage: Literal["ok", "error"]
    storage_backend: str
    users: int
    admins: int
    comparisons_24h: int
    comparisons_7d: int
    comparisons_by_status_7d: dict[str, int]
    marketplace_checks_24h: int
    marketplace_failures_24h: int
    active_alerts: int
    alerts_triggered_7d: int


@router.get("/overview", response_model=Overview, responses=_ERR, summary="Platform health")
def overview(_: Admin, catalog: Catalog) -> Overview:
    store = catalog.store
    try:
        store.ping()
        storage: Literal["ok", "error"] = "ok"
    except Exception:
        storage = "error"
    users = store.find("users")
    comparisons = store.find("comparisons")
    week = [c for c in comparisons if c["created_at"] >= _since(24 * 7)]
    logs = [r for r in store.find("integration_health_logs") if r["occurred_at"] >= _since(24)]
    alerts = store.find("price_alerts")
    return Overview(
        storage=storage,
        storage_backend=store.backend_name,
        users=len(users),
        admins=sum(1 for u in users if u["role"] is UserRole.ADMIN),
        comparisons_24h=sum(1 for c in comparisons if c["created_at"] >= _since(24)),
        comparisons_7d=len(week),
        comparisons_by_status_7d=dict(Counter(str(c["status"].value) for c in week)),
        marketplace_checks_24h=len(logs),
        marketplace_failures_24h=sum(1 for r in logs if r["status"].value == "DOWN"),
        active_alerts=sum(1 for a in alerts if a["is_active"]),
        alerts_triggered_7d=sum(
            1
            for a in alerts
            if a.get("last_triggered_at") and a["last_triggered_at"] >= _since(24 * 7)
        ),
    )


# ------------------------------------------------------------------ users


class AdminUser(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    role: UserRole
    created_at: datetime
    last_seen_at: datetime | None


class UsersPage(BaseModel):
    items: list[AdminUser]
    next_cursor: str | None


@router.get("/users", response_model=UsersPage, responses=_ERR, summary="Users")
def list_users(
    _: Admin,
    catalog: Catalog,
    cursor: Annotated[str | None, Query(pattern=r"^\d{1,6}$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> UsersPage:
    rows = catalog.store.find("users", order_by="created_at", descending=True)
    start = int(cursor or 0)
    nxt = start + limit
    return UsersPage(
        items=[
            AdminUser(
                id=r["id"],
                email=r["email"],
                display_name=r.get("display_name"),
                role=r["role"],
                created_at=r["created_at"],
                last_seen_at=r.get("last_seen_at"),
            )
            for r in rows[start:nxt]
        ],
        next_cursor=str(nxt) if nxt < len(rows) else None,
    )


class RoleChange(BaseModel):
    role: UserRole


class CannotDemoteSelf(AppError):
    status_code = 409
    code = "cannot_demote_self"


@router.patch("/users/{user_id}", response_model=AdminUser, responses=_ERR, summary="Change a role")
def change_role(user_id: uuid.UUID, body: RoleChange, admin: Admin, catalog: Catalog) -> AdminUser:
    if user_id == admin.id and body.role is not UserRole.ADMIN:
        raise CannotDemoteSelf("You can't remove your own admin role.")
    try:
        before = catalog.store.get("users", user_id)
    except RowNotFound:
        raise NotFoundError("User not found.") from None
    row = catalog.store.update("users", user_id, {"role": body.role})
    audit(
        catalog.store,
        "user_role_changed",
        actor_id=admin.id,
        target=f"user:{user_id}",
        metadata={"from": str(before["role"].value), "to": body.role.value},
    )
    return AdminUser(
        id=row["id"],
        email=row["email"],
        display_name=row.get("display_name"),
        role=row["role"],
        created_at=row["created_at"],
        last_seen_at=row.get("last_seen_at"),
    )


# ------------------------------------------------------------------ integrations


class IntegrationRow(BaseModel):
    marketplace: str
    marketplace_name: str
    state: str
    reason: str
    checks_24h: int
    failures_24h: int
    avg_latency_ms: int | None
    last_error: str | None
    last_checked_at: datetime | None


@router.get(
    "/integrations",
    response_model=list[IntegrationRow],
    responses=_ERR,
    summary="Integration health",
)
def integrations(_: Admin, catalog: Catalog, service: Service) -> list[IntegrationRow]:
    codes = {r["id"]: r["code"].value for r in catalog.store.find("marketplaces")}
    logs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in catalog.store.find("integration_health_logs", order_by="occurred_at"):
        if r["occurred_at"] >= _since(24):
            logs[codes[r["marketplace_id"]]].append(r)
    out = []
    for s in service.statuses():
        rows = logs.get(s.marketplace.value, [])
        latencies = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]
        errors = [r for r in rows if r.get("error_code")]
        out.append(
            IntegrationRow(
                marketplace=s.marketplace.value,
                marketplace_name=name_of(s.marketplace.value),
                state=s.state.value,
                reason=s.reason,
                checks_24h=len(rows),
                failures_24h=sum(1 for r in rows if r["status"].value == "DOWN"),
                avg_latency_ms=round(sum(latencies) / len(latencies)) if latencies else None,
                last_error=(errors[-1].get("message") or errors[-1]["error_code"])
                if errors
                else None,
                last_checked_at=rows[-1]["occurred_at"] if rows else None,
            )
        )
    return out


# ------------------------------------------------------------------ activity / errors / audit


class ActivityItem(BaseModel):
    comparison_id: str
    created_at: datetime
    pincode: str
    status: str
    data_mode: str
    signed_in: bool
    title: str | None


@router.get(
    "/activity", response_model=list[ActivityItem], responses=_ERR, summary="Recent comparisons"
)
def activity(
    _: Admin, catalog: Catalog, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[ActivityItem]:
    rows = catalog.store.find("comparisons", order_by="created_at", descending=True, limit=limit)
    out = []
    for r in rows:
        title = None
        if r.get("source_marketplace_product_id"):
            with suppress(RowNotFound):
                title = catalog.store.get(
                    "marketplace_products", r["source_marketplace_product_id"]
                )["title_raw"]
        out.append(
            ActivityItem(
                comparison_id=str(r["id"]),
                created_at=r["created_at"],
                pincode=r["pincode"],
                status=r["status"].value,
                data_mode=r["data_mode"].value,
                signed_in=r.get("user_id") is not None,
                title=title,
            )
        )
    return out


class ErrorItem(BaseModel):
    occurred_at: datetime
    marketplace_name: str
    status: str
    error_code: str | None
    message: str | None
    latency_ms: int | None


@router.get(
    "/errors", response_model=list[ErrorItem], responses=_ERR, summary="Recent integration errors"
)
def errors(
    _: Admin, catalog: Catalog, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[ErrorItem]:
    codes = {r["id"]: r["code"].value for r in catalog.store.find("marketplaces")}
    rows = [
        r
        for r in catalog.store.find(
            "integration_health_logs", order_by="occurred_at", descending=True
        )
        if r.get("error_code")
    ][:limit]
    return [
        ErrorItem(
            occurred_at=r["occurred_at"],
            marketplace_name=name_of(codes[r["marketplace_id"]]),
            status=r["status"].value,
            error_code=r.get("error_code"),
            message=r.get("message"),
            latency_ms=r.get("latency_ms"),
        )
        for r in rows
    ]


class AuditItem(BaseModel):
    occurred_at: datetime
    action: str
    actor_id: uuid.UUID | None
    target: str | None
    metadata: dict[str, Any]


@router.get("/audit", response_model=list[AuditItem], responses=_ERR, summary="Audit log")
def audit_log(
    _: Admin, catalog: Catalog, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[AuditItem]:
    rows = catalog.store.find("audit_logs", order_by="occurred_at", descending=True, limit=limit)
    return [
        AuditItem(
            occurred_at=r["occurred_at"],
            action=r["action"],
            actor_id=r.get("actor_id"),
            target=r.get("target"),
            metadata=r.get("metadata") or {},
        )
        for r in rows
    ]


class RequestInfo(BaseModel):
    peer: str | None
    forwarded_for: list[str]
    trusted_proxy_hops: int
    client_ip_used: str
    note: str


@router.get(
    "/request-info",
    response_model=RequestInfo,
    responses=_ERR,
    summary="How the API sees your connection (to set PRICESCOPE_TRUSTED_PROXY_HOPS)",
    description="Shows the proxy chain for this request only. Nothing is stored or logged.",
)
def request_info(
    _: Admin, request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> RequestInfo:
    forwarded = [
        p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()
    ]
    return RequestInfo(
        peer=request.client.host if request.client else None,
        forwarded_for=forwarded,
        trusted_proxy_hops=settings.trusted_proxy_hops,
        client_ip_used=client_ip(request, settings.trusted_proxy_hops),
        note=(
            "client_ip_used should be your own public IP. If it is a proxy address, count "
            "the entries from the right of forwarded_for up to your IP and set "
            "PRICESCOPE_TRUSTED_PROXY_HOPS to that number."
        ),
    )
