"""Password reset tokens: creating them, delivering them, and spending them.

The rule that shapes this module: **the API must never return a token.** The
moment it does, anyone who knows a username — and usernames here are guessable
— can take the account over. "Displayed" means displayed to the operator.

So delivery is pluggable. With SMTP configured the link is emailed, which is
the only way that works away from the box. Without it the link goes to the log,
which is honest for a self-hosted instance where the operator is the only user.
An email that lands in spam would be worse than no email, so neither path
pretends the other exists.
"""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

DEFAULT_RESET_TOKEN_MINUTES = 30
DEFAULT_APP_URL = "http://localhost:3000"
DEFAULT_RESET_REQUESTS_PER_HOUR = 3


def _positive_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


def reset_token_minutes() -> int:
    """How long a link stays good for. Zero means immediately expired."""
    return _positive_int("RESET_TOKEN_MINUTES", DEFAULT_RESET_TOKEN_MINUTES)


def reset_requests_per_hour() -> int:
    """How many links may be created for one account in an hour."""
    return _positive_int(
        "RESET_REQUESTS_PER_HOUR", DEFAULT_RESET_REQUESTS_PER_HOUR
    )


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_token() -> tuple[str, str]:
    """Return (raw, hash). The raw value only ever leaves through delivery."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def expiry_from_now() -> datetime:
    """Naive UTC, matching the TIMESTAMP columns the rest of the app uses."""
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        minutes=reset_token_minutes()
    )


def reset_link(raw_token: str) -> str:
    base = os.getenv("APP_URL", DEFAULT_APP_URL).rstrip("/")
    return f"{base}/reset-password?token={raw_token}"


def deliver(identifier: str, link: str) -> bool:
    """Send the link by email if configured, otherwise write it to the log.

    Returns whether it was emailed, so the caller can be honest about which
    happened rather than implying a message went out.
    """
    host = os.getenv("SMTP_HOST")
    if not host:
        logger.warning("Password reset link for %s: %s", identifier, link)
        return False

    import smtplib
    from email.message import EmailMessage

    message = EmailMessage()
    message["Subject"] = "Reset your Tapestry password"
    message["From"] = os.getenv("SMTP_FROM", "tapestry@localhost")
    message["To"] = identifier
    message.set_content(
        "Use this link to choose a new password:\n\n"
        f"{link}\n\n"
        "If you did not ask for this, nothing has changed.\n"
    )

    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as smtp:
        if os.getenv("SMTP_USER"):
            smtp.starttls()
            smtp.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(message)
    return True
