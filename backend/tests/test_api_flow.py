"""End-to-end API flows using the (clearly labelled) sample provider."""

from app.strategies.definition import TEMPLATES


async def test_market_overview_and_candles(auth_client) -> None:  # type: ignore[no-untyped-def]
    ov = (await auth_client.get("/api/v1/market/overview")).json()
    assert ov["meta"]["is_sample"] is True
    assert len(ov["assets"]) == 10 and ov["assets"][0]["ticker"]["price"] > 0

    resp = await auth_client.get("/api/v1/market/assets/BTC-USD/candles", params={"timeframe": "1h", "limit": 200})
    data = resp.json()
    assert resp.status_code == 200 and len(data["candles"]) == 200
    assert data["indicators"]["sma_200"], "SMA200 should be warmed up over the visible range"
    assert data["latest"]["rsi_14"] is not None

    bad = await auth_client.get("/api/v1/market/assets/BTC-USD/candles", params={"timeframe": "3h"})
    assert bad.status_code == 422

    search = (await auth_client.get("/api/v1/market/assets", params={"q": "bit"})).json()
    assert [a["symbol"] for a in search] == ["BTC-USD"]


async def test_watchlist(auth_client) -> None:  # type: ignore[no-untyped-def]
    wl = (await auth_client.get("/api/v1/watchlists/default")).json()
    assert len(wl["items"]) == 5
    added = await auth_client.post("/api/v1/watchlists/default/items", json={"symbol": "DOT-USD"})
    assert added.status_code == 201 and added.json()["items"][-1]["asset"]["symbol"] == "DOT-USD"
    dup = await auth_client.post("/api/v1/watchlists/default/items", json={"symbol": "DOT-USD"})
    assert dup.status_code == 409
    removed = await auth_client.delete("/api/v1/watchlists/default/items/DOT-USD")
    assert all(i["asset"]["symbol"] != "DOT-USD" for i in removed.json()["items"])


async def test_analysis_and_signals(auth_client) -> None:  # type: ignore[no-untyped-def]
    resp = await auth_client.post("/api/v1/analysis", json={"symbol": "ETH-USD", "timeframe": "1h"})
    assert resp.status_code == 201, resp.text
    a = resp.json()
    assert a["narrative_source"] == "rule_based"
    assert a["signal"]["action"] in {"buy", "sell", "hold"}
    assert "estimate" in a["disclaimer"]
    assert any(r["title"] == "Sample data" for r in a["signal"]["risks"])
    signals = (await auth_client.get("/api/v1/signals")).json()
    assert signals[0]["id"] == a["signal"]["id"]


async def test_strategy_crud_backtest_and_compare(auth_client) -> None:  # type: ignore[no-untyped-def]
    ids = []
    for tpl in TEMPLATES[:2]:
        d = tpl["definition"]
        body = {
            "name": tpl["name"],
            "description": tpl["description"],
            "config": {"symbol": "BTC-USD", "timeframe": "1h", "entry": d["entry"], "exit": d["exit"], "risk": d["risk"]},
        }
        resp = await auth_client.post("/api/v1/strategies", json=body)
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])

    # Editing the config creates a new immutable version
    s = (await auth_client.get(f"/api/v1/strategies/{ids[0]}")).json()
    cfg = s["current_config"]
    cfg_in = {"symbol": "BTC-USD", "timeframe": "6h", "entry": cfg["entry_rules"], "exit": cfg["exit_rules"], "risk": cfg["risk"]}
    upd = (await auth_client.patch(f"/api/v1/strategies/{ids[0]}", json={"config": cfg_in})).json()
    assert upd["current_version"] == 2 and upd["current_config"]["timeframe"] == "6h"

    bt_ids = []
    for sid in ids:
        resp = await auth_client.post("/api/v1/backtests", json={"strategy_id": sid, "bars": 800})
        assert resp.status_code == 201, resp.text
        bt = resp.json()
        assert bt["status"] == "completed", bt["error"]
        assert "HYPOTHETICAL" in bt["disclaimer"]
        assert bt["metrics"]["bars"] == 800
        assert bt["equity_curve"]
        bt_ids.append(bt["id"])
    assert (await auth_client.get(f"/api/v1/backtests/{bt_ids[0]}")).json()["strategy_version"] == 2

    cmp = (await auth_client.get("/api/v1/backtests/compare", params={"ids": ",".join(map(str, bt_ids))})).json()
    assert [b["id"] for b in cmp] == bt_ids

    listed = (await auth_client.get("/api/v1/strategies")).json()
    assert all(s["latest_backtest"] for s in listed)

    assert (await auth_client.delete(f"/api/v1/strategies/{ids[1]}")).status_code == 204
    assert (await auth_client.get(f"/api/v1/strategies/{ids[1]}")).status_code == 404


async def test_invalid_strategy_rejected(auth_client) -> None:  # type: ignore[no-untyped-def]
    body = {"name": "bad", "config": {"symbol": "BTC-USD", "entry": {"conditions": []}, "exit": {"conditions": []}}}
    resp = await auth_client.post("/api/v1/strategies", json=body)
    assert resp.status_code == 422


async def test_strategies_are_user_scoped(client) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import register

    await register(client, email="a@example.com")
    tpl = TEMPLATES[0]["definition"]
    body = {"name": "mine", "config": {"symbol": "BTC-USD", **{k: tpl[k] for k in ("entry", "exit", "risk")}}}
    sid = (await client.post("/api/v1/strategies", json=body)).json()["id"]
    client.cookies.clear()
    await register(client, email="b@example.com")
    assert (await client.get(f"/api/v1/strategies/{sid}")).status_code == 404
    assert (await client.post("/api/v1/backtests", json={"strategy_id": sid})).status_code == 404


async def test_assistant_rule_based_grounded(auth_client) -> None:  # type: ignore[no-untyped-def]
    resp = await auth_client.post("/api/v1/assistant/chat", json={"message": "Explain the current BTC trend"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    msg = data["message"]
    assert msg["meta"]["engine"] == "rule_based"
    assert "get_asset_analysis" in msg["meta"]["tools"]
    assert "BTC-USD" in msg["content"]

    follow = await auth_client.post(
        "/api/v1/assistant/chat", json={"message": "Compare ETH vs SOL", "conversation_id": data["conversation_id"]}
    )
    assert "compare_assets" in follow.json()["message"]["meta"]["tools"]

    conv = (await auth_client.get(f"/api/v1/assistant/conversations/{data['conversation_id']}")).json()
    assert len(conv["messages"]) == 4

    pf = await auth_client.post("/api/v1/assistant/chat", json={"message": "How is my portfolio doing?"})
    assert "get_portfolio" in pf.json()["message"]["meta"]["tools"]


async def test_dashboard(auth_client) -> None:  # type: ignore[no-untyped-def]
    resp = await auth_client.get("/api/v1/dashboard")
    assert resp.status_code == 200, resp.text
    d = resp.json()
    assert d["portfolio"]["equity"] > 0
    assert len(d["market"]) == 10 and len(d["watchlist"]) == 5
    assert d["meta"]["is_sample"] is True


async def test_health(client) -> None:  # type: ignore[no-untyped-def]
    r = (await client.get("/health/ready")).json()
    assert r["checks"]["database"] == "ok"
    assert (await client.get("/health")).headers["x-request-id"]
