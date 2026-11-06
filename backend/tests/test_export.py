"""CSV exports: content, ownership and spreadsheet-formula safety."""

import csv
import io

from app.services.export import _cell, safe_filename
from app.strategies.definition import TEMPLATES
from tests.conftest import register

RSI = next(t for t in TEMPLATES if t["key"] == "rsi_mean_reversion")["definition"]


def _rows(resp) -> list[list[str]]:  # type: ignore[no-untyped-def]
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.headers["content-disposition"].startswith('attachment; filename="')
    text = resp.content.decode("utf-8-sig")  # tolerate the Excel BOM
    return list(csv.reader(io.StringIO(text)))


async def _strategy(client, name: str = "=HYPERLINK(evil)") -> int:  # type: ignore[no-untyped-def]
    body = {"name": name, "config": {"symbol": "BTC-USD", "timeframe": "1h", **RSI}}
    resp = await client.post("/api/v1/strategies", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_formula_cells_are_neutralized_but_numbers_are_kept() -> None:
    assert _cell("=1+1") == "'=1+1"
    assert _cell("@SUM(A1)") == "'@SUM(A1)"
    assert _cell("+cmd") == "'+cmd"
    assert _cell("-2+3") == "'-2+3"
    assert _cell(-2.5) == -2.5  # negative numbers stay numeric
    assert _cell("BTC-USD") == "BTC-USD"
    assert _cell(None) == ""
    assert safe_filename("backtest", 7, '=HYPERLINK("x")', "BTC-USD") == "backtest-7-hyperlink-x-btc-usd.csv"


async def test_backtest_trades_and_equity_csv(auth_client) -> None:  # type: ignore[no-untyped-def]
    sid = await _strategy(auth_client)
    bt = (await auth_client.post("/api/v1/backtests", json={"strategy_id": sid, "bars": 1500})).json()
    trades = _rows(await auth_client.get(f"/api/v1/backtests/{bt['id']}/trades.csv"))
    assert trades[0] == ["entry_time", "entry_price", "quantity", "entry_fee", "exit_time", "exit_price", "exit_fee",
                         "exit_reason", "pnl", "return_pct", "bars_held"]  # fmt: skip
    assert len(trades) - 1 == len(bt["trades"])
    if bt["trades"]:
        first = bt["trades"][0]
        assert trades[1][0].endswith("+00:00")  # ISO 8601 UTC
        assert float(trades[1][8]) == first["pnl"]  # full precision round-trip

    equity = _rows(await auth_client.get(f"/api/v1/backtests/{bt['id']}/equity.csv"))
    assert equity[0] == ["time", "equity", "drawdown_pct", "buy_and_hold_equity"]
    assert len(equity) - 1 == len(bt["equity_curve"])
    assert float(equity[-1][1]) == bt["equity_curve"][-1]["equity"]


async def test_paper_trades_and_history_csv(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("BTC-USD", 50_000.0)
    for side in ("buy", "sell"):
        r = await auth_client.post("/api/v1/paper/orders", json={"symbol": "BTC-USD", "side": side, "order_type": "market", "quantity": 0.1})
        assert r.json()["status"] == "filled"
    trades = _rows(await auth_client.get("/api/v1/paper/trades.csv"))
    assert trades[0][:3] == ["executed_at", "symbol", "side"]
    assert [row[2] for row in trades[1:]] == ["buy", "sell"]  # oldest first
    assert all(row[-1] == "True" for row in trades[1:])  # flagged as simulated
    history = _rows(await auth_client.get("/api/v1/paper/history.csv"))
    assert history[0] == ["time", "equity", "cash", "positions_value"] and len(history) >= 2


async def test_research_csv_and_ownership(auth_client, client) -> None:  # type: ignore[no-untyped-def]
    sid = await _strategy(auth_client)
    grid = [{"path": "entry.conditions.0.right.value", "values": [25, 30]}, {"path": "risk.stop_loss_pct", "values": [2, 5, 8]}]
    sweep = (await auth_client.post("/api/v1/research/sweeps", json={"strategy_id": sid, "bars": 800, "params": grid, "min_trades": 0})).json()
    rows = _rows(await auth_client.get(f"/api/v1/research/{sweep['id']}/results.csv"))
    assert rows[0][:4] == ["Entry #1 (RSI(14) crosses above 30): threshold", "Risk: stop loss pct", "valid", "score"]
    assert [r[:2] for r in rows[1:]] == [["25.0", "2.0"], ["25.0", "5.0"], ["25.0", "8.0"], ["30.0", "2.0"], ["30.0", "5.0"], ["30.0", "8.0"]]
    disposition = (await auth_client.get(f"/api/v1/research/{sweep['id']}/results.csv")).headers["content-disposition"]
    assert "hyperlink" in disposition and "=" not in disposition.split("filename=")[1]

    wf = (await auth_client.post("/api/v1/research/walk-forward", json={"strategy_id": sid, "bars": 800, "params": grid[:1], "folds": 3, "is_ratio": 2})).json()
    folds = _rows(await auth_client.get(f"/api/v1/research/{wf['id']}/results.csv"))
    assert folds[0][:5] == ["fold", "tuning_start", "tuning_end", "test_start", "test_end"]
    assert [r[0] for r in folds[1:]] == ["1", "2", "3"]

    bt = (await auth_client.post("/api/v1/backtests", json={"strategy_id": sid, "bars": 300})).json()
    await auth_client.post("/api/v1/auth/logout")
    await register(client, email="other@example.com")
    for path in (f"/api/v1/research/{sweep['id']}/results.csv", f"/api/v1/backtests/{bt['id']}/trades.csv",
                 f"/api/v1/backtests/{bt['id']}/equity.csv"):  # fmt: skip
        assert (await client.get(path)).status_code == 404
    assert len(_rows(await client.get("/api/v1/paper/trades.csv"))) == 1  # only the header: other users' trades never leak
