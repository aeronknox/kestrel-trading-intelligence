"""Alert webhooks: SSRF protection, pinned delivery, signatures, formats and the API."""

import asyncio
import json
import socket

import httpx
import pytest

from app.services import webhooks
from tests.test_forward import cond, rewind, strategy, use

API = "/api/v1"
PUBLIC_IP = "93.184.215.14"


def fake_dns(monkeypatch, *addresses: str) -> None:  # type: ignore[no-untyped-def]
    async def getaddrinfo(host, port, **_):  # type: ignore[no-untyped-def]
        family = socket.AF_INET6 if ":" in addresses[0] else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", getaddrinfo)


class Receiver:
    """Stands in for the network: records requests and answers with `status`."""

    def __init__(self, status: int = 204, headers: dict | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.status, self.headers = status, headers or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, headers=self.headers)


@pytest.fixture
def receiver(monkeypatch):  # type: ignore[no-untyped-def]
    r = Receiver()
    monkeypatch.setattr(webhooks, "transport", httpx.MockTransport(r))
    return r


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://hooks.example.com/x", "https://"),
        ("ftp://hooks.example.com/x", "https://"),
        ("https://user:pw@hooks.example.com/x", "user name or password"),
        ("https:///no-host", "host name"),
        ("https://hooks.example.com/" + "a" * 500, "at most 500"),
    ],
)
def test_url_syntax_is_checked(url: str, reason: str) -> None:
    with pytest.raises(webhooks.WebhookError, match=reason):
        webhooks.parse_url(url)


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("10.1.2.3",),
        ("192.168.0.10",),
        ("172.16.5.5",),
        ("169.254.169.254",),  # cloud metadata
        ("100.64.0.1",),  # carrier-grade NAT
        ("0.0.0.0",),
        ("::1",),
        ("fd00::1",),
        ("fe80::1%eth0",),
        ("::ffff:127.0.0.1",),  # IPv4-mapped loopback
        (PUBLIC_IP, "10.0.0.1"),  # one private answer is enough to refuse (rebinding setups)
    ],
)
async def test_non_public_addresses_are_refused(monkeypatch, addresses) -> None:  # type: ignore[no-untyped-def]
    fake_dns(monkeypatch, *addresses)
    with pytest.raises(webhooks.WebhookError, match="public internet address"):
        await webhooks.check_url("https://hooks.example.com/abc")


async def test_ip_literal_urls_are_checked_too() -> None:
    with pytest.raises(webhooks.WebhookError, match="public internet address"):
        await webhooks.check_url("https://127.0.0.1:8000/internal")


async def test_delivery_is_pinned_to_the_checked_address_and_signed(monkeypatch, receiver) -> None:  # type: ignore[no-untyped-def]
    fake_dns(monkeypatch, PUBLIC_IP)
    status = await webhooks.deliver("https://hooks.example.com/in/abc?x=1", "s3cret", {"hello": "world"})
    assert status == "HTTP 204"
    req = receiver.requests[0]
    # Connects to the address that passed the check, not whatever DNS says next...
    assert req.url.host == PUBLIC_IP and req.url.path == "/in/abc" and req.url.query == b"x=1"
    # ...while TLS and virtual hosting still use the real name.
    assert req.headers["host"] == "hooks.example.com"
    assert req.extensions["sni_hostname"] == "hooks.example.com"
    body = req.content
    assert json.loads(body) == {"hello": "world"}
    ts = req.headers["x-kestrel-timestamp"]
    assert req.headers["x-kestrel-signature"] == webhooks.sign("s3cret", ts, body)
    assert req.headers["user-agent"] == webhooks.USER_AGENT


async def test_redirects_and_errors_are_failures(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_dns(monkeypatch, PUBLIC_IP)
    monkeypatch.setattr(webhooks, "transport", httpx.MockTransport(Receiver(302, {"location": "http://169.254.169.254/"})))
    with pytest.raises(webhooks.WebhookError, match="redirects are not followed"):
        await webhooks.deliver("https://hooks.example.com/x", "s", {})
    monkeypatch.setattr(webhooks, "transport", httpx.MockTransport(Receiver(500)))
    with pytest.raises(webhooks.WebhookError, match="HTTP 500"):
        await webhooks.deliver("https://hooks.example.com/x", "s", {})


def test_payload_formats() -> None:
    assert webhooks.webhook_format("https://hooks.slack.com/services/T/B/x") == "slack"
    assert webhooks.webhook_format("https://discord.com/api/webhooks/1/abc") == "discord"
    assert webhooks.webhook_format("https://example.com/hook") == "json"
    assert webhooks.build_payload("slack", "Title", ["a", "b"], {"k": 1}) == {"text": "Title\na\nb"}
    discord = webhooks.build_payload("discord", "Title", ["@everyone"], {})
    assert discord["allowed_mentions"] == {"parse": []}  # message text can't ping a whole server
    assert webhooks.build_payload("json", "Title", ["a"], {"type": "t"}) == {"title": "Title", "text": "a", "type": "t"}


async def test_webhook_settings_api(auth_client, monkeypatch, receiver) -> None:  # type: ignore[no-untyped-def]
    assert (await auth_client.get(f"{API}/users/me/webhook")).json()["url"] is None
    fake_dns(monkeypatch, "10.0.0.7")
    bad = await auth_client.put(f"{API}/users/me/webhook", json={"url": "https://internal.example.com/hook"})
    assert bad.status_code == 422 and "public internet address" in bad.json()["error"]["message"]

    fake_dns(monkeypatch, PUBLIC_IP)
    saved = (await auth_client.put(f"{API}/users/me/webhook", json={"url": "https://hooks.slack.com/services/T/B/x"})).json()
    assert saved["format"] == "slack" and len(saved["secret"]) == 48
    rotated = (await auth_client.post(f"{API}/users/me/webhook/secret")).json()
    assert rotated["secret"] != saved["secret"]

    tested = (await auth_client.post(f"{API}/users/me/webhook/test")).json()
    assert tested["ok"] is True and tested["webhook"]["last_status"] == "HTTP 204"
    assert "Test notification" in json.loads(receiver.requests[-1].content)["text"]

    cleared = (await auth_client.delete(f"{API}/users/me/webhook")).json()
    assert cleared["url"] is None and cleared["secret"] is None


async def test_failed_test_delivery_is_reported_not_raised(auth_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_dns(monkeypatch, PUBLIC_IP)
    monkeypatch.setattr(webhooks, "transport", httpx.MockTransport(Receiver(404)))
    await auth_client.put(f"{API}/users/me/webhook", json={"url": "https://example.com/gone"})
    tested = (await auth_client.post(f"{API}/users/me/webhook/test")).json()
    assert tested["ok"] is False and tested["webhook"]["last_status"] == "Failed: example.com answered HTTP 404"


async def test_demo_accounts_cannot_use_webhooks(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "demo_mode", True)
    assert (await client.post(f"{API}/auth/demo")).status_code == 201
    resp = await client.put(f"{API}/users/me/webhook", json={"url": "https://example.com/hook"})
    assert resp.status_code == 403


async def test_alert_events_are_delivered_as_signed_json(auth_client, monkeypatch, receiver) -> None:  # type: ignore[no-untyped-def]
    from app.services.alerts import evaluate_alerts

    fake_dns(monkeypatch, PUBLIC_IP)
    hook = (await auth_client.put(f"{API}/users/me/webhook", json={"url": "https://example.com/kestrel"})).json()
    await use(lambda ago: 110.0 if ago <= 1 else 100.0)
    sid = await strategy(auth_client, cond(">", 105), cond("<", 95))
    on = {"auto_trade": True, "notify_webhook": True}
    assert (await auth_client.put(f"{API}/alerts/strategy/{sid}", json=on)).json()["notify_webhook"] is True
    await evaluate_alerts()  # baseline
    await rewind(sid, 2)
    await evaluate_alerts()

    req = receiver.requests[-1]
    payload = json.loads(req.content)
    assert payload["type"] == "strategy_alert" and payload["strategy_id"] == sid
    event = payload["events"][0]
    assert event["kind"] == "entry" and event["symbol"] == "BTC-USD" and event["order_id"]  # the forward test's order
    assert "No real-money order is ever placed" in payload["disclaimer"]
    assert req.headers["x-kestrel-signature"] == webhooks.sign(hook["secret"], req.headers["x-kestrel-timestamp"], req.content)
    assert (await auth_client.get(f"{API}/users/me/webhook")).json()["last_status"] == "HTTP 204"
