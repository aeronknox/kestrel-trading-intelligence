"""Email verification and password reset."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.core.config import get_settings
from app.database.session import get_sessionmaker
from app.models.user import AuthToken
from app.services import email as email_service
from tests.conftest import register

API = "/api/v1/auth"


def last_token(to: str, path: str = "/verify-email") -> str:
    """Token from the newest console-backend email to `to` containing a `path` link."""
    for msg in reversed(email_service.outbox):
        m = re.search(re.escape(path) + r"\?token=([\w-]+)", msg.text)
        if msg.to == to and m:
            return m.group(1)
    raise AssertionError(f"no {path} email to {to}")


@pytest.fixture(autouse=True)
def _clear_outbox():  # type: ignore[no-untyped-def]
    email_service.outbox.clear()
    yield
    email_service.outbox.clear()


async def test_registration_sends_verification_and_link_verifies(client) -> None:  # type: ignore[no-untyped-def]
    user = await register(client)
    assert user["email_verified"] is False
    msg = email_service.outbox[-1]
    assert msg.to == "user@example.com" and "Confirm" in msg.subject
    assert f"{get_settings().public_app_url}/verify-email?token=" in msg.text

    client.cookies.clear()  # the link works without being signed in (e.g. on another device)
    ok = await client.post(f"{API}/verify-email", json={"token": last_token("user@example.com")})
    assert ok.status_code == 200
    reused = await client.post(f"{API}/verify-email", json={"token": last_token("user@example.com")})
    assert reused.status_code == 422 and "invalid or has expired" in reused.json()["error"]["message"]

    await client.post(f"{API}/login", json={"email": "user@example.com", "password": "s3cure-passw0rd"})
    assert (await client.get(f"{API}/me")).json()["email_verified"] is True


async def test_resend_replaces_old_link_and_has_cooldown(client) -> None:  # type: ignore[no-untyped-def]
    await register(client)
    first = last_token("user@example.com")
    resend = await client.post(f"{API}/verify-email/resend")
    assert resend.status_code == 200
    second = last_token("user@example.com")
    assert second != first
    assert (await client.post(f"{API}/verify-email/resend")).status_code == 429  # within the cooldown
    assert (await client.post(f"{API}/verify-email", json={"token": first})).status_code == 422  # superseded
    assert (await client.post(f"{API}/verify-email", json={"token": second})).status_code == 200
    again = await client.post(f"{API}/verify-email/resend")
    assert again.json()["message"] == "Your email address is already verified"


async def test_expired_and_wrong_purpose_tokens_are_rejected(client) -> None:  # type: ignore[no-untyped-def]
    await register(client)
    token = last_token("user@example.com")
    # A verification token can't reset a password.
    bad = await client.post(f"{API}/reset-password", json={"token": token, "new_password": "brand-new-passw0rd"})
    assert bad.status_code == 422
    async with get_sessionmaker()() as s:
        await s.execute(update(AuthToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await s.commit()
    assert (await client.post(f"{API}/verify-email", json={"token": token})).status_code == 422


async def test_forgot_password_does_not_reveal_accounts(client) -> None:  # type: ignore[no-untyped-def]
    await register(client)
    email_service.outbox.clear()
    known = await client.post(f"{API}/forgot-password", json={"email": "USER@example.com"})
    unknown = await client.post(f"{API}/forgot-password", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [m.to for m in email_service.outbox] == ["user@example.com"]  # only real accounts get mail
    # A second request within the cooldown is accepted but sends nothing (no inbox flooding).
    await client.post(f"{API}/forgot-password", json={"email": "user@example.com"})
    assert len(email_service.outbox) == 1


async def test_password_reset_changes_password_and_signs_out_everywhere(client) -> None:  # type: ignore[no-untyped-def]
    await register(client)  # signed in: session A
    session_a = dict(client.cookies)
    await client.post(f"{API}/forgot-password", json={"email": "user@example.com"})
    token = last_token("user@example.com", "/reset-password")

    weak = await client.post(f"{API}/reset-password", json={"token": token, "new_password": "short"})
    assert weak.status_code == 422  # password rules apply; the token is not consumed
    done = await client.post(f"{API}/reset-password", json={"token": token, "new_password": "brand-new-passw0rd"})
    assert done.status_code == 200
    assert (await client.post(f"{API}/reset-password", json={"token": token, "new_password": "other-passw0rd1"})).status_code == 422

    client.cookies.clear()
    client.cookies.update(session_a)
    assert (await client.get(f"{API}/me")).status_code == 401  # existing sessions were revoked
    client.cookies.clear()
    old = await client.post(f"{API}/login", json={"email": "user@example.com", "password": "s3cure-passw0rd"})
    assert old.status_code == 401
    new = await client.post(f"{API}/login", json={"email": "user@example.com", "password": "brand-new-passw0rd"})
    assert new.status_code == 200 and new.json()["email_verified"] is True  # the link proved ownership


async def test_reset_clears_account_lockout(client) -> None:  # type: ignore[no-untyped-def]
    s = get_settings()
    saved = s.login_max_failures
    s.login_max_failures = 2
    try:
        await register(client)
        client.cookies.clear()
        for _ in range(2):
            await client.post(f"{API}/login", json={"email": "user@example.com", "password": "wrong-passw0rd"})
        assert (await client.post(f"{API}/login", json={"email": "user@example.com", "password": "s3cure-passw0rd"})).status_code == 429
        await client.post(f"{API}/forgot-password", json={"email": "user@example.com"})
        token = last_token("user@example.com", "/reset-password")
        await client.post(f"{API}/reset-password", json={"token": token, "new_password": "brand-new-passw0rd"})
        assert (await client.post(f"{API}/login", json={"email": "user@example.com", "password": "brand-new-passw0rd"})).status_code == 200
    finally:
        s.login_max_failures = saved


async def test_smtp_backend_sends_and_failures_do_not_break_signup(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sent: list = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):  # type: ignore[no-untyped-def]
            self.host, self.port = host, port

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *a):  # type: ignore[no-untyped-def]
            return False

        def starttls(self, context):  # type: ignore[no-untyped-def]
            sent.append("starttls")

        def login(self, user, password):  # type: ignore[no-untyped-def]
            sent.append(("login", user))

        def send_message(self, msg):  # type: ignore[no-untyped-def]
            sent.append(msg)

    s = get_settings()
    monkeypatch.setattr(s, "email_backend", "smtp")
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "smtp_username", "apikey")
    monkeypatch.setattr(s, "smtp_password", "not-a-real-secret")
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    assert (await client.get(f"{API}/config")).json()["email_delivery"] == "smtp"  # the pages then say "check your inbox"
    await register(client, email="mail@example.com")
    assert sent[0] == "starttls" and sent[1] == ("login", "apikey")
    assert sent[2]["To"] == "mail@example.com" and sent[2]["Subject"] == "Confirm your email address"

    def broken(*a, **k):  # type: ignore[no-untyped-def]
        raise OSError("connection refused")

    monkeypatch.setattr(email_service.smtplib, "SMTP", broken)
    client.cookies.clear()
    assert (await client.post(f"{API}/register", json={"email": "down@example.com", "password": "s3cure-passw0rd", "full_name": "D"})).status_code == 201
    assert (await client.post(f"{API}/forgot-password", json={"email": "down@example.com"})).status_code == 202
