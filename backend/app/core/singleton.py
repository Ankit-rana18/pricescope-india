"""Thread-safe memoisation for process-wide singletons.

``functools.lru_cache`` does not stop two threads from computing the same entry at once.
FastAPI runs sync dependencies in a thread pool, so the first burst of requests after a
start could build several ``ComparisonService`` (or storage, engine...) instances: work
started on a losing instance became invisible to later requests. This cache computes each
entry exactly once.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable, Hashable
from typing import Any


def once[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Cache ``fn`` per argument tuple; concurrent first calls wait for a single build."""
    cache: dict[Hashable, Any] = {}
    lock = threading.Lock()

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        key = (args, tuple(sorted(kwargs.items())))
        try:
            return cache[key]  # type: ignore[no-any-return]
        except KeyError:
            pass
        with lock:
            if key not in cache:
                cache[key] = fn(*args, **kwargs)
            return cache[key]  # type: ignore[no-any-return]

    def cache_clear() -> None:
        with lock:
            cache.clear()

    wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
    return wrapper
