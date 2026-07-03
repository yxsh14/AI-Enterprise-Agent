"""Extract enterprise user email addresses from free-text questions."""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

_IDENTITY_PHRASES = (
    "here is my email",
    "here's my email",
    "here is my mail",
    "here's my mail",
    "my email is",
    "my mail is",
    "email is",
    "use this email",
    "use my email",
    "requested by",
    "sure here",
    "yes here",
)


def extract_email_from_text(text: str) -> str | None:
    """Return the first email address found in *text*, normalized to lowercase."""
    match = _EMAIL_RE.search(text)
    if not match:
        return None
    return match.group(0).strip().lower()


def is_email_identity_reply(text: str) -> bool:
    """True when the message is mainly providing an email for audit / ticket creation."""
    if not extract_email_from_text(text):
        return False

    lowered = text.lower()
    if any(phrase in lowered for phrase in _IDENTITY_PHRASES):
        return True

    # Short reply that is mostly an email address.
    words = [word for word in lowered.split() if word not in {"is", "the", "a", "an", "my"}]
    return len(words) <= 6
