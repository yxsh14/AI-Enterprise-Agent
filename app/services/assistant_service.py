from app.schemas import AskResponse
from app.services.confluence_service import ConfluenceService
from app.services.jira_service import JiraService
from app.services.llm_service import LLMService
from app.services.memory_service import MemoryService
from app.services.rag_service import RagService
from app.core.errors import IntegrationError
from app.utils.intent import (
    detect_intent,
    extract_requested_date,
    extract_ticket_details,
    extract_ticket_id,
    extract_update_summary,
)


class AssistantService:
    def __init__(self) -> None:
        self.confluence_service = ConfluenceService()
        self.jira_service = JiraService()
        self.llm_service = LLMService()
        self.memory_service = MemoryService()
        self.rag_service = RagService()

    async def handle_question(
        self,
        question: str,
        user_email: str | None = None,
        conversation_id: str | None = None,
    ) -> AskResponse:
        memory_key = self.memory_service.get_key(conversation_id, user_email)
        intent_name = await self._resolve_intent_name(question)

        try:
            if intent_name == "create_jira_ticket":
                return await self._handle_ticket_request(question, user_email, memory_key)

            if intent_name == "update_jira_ticket":
                return await self._handle_ticket_update(question, user_email)

            if intent_name == "delete_jira_ticket":
                return await self._handle_ticket_delete(question, user_email)

            if intent_name in {"fetch_employee", "read_meeting_docs"}:
                return await self._handle_rag_question(question, memory_key)
        except IntegrationError as exc:
            return AskResponse(
                answer=str(exc),
                action="integration_error",
                data={"error_type": exc.__class__.__name__},
            )

        return AskResponse(
            answer=(
                "I can help with enterprise support tasks such as creating Jira tickets, "
                "retrieving Confluence context, and creating follow-up Jira actions."
            ),
            action="answer",
            data={"supported_tools": ["jira", "confluence_rag"]},
        )

    async def _resolve_intent_name(self, question: str) -> str:
        llm_plan = await self.llm_service.plan_tool_call(question)
        if llm_plan is not None and llm_plan.tool_name in {
            "create_jira_ticket",
            "update_jira_ticket",
            "delete_jira_ticket",
            "read_meeting_docs",
            "fetch_employee",
        }:
            return llm_plan.tool_name

        return detect_intent(question).name

    async def _handle_ticket_request(
        self,
        question: str,
        user_email: str | None,
        memory_key: str,
    ) -> AskResponse:
        identity_guardrail = self._require_user_identity(user_email, "create a Jira ticket")
        if identity_guardrail is not None:
            return identity_guardrail

        meeting_ticket = await self._maybe_create_ticket_from_confluence_context(question, memory_key)
        if meeting_ticket is not None:
            return meeting_ticket

        summary, description, priority = extract_ticket_details(question)

        if not summary or not description:
            return AskResponse(
                answer="I can create a Jira ticket, but I need a short description of the issue first.",
                action="needs_clarification",
                data={"missing_fields": ["issue_description"]},
            )

        ticket = await self.jira_service.create_ticket(
            summary=summary,
            description=description,
            priority=priority,
        )

        return AskResponse(
            answer=(
                f"Created Jira ticket {ticket['ticket_id']} with {priority.lower()} priority: "
                f"{ticket['summary']}. Requested by {user_email}."
            ),
            action="create_jira_ticket",
            data=ticket,
            source="jira",
        )

    async def _handle_ticket_update(self, question: str, user_email: str | None) -> AskResponse:
        identity_guardrail = self._require_user_identity(user_email, "update a Jira ticket")
        if identity_guardrail is not None:
            return identity_guardrail

        ticket_id = extract_ticket_id(question)
        if ticket_id is None:
            return AskResponse(
                answer="I can update a Jira ticket, but I need the ticket ID, for example HELP-123.",
                action="needs_clarification",
                data={"missing_fields": ["ticket_id"]},
            )

        summary = extract_update_summary(question, ticket_id)
        if summary is None:
            return AskResponse(
                answer="I found the ticket ID, but I need what should be updated.",
                action="needs_clarification",
                data={"missing_fields": ["update_description"]},
            )

        ticket = await self.jira_service.update_ticket(ticket_id=ticket_id, summary=summary)
        return AskResponse(
            answer=f"Updated Jira ticket {ticket_id}. Requested by {user_email}.",
            action="update_jira_ticket",
            data=ticket,
            source="jira",
        )

    async def _handle_ticket_delete(self, question: str, user_email: str | None) -> AskResponse:
        identity_guardrail = self._require_user_identity(user_email, "delete a Jira ticket")
        if identity_guardrail is not None:
            return identity_guardrail

        ticket_id = extract_ticket_id(question)
        if ticket_id is None:
            return AskResponse(
                answer="I can delete a Jira ticket, but I need the ticket ID, for example HELP-123.",
                action="needs_clarification",
                data={"missing_fields": ["ticket_id"]},
            )

        ticket = await self.jira_service.delete_ticket(ticket_id)
        return AskResponse(
            answer=f"Deleted Jira ticket {ticket_id}. Requested by {user_email}.",
            action="delete_jira_ticket",
            data=ticket,
            source="jira",
        )

    async def _handle_rag_question(self, question: str, memory_key: str) -> AskResponse:
        requested_date = extract_requested_date(question)
        documents = (
            await self.confluence_service.get_meeting_docs_by_date(requested_date)
            if requested_date
            else await self.confluence_service.get_meeting_documents()
        )
        results = self.rag_service.retrieve(question, documents)
        if not results:
            return AskResponse(
                answer="I could not find relevant Confluence context. Please add a date, topic, employee name, or issue.",
                action="needs_clarification",
                data={"missing_fields": ["date_or_topic"]},
            )

        fallback_answer = self.rag_service.build_answer(question, results)
        answer, answer_mode = await self.llm_service.answer_with_context(
            question=question,
            context_chunks=results,
            fallback_answer=fallback_answer,
        )

        remembered_documents = []
        for result in results:
            document = result["document"]
            if document not in remembered_documents:
                remembered_documents.append(document)
        self.memory_service.remember_documents(memory_key, remembered_documents, results)

        return AskResponse(
            answer=answer,
            action="read_meeting_docs",
            data={
                "retrieved_context": results,
                "answer_mode": answer_mode,
                "conversation_id": memory_key,
            },
            source="rag",
        )

    async def _maybe_create_ticket_from_confluence_context(
        self,
        question: str,
        memory_key: str,
    ) -> AskResponse | None:
        if not self._is_contextual_ticket_request(question):
            return None

        requested_date = extract_requested_date(question)
        if requested_date:
            documents = await self.confluence_service.get_meeting_docs_by_date(requested_date)
        elif self._uses_follow_up_reference(question):
            documents = self.memory_service.get_last_documents(memory_key)
        else:
            documents = await self.confluence_service.get_meeting_documents()

        if not documents:
            return AskResponse(
                answer=(
                    "I can create a Jira ticket from the previous Confluence context, "
                    "but I do not have a previous document in this conversation yet."
                ),
                action="needs_clarification",
                data={"missing_fields": ["confluence_context"]},
            )

        results = self.rag_service.retrieve(question, documents)
        if not results:
            last_context = self.memory_service.get_last_context(memory_key)
            results = last_context if self._uses_follow_up_reference(question) else []

        if not results:
            return AskResponse(
                answer="I can create a ticket from Confluence context, but I could not find the relevant document.",
                action="needs_clarification",
                data={"missing_fields": ["meeting_date_or_topic"]},
            )

        doc = results[0]["document"]
        summary = self.rag_service.extract_action_summary(doc)

        ticket = await self.jira_service.create_ticket(
            summary=summary[:80],
            description=f"Created from Confluence meeting doc {doc['id']}: {doc['content']}",
            priority=self._priority_from_document(doc),
        )

        return AskResponse(
            answer=f"Created Jira ticket {ticket['ticket_id']} from Confluence page {doc['title']}.",
            action="create_jira_ticket",
            data={"ticket": ticket, "source_document": doc},
            source="jira",
        )

    def _priority_from_document(self, document: dict) -> str:
        content = document["content"].lower()
        if "high priority" in content or "high-priority" in content or "revenue" in content:
            return "High"
        if "failed smoke tests" in content or "block production release" in content:
            return "High"
        if "release candidate failed" in content or "before release approval" in content:
            return "High"
        if "low priority" in content:
            return "Low"
        return "Medium"

    def _require_user_identity(self, user_email: str | None, action: str) -> AskResponse | None:
        if user_email:
            return None
        return AskResponse(
            answer=f"Please provide user_email so I can audit who requested to {action}.",
            action="needs_clarification",
            data={"missing_fields": ["user_email"], "guardrail": "write_action_identity_required"},
        )

    def _is_contextual_ticket_request(self, question: str) -> bool:
        text = question.lower()
        return any(keyword in text for keyword in ["meeting", "confluence", "from this", "from it", "from that"])

    def _uses_follow_up_reference(self, question: str) -> bool:
        text = question.lower()
        return any(keyword in text for keyword in ["this", "that", "it", "above", "previous"])
