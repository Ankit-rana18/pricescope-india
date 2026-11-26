"""Load sanity check for a running PriceScope API (demo mode only).

Starts N comparisons with C in flight at once, polls each to completion, and hammers the
read endpoints. Reports status codes and latency percentiles. Use it against a local or
staging deployment in demo mode; it never calls a marketplace directly.

    cd backend; uv run python ../scripts/load_check.py --base http://127.0.0.1:8010
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
from collections import Counter

import httpx

DEMO_URLS = [f"https://www.amazon.in/dp/DEMO00000{i}" for i in range(1, 5)]
FINAL = {"COMPLETE", "PARTIAL", "FAILED"}


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


def summary(name: str, codes: Counter[int], times: list[float]) -> None:
    ms = [t * 1000 for t in times]
    print(
        f"{name:<22} n={sum(codes.values()):<4} codes={dict(sorted(codes.items()))} "
        f"p50={pct(ms, 50):.0f}ms p95={pct(ms, 95):.0f}ms max={max(ms, default=0):.0f}ms"
    )


async def one_comparison(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, codes: Counter[int], done: list[float],
    statuses: Counter[str], start_times: list[float],
) -> None:
    async with sem:
        body = {"url": random.choice(DEMO_URLS), "pincode": str(random.randint(110001, 855117))}
        t0 = time.perf_counter()
        r = await client.post("/api/v1/comparisons", json=body)
        start_times.append(time.perf_counter() - t0)
        codes[r.status_code] += 1
        if r.status_code not in (200, 202):
            return
        cid = r.json()["id"]
        deadline = t0 + 60
        while time.perf_counter() < deadline:
            poll = await client.get(f"/api/v1/comparisons/{cid}")
            if poll.status_code != 200:
                statuses[f"poll_{poll.status_code}:{poll.json()['error']['code']}"] += 1
                return
            view = poll.json()
            if view["status"] in FINAL and not view.get("saving"):
                statuses[view["status"]] += 1
                done.append(time.perf_counter() - t0)
                return
            await asyncio.sleep(0.5)
        statuses["TIMED_OUT"] += 1


async def reads(client: httpx.AsyncClient, n: int, concurrency: int) -> None:
    sem = asyncio.Semaphore(concurrency)
    codes: Counter[int] = Counter()
    times: list[float] = []

    async def hit(path: str) -> None:
        async with sem:
            t0 = time.perf_counter()
            r = await client.get(path)
            times.append(time.perf_counter() - t0)
            codes[r.status_code] += 1

    paths = ["/api/v1/health/ready", "/api/v1/marketplaces"]
    await asyncio.gather(*(hit(paths[i % 2]) for i in range(n)))
    summary("reads", codes, times)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--comparisons", type=int, default=40)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--reads", type=int, default=300)
    args = ap.parse_args()

    async with httpx.AsyncClient(base_url=args.base, timeout=30) as client:
        ready = (await client.get("/api/v1/health/ready")).json()
        if ready.get("data_mode") != "DEMO":
            raise SystemExit("Refusing to run: the target is not in demo mode.")

        codes: Counter[int] = Counter()
        statuses: Counter[str] = Counter()
        done: list[float] = []
        starts: list[float] = []
        sem = asyncio.Semaphore(args.concurrency)
        t0 = time.perf_counter()
        await asyncio.gather(
            *(one_comparison(client, sem, codes, done, statuses, starts)
              for _ in range(args.comparisons))
        )
        wall = time.perf_counter() - t0
        summary("POST /comparisons", codes, starts)
        summary("comparison complete", Counter({200: len(done)}), done)
        print(f"{'outcomes':<22} {dict(statuses)}  wall={wall:.1f}s")
        await reads(client, args.reads, args.concurrency * 2)


if __name__ == "__main__":
    asyncio.run(main())
