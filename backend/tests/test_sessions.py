"""Active sessions: see where the account is signed in, sign out one place or everywhere else."""

from httpx import ASGITransport, AsyncClient

from app.services.auth import describe_user_agent
from tests.conftest import register

API = "/api/v1/auth"
PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0 Mobile/15E148 Safari/604.1"
LAPTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"


async def sign_in(app, user_agent: str) -> AsyncClient:  # type: ignore[no-untyped-def]
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"user-agent": user_agent})
    resp = await c.post(f"{API}/login", json={"email": "user@example.com", "password": "s3cure-passw0rd"})
    assert resp.status_code == 200, resp.text
    return c


async def test_sessions_are_listed_and_one_can_be_signed_out(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    phone, laptop = await sign_in(app, PHONE), await sign_in(app, LAPTOP)
    try:
        sessions = (await auth_client.get(f"{API}/sessions")).json()
        assert len(sessions) == 3
        assert [s["current"] for s in sessions].count(True) == 1
        devices = {s["device"] for s in sessions}
        assert {"Chrome on iPhone", "Edge on Windows"} <= devices
        phone_id = next(s["id"] for s in sessions if s["device"] == "Chrome on iPhone")

        # Sign the phone out from here: it can't do anything any more; the others carry on.
        assert (await auth_client.delete(f"{API}/sessions/{phone_id}")).status_code == 200
        assert (await phone.get(f"{API}/me")).status_code == 401
        assert (await laptop.get(f"{API}/me")).status_code == 200
        assert (await auth_client.get(f"{API}/me")).status_code == 200
        assert len((await auth_client.get(f"{API}/sessions")).json()) == 2
        assert (await auth_client.delete(f"{API}/sessions/{phone_id}")).status_code == 404  # already gone
    finally:
        await phone.aclose()
        await laptop.aclose()


async def test_sign_out_everywhere_else(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    others = [await sign_in(app, PHONE), await sign_in(app, LAPTOP)]
    try:
        resp = await auth_client.post(f"{API}/sessions/revoke-others")
        assert resp.status_code == 200 and resp.json()["message"] == "Signed out of 2 other sessions"
        for c in others:
            assert (await c.get(f"{API}/me")).status_code == 401
        (only,) = (await auth_client.get(f"{API}/sessions")).json()
        assert only["current"] is True
        assert (await auth_client.post(f"{API}/sessions/revoke-others")).json()["message"] == "No other sessions were signed in"
    finally:
        for c in others:
            await c.aclose()


async def test_signing_out_the_current_session_logs_out(auth_client) -> None:  # type: ignore[no-untyped-def]
    (me,) = (await auth_client.get(f"{API}/sessions")).json()
    resp = await auth_client.delete(f"{API}/sessions/{me['id']}")
    assert resp.status_code == 200 and "ti_session" in resp.headers.get("set-cookie", "")
    assert (await auth_client.get(f"{API}/me")).status_code == 401


async def test_sessions_are_private(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    (mine,) = (await auth_client.get(f"{API}/sessions")).json()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        await register(other, email="other@example.com")
        theirs = (await other.get(f"{API}/sessions")).json()
        assert [s["id"] for s in theirs] != [mine["id"]]
        assert (await other.delete(f"{API}/sessions/{mine['id']}")).status_code == 404  # can't sign out someone else
    assert (await auth_client.get(f"{API}/me")).status_code == 200


def test_describe_user_agent() -> None:
    assert describe_user_agent(PHONE) == "Chrome on iPhone"
    assert describe_user_agent(LAPTOP) == "Edge on Windows"
    firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"
    assert describe_user_agent(firefox) == "Firefox on Linux"
    mac_safari = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15"
    assert describe_user_agent(mac_safari) == "Safari on macOS"
    assert describe_user_agent(None) == "Unknown device"
    assert describe_user_agent("python-httpx/0.28") == "python-httpx/0.28"
