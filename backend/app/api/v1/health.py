"""Liveness and readiness probes."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.core.config import Settings, StorageBackendName, get_settings
from app.storage.base import TableStore
from app.storage.errors import StorageNotConfigured
from app.storage.factory import get_store

router = APIRouter(tags=["health"])
log = structlog.get_logger(__name__)

CheckStatus = Literal["ok", "error", "not_configured"]


class LivenessResponse(BaseModel):
    status: Literal["ok"]
    time: datetime


class ReadinessResponse(BaseModel):
    status: Literal["ok", "error"]
    data_mode: Literal["DEMO", "LIVE"]
    storage_backend: StorageBackendName
    checks: dict[str, CheckStatus]


def storage_provider() -> Callable[[], TableStore]:
    """Indirection so the probe can report a misconfigured store instead of failing."""
    return get_store


@router.get("/health", response_model=LivenessResponse, summary="Liveness probe")
def liveness() -> LivenessResponse:
    return LivenessResponse(status="ok", time=datetime.now(UTC))


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe (storage backend connectivity)",
    responses={503: {"model": ReadinessResponse}},
)
def readiness(
    response: Response,
    provide_store: Annotated[Callable[[], TableStore], Depends(storage_provider)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReadinessResponse:
    checks: dict[str, CheckStatus] = {}
    try:
        provide_store().ping()
        checks["storage"] = "ok"
    except StorageNotConfigured as exc:
        log.warning("readiness_storage_not_configured", reason=exc.message)
        checks["storage"] = "not_configured"
    except Exception as exc:  # report, never crash the probe
        log.warning("readiness_storage_failed", error=type(exc).__name__)
        checks["storage"] = "error"
    ok = all(v == "ok" for v in checks.values())
    if not ok:
        response.status_code = 503
    return ReadinessResponse(
        status="ok" if ok else "error",
        data_mode="DEMO" if settings.demo_mode else "LIVE",
        storage_backend=settings.storage_backend,
        checks=checks,
    )
