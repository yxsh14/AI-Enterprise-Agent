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
