"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import comparisons, health, lookup
from app.core.config import Settings, get_settings
from app.core.errors import ErrorResponse, register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware

API_V1 = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.is_production)

    app = FastAPI(
        title="PriceScope India API",
        version="0.1.0",
        description=(
            "Exact-variant price comparison across Indian marketplaces. "
            "Results from demo adapters are labelled `data_mode: DEMO` and never mixed with "
            "live data."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    # Endpoints must see the settings this app was built with, not a fresh global copy.
    app.dependency_overrides[get_settings] = lambda: settings

    app.include_router(health.router, prefix=API_V1)
    app.include_router(lookup.router, prefix=API_V1)
    app.include_router(comparisons.router, prefix=API_V1)
    return app


app = create_app()
