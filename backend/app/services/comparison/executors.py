"""Run marketplace fetches concurrently: in-process threads or Celery workers.

Both yield results as each marketplace finishes, so the UI fills in progressively, and both
turn a stuck marketplace into a FAILED result instead of waiting forever.
"""

import time
from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Protocol

import structlog
from pricescope_integrations.base import MarketplaceAdapter
from pricescope_integrations.models import (
    FetchResult,
    FetchStatus,
    Listing,
    Marketplace,
    ProductQuery,
)
from pricescope_integrations.registry import IntegrationConfig
from pricescope_integrations.runner import RetryPolicy, fetch_marketplace

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class FetchJob:
    marketplace: Marketplace
    query: ProductQuery
    pincode: str
    source: Listing | None


def _deadline_failure(m: Marketplace, message: str) -> FetchResult:
    return FetchResult(
        marketplace=m,
        status=FetchStatus.FAILED,
        error_code="deadline_exceeded",
        error_message=message,
    )


class FetchExecutor(Protocol):
    name: str

    def run(self, jobs: list[FetchJob]) -> Iterator[FetchResult]: ...


class ThreadFetchExecutor:
    name = "threads"

    def __init__(
        self,
        adapters: dict[Marketplace, MarketplaceAdapter],
        *,
        policy: RetryPolicy | None = None,
        overall_timeout_seconds: float = 20.0,
        max_workers: int = 16,
    ) -> None:
        self._adapters = adapters
        self._policy = policy or RetryPolicy()
        self._timeout = overall_timeout_seconds
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fetch")

    def run(self, jobs: list[FetchJob]) -> Iterator[FetchResult]:
        futures: dict[Future[FetchResult], FetchJob] = {
            self._pool.submit(
                fetch_marketplace,
                self._adapters[j.marketplace],
                j.query,
                j.pincode,
                source=j.source,
                policy=self._policy,
            ): j
            for j in jobs
        }
        deadline = time.monotonic() + self._timeout
        pending = set(futures)
        while pending:
            done, pending = wait(
                pending, timeout=max(0.0, deadline - time.monotonic()), return_when=FIRST_COMPLETED
            )
            if not done:
                break
            for fut in done:
                job = futures[fut]
                try:
                    yield fut.result()
                except Exception as exc:  # fetch_marketplace never raises; belt and braces
                    log.exception("fetch_crashed", marketplace=job.marketplace.value)
                    yield FetchResult(
                        marketplace=job.marketplace,
                        status=FetchStatus.FAILED,
                        error_code="executor_error",
                        error_message=type(exc).__name__,
                    )
        for fut in pending:
            fut.cancel()
            yield _deadline_failure(futures[fut].marketplace, "Took too long to respond")


class CeleryFetchExecutor:
    name = "celery"

    def __init__(self, config: IntegrationConfig, *, overall_timeout_seconds: float = 25.0) -> None:
        from pricescope_workers.tasks import config_to_dict

        self._config = config_to_dict(config)
        self._timeout = overall_timeout_seconds

    def run(self, jobs: list[FetchJob]) -> Iterator[FetchResult]:
        from pricescope_workers.tasks import fetch_marketplace_task

        pending: dict[Any, FetchJob] = {}
        for j in jobs:
            async_result = fetch_marketplace_task.apply_async(
                args=[
                    j.marketplace.value,
                    j.query.model_dump(mode="json"),
                    j.pincode,
                    j.source.model_dump(mode="json") if j.source else None,
                    self._config,
                ]
            )
            pending[async_result] = j
        deadline = time.monotonic() + self._timeout
        while pending and time.monotonic() < deadline:
            for ar in [a for a in pending if a.ready()]:
                job = pending.pop(ar)
                try:
                    yield FetchResult.model_validate(ar.get(timeout=1, propagate=True))
                except Exception as exc:
                    log.warning(
                        "celery_task_failed",
                        marketplace=job.marketplace.value,
                        error=type(exc).__name__,
                    )
                    yield FetchResult(
                        marketplace=job.marketplace,
                        status=FetchStatus.FAILED,
                        error_code="worker_error",
                        error_message="The background worker failed for this marketplace",
                    )
            if pending:
                time.sleep(0.1)
        for ar, job in pending.items():
            ar.revoke()
            yield _deadline_failure(job.marketplace, "No worker answered in time")
