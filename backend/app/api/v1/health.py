"""Liveness and readiness probes."""

from datetime import UTC, datetime
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db

router = APIRouter(tags=["health"])
log = structlog.get_logger(__name__)

CheckStatus = Literal["ok", "error"]


class LivenessResponse(BaseModel):
    status: Literal["ok"]
    time: datetime


class ReadinessResponse(BaseModel):
    status: CheckStatus
    data_mode: Literal["DEMO", "LIVE"]
    checks: dict[str, CheckStatus]


@router.get("/health", response_model=LivenessResponse, summary="Liveness probe")
def liveness() -> LivenessResponse:
    return LivenessResponse(status="ok", time=datetime.now(UTC))


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe (database connectivity)",
    responses={503: {"model": ReadinessResponse}},
)
def readiness(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReadinessResponse:
    checks: dict[str, CheckStatus] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # report, never crash the probe
        log.warning("readiness_db_failed", error=type(exc).__name__)
        checks["database"] = "error"
    overall: CheckStatus = "ok" if all(v == "ok" for v in checks.values()) else "error"
    if overall != "ok":
        response.status_code = 503
    return ReadinessResponse(
        status=overall,
        data_mode="DEMO" if settings.demo_mode else "LIVE",
        checks=checks,
    )
