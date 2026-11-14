"""Your own data: export all of it, delete the account and everything in it."""

import json

from sqlalchemy import func, select

from app.database.session import get_sessionmaker
from app.models.audit import AuditLog
from app.services.account import SECTIONS
from tests.conftest import register
from tests.test_alerts import cond, make_strategy

API = "/api/v1"
PASSWORD = "s3cure-passw0rd"


async def fill(client, provider) -> None:  # type: ignore[no-untyped-def]
    """Give the signed-in account data in as many places as possible."""
    await provider.set_price("SOL-USD", 100.0)
    await make_strategy(client, cond("crosses_above", 50))
    assert (await client.post(f"{API}/analysis", json={"symbol": "ETH-USD", "timeframe": "1h"})).status_code in (200, 201)
    for side in ("buy", "sell"):
        body = {"symbol": "SOL-USD", "side": side, "order_type": "market", "quantity": 10}
        assert (await client.post(f"{API}/paper/orders", json=body)).status_code == 201
    trip = (await client.get(f"{API}/paper/journal")).json()["trips"][0]
    assert (await client.put(f"{API}/paper/journal/{trip['trade_id']}", json={"setup": "Breakout"})).status_code == 200
    assert (await client.post(f"{API}/price-alerts", json={"symbol": "SOL-USD", "target": 150})).status_code == 201
    assert (await client.put(f"{API}/users/me/webhook", json={"url": "https://example.com/hook"})).status_code == 200


async def rows_for(uid: int) -> dict[str, int]:
    async with get_sessionmaker()() as s:
        return {name: int(await s.scalar(select(func.count()).select_from(model).where(belongs(uid))) or 0)
                for name, model, belongs in SECTIONS}  # fmt: skip


async def test_export_has_everything_and_no_secrets(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await fill(auth_client, provider)
    resp = await auth_client.get(f"{API}/users/me/export")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith('attachment; filename="kestrel-data-')
    assert resp.headers["cache-control"] == "no-store"
    data = json.loads(resp.text)
    assert data["profile"]["email"] == "user@example.com" and data["settings"]["webhook_url"] == "https://example.com/hook"
    for section in ("strategies", "strategy_versions", "ai_analyses", "paper_orders", "paper_trades", "journal_entries",
                    "price_alerts", "watchlists", "sessions", "activity_log"):  # fmt: skip
        assert data[section], section
    assert data["journal_entries"][0]["setup"] == "Breakout"
    for secret in ("hashed_password", "token_hash", "webhook_secret"):
        assert secret not in resp.text, secret
    assert "simulated" in data["about"]


async def test_export_is_only_your_own(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await fill(auth_client, provider)
    auth_client.cookies.clear()
    await register(auth_client, email="other@example.com")
    data = (await auth_client.get(f"{API}/users/me/export")).json()
    assert data["profile"]["email"] == "other@example.com"
    assert "user@example.com" not in json.dumps(data)
    assert data["strategies"] == [] and data["paper_orders"] == [] and data["price_alerts"] == []


async def test_deleting_the_account_removes_everything_and_only_that(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    # Someone else, with their own data, who must be untouched.
    await register(auth_client, email="keep@example.com")
    await fill(auth_client, provider)
    keep_id = (await auth_client.get(f"{API}/auth/me")).json()["id"]
    keep_before = await rows_for(keep_id)

    auth_client.cookies.clear()
    await register(auth_client, email="leave@example.com")
    await fill(auth_client, provider)
    leave_id = (await auth_client.get(f"{API}/auth/me")).json()["id"]
    assert (await auth_client.post(f"{API}/auth/login", json={"email": "leave@example.com", "password": "wrong-pass-123"})).status_code == 401
    assert sum((await rows_for(leave_id)).values()) > 10

    bad = await auth_client.post(f"{API}/auth/delete-account", json={"password": "wrong-pass-123", "confirm": "DELETE"})
    assert bad.status_code == 422 and "password" in bad.json()["error"]["message"]  # 422: a typo isn't a sign-out
    assert (await auth_client.post(f"{API}/auth/delete-account", json={"password": PASSWORD, "confirm": "yes"})).status_code == 422
    assert (await auth_client.get(f"{API}/auth/me")).status_code == 200  # still there

    resp = await auth_client.post(f"{API}/auth/delete-account", json={"password": PASSWORD, "confirm": "DELETE"})
    assert resp.status_code == 200, resp.text
    assert "ti_session" in resp.headers.get("set-cookie", "")  # the session cookie is cleared
    assert (await auth_client.get(f"{API}/auth/me")).status_code == 401

    left = await rows_for(leave_id)
    assert sum(left.values()) == 0, {k: v for k, v in left.items() if v}
    assert await rows_for(keep_id) == keep_before
    async with get_sessionmaker()() as s:
        logs = (await s.scalars(select(AuditLog))).all()
    assert any(log.action == "user.deleted" and log.entity_id == str(leave_id) for log in logs)
    # Earlier security records stay, but no copy of the address (here: the failed sign-in before deleting).
    assert any(log.action == "auth.login_failed" for log in logs)
    assert not any("leave@example.com" in json.dumps(log.details or {}) for log in logs)

    login = await auth_client.post(f"{API}/auth/login", json={"email": "leave@example.com", "password": PASSWORD})
    assert login.status_code == 401  # the account is gone

    # The address is free again.
    auth_client.cookies.clear()
    await register(auth_client, email="leave@example.com")


async def test_the_only_admin_cannot_delete_themselves(auth_client) -> None:  # type: ignore[no-untyped-def]
    from app.cli import set_role
    from app.models.enums import UserRole

    await set_role("user@example.com", UserRole.ADMIN)
    resp = await auth_client.post(f"{API}/auth/delete-account", json={"password": PASSWORD, "confirm": "DELETE"})
    assert resp.status_code == 422 and "only admin" in resp.json()["error"]["message"]


async def test_a_demo_sandbox_is_deleted_without_a_password(client, provider, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "demo_mode", True)
    await provider.set_price("BTC-USD", 60_000.0)
    assert (await client.post(f"{API}/auth/demo")).status_code == 201
    resp = await client.post(f"{API}/auth/delete-account", json={"confirm": "DELETE"})
    assert resp.status_code == 200, resp.text
    assert (await client.get(f"{API}/auth/me")).status_code == 401
