"""Comparisons and marketplace status."""

from functools import lru_cache
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Response
from pricescope_integrations.demo.adapter import demo_fee_policies, demo_source_links
from pricescope_integrations.registry import build_adapters
from pydantic import BaseModel, Field

from app.api.v1.lookup import Directory, InvalidInput, LinkResolver
from app.core.config import Settings, TaskExecutor, get_settings
from app.core.errors import ErrorResponse, NotFoundError
from app.models.enums import DataMode, MarketplaceCode
from app.schemas.comparison import (
    ComparisonRequest,
    ComparisonView,
    DemoProductView,
    MarketplaceStatusView,
    MarketplacesView,
)
from app.schemas.lookup import FieldError
from app.services.comparison.evaluate import name_of
from app.services.comparison.executors import (
    CeleryFetchExecutor,
    FetchExecutor,
    ThreadFetchExecutor,
)
from app.services.comparison.service import ComparisonService
from app.services.fee_policies import FeePolicySource, StoreFeePolicies, demo_policies
from app.services.matching import CachedReviewer, ClaudeMatchReviewer, MatchReviewer
from app.services.pincode import PincodeError, load_directory, validate_pincode
from app.services.url_parser import UrlParseError, resolve_product_url
from app.storage.factory import get_store

router = APIRouter(tags=["comparisons"])
log = structlog.get_logger(__name__)


def build_reviewer(settings: Settings) -> MatchReviewer | None:
    """The optional AI match reviewer; None when disabled or not usable."""
    if not settings.llm_review_enabled:
        return None
    try:
        reviewer = ClaudeMatchReviewer.from_environment(
            model=settings.llm_review_model,
            timeout_seconds=settings.llm_review_timeout_seconds,
        )
    except Exception as exc:  # e.g. no Anthropic credentials configured
        log.warning("match_review_disabled", reason=type(exc).__name__)
        return None
    log.info("match_review_enabled", model=settings.llm_review_model)
    return CachedReviewer(reviewer)


@lru_cache
def get_comparison_service() -> ComparisonService:
    settings = get_settings()
    config = settings.integration_config()
    adapters = build_adapters(config)
    executor: FetchExecutor = (
        CeleryFetchExecutor(config)
        if settings.task_executor is TaskExecutor.CELERY
        else ThreadFetchExecutor(adapters)
    )
    # Demo and live never mix: fictional demo policies, or admin-entered live ones.
    store = get_store()
    policies: FeePolicySource = (
        demo_policies(demo_fee_policies()) if settings.demo_mode else StoreFeePolicies(store)
    )
    return ComparisonService(
        store,
        adapters,
        executor,
        data_mode=DataMode.DEMO if settings.demo_mode else DataMode.LIVE,
        reviewer=build_reviewer(settings),
        reviews_per_comparison=settings.llm_review_max_per_comparison,
        directory=load_directory(settings.pincode_directory_file),
        policies=policies,
    )


Service = Annotated[ComparisonService, Depends(get_comparison_service)]


@router.post(
    "/comparisons",
    response_model=ComparisonView,
    status_code=202,
    summary="Start a comparison for a product link and PIN code",
    description="Returns immediately with the comparison running; results fill in as each "
    "marketplace answers. Poll GET /comparisons/{id}. Identical requests within 10 minutes "
    "reuse the finished comparison (`reused: true`, HTTP 200).",
    responses={
        404: {"model": ErrorResponse, "description": "Product not found on its marketplace"},
        422: {"model": ErrorResponse, "description": "Invalid link or PIN code"},
        503: {"model": ErrorResponse, "description": "Source marketplace not connected"},
    },
)
def create_comparison(
    body: ComparisonRequest,
    response: Response,
    service: Service,
    directory: Directory,
    link_resolver: LinkResolver,
) -> ComparisonView:
    errors: list[FieldError] = []
    parsed = pincode = None
    try:
        parsed = resolve_product_url(body.url, link_resolver)
    except UrlParseError as exc:
        errors.append(FieldError(field="url", code=exc.code, message=exc.message))
    try:
        pincode = validate_pincode(body.pincode, directory).pincode
    except PincodeError as exc:
        errors.append(FieldError(field="pincode", code=exc.code, message=exc.message))
    if errors or parsed is None or pincode is None:
        raise InvalidInput(errors)
    view = service.start(parsed, pincode)
    if view.reused:
        response.status_code = 200
    return view


@router.get(
    "/comparisons/{comparison_id}",
    response_model=ComparisonView,
    summary="Get a comparison (running or finished)",
    responses={404: {"model": ErrorResponse}},
)
def get_comparison(comparison_id: str, service: Service) -> ComparisonView:
    return service.get(comparison_id)


class RetryRequest(BaseModel):
    marketplaces: list[MarketplaceCode] | None = Field(
        None, description="Marketplaces to re-check; default: every one that failed."
    )


@router.post(
    "/comparisons/{comparison_id}/retry",
    response_model=ComparisonView,
    status_code=202,
    summary="Re-check failed marketplaces of a finished comparison",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def retry_comparison(
    comparison_id: str, service: Service, body: RetryRequest | None = None
) -> ComparisonView:
    return service.retry(comparison_id, body.marketplaces if body else None)


@router.post(
    "/comparisons/{comparison_id}/refresh",
    response_model=ComparisonView,
    status_code=202,
    summary="Run a fresh comparison of the same product and PIN code",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def refresh_comparison(comparison_id: str, service: Service) -> ComparisonView:
    return service.refresh(comparison_id)


def _marketplaces(service: ComparisonService, settings: Settings) -> MarketplacesView:
    return MarketplacesView(
        data_mode=DataMode.DEMO if settings.demo_mode else DataMode.LIVE,
        marketplaces=[
            MarketplaceStatusView(
                marketplace=MarketplaceCode(s.marketplace.value),
                marketplace_name=name_of(s.marketplace.value),
                state=s.state.value,
                data_source=DataMode(s.data_source.value) if s.data_source else None,
                reason=s.reason,
                capabilities=s.capabilities.model_dump(mode="json"),
            )
            for s in service.statuses()
        ],
    )


@router.get(
    "/marketplaces",
    response_model=MarketplacesView,
    tags=["marketplaces"],
    summary="Marketplaces and the state of each integration",
)
def list_marketplaces(
    service: Service, settings: Annotated[Settings, Depends(get_settings)]
) -> MarketplacesView:
    return _marketplaces(service, settings)


@router.get(
    "/marketplaces/health",
    response_model=MarketplacesView,
    tags=["marketplaces"],
    summary="Integration health (LIVE only after a verified real call)",
)
def marketplaces_health(
    service: Service, settings: Annotated[Settings, Depends(get_settings)]
) -> MarketplacesView:
    return _marketplaces(service, settings)


@router.get(
    "/demo/products",
    response_model=list[DemoProductView],
    tags=["demo"],
    summary="Sample product links (demo mode only)",
    responses={404: {"model": ErrorResponse}},
)
def demo_products(settings: Annotated[Settings, Depends(get_settings)]) -> list[DemoProductView]:
    if not settings.demo_mode:
        raise NotFoundError("Demo products are only available in demo mode.")
    return [DemoProductView(**d) for d in demo_source_links()]
