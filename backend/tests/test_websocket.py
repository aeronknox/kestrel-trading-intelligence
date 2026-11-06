"""WebSocket market stream (sync TestClient drives the ASGI app in its own event loop)."""

import asyncio

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.routes.ws import broadcaster
from app.database.base import Base
from app.database.session import dispose_engine, get_engine, init_engine
from app.main import create_app
from app.market_data.providers.registry import register_provider
from tests.conftest import ControllableProvider

ORIGIN = {"origin": "http://localhost:3000"}


@pytest.fixture
def client():  # type: ignore[no-untyped-def]
    async def prepare() -> None:
        init_engine()
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await dispose_engine()

    asyncio.run(prepare())
    register_provider(ControllableProvider())
    with TestClient(create_app(background=False)) as c:
        yield c


def test_streams_only_subscribed_symbols(client) -> None:  # type: ignore[no-untyped-def]
    with client.websocket_connect("/api/v1/ws/market", headers=ORIGIN) as ws:
        ws.send_json({"action": "subscribe", "symbols": ["btc-usd", "ETH-USD"]})
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}  # messages are handled in order
        client.portal.call(broadcaster._tick)
        msg = ws.receive_json()
        assert msg["type"] == "tickers"
        assert sorted(d["symbol"] for d in msg["data"]) == ["BTC-USD", "ETH-USD"]
        assert all(d["price"] > 0 for d in msg["data"])
        assert msg["meta"]["is_sample"] is True  # provenance travels with the stream


def test_unsubscribed_client_receives_all_tracked_assets(client) -> None:  # type: ignore[no-untyped-def]
    with client.websocket_connect("/api/v1/ws/market", headers=ORIGIN) as ws:
        client.portal.call(broadcaster._tick)
        assert len(ws.receive_json()["data"]) == 10


def test_foreign_origin_rejected(client) -> None:  # type: ignore[no-untyped-def]
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/api/v1/ws/market", headers={"origin": "https://evil.example"}) as ws,
    ):
        ws.receive_json()
    assert exc.value.code == 1008


def test_malformed_messages_are_ignored(client) -> None:  # type: ignore[no-untyped-def]
    with client.websocket_connect("/api/v1/ws/market", headers=ORIGIN) as ws:
        ws.send_text("not json")
        ws.send_json({"action": "subscribe", "symbols": "BTC-USD"})  # wrong type
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}
