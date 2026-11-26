"""Per-user / per-IP rate limits.

Keys are ``<bucket>:u:<user id>`` for signed-in users and ``<bucket>:ip:<hash>`` for
everyone else. Raw IP addresses are never stored: they are hashed with a per-process salt
(memory) or a stable server-side salt (Redis, so every API instance agrees).

Two backends:
- ``memory``: a sliding window per process. Right for one instance (the default).
- ``redis``: a fixed window shared by every instance. If Redis is unreachable the limiter
  falls back to the in-memory window rather than failing every request.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Protocol

import structlog
from fastapi import Depends, Request

from app.core.auth import OptionalUser
from app.core.config import Settings, get_settings
from app.core.errors import AppError

log = structlog.get_logger(__name__)


class Bucket(StrEnum):
    COMPARE = "compare"  # starts outbound marketplace calls: the expensive one
    LOOKUP = "lookup"  # may follow a short link (one outbound request)
    WRITE = "write"  # account writes: saved products, alerts, profile


@dataclass(frozen=True)
class Limit:
    requests: int
    window_seconds: int


class RateLimited(AppError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limited"


class Limiter(Protocol):
    def hit(self, key: str, limit: Limit) -> float:
        """Count one request. Returns 0 if allowed, else seconds until a retry can pass."""
        ...


class MemoryLimiter:
    """Sliding window log. Thread-safe; old timestamps are dropped as keys are touched."""

    MAX_KEYS = 50_000

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: Limit) -> float:
        now = self._clock()
        with self._lock:
            window = self._hits.get(key)
            if window is None:
                if len(self._hits) >= self.MAX_KEYS:
                    self._evict(now)
                window = self._hits[key] = deque()
            while window and window[0] <= now - limit.window_seconds:
                window.popleft()
            if len(window) >= limit.requests:
                return max(window[0] + limit.window_seconds - now, 0.001)
            window.append(now)
            return 0.0

    def _evict(self, now: float) -> None:
        # Drop keys idle for over an hour (longer than any window we use).
        for k in [k for k, w in self._hits.items() if not w or w[-1] < now - 3600]:
            del self._hits[k]


class RedisLimiter:
    """Fixed window counter shared across instances (INCR + EXPIRE in one round trip)."""

    def __init__(self, client: object, fallback: MemoryLimiter | None = None) -> None:
        self._redis = client
        self._fallback = fallback or MemoryLimiter()

    def hit(self, key: str, limit: Limit) -> float:
        now = time.time()
        window_start = int(now // limit.window_seconds) * limit.window_seconds
        redis_key = f"pricescope:rl:{key}:{window_start}"
        try:
            pipe = self._redis.pipeline()  # type: ignore[attr-defined]
            pipe.incr(redis_key)
            pipe.expire(redis_key, limit.window_seconds + 1)
            count, _ = pipe.execute()
        except Exception as exc:
            log.warning("rate_limit_redis_unavailable", error=type(exc).__name__)
            return self._fallback.hit(key, limit)
        if int(count) > limit.requests:
            return max(window_start + limit.window_seconds - now, 0.001)
        return 0.0


def build_limiter(settings: Settings) -> Limiter:
    if settings.rate_limit_backend == "redis":
        import redis

        client = redis.Redis.from_url(
            settings.redis_url.get_secret_value(), socket_timeout=0.5, socket_connect_timeout=0.5
        )
        return RedisLimiter(client)
    return MemoryLimiter()


def client_ip(request: Request, trusted_hops: int) -> str:
    """The caller's IP. X-Forwarded-For is only read when we sit behind known proxies.

    Each trusted proxy appends the address it saw, so with N trusted hops the client is the
    Nth entry from the right. Anything further left could have been written by the client.
    """
    if trusted_hops > 0:
        forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",")]
        forwarded = [p for p in forwarded if p]
        if len(forwarded) >= trusted_hops:
            return forwarded[-trusted_hops]
    return request.client.host if request.client else "unknown"


_PROCESS_SALT = secrets.token_bytes(16)


def _ip_key(ip: str, settings: Settings) -> str:
    salt = (
        settings.rate_limit_salt.get_secret_value().encode()
        if settings.rate_limit_salt
        else _PROCESS_SALT
    )
    return hashlib.sha256(salt + ip.encode()).hexdigest()[:24]


def limits_for(settings: Settings, bucket: Bucket, signed_in: bool) -> Limit:
    per_minute = {
        Bucket.COMPARE: (settings.rate_limit_compare_anon, settings.rate_limit_compare_user),
        Bucket.LOOKUP: (settings.rate_limit_lookup_anon, settings.rate_limit_lookup_user),
        Bucket.WRITE: (settings.rate_limit_write_user, settings.rate_limit_write_user),
    }[bucket]
    return Limit(requests=per_minute[1 if signed_in else 0], window_seconds=60)


def rate_limit(bucket: Bucket) -> Callable[..., None]:
    """FastAPI dependency: count this request against ``bucket`` or raise 429."""

    def dependency(
        request: Request,
        user: OptionalUser,
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        limiter: Limiter = request.app.state.limiter
        if user:
            key = f"{bucket}:u:{user.id}"
        else:
            key = (
                f"{bucket}:ip:{_ip_key(client_ip(request, settings.trusted_proxy_hops), settings)}"
            )
        limit = limits_for(settings, bucket, signed_in=user is not None)
        wait = limiter.hit(key, limit)
        if wait > 0:
            retry_after = max(1, math.ceil(wait))
            log.info("rate_limited", bucket=str(bucket), signed_in=user is not None)
            raise RateLimited(
                f"Too many requests. Try again in {retry_after} seconds.",
                details={"bucket": str(bucket), "limit_per_minute": limit.requests},
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
