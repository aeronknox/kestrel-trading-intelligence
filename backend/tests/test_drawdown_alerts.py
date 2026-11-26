"""Drawdown alerts: notify once when the paper portfolio falls a set % below its high; re-arm on a new high."""

from app.services.drawdown_alerts import check_drawdown_alerts
from tests.test_stop_orders import API, limits, order


async def notes(client) -> list[dict]:  # type: ignore[no-untyped-def]
    return [n for n in (await client.get("/api/v1/notifications")).json()["notifications"] if n["kind"] == "drawdown"]


async def test_alerts_once_per_drawdown_and_rearms_on_a_new_high(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    pf = await limits(auth_client, max_position_pct=100, drawdown_alert_pct=5)
    assert pf["risk_limits"]["drawdown_alert_pct"] == 5
    await order(auth_client, quantity=900)  # $90k of SOL in a $100k account

    await provider.set_price("SOL-USD", 97.0)  # about -2.7%: under the threshold
    assert await check_drawdown_alerts() == 0
    await provider.set_price("SOL-USD", 93.0)  # about -6.4%
    assert await check_drawdown_alerts() == 1
    assert await check_drawdown_alerts() == 0  # once per drawdown
    await provider.set_price("SOL-USD", 90.0)  # deeper, same drawdown: still quiet
    assert await check_drawdown_alerts() == 0
    (n,) = await notes(auth_client)
    assert n["title"].startswith("Portfolio down 6.") and "below its high of $100," in n["message"] and "Nothing was sold" in n["message"]

    # A new high re-arms it: the snapshot taken at the next fill records it.
    await provider.set_price("SOL-USD", 110.0)
    await order(auth_client, quantity=1)
    assert await check_drawdown_alerts() == 0
    await provider.set_price("SOL-USD", 100.0)
    assert await check_drawdown_alerts() == 1
    assert len(await notes(auth_client)) == 2


async def test_off_by_default_and_validated(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client, quantity=200)
    await provider.set_price("SOL-USD", 10.0)
    assert await check_drawdown_alerts() == 0  # not set
    for bad in (0.5, 95):
        resp = await auth_client.put(f"{API}/portfolio/risk-limits", json={
            "max_position_pct": 25, "max_open_positions": 10, "daily_loss_limit_pct": 5, "drawdown_alert_pct": bad})  # fmt: skip
        assert resp.status_code == 422
