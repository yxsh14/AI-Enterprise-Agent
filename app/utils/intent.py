from dataclasses import dataclass
from typing import Literal


IntentName = Literal[
    "create_jira_ticket",
    "update_jira_ticket",
    "delete_jira_ticket",
    "list_jira_tickets",
    "read_meeting_docs",
    "fetch_employee",
    "general_answer",
]


@dataclass(frozen=True)
class Intent:
    name: IntentName
    confidence: float


def detect_intent(question: str) -> Intent:
    """Regex fallback for single-turn routing when no dialogue state is active."""
    text = question.lower()

    ticket_keywords = ["ticket", "jira", "bug", "incident", "request", "escalation"]
    update_keywords = ["update", "edit", "change", "modify"]
    delete_keywords = ["delete", "remove", "close permanently"]
    employee_keywords = ["employee", "profile", "who is", "manager", "department"]
    meeting_doc_keywords = [
        "meeting",
        "meeting doc",
        "meeting docs",
        "meeting notes",
        "standup",
        "sync notes",
        "confluence",
        "issue addressed",
        "issues addressed",
    ]
    knowledge_keywords = [
        "policy",
        "how do",
        "how to",
        "process",
        "workflow",
        "vpn",
        "laptop",
        "checkout",
        "dashboard",
        "payment",
    ]

    if _is_jira_ticket_read_request(text):
        return Intent("list_jira_tickets", 0.9)
    if any(keyword in text for keyword in meeting_doc_keywords) and not (
        "create" in text and any(keyword in text for keyword in ticket_keywords)
    ):
        return Intent("read_meeting_docs", 0.82)
    if any(keyword in text for keyword in delete_keywords) and any(
        keyword in text for keyword in ticket_keywords
    ):
        return Intent("delete_jira_ticket", 0.9)
    if any(keyword in text for keyword in update_keywords) and any(
        keyword in text for keyword in ticket_keywords
    ):
        return Intent("update_jira_ticket", 0.88)
    if any(keyword in text for keyword in ticket_keywords):
        return Intent("create_jira_ticket", 0.85)
    if any(keyword in text for keyword in employee_keywords):
        return Intent("fetch_employee", 0.8)
    if any(keyword in text for keyword in knowledge_keywords):
        return Intent("read_meeting_docs", 0.75)

    return Intent("general_answer", 0.4)


def _is_jira_ticket_read_request(text: str) -> bool:
    read_verbs = ("list", "show", "provide", "get", "fetch", "display", "what are", "any")
    ticket_terms = ("ticket", "tickets", "jira", "issue", "issues")
    create_terms = ("create", "open", "make", "raise", "file")

    if any(term in text for term in create_terms):
        return False

    if any(verb in text for verb in read_verbs) and any(term in text for term in ticket_terms):
        return True

    if "related to this meeting" in text and any(term in text for term in ticket_terms):
        return True

    return False


def extract_ticket_details(question: str) -> tuple[str | None, str | None, str]:
    text = question.strip()
    lowered = text.lower()

    priority = "Medium"
    if "urgent" in lowered or "severity 1" in lowered or "sev1" in lowered:
        priority = "High"
    elif "low priority" in lowered:
        priority = "Low"

    weak_requests = {"create ticket", "create a ticket", "open ticket", "open a ticket"}
    normalized = lowered.replace(".", "").strip()
    if normalized in weak_requests:
        return None, None, priority

    cleaned = text
    for phrase in [
        "create a jira ticket for",
        "create jira ticket for",
        "create a ticket for",
        "create ticket for",
        "open a ticket for",
        "open ticket for",
        "create a ticket",
        "create ticket",
        "open a ticket",
        "open ticket",
    ]:
        if cleaned.lower().startswith(phrase):
            cleaned = cleaned[len(phrase) :].strip(" :-")
            break

    if len(cleaned.split()) < 3:
        return None, None, priority

    summary = cleaned[:80].rstrip(".")
    description = f"User request captured by AI Enterprise Assistant: {text}"
    return summary, description, priority


def extract_ticket_id(question: str) -> str | None:
    for token in question.replace(".", " ").replace(",", " ").split():
        cleaned = token.strip().upper()
        if "-" not in cleaned:
            continue
        prefix, number = cleaned.split("-", 1)
        if prefix.isalpha() and number.replace("_", "").isalnum():
            return cleaned
    return None


def extract_requested_date(question: str) -> str | None:
    from app.utils.date_resolver import resolve_date

    return resolve_date(question)


def extract_update_summary(question: str, ticket_id: str) -> str | None:
    lowered = question.lower()
    markers = ["to say", "to", "with", "summary"]
    for marker in markers:
        marker_text = f" {marker} "
        if marker_text in lowered:
            candidate = question[lowered.index(marker_text) + len(marker_text) :].strip(" .")
            if candidate and ticket_id.lower() not in candidate.lower():
                return candidate[:80]
    return None
