from fastapi.testclient import TestClient

from app.main import app, assistant
from app.services.jira_service import JiraService


client = TestClient(app)


CONFLUENCE_DOC = {
    "id": "conf-page-1001",
    "date": "2026-07-01",
    "title": "Engineering Daily Standup",
    "attendees": ["Daniel Chen", "Priya Sharma", "Maya Johnson"],
    "content": (
        "# Engineering Daily Standup\n\n"
        "Date: 2026-07-01\n"
        "Attendees: Daniel Chen, Priya Sharma, Maya Johnson\n\n"
        "## Issues Addressed\n\n"
        "- Checkout payments showed intermittent failures in the US region.\n"
        "- The failure rate was highest for saved-card transactions.\n\n"
        "## Action Items\n\n"
        "- Create a high-priority Jira ticket for payment gateway investigation.\n"
        "- Attach checkout error samples to the ticket.\n"
    ),
    "source": "confluence",
    "source_url": "https://example.atlassian.net/wiki/spaces/ENG/pages/1001",
}


EMPLOYEE_DOC = {
    "id": "conf-page-2001",
    "date": "unknown",
    "title": "Employee Profile - Priya Sharma",
    "attendees": [],
    "content": (
        "# Employee Profile - Priya Sharma\n\n"
        "Role: Product Manager\n"
        "Department: Product\n"
        "Location: Bengaluru\n"
        "Manager: Amit Rao\n"
        "Email: priya.sharma@example-enterprise.com\n"
    ),
    "source": "confluence",
    "source_url": "https://example.atlassian.net/wiki/spaces/HR/pages/2001",
}


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_validation_rejects_empty_question() -> None:
    response = client.post("/ask", json={"question": "   "})

    assert response.status_code == 422


def test_rag_reads_confluence_context(monkeypatch) -> None:
    async def fake_get_documents():
        return [CONFLUENCE_DOC]

    monkeypatch.setattr(assistant.confluence_service, "get_meeting_documents", fake_get_documents)

    response = client.post(
        "/ask",
        json={
            "question": "What issue was addressed about checkout payments in the meeting?",
            "conversation_id": "rag-test",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "read_meeting_docs"
    assert body["source"] == "rag"
    assert "Checkout payments" in body["answer"]


def test_employee_lookup_comes_from_confluence(monkeypatch) -> None:
    async def fake_get_documents():
        return [EMPLOYEE_DOC]

    monkeypatch.setattr(assistant.confluence_service, "get_meeting_documents", fake_get_documents)

    response = client.post(
        "/ask",
        json={"question": "Fetch employee information for Priya Sharma"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "read_meeting_docs"
    assert "Priya Sharma" in body["answer"]


def test_email_in_question_creates_ticket_from_context(monkeypatch) -> None:
    async def fake_get_documents():
        return [CONFLUENCE_DOC]

    async def fake_create_ticket(summary, description, priority="Medium", issue_type=None):
        resolved_issue_type = issue_type or JiraService().infer_issue_type(summary, description)
        return {
            "ticket_id": "SCRUM-789",
            "ticket_url": "https://example.atlassian.net/browse/SCRUM-789",
            "summary": summary,
            "description": description,
            "priority": priority,
            "issue_type": resolved_issue_type,
            "mode": "jira",
        }

    monkeypatch.setattr(assistant.confluence_service, "get_meeting_documents", fake_get_documents)
    monkeypatch.setattr(assistant.jira_service, "create_ticket", fake_create_ticket)

    first = client.post(
        "/ask",
        json={
            "question": "Summarize the meeting log about checkout payments",
            "conversation_id": "email-in-text-test",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/ask",
        json={
            "question": (
                "Create a Jira ticket from this, my email is daniel.chen@example-enterprise.com"
            ),
            "conversation_id": "email-in-text-test",
        },
    )

    assert second.status_code == 200
    body = second.json()
    assert body["action"] == "create_jira_ticket"


def test_follow_up_email_reply_resumes_ticket_creation(monkeypatch) -> None:
    async def fake_get_documents():
        return [CONFLUENCE_DOC]

    async def fake_create_ticket(summary, description, priority="Medium", issue_type=None):
        return {
            "ticket_id": "SCRUM-999",
            "ticket_url": "https://example.atlassian.net/browse/SCRUM-999",
            "summary": summary,
            "description": description,
            "priority": priority,
            "issue_type": "Bug",
            "mode": "jira",
        }

    monkeypatch.setattr(assistant.confluence_service, "get_meeting_documents", fake_get_documents)
    monkeypatch.setattr(assistant.jira_service, "create_ticket", fake_create_ticket)

    client.post(
        "/ask",
        json={
            "question": "Summarize the meeting log about checkout payments",
            "conversation_id": "follow-up-email-test",
        },
    )

    clarify = client.post(
        "/ask",
        json={
            "question": "Create a Jira ticket from this",
            "conversation_id": "follow-up-email-test",
        },
    )
    assert clarify.status_code == 200
    assert clarify.json()["action"] == "needs_clarification"

    resumed = client.post(
        "/ask",
        json={
            "question": "Sure, here is my mail daniel.chen@example-enterprise.com",
            "conversation_id": "follow-up-email-test",
        },
    )

    assert resumed.status_code == 200
    body = resumed.json()
    assert body["action"] == "create_jira_ticket"
    assert body["data"]["ticket"]["ticket_id"] == "SCRUM-999"


def test_email_reply_does_not_trigger_employee_lookup(monkeypatch) -> None:
    async def fake_get_documents():
        return [EMPLOYEE_DOC, CONFLUENCE_DOC]

    monkeypatch.setattr(assistant.confluence_service, "get_meeting_documents", fake_get_documents)

    client.post(
        "/ask",
        json={
            "question": "Summarize checkout payment meeting issues",
            "conversation_id": "no-employee-rag-test",
        },
    )

    response = client.post(
        "/ask",
        json={
            "question": "Sure here is my email daniel.chen@example-enterprise.com",
            "conversation_id": "no-employee-rag-test",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] != "read_meeting_docs" or "Employee Profile" not in body.get("answer", "")


def test_full_conversation_summarize_then_ticket_then_email(monkeypatch) -> None:
    """Q1 summarize → Q2 create ticket for it → Q3 here is my mail → ticket created."""
    async def fake_get_documents():
        return [CONFLUENCE_DOC, EMPLOYEE_DOC]

    async def fake_create_ticket(summary, description, priority="Medium", issue_type=None):
        return {
            "ticket_id": "SCRUM-100",
            "ticket_url": "https://example.atlassian.net/browse/SCRUM-100",
            "summary": summary,
            "description": description,
            "priority": priority,
            "issue_type": issue_type or "Bug",
            "mode": "jira",
        }

    monkeypatch.setattr(assistant.confluence_service, "get_meeting_documents", fake_get_documents)
    monkeypatch.setattr(assistant.jira_service, "create_ticket", fake_create_ticket)

    conv = "full-flow-test"

    q1 = client.post(
        "/ask",
        json={"question": "Summarize the meeting log about checkout payments", "conversation_id": conv},
    )
    assert q1.status_code == 200
    assert q1.json()["action"] == "read_meeting_docs"

    q2 = client.post(
        "/ask",
        json={"question": "Can you create a ticket for it", "conversation_id": conv},
    )
    assert q2.status_code == 200
    assert q2.json()["action"] == "needs_clarification"
    assert q2.json()["data"]["conversation_stage"] == "awaiting_user_email"

    q3 = client.post(
        "/ask",
        json={
            "question": "Sure here is my mail daniel.chen@example-enterprise.com",
            "conversation_id": conv,
        },
    )
    assert q3.status_code == 200
    body = q3.json()
    assert body["action"] == "create_jira_ticket"
    assert "Got your email" in body["answer"]
    assert "Employee Profile" not in body["answer"]


def test_whose_mail_triggers_employee_lookup(monkeypatch) -> None:
    async def fake_get_documents():
        return [EMPLOYEE_DOC]

    monkeypatch.setattr(assistant.confluence_service, "get_meeting_documents", fake_get_documents)

    response = client.post(
        "/ask",
        json={
            "question": "Whose mail is priya.sharma@example-enterprise.com?",
            "conversation_id": "employee-mail-lookup",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "read_meeting_docs"
    assert "Priya Sharma" in body["answer"]


def test_create_ticket_from_this_uses_conversation_memory(monkeypatch) -> None:
    async def fake_get_documents():
        return [CONFLUENCE_DOC]

    async def fake_create_ticket(summary, description, priority="Medium", issue_type=None):
        resolved_issue_type = issue_type or JiraService().infer_issue_type(summary, description)
        return {
            "ticket_id": "SCRUM-123",
            "ticket_url": "https://example.atlassian.net/browse/SCRUM-123",
            "summary": summary,
            "description": description,
            "priority": priority,
            "issue_type": resolved_issue_type,
            "mode": "jira",
        }

    monkeypatch.setattr(assistant.confluence_service, "get_meeting_documents", fake_get_documents)
    monkeypatch.setattr(assistant.jira_service, "create_ticket", fake_create_ticket)

    first = client.post(
        "/ask",
        json={
            "question": "Summarize the meeting log about checkout payments",
            "conversation_id": "follow-up-test",
        },
    )
    assert first.status_code == 200
    assert first.json()["action"] == "read_meeting_docs"

    second = client.post(
        "/ask",
        json={
            "question": "Create a Jira ticket from this",
            "user_email": "daniel.chen@example-enterprise.com",
            "conversation_id": "follow-up-test",
        },
    )

    assert second.status_code == 200
    body = second.json()
    assert body["action"] == "create_jira_ticket"
    assert body["data"]["source_document"]["id"] == "conf-page-1001"
    assert body["data"]["ticket"]["issue_type"] == "Bug"


def test_write_action_requires_user_email() -> None:
    response = client.post(
        "/ask",
        json={"question": "Create a Jira ticket for checkout payment failures"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "needs_clarification"
    assert "user_email" in body["data"]["missing_fields"]


def test_jira_issue_type_inference() -> None:
    service = JiraService()

    assert service.infer_issue_type("API timeout errors", "release smoke tests failed") == "Bug"
    assert service.infer_issue_type("CRM cleanup", "Create a service request for cleanup") == "Service Request"
    assert service.infer_issue_type("Missing laptop", "Security could not confirm owner") == "Incident"
    assert service.infer_issue_type("Follow up", "Review onboarding status") == "Task"


# --- New tests for date-aware RAG and LLM polish ---


INDEX_DOC = {
    "id": "conf-page-index",
    "date": "unknown",
    "title": "Meeting Log Index",
    "attendees": [],
    "parent_id": "1277953",
    "content": (
        "# Meeting Log Index\n\n"
        "## Usage Notes\n\n"
        "Use this index when a user asks about a meeting.\n\n"
        "## Meeting Log\n\n"
        "2026-07-01 | Engineering Daily Standup | Checkout payment failures | "
        "Create Jira ticket | High\n"
        "2026-07-03 | Product Sync | Roadmap review | None | Low\n"
    ),
    "source": "confluence",
    "source_url": "https://example.atlassian.net/wiki/spaces/ENG/pages/index",
}


CUSTOMER_ESCALATION_DOC = {
    "id": "conf-page-1002",
    "date": "2026-07-02",
    "title": "Customer Escalation Review",
    "attendees": ["Maya Johnson", "Priya Sharma"],
    "parent_id": "1277953",
    "content": (
        "# Customer Escalation Review\n\n"
        "Date: 2026-07-02\n"
        "Attendees: Maya Johnson, Priya Sharma\n\n"
        "## Issues Addressed\n\n"
        "- Acme Corp reported slow dashboard loading after the analytics release.\n\n"
        "## Action Items\n\n"
        "- Create a customer-impact ticket with dashboard latency details.\n"
    ),
    "source": "confluence",
    "source_url": "https://example.atlassian.net/wiki/spaces/ENG/pages/1002",
}


def test_rag_date_query_not_usage_notes(monkeypatch) -> None:
    """Answer for a date-based meeting query must not contain index usage notes."""

    async def fake_get_documents():
        return [INDEX_DOC, CONFLUENCE_DOC]

    async def fake_get_by_date(date_str):
        return [doc for doc in [INDEX_DOC, CONFLUENCE_DOC] if doc["date"] == date_str]

    monkeypatch.setattr(assistant.confluence_service, "get_meeting_documents", fake_get_documents)
    monkeypatch.setattr(assistant.confluence_service, "get_meeting_docs_by_date", fake_get_by_date)

    response = client.post(
        "/ask",
        json={
            "question": "Can you summarize the meeting on 2026-07-01",
            "conversation_id": "date-summary-test",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "read_meeting_docs"
    assert "Use this index" not in body["answer"]
    # Should reference the actual meeting content, not the index meta-text
    assert "Checkout" in body["answer"] or "payment" in body["answer"].lower()


OPERATIONS_SYNC_DOC = {
    "id": "conf-page-1003",
    "date": "2026-07-03",
    "title": "Operations Sync",
    "parent_id": "1277953",
    "attendees": ["Daniel Chen", "Maya Johnson"],
    "content": (
        "# Operations Sync\n\n"
        "Date: 2026-07-03\n"
        "Attendees: Daniel Chen, Maya Johnson\n\n"
        "## Issues Addressed\n\n"
        "- VPN login failures increased after the MFA policy rollout.\n\n"
        "## Action Items\n\n"
        "- Review the VPN profile reset process.\n"
    ),
    "source": "confluence",
    "source_url": "https://example.atlassian.net/wiki/spaces/ENG/pages/1003",
}


def test_rag_natural_language_date_july_3_user_wording(monkeypatch) -> None:
    """Exact user wording with '03 July 2026' must return VPN meeting summary."""

    async def fake_get_documents():
        return [OPERATIONS_SYNC_DOC]

    monkeypatch.setattr(assistant.confluence_service, "get_meeting_documents", fake_get_documents)

    response = client.post(
        "/ask",
        json={
            "question": "Can you summaries me the meeting from happened on 03 July 2026?",
            "conversation_id": "july-3-test",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "read_meeting_docs"
    assert "VPN" in body["answer"] or "vpn" in body["answer"].lower()


def test_rag_natural_language_date_july_2(monkeypatch) -> None:
    """'02 July 2026' resolves to the correct meeting summary."""

    async def fake_get_documents():
        return [INDEX_DOC, CUSTOMER_ESCALATION_DOC]

    monkeypatch.setattr(assistant.confluence_service, "get_meeting_documents", fake_get_documents)

    response = client.post(
        "/ask",
        json={
            "question": "Give the meeting summary for the date 02 July 2026",
            "conversation_id": "july-2-test",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "read_meeting_docs"
    assert "Use this index" not in body["answer"]
    assert "dashboard" in body["answer"].lower() or "Acme" in body["answer"]


def test_jira_description_not_full_content(monkeypatch) -> None:
    """Jira ticket description from meeting context must be concise (<500 chars)."""

    async def fake_get_documents():
        return [CONFLUENCE_DOC]

    async def fake_create_ticket(summary, description, priority="Medium", issue_type=None):
        resolved_issue_type = issue_type or JiraService().infer_issue_type(summary, description)
        return {
            "ticket_id": "SCRUM-456",
            "ticket_url": "https://example.atlassian.net/browse/SCRUM-456",
            "summary": summary,
            "description": description,
            "priority": priority,
            "issue_type": resolved_issue_type,
            "mode": "jira",
        }

    monkeypatch.setattr(assistant.confluence_service, "get_meeting_documents", fake_get_documents)
    monkeypatch.setattr(assistant.jira_service, "create_ticket", fake_create_ticket)

    # Step 1: Prime the memory
    first = client.post(
        "/ask",
        json={
            "question": "Summarize the meeting log about checkout payments",
            "conversation_id": "jira-desc-test",
        },
    )
    assert first.status_code == 200

    # Step 2: Create ticket from context
    second = client.post(
        "/ask",
        json={
            "question": "Create a Jira ticket from this",
            "user_email": "test@example.com",
            "conversation_id": "jira-desc-test",
        },
    )

    assert second.status_code == 200
    body = second.json()
    assert body["action"] == "create_jira_ticket"
    description = body["data"]["ticket"]["description"]
    assert len(description) < 500, f"Description too long: {len(description)} chars"


def test_guardrail_create_ticket_needs_clarification() -> None:
    """'Create a ticket' without context must return needs_clarification."""
    response = client.post(
        "/ask",
        json={
            "question": "Create a ticket please",
            "user_email": "test@example.com",
            "conversation_id": "guardrail-test",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "needs_clarification"

