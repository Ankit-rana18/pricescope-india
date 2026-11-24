"""Fetch one marketplace's candidates and offers, with retries, backoff and a deadline.

This is pure adapter I/O. It never raises: every outcome, including failures, becomes a
``FetchResult`` so one broken marketplace cannot break a comparison. The same function
runs in an API thread or inside a Celery task.
"""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from pricescope_integrations.base import (
    AdapterError,
    AdapterNotConfigured,
    AdapterRateLimited,
    AdapterUnsupported,
    ListingNotFound,
    MarketplaceAdapter,
)
from pricescope_integrations.models import (
    AdapterState,
    CandidateOffer,
    FetchResult,
    FetchStatus,
    Listing,
    ProductQuery,
)

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.4
    max_delay_seconds: float = 3.0
    deadline_seconds: float = 12.0  # whole marketplace fetch, all retries included

    def delay(self, attempt: int, hint: float | None = None) -> float:
        """Exponential backoff with full jitter; honours a server Retry-After hint."""
        if hint is not None:
            return min(hint, self.max_delay_seconds)
        cap = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (attempt - 1)))
        return random.uniform(0, cap)  # noqa: S311 - jitter, not security


class _Budget:
    def __init__(self, policy: RetryPolicy, sleep: Callable[[float], None]) -> None:
        self.policy = policy
        self.sleep = sleep
        self.started = time.monotonic()
        self.attempts = 0

    def remaining(self) -> float:
        return self.policy.deadline_seconds - (time.monotonic() - self.started)

    def call(self, fn: Callable[[], T]) -> T:
        attempt = 0
        while True:
            attempt += 1
            self.attempts += 1
            try:
                return fn()
            except AdapterError as exc:
                if not exc.retryable or attempt >= self.policy.max_attempts:
                    raise
                hint = exc.retry_after_seconds if isinstance(exc, AdapterRateLimited) else None
                wait = self.policy.delay(attempt, hint)
                if wait >= self.remaining():
                    raise
                self.sleep(wait)


def call_with_retry[R](
    fn: Callable[[], R],
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> R:
    """Run one adapter call under the retry policy (raises the final AdapterError)."""
    return _Budget(policy or RetryPolicy(), sleep).call(fn)


def fetch_marketplace(
    adapter: MarketplaceAdapter,
    query: ProductQuery,
    pincode: str,
    *,
    source: Listing | None = None,
    policy: RetryPolicy | None = None,
    limit: int = 5,
    sleep: Callable[[float], None] = time.sleep,
) -> FetchResult:
    """Search one marketplace and price its candidates at ``pincode``.

    ``source`` is the listing the user pasted; on its own marketplace it is always priced
    first (that is the "original marketplace" price savings are measured against).
    """
    policy = policy or RetryPolicy()
    budget = _Budget(policy, sleep)
    marketplace = adapter.marketplace
    status = adapter.status()
    data_source = status.data_source

    def done(fetch_status: FetchStatus, **kw: object) -> FetchResult:
        return FetchResult(
            marketplace=marketplace,
            status=fetch_status,
            attempts=budget.attempts,
            latency_ms=int((time.monotonic() - budget.started) * 1000),
            data_source=data_source,
            **kw,
        )

    if status.state is AdapterState.UNSUPPORTED:
        return done(FetchStatus.UNSUPPORTED, error_code="unsupported", error_message=status.reason)
    if status.state is AdapterState.NOT_CONFIGURED:
        return done(
            FetchStatus.NOT_CONFIGURED, error_code="not_configured", error_message=status.reason
        )

    try:
        listings = budget.call(lambda: adapter.search(query, limit))
    except AdapterUnsupported as exc:
        return done(FetchStatus.UNSUPPORTED, error_code=exc.code, error_message=exc.message)
    except AdapterNotConfigured as exc:
        return done(FetchStatus.NOT_CONFIGURED, error_code=exc.code, error_message=exc.message)
    except AdapterError as exc:
        return done(FetchStatus.FAILED, error_code=exc.code, error_message=exc.message)
    except Exception as exc:  # an adapter bug must not break the comparison
        return done(
            FetchStatus.FAILED, error_code="adapter_crash", error_message=type(exc).__name__
        )

    if source is not None and source.marketplace is marketplace:
        others = [lst for lst in listings if lst.external_id != source.external_id]
        listings = [source, *others]
    listings = listings[:limit]
    if not listings:
        return done(FetchStatus.NOT_FOUND)

    candidates: list[CandidateOffer] = []
    for listing in listings:
        if budget.remaining() <= 0:
            candidates.append(CandidateOffer(listing=listing, offer_error="deadline_exceeded"))
            continue
        try:
            offer = budget.call(lambda lst=listing: adapter.get_offer(lst.external_id, pincode))  # type: ignore[misc]
            candidates.append(CandidateOffer(listing=listing, offer=offer))
        except ListingNotFound:
            candidates.append(CandidateOffer(listing=listing, offer_error="listing_not_found"))
        except AdapterError as exc:
            candidates.append(CandidateOffer(listing=listing, offer_error=exc.code))
        except Exception as exc:
            candidates.append(CandidateOffer(listing=listing, offer_error=type(exc).__name__))
    return done(FetchStatus.OK, candidates=tuple(candidates))
