"""Rate-limit windows, Redis fallback and client-IP handling."""

from typing import Any

from starlette.requests import Request

from app.core.ratelimit import Limit, MemoryLimiter, RedisLimiter, client_ip

PER_MIN_3 = Limit(requests=3, window_seconds=60)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_memory_limiter_allows_up_to_the_limit_then_reports_the_wait() -> None:
    clock = Clock()
    limiter = MemoryLimiter(clock)
    assert [limiter.hit("k", PER_MIN_3) for _ in range(3)] == [0, 0, 0]
    clock.now += 10
    assert limiter.hit("k", PER_MIN_3) == 50  # first hit leaves the window at t+60
    assert limiter.hit("other", PER_MIN_3) == 0  # keys are independent


def test_memory_limiter_is_a_sliding_window() -> None:
    clock = Clock()
    limiter = MemoryLimiter(clock)
    for _ in range(3):
        limiter.hit("k", PER_MIN_3)
    clock.now += 60
    assert limiter.hit("k", PER_MIN_3) == 0
    # A refused request doesn't count against the caller.
    clock.now += 1
    assert limiter.hit("k", PER_MIN_3) == 0


class FakePipeline:
    def __init__(self, store: dict[str, int], fail: bool) -> None:
        self.store, self.fail = store, fail
        self.ops: list[str] = []

    def incr(self, key: str) -> None:
        self.ops.append(key)

    def expire(self, key: str, seconds: int) -> None:
        assert seconds == 61

    def execute(self) -> list[Any]:
        if self.fail:
            raise ConnectionError("redis down")
        key = self.ops[0]
        self.store[key] = self.store.get(key, 0) + 1
        return [self.store[key], True]


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.store: dict[str, int] = {}
        self.fail = fail

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self.store, self.fail)


def test_redis_limiter_counts_in_a_shared_window() -> None:
    redis = FakeRedis()
    a, b = RedisLimiter(redis), RedisLimiter(redis)  # two API instances
    assert [a.hit("k", PER_MIN_3), b.hit("k", PER_MIN_3), a.hit("k", PER_MIN_3)] == [0, 0, 0]
    assert 0 < b.hit("k", PER_MIN_3) <= 60
    assert all(k.startswith("pricescope:rl:k:") for k in redis.store)


def test_redis_limiter_falls_back_to_memory_when_redis_is_down() -> None:
    limiter = RedisLimiter(FakeRedis(fail=True))
    assert [limiter.hit("k", PER_MIN_3) for _ in range(3)] == [0, 0, 0]
    assert limiter.hit("k", PER_MIN_3) > 0  # still limited, not wide open


def _request(xff: str | None, peer: str = "10.0.0.5") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_forwarded_for_is_ignored_unless_proxies_are_trusted() -> None:
    assert client_ip(_request("1.2.3.4"), trusted_hops=0) == "10.0.0.5"


def test_forwarded_for_uses_the_entry_the_trusted_proxy_added() -> None:
    # The client sent a fake "6.6.6.6"; Render's proxy appended the real address.
    assert client_ip(_request("6.6.6.6, 203.0.113.9"), trusted_hops=1) == "203.0.113.9"
    assert client_ip(_request("203.0.113.9, 10.1.1.1"), trusted_hops=2) == "203.0.113.9"


def test_too_few_forwarded_entries_falls_back_to_the_peer() -> None:
    assert client_ip(_request(""), trusted_hops=1) == "10.0.0.5"
    assert client_ip(_request(None), trusted_hops=2) == "10.0.0.5"
