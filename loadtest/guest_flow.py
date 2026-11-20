"""The same 50-guest scenario as guest_flow.js, for machines without k6 (Python 3.12 + httpx).

    uv run --with httpx python loadtest/guest_flow.py --base http://localhost:8010 \
        --tokens tokens.json --guests 50 --seconds 120

Prints a JSON summary: requests, 5xx count, other failures, p50/p95/p99 per endpoint and overall.
Exit code 1 when a threshold fails (any 5xx, any unexpected status, p95 >= 500 ms).
"""

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from collections import defaultdict

import httpx

P95_LIMIT_MS = 500


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    k = max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.5) - 1))
    return ordered[k]


class Stats:
    def __init__(self) -> None:
        self.durations: dict[str, list[float]] = defaultdict(list)
        self.server_errors = 0
        self.unexpected: list[str] = []

    def record(self, name: str, response: httpx.Response, ms: float, ok: set[int]) -> None:
        self.durations[name].append(ms)
        if response.status_code >= 500:
            self.server_errors += 1
        if response.status_code not in ok:
            self.unexpected.append(f"{name}:{response.status_code}")


async def guest(client: httpx.AsyncClient, token: str, stats: Stats, until: float, vu: int) -> None:
    auth = {"Authorization": f"Bearer {token}"}

    async def call(name: str, method: str, path: str, ok: set[int], **kw) -> httpx.Response:
        started = time.perf_counter()
        response = await client.request(method, path, headers={**auth, **kw.pop("headers", {})}, **kw)
        stats.record(name, response, (time.perf_counter() - started) * 1000, ok)
        return response

    iteration = 0
    while time.monotonic() < until:
        iteration += 1
        await call("me", "GET", "/guest/me", {200})
        menu = await call("menu", "GET", "/guest/menu", {200})
        await asyncio.sleep(1)
        data = menu.json() if menu.status_code == 200 else {}
        items = [i for i in data.get("items", []) if i.get("available")]
        if items and data.get("is_open_now"):
            dish = random.choice(items)
            order = await call(
                "place_order",
                "POST",
                "/guest/orders",
                {201, 409},  # 409: at most 5 pending orders per stay (business rule)
                json={"items": [{"item_id": dish["item_id"], "quantity": 1}]},
                headers={"Idempotency-Key": f"load-{vu}-{iteration}-{time.time_ns()}"},
            )
            if order.status_code == 201:
                await call("order_detail", "GET", f"/guest/orders/{order.json()['id']}", {200})
        await asyncio.sleep(1)
        await call("orders", "GET", "/guest/orders", {200})
        await call("housekeeping", "GET", "/guest/housekeeping-requests", {200})
        await asyncio.sleep(2)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8010")
    parser.add_argument("--tokens", default="tokens.json")
    parser.add_argument("--guests", type=int, default=50)
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()

    with open(args.tokens, encoding="utf-8") as handle:
        tokens = [s["token"] for s in json.load(handle)]
    stats = Stats()
    until = time.monotonic() + args.seconds
    limits = httpx.Limits(max_connections=args.guests, max_keepalive_connections=args.guests)
    async with httpx.AsyncClient(
        base_url=f"{args.base.rstrip('/')}/api/v1", timeout=30, limits=limits
    ) as client:
        await asyncio.gather(
            *(guest(client, tokens[i % len(tokens)], stats, until, i) for i in range(args.guests))
        )

    every = [ms for values in stats.durations.values() for ms in values]
    summary = {
        "guests": args.guests,
        "seconds": args.seconds,
        "requests": len(every),
        "requests_per_second": round(len(every) / args.seconds, 1),
        "server_errors_5xx": stats.server_errors,
        "unexpected_statuses": sorted(set(stats.unexpected))[:20],
        "overall_ms": {
            "p50": round(statistics.median(every), 1) if every else 0,
            "p95": round(percentile(every, 95), 1),
            "p99": round(percentile(every, 99), 1),
        },
        "endpoints_ms": {
            name: {
                "count": len(values),
                "p50": round(statistics.median(values), 1),
                "p95": round(percentile(values, 95), 1),
            }
            for name, values in sorted(stats.durations.items())
        },
    }
    print(json.dumps(summary, indent=2))
    failed = (
        stats.server_errors > 0
        or stats.unexpected
        or any(v["p95"] >= P95_LIMIT_MS for v in summary["endpoints_ms"].values())
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
