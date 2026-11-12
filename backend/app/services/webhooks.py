"""Webhook notifications for strategy alerts (Slack, Discord or any HTTPS endpoint).

The server makes these requests on a user's behalf, so they are restricted to the public
internet (SSRF protection):

- https only (WEBHOOK_ALLOW_PRIVATE also allows http, for local development receivers);
- no credentials in the URL, at most 500 characters;
- the host is resolved and *every* address must be public (no loopback, private, link-local
  such as cloud metadata at 169.254.169.254, multicast or reserved ranges);
- the connection goes to that checked address (the hostname is kept for TLS verification
  and the Host header), so DNS can't be switched to an internal address between the
  check and the request (DNS rebinding);
- redirects are not followed, the timeout is short and the response body is never read.

Generic endpoints get a JSON event signed with the user's secret:
X-Kestrel-Signature: sha256=HMAC_SHA256(secret, f"{timestamp}.{body}"), with the timestamp in
X-Kestrel-Timestamp, so receivers can verify origin and reject replays.
"""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import secrets
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import WEBHOOKS

logger = get_logger(__name__)

MAX_URL_LENGTH = 500
TIMEOUT_SECONDS = 5.0
USER_AGENT = "Kestrel-Webhooks/1.0"
WebhookFormat = Literal["slack", "discord", "json"]

# Tests replace this to observe requests without a network.
transport: httpx.AsyncBaseTransport | None = None


class WebhookError(Exception):
    """The URL is not allowed, or delivery failed. The message is safe to show the user."""


@dataclass(frozen=True)
class Target:
    url: str
    host: str
    port: int
    scheme: str


def new_secret() -> str:
    return secrets.token_hex(24)


def webhook_format(url: str) -> WebhookFormat:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host == "hooks.slack.com":
        return "slack"
    if host in ("discord.com", "discordapp.com") and parts.path.startswith("/api/webhooks/"):
        return "discord"
    return "json"


def parse_url(url: str) -> Target:
    """Syntax checks (no network). Raises WebhookError with a user-facing reason."""
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise WebhookError(f"Webhook URL must be at most {MAX_URL_LENGTH} characters")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise WebhookError("Webhook URL is not valid") from exc
    allowed = ("https", "http") if get_settings().webhook_allow_private else ("https",)
    if parts.scheme not in allowed:
        raise WebhookError("Webhook URL must start with https://")
    if not parts.hostname:
        raise WebhookError("Webhook URL needs a host name")
    if parts.username or parts.password:
        raise WebhookError("Webhook URL must not contain a user name or password")
    return Target(url=url, host=parts.hostname, port=port or (443 if parts.scheme == "https" else 80), scheme=parts.scheme)


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])  # drop an IPv6 zone index
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def resolve(target: Target) -> str:
    """The address to connect to; every address the host resolves to must be public."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(target.host, target.port, proto=6)  # TCP
    except OSError as exc:
        raise WebhookError(f"Could not resolve {target.host}") from exc
    addresses = list(dict.fromkeys(str(info[4][0]) for info in infos))
    if not addresses:
        raise WebhookError(f"Could not resolve {target.host}")
    if not get_settings().webhook_allow_private and not all(_public(a) for a in addresses):
        raise WebhookError("Webhook URL must point to a public internet address")
    return addresses[0]


async def check_url(url: str) -> Target:
    """Full validation, including DNS, for saving a URL."""
    target = parse_url(url)
    await resolve(target)
    return target


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def build_payload(fmt: WebhookFormat, title: str, lines: list[str], event: dict) -> dict:
    text = "\n".join([title, *lines])
    if fmt == "slack":
        return {"text": text}
    if fmt == "discord":
        return {"content": text[:2000], "allowed_mentions": {"parse": []}}  # never ping @everyone
    return {"title": title, "text": "\n".join(lines), **event}


async def deliver(url: str, secret: str, payload: dict) -> str:
    """POST the payload; returns a short status ("HTTP 204"). Raises WebhookError on failure."""
    target = parse_url(url)
    address = await resolve(target)
    parts = urlsplit(target.url)
    literal = f"[{address}]" if ":" in address else address
    default_port = (target.scheme == "https" and target.port == 443) or (target.scheme == "http" and target.port == 80)
    pinned = urlunsplit((parts.scheme, f"{literal}:{target.port}", parts.path or "/", parts.query, ""))
    body = json.dumps(payload, separators=(",", ":"), default=str).encode()
    timestamp = str(int(time.time()))
    headers = {
        "Host": target.host if default_port else f"{target.host}:{target.port}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-Kestrel-Timestamp": timestamp,
        "X-Kestrel-Signature": sign(secret, timestamp, body),
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False, transport=transport) as client:
            response = await client.post(pinned, content=body, headers=headers, extensions={"sni_hostname": target.host})
    except httpx.HTTPError as exc:
        WEBHOOKS.labels("failed").inc()
        raise WebhookError(f"Could not reach {target.host} ({type(exc).__name__})") from exc
    status = f"HTTP {response.status_code}"
    if not 200 <= response.status_code < 300:
        WEBHOOKS.labels("failed").inc()
        raise WebhookError(f"{target.host} answered {status}" + (" (redirects are not followed)" if response.is_redirect else ""))
    WEBHOOKS.labels("sent").inc()
    return status
