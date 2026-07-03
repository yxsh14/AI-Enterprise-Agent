"""State-first routing: active dialogue turns skip fresh intent classification."""

from __future__ import annotations

from app.utils.intent import detect_intent


def is_ticket_continuation(question: str, has_meeting_context: bool) -> bool:
    """True when the user is continuing a meeting → ticket flow."""
    if not has_meeting_context:
        return False

    text = question.lower()
    continuation_phrases = (
        "create a ticket",
        "create ticket",
        "open a ticket",
        "make a ticket",
        "jira ticket",
        "ticket for it",
        "ticket for this",
        "ticket from this",
        "ticket from it",
        "from this",
        "from it",
        "for it",
        "for this",
    )
    return any(phrase in text for phrase in continuation_phrases)


def is_employee_lookup_question(question: str) -> bool:
    """True for fresh employee/profile questions (not email slot-filling)."""
    text = question.lower()
    lookup_phrases = (
        "who is",
        "employee",
        "profile",
        "whose mail",
        "who's mail",
        "who owns this email",
        "who owns this mail",
        "fetch employee",
    )
    return any(phrase in text for phrase in lookup_phrases)


def resolve_fresh_intent(question: str) -> str:
    """Classify a new turn when no dialogue state is active (regex fallback)."""
    if is_employee_lookup_question(question):
        return "fetch_employee"
    return detect_intent(question).name
