"""Rate limiting, client-IP trust and account lockout."""

import pytest

from app.core.config import get_settings
from tests.conftest import register

LOGIN = "/api/v1/auth/login"
BAD = {"email": "victim@example.com", "password": "wrong-passw0rd"}


@pytest.fixture
def settings():  # type: ignore[no-untyped-def]
    s = get_settings()
    saved = {k: getattr(s, k) for k in ("auth_rate_limit_per_minute", "trusted_proxies", "proxy_shared_secret", "login_max_failures")}
    yield s
    for k, v in saved.items():
        setattr(s, k, v)


async def test_spoofed_forwarded_for_does_not_bypass_ip_limit(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings.auth_rate_limit_per_minute = 5
    settings.login_max_failures = 1000
    settings.trusted_proxies = []  # the test client's peer is NOT a trusted proxy
    codes = [
        (await client.post(LOGIN, json=BAD, headers={"X-Forwarded-For": f"10.0.0.{i}"})).status_code for i in range(8)
    ]
    assert codes[:5] == [401] * 5
    assert codes[5:] == [429] * 3


async def test_forwarded_for_trusted_with_proxy_secret(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings.auth_rate_limit_per_minute = 3
    settings.login_max_failures = 1000
    settings.trusted_proxies = []
    settings.proxy_shared_secret = "s3cret-proxy"
    # Each distinct (trusted) client IP gets its own bucket.
    for i in range(6):
        r = await client.post(LOGIN, json=BAD, headers={"X-Forwarded-For": f"10.1.0.{i}", "X-Proxy-Secret": "s3cret-proxy"})
        assert r.status_code == 401
    # A wrong secret is ignored -> falls back to the peer address, which then hits the limit.
    codes = [(await client.post(LOGIN, json=BAD, headers={"X-Forwarded-For": f"10.2.0.{i}", "X-Proxy-Secret": "nope"})).status_code for i in range(4)]
    assert codes[-1] == 429


async def test_account_lockout_after_repeated_failures(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings.login_max_failures = 3
    await register(client, email="victim@example.com", password="real-passw0rd1")
    client.cookies.clear()
    for i in range(3):
        assert (await client.post(LOGIN, json=BAD, headers={"X-Forwarded-For": f"10.3.0.{i}"})).status_code == 401
    # Even the correct password is refused while locked, from any IP.
    locked = await client.post(LOGIN, json={"email": "victim@example.com", "password": "real-passw0rd1"})
    assert locked.status_code == 429


async def test_successful_login_resets_failure_counter(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings.login_max_failures = 3
    await register(client, email="victim@example.com", password="real-passw0rd1")
    client.cookies.clear()
    for _ in range(2):
        await client.post(LOGIN, json=BAD)
    assert (await client.post(LOGIN, json={"email": "victim@example.com", "password": "real-passw0rd1"})).status_code == 200
    for _ in range(2):
        assert (await client.post(LOGIN, json=BAD)).status_code == 401


async def test_security_headers_and_error_shape(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.json()["error"]["code"] == "http_error"
    assert "request_id" in r.json()["error"]


async def test_integrity_errors_map_to_409(app) -> None:  # type: ignore[no-untyped-def]
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.exc import IntegrityError

    @app.get("/__boom")
    async def boom() -> None:
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/__boom")
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


async def test_failed_commit_is_reported_not_silently_ok(auth_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import AsyncSession

    async def failing_commit(self):  # type: ignore[no-untyped-def]
        raise IntegrityError("COMMIT", {}, Exception("simulated commit failure"))

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)
    r = await auth_client.post("/api/v1/watchlists/default/items", json={"symbol": "DOT-USD"})
    assert r.status_code == 409  # previously returned 201 although nothing was saved
    monkeypatch.undo()
    wl = (await auth_client.get("/api/v1/watchlists/default")).json()
    assert all(i["asset"]["symbol"] != "DOT-USD" for i in wl["items"])
