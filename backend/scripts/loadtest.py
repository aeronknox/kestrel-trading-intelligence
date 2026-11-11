"""Load test: many simulated visitors browsing the API at once.

    python scripts/loadtest.py --url http://localhost:8000 --users 25 --duration 60

Each virtual user signs in to its own demo sandbox (the target needs DEMO_MODE=true), then
loops through what the web app requests: weighted page loads (dashboard, markets, charts,
paper trading, strategies, alerts), occasional simulated paper orders and rare backtests,
with a short think time between steps. Prints latency percentiles and errors per endpoint
and exits non-zero when --max-p95-ms or --max-error-rate is exceeded.

Run it against your own deployment only. Requests come from one IP, so raise
RATE_LIMIT_PER_MINUTE, AUTH_RATE_LIMIT_PER_MINUTE and COMPUTE_RATE_LIMIT_PER_MINUTE on the
target first; 429 responses are reported separately so they aren't mistaken for slowness.
Everything it does is simulated: demo accounts and paper orders only.
"""

import argparse
import asyncio
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

API = "/api/v1"
SYMBOLS = ("BTC-USD", "ETH-USD", "SOL-USD")


@dataclass
class Stats:
    latencies: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    limited: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    samples: dict[str, str] = field(default_factory=dict)  # first error per endpoint

    def total(self) -> int:
        return sum(len(v) for v in self.latencies.values())


class User:
    def __init__(self, client: httpx.AsyncClient, stats: Stats) -> None:
        self.client = client
        self.stats = stats
        self.strategy_id: int | None = None

    async def call(self, name: str, method: str, path: str, **kw: object) -> httpx.Response | None:
        start = time.perf_counter()
        try:
            resp = await self.client.request(method, API + path, **kw)  # type: ignore[arg-type]
        except httpx.HTTPError as exc:
            self.stats.latencies[name].append(time.perf_counter() - start)
            self.stats.errors[name] += 1
            self.stats.samples.setdefault(name, f"{type(exc).__name__}: {exc}")
            return None
        self.stats.latencies[name].append(time.perf_counter() - start)
        if resp.status_code == 429:
            self.stats.limited[name] += 1
        elif resp.status_code >= 400:
            self.stats.errors[name] += 1
            self.stats.samples.setdefault(name, f"{resp.status_code} {resp.text[:160]}")
        return resp

    async def sign_in(self) -> bool:
        resp = await self.call("POST /auth/demo", "POST", "/auth/demo")
        if resp is None or resp.status_code != 201:
            return False
        strategies = await self.call("GET /strategies", "GET", "/strategies")
        if strategies is not None and strategies.status_code == 200 and strategies.json():
            self.strategy_id = strategies.json()[0]["id"]
        return True

    # ------------------------------------------------------------------ actions
    async def dashboard(self) -> None:
        await self.call("GET /dashboard", "GET", "/dashboard")

    async def markets(self) -> None:
        await self.call("GET /market/overview", "GET", "/market/overview")
        await self.call("GET /market/assets", "GET", "/market/assets")

    async def chart(self) -> None:
        sym = random.choice(SYMBOLS)
        tf = random.choice(("1h", "1h", "6h", "1d"))
        await self.call(
            "GET /market/assets/{s}/candles", "GET", f"/market/assets/{sym}/candles", params={"timeframe": tf, "limit": 300}
        )
        await self.call("GET /market/assets/{s}/ticker", "GET", f"/market/assets/{sym}/ticker")

    async def paper(self) -> None:
        await self.call("GET /paper/portfolio", "GET", "/paper/portfolio")
        await self.call("GET /paper/orders", "GET", "/paper/orders")
        await self.call("GET /paper/history", "GET", "/paper/history")

    async def order(self) -> None:
        body = {"symbol": random.choice(SYMBOLS), "side": "buy", "order_type": "market", "quantity": 0.001}
        await self.call("POST /paper/orders", "POST", "/paper/orders", json=body)

    async def strategies(self) -> None:
        await self.call("GET /strategies", "GET", "/strategies")
        await self.call("GET /backtests", "GET", "/backtests")
        if self.strategy_id is not None:
            await self.call("GET /strategies/{id}", "GET", f"/strategies/{self.strategy_id}")

    async def alerts(self) -> None:
        await self.call("GET /alerts/events", "GET", "/alerts/events", params={"limit": 50})

    async def backtest(self) -> None:
        if self.strategy_id is None:
            return
        body = {"strategy_id": self.strategy_id, "bars": 1000, "initial_capital": 10_000, "fee_bps": 10, "slippage_bps": 5}
        await self.call("POST /backtests", "POST", "/backtests", json=body)


# Roughly what a browsing session requests: mostly reads, some orders, few heavy runs.
WEIGHTS: list[tuple[Callable[[User], Callable[[], Awaitable[None]]], int]] = [
    (lambda u: u.dashboard, 25),
    (lambda u: u.markets, 15),
    (lambda u: u.chart, 20),
    (lambda u: u.paper, 15),
    (lambda u: u.strategies, 10),
    (lambda u: u.alerts, 8),
    (lambda u: u.order, 5),
    (lambda u: u.backtest, 2),
]


async def run_user(base: str, stats: Stats, deadline: float, think: float) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=60, follow_redirects=False) as client:
        user = User(client, stats)
        if not await user.sign_in():
            return
        actions, weights = zip(*WEIGHTS, strict=True)
        while time.monotonic() < deadline:
            await random.choices(actions, weights)[0](user)()
            await asyncio.sleep(random.uniform(0, 2 * think))


def pct(values: list[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[q - 1] if q < 100 else max(values)  # type: ignore[index]


def report(stats: Stats, elapsed: float) -> tuple[float, float, str]:
    rows = sorted(stats.latencies.items(), key=lambda kv: -len(kv[1]))
    print(f"\n{'endpoint':<36}{'count':>7}{'err':>6}{'429':>6}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'max ms':>9}")
    for name, lat in rows:
        print(
            f"{name:<36}{len(lat):>7}{stats.errors[name]:>6}{stats.limited[name]:>6}"
            f"{pct(lat, 50) * 1000:>9.0f}{pct(lat, 95) * 1000:>9.0f}{pct(lat, 99) * 1000:>9.0f}{max(lat) * 1000:>9.0f}"
        )
    everything = [x for lat in stats.latencies.values() for x in lat]
    total, errors, limited = len(everything), sum(stats.errors.values()), sum(stats.limited.values())
    p95 = pct(everything, 95) * 1000 if everything else 0.0
    error_rate = errors / total if total else 1.0
    summary = (
        f"{total} requests in {elapsed:.0f}s ({total / elapsed:.1f}/s), p95 {p95:.0f} ms, errors {errors} ({error_rate:.2%})"
    )
    print(f"\n{summary}, rate-limited {limited}")
    slowest = sorted(rows, key=lambda kv: -pct(kv[1], 95))[:4]
    summary += ". Slowest p95: " + ", ".join(f"{name} {pct(lat, 95) * 1000:.0f} ms" for name, lat in slowest)
    for name, sample in stats.samples.items():
        print(f"  first error on {name}: {sample}")
    if limited:
        print("  Some requests were rate-limited: raise the target's *_RATE_LIMIT_PER_MINUTE settings for load tests.")
    return p95, error_rate, summary


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default="http://localhost:8000", help="API base URL (the backend, or the site behind its proxy)")
    ap.add_argument("--users", type=int, default=20, help="concurrent virtual users")
    ap.add_argument("--duration", type=float, default=60, help="seconds of load after ramp-up")
    ap.add_argument("--ramp", type=float, default=10, help="seconds over which users start")
    ap.add_argument("--think", type=float, default=0.5, help="average seconds between a user's steps")
    ap.add_argument("--max-p95-ms", type=float, default=None, help="fail if overall p95 latency exceeds this")
    ap.add_argument("--max-error-rate", type=float, default=None, help="fail if the error share exceeds this (e.g. 0.01)")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    stats = Stats()
    start = time.monotonic()
    deadline = start + args.ramp + args.duration
    tasks = []
    for i in range(args.users):
        tasks.append(asyncio.create_task(run_user(args.url.rstrip("/"), stats, deadline, args.think)))
        if i < args.users - 1:
            await asyncio.sleep(args.ramp / args.users)
    await asyncio.gather(*tasks)
    elapsed = time.monotonic() - start
    if not stats.total():
        print("No requests completed. Is the API reachable and DEMO_MODE=true?")
        return 2
    signed_in = len(stats.latencies["POST /auth/demo"]) - stats.errors["POST /auth/demo"] - stats.limited["POST /auth/demo"]
    print(f"{signed_in}/{args.users} virtual users signed in")
    p95, error_rate, summary = report(stats, elapsed)
    failures = []
    if args.max_p95_ms is not None and p95 > args.max_p95_ms:
        failures.append(f"p95 {p95:.0f} ms > {args.max_p95_ms:.0f} ms")
    if args.max_error_rate is not None and error_rate > args.max_error_rate:
        failures.append(f"error rate {error_rate:.2%} > {args.max_error_rate:.2%}")
    if signed_in < args.users:
        failures.append(f"only {signed_in}/{args.users} virtual users could sign in")
    for failure in failures:
        print(f"FAIL: {failure}")
    if os.environ.get("GITHUB_ACTIONS"):  # results on the run page, readable without signing in
        print(f"::notice title=Load test ({args.users} users)::{summary}")
        for failure in failures:
            print(f"::error title=Load test failed::{failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
