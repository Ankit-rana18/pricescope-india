"""Process-wide singletons must be built exactly once, even under a burst of requests."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.core.singleton import once


def test_concurrent_first_calls_share_one_instance() -> None:
    builds = 0
    start = threading.Barrier(16)

    @once
    def service() -> object:
        nonlocal builds
        builds += 1
        time.sleep(0.05)  # slow construction widens the race window
        return object()

    def call() -> object:
        start.wait()
        return service()

    with ThreadPoolExecutor(16) as pool:
        results = list(pool.map(lambda _: call(), range(16)))
    assert builds == 1
    assert len({id(r) for r in results}) == 1


def test_entries_are_per_argument_and_clearable() -> None:
    @once
    def load(path: str) -> list[str]:
        return [path]

    a = load("x")
    assert load("x") is a
    assert load("y") is not a
    load.cache_clear()  # type: ignore[attr-defined]
    assert load("x") is not a


def test_the_comparison_service_dependency_is_a_true_singleton() -> None:
    from app.api.v1.comparisons import get_comparison_service

    assert hasattr(get_comparison_service, "cache_clear")
    assert get_comparison_service.__wrapped__  # type: ignore[attr-defined]
