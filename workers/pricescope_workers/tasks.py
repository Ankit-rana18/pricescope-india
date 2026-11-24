"""Worker tasks: adapter I/O only.

Tasks never touch storage. They return a JSON ``FetchResult`` and the API process (the
single writer) matches, prices and stores it. That keeps Google Sheets storage safe while
fetches run in parallel across workers.
"""

from dataclasses import asdict
from typing import Any

from pricescope_integrations.models import FetchResult, Listing, Marketplace, ProductQuery
from pricescope_integrations.registry import IntegrationConfig, build_adapters
from pricescope_integrations.runner import RetryPolicy, fetch_marketplace

from pricescope_workers.celery_app import app


def config_to_dict(config: IntegrationConfig) -> dict[str, Any]:
    data = asdict(config)
    data["demo_latency_seconds"] = list(config.demo_latency_seconds)
    return data


def config_from_dict(data: dict[str, Any]) -> IntegrationConfig:
    data = dict(data)
    data["demo_latency_seconds"] = tuple(data["demo_latency_seconds"])
    return IntegrationConfig(**data)


@app.task(name="pricescope.fetch_marketplace")  # type: ignore[untyped-decorator]
def fetch_marketplace_task(
    marketplace: str,
    query: dict[str, Any],
    pincode: str,
    source: dict[str, Any] | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    adapters = build_adapters(config_from_dict(config))
    result: FetchResult = fetch_marketplace(
        adapters[Marketplace(marketplace)],
        ProductQuery.model_validate(query),
        pincode,
        source=Listing.model_validate(source) if source else None,
        policy=RetryPolicy(),
    )
    return result.model_dump(mode="json")
