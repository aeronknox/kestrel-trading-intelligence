"""Outgoing email for account verification and password resets.

Backends:
  * console (default): logs the message, including its link, and keeps the last
    messages in memory. For development and tests; nothing leaves the machine.
  * smtp: any SMTP relay (Resend, SES, Postmark, Mailgun, Gmail, ...), sent in a
    worker thread with the standard library so no extra dependency is needed.

Sending is best-effort for the caller: failures are logged and reported as False,
never raised, so a mail outage cannot break sign-up or leak whether an account exists.
"""

import asyncio
import smtplib
import ssl
from collections import deque
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from email.utils import make_msgid

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import EMAILS

logger = get_logger(__name__)


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str


# Console backend outbox (most recent last); tests read it to follow links.
outbox: deque[OutgoingEmail] = deque(maxlen=50)


def _mime(msg: OutgoingEmail) -> MimeMessage:
    settings = get_settings()
    mime = MimeMessage()
    mime["From"] = settings.email_from
    mime["To"] = msg.to
    mime["Subject"] = msg.subject
    mime["Message-ID"] = make_msgid()
    mime.set_content(msg.text)
    return mime


def _send_smtp(msg: OutgoingEmail) -> None:
    s = get_settings()
    assert s.smtp_host is not None
    context = ssl.create_default_context()
    if s.smtp_security == "ssl":
        client: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=context)
    else:
        client = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
    with client:
        if s.smtp_security == "starttls":
            client.starttls(context=context)
        if s.smtp_username and s.smtp_password:
            client.login(s.smtp_username, s.smtp_password)
        client.send_message(_mime(msg))


async def send_email(msg: OutgoingEmail) -> bool:
    backend = get_settings().email_backend
    if backend == "console":
        outbox.append(msg)
        EMAILS.labels("console").inc()
        logger.info("email_console", to=msg.to, subject=msg.subject, body=msg.text)
        return True
    try:
        await asyncio.to_thread(_send_smtp, msg)
    except Exception as exc:  # noqa: BLE001 - see module docstring
        EMAILS.labels("failed").inc()
        logger.warning("email_send_failed", to=msg.to, subject=msg.subject, error=f"{type(exc).__name__}: {exc}")
        return False
    EMAILS.labels("sent").inc()
    logger.info("email_sent", to=msg.to, subject=msg.subject)
    return True


# ------------------------------------------------------------------ messages
def _link(path: str, token: str) -> str:
    return f"{get_settings().public_app_url.rstrip('/')}{path}?token={token}"


def verification_email(to: str, name: str, token: str) -> OutgoingEmail:
    hours = get_settings().email_verification_ttl_hours
    return OutgoingEmail(
        to=to,
        subject="Confirm your email address",
        text=(
            f"Hi {name},\n\n"
            f"Confirm the email address for your Kestrel Intelligence account by opening this link:\n\n"
            f"{_link('/verify-email', token)}\n\n"
            f"The link expires in {hours} hours. If you did not create an account, you can ignore this email.\n\n"
            "Kestrel Intelligence is a research and paper-trading simulator; it never handles real money.\n"
        ),
    )


def password_reset_email(to: str, name: str, token: str) -> OutgoingEmail:
    minutes = get_settings().password_reset_ttl_minutes
    return OutgoingEmail(
        to=to,
        subject="Reset your password",
        text=(
            f"Hi {name},\n\n"
            f"Someone asked to reset the password for your Kestrel Intelligence account. To choose a new one, open:\n\n"
            f"{_link('/reset-password', token)}\n\n"
            f"The link expires in {minutes} minutes and can be used once. Resetting signs you out everywhere.\n"
            "If you did not ask for this, ignore this email; your password stays the same.\n"
        ),
    )
