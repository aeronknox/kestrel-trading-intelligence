"""Prometheus metrics: the API endpoint, its optional token, labels, and the worker's own server."""

import asyncio
import socket
import urllib.error
import urllib.request

import pytest

from app.core.config import get_settings
from app.core.metrics import REGISTRY

API = "/api/v1"


def value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_metrics_exposes_requests_by_route_template(client) -> None:  # type: ignore[no-untyped-def]
    route = f"{API}/strategies/{{strategy_id}}"
    before = value("kestrel_http_requests_total", method="GET", route=route, status="401")
    for sid in (1, 2, 3):  # three raw paths, one route label
        assert (await client.get(f"{API}/strategies/{sid}")).status_code == 401
    await client.get("/no-such-page")

    resp = await client.get("/metrics")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert value("kestrel_http_requests_total", method="GET", route=route, status="401") == before + 3
    assert 'route="unmatched"' in body
    assert f'{API}/strategies/1"' not in body
    assert "kestrel_http_request_duration_seconds_bucket" in body
    assert "kestrel_ws_clients" in body and "kestrel_background_jobs_leader" in body
    assert 'route="/metrics"' not in body  # scrapes don't count themselves


async def test_metrics_token(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "metrics_token", "scrape-token")
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer scrape-token"})).status_code == 200
    monkeypatch.setattr(get_settings(), "metrics_enabled", False)
    assert (await client.get("/metrics", headers={"Authorization": "Bearer scrape-token"})).status_code == 404


async def test_paper_orders_are_counted_by_source_and_status(auth_client) -> None:  # type: ignore[no-untyped-def]
    filled = {"source": "user", "side": "buy", "status": "filled"}
    rejected = {"source": "user", "side": "sell", "status": "rejected"}
    before = value("kestrel_paper_orders_total", **filled), value("kestrel_paper_orders_total", **rejected)
    fills = value("kestrel_paper_fills_total", side="buy")
    ok = await auth_client.post(
        f"{API}/paper/orders", json={"symbol": "BTC-USD", "side": "buy", "order_type": "market", "quantity": 0.01}
    )
    assert ok.json()["status"] == "filled"
    # Selling what isn't held is rejected while short selling is off.
    no = await auth_client.post(
        f"{API}/paper/orders", json={"symbol": "ETH-USD", "side": "sell", "order_type": "market", "quantity": 1}
    )
    assert no.json()["status"] == "rejected"
    assert value("kestrel_paper_orders_total", **filled) == before[0] + 1
    assert value("kestrel_paper_orders_total", **rejected) == before[1] + 1
    assert value("kestrel_paper_fills_total", side="buy") == fills + 1


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def scrape(port: int, token: str | None = None) -> tuple[int, str]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/metrics", headers={"Authorization": f"Bearer {token}"} if token else {}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, ""


async def test_worker_serves_metrics(app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app import worker

    port = free_port()
    monkeypatch.setattr(get_settings(), "worker_metrics_port", port)
    monkeypatch.setattr(get_settings(), "metrics_token", "worker-token")
    stop = asyncio.Event()
    seen: dict[str, tuple[int, str]] = {}

    async def probe() -> None:
        await asyncio.sleep(0.3)
        seen["anonymous"] = await asyncio.to_thread(scrape, port)
        seen["token"] = await asyncio.to_thread(scrape, port, "worker-token")
        stop.set()

    await asyncio.gather(worker.run(stop), probe())
    assert seen["anonymous"][0] == 401
    status, body = seen["token"]
    assert status == 200 and "kestrel_background_jobs_running 1.0" in body
    with pytest.raises(OSError):  # shut down with the worker
        await asyncio.to_thread(scrape, port)
