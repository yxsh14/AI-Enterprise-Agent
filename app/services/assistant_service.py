from app.schemas import AskResponse
from app.services.confluence_service import ConfluenceService
from app.services.conversation_router import (
    is_employee_lookup_question,
    is_jira_ticket_read_question,
    is_ticket_continuation,
    resolve_fresh_intent,
)
from app.services.jira_service import JiraService
from app.services.llm_service import LLMService
from app.services.memory_service import MemoryService
from app.services.rag_service import RagService
from app.core.errors import IntegrationError
from app.utils.date_resolver import resolve_date
from app.utils.email_extractor import extract_email_from_text
from app.utils.intent import (
    extract_ticket_details,
    extract_ticket_id,
    extract_update_summary,
)

_MEETING_FOLDER_ID = "1277953"
_EMPLOYEE_FOLDER_ID = "1179656"
_POLICY_FOLDER_ID = "1638401"


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
        effective_email = self._resolve_user_email(user_email, question)
        memory_key = self.memory_service.get_key(conversation_id, effective_email)
        state = self.memory_service.get_state(memory_key)

        try:
            # Step 1 — Active dialogue: slot-filling always wins over fresh intent.
            if state.is_active:
                if is_jira_ticket_read_question(question):
                    self.memory_service.clear_dialogue(memory_key)
                    return await self._handle_jira_ticket_read(question, memory_key)

                active_response = await self._handle_active_dialogue(
                    question=question,
                    user_email=effective_email,
                    memory_key=memory_key,
                    state=state,
                )
                if active_response is not None:
                    return active_response

            # Step 2 — Continuation without explicit pending stage (e.g. "create ticket for it").
            if is_ticket_continuation(question, self.memory_service.has_meeting_context(memory_key)):
                return await self._handle_ticket_request(
                    question, effective_email, memory_key
                )

            # Step 3 — Fresh turn: LLM tool pick, then regex intent fallback.
            intent_name = await self._resolve_fresh_intent(question)

            if intent_name == "create_jira_ticket":
                return await self._handle_ticket_request(question, effective_email, memory_key)

            if intent_name == "update_jira_ticket":
                return await self._handle_ticket_update(question, effective_email, memory_key)

            if intent_name == "delete_jira_ticket":
                return await self._handle_ticket_delete(question, effective_email, memory_key)

            if intent_name == "list_jira_tickets":
                return await self._handle_jira_ticket_read(question, memory_key)

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

    async def _handle_active_dialogue(
        self,
        question: str,
        user_email: str | None,
        memory_key: str,
        state,
    ) -> AskResponse | None:
        if state.is_awaiting_email:
            email = user_email or extract_email_from_text(question)
            if email:
                pending_question = state.pending_question or "Create a Jira ticket from this"
                self.memory_service.clear_dialogue(memory_key)
                response = await self._handle_ticket_request(
                    pending_question, email, memory_key
                )
                if response.action == "create_jira_ticket":
                    response.answer = (
                        f"Got your email ({email}). {response.answer}"
                    )
                return response

            return AskResponse(
                answer=(
                    "I still need your email to create the Jira ticket. "
                    "Reply with: 'Here is my email you@company.com'."
                ),
                action="needs_clarification",
                data={
                    "missing_fields": ["user_email"],
                    "conversation_stage": state.stage,
                },
            )

        if state.stage == "awaiting_ticket_id":
            ticket_id = extract_ticket_id(question)
            if ticket_id and user_email:
                self.memory_service.clear_dialogue(memory_key)
                pending = state.pending_question or question
                return await self._handle_ticket_update(
                    f"Update ticket {ticket_id} {pending}", user_email, memory_key
                )

        if state.stage == "awaiting_issue_description":
            if user_email:
                self.memory_service.clear_dialogue(memory_key)
                combined = f"Create a Jira ticket for {question}"
                return await self._handle_ticket_request(combined, user_email, memory_key)

        return None

    async def _resolve_fresh_intent(self, question: str) -> str:
        llm_plan = await self.llm_service.plan_tool_call(question)
        if llm_plan is not None and llm_plan.tool_name in {
            "create_jira_ticket",
            "update_jira_ticket",
            "delete_jira_ticket",
            "list_jira_tickets",
            "read_meeting_docs",
            "fetch_employee",
        }:
            return llm_plan.tool_name

        return resolve_fresh_intent(question)

    async def _handle_jira_ticket_read(self, question: str, memory_key: str) -> AskResponse:
        jql = await self._build_ticket_read_jql(question, memory_key)
        result = await self.jira_service.search_tickets(jql=jql, max_results=10)
        tickets = result["tickets"]

        if not tickets:
            return AskResponse(
                answer="I could not find any Jira tickets matching that request.",
                action="list_jira_tickets",
                data=result,
                source="jira",
            )

        ticket_lines = [
            f"{ticket['ticket_id']} [{ticket['status']}] {ticket['summary']}"
            for ticket in tickets
        ]
        return AskResponse(
            answer="Here are the matching Jira tickets:\n" + "\n".join(ticket_lines),
            action="list_jira_tickets",
            data=result,
            source="jira",
        )

    async def _build_ticket_read_jql(self, question: str, memory_key: str) -> str:
        text = question.lower()
        base = f"project = {self.jira_service.project_key}"

        if any(phrase in text for phrase in ["this meeting", "that meeting", "related to this", "related to it", "related to meeting"]):
            resolved_date = resolve_date(question)
            if resolved_date:
                all_docs = await self.confluence_service.get_meeting_documents()
                dated_docs = [
                    doc
                    for doc in all_docs
                    if doc.get("date") == resolved_date
                    and doc.get("parent_id") == _MEETING_FOLDER_ID
                    and "meeting log index" not in doc.get("title", "").lower()
                ]
                terms = self._ticket_search_terms_from_documents(dated_docs)
                if terms:
                    clauses = [f'text ~ "{term}"' for term in terms]
                    return f"{base} AND ({' OR '.join(clauses)}) ORDER BY created DESC"

            terms = self._ticket_search_terms_from_memory(memory_key)
            if terms:
                clauses = [f'text ~ "{term}"' for term in terms]
                return f"{base} AND ({' OR '.join(clauses)}) ORDER BY created DESC"

        ticket_id = extract_ticket_id(question)
        if ticket_id:
            return f"issue = {ticket_id}"

        return f"{base} ORDER BY created DESC"

    def _ticket_search_terms_from_documents(self, documents: list[dict]) -> list[str]:
        terms = []
        for doc in documents[:2]:
            for phrase in self._ticket_search_terms_from_document(doc):
                cleaned = phrase.strip(" .")
                if cleaned:
                    terms.append(cleaned[:70])
        return terms[:3]

    def _ticket_search_terms_from_memory(self, memory_key: str) -> list[str]:
        docs = self.memory_service.get_last_documents(memory_key)
        if not docs:
            return []

        terms = []
        for doc in docs[:2]:
            for phrase in self._ticket_search_terms_from_document(doc):
                cleaned = phrase.strip(" .")
                if cleaned:
                    terms.append(cleaned[:70])
        return terms[:3]

    def _ticket_search_terms_from_document(self, document: dict) -> list[str]:
        content = document.get("content", "")
        lowered = content.lower()
        terms = []

        known_phrases = [
            "staging api timeout",
            "cache invalidation",
            "failed smoke tests",
            "payment gateway investigation",
            "checkout error samples",
            "vpn profile reset",
            "dashboard latency",
            "crm duplicate account cleanup",
            "missing laptop",
        ]
        terms.extend(phrase for phrase in known_phrases if phrase in lowered)

        action_summary = self.rag_service.extract_action_summary(document)
        if action_summary:
            terms.append(action_summary)

        title = document.get("title", "")
        if title:
            terms.append(title)

        return terms

    async def _handle_ticket_request(
        self,
        question: str,
        user_email: str | None,
        memory_key: str,
    ) -> AskResponse:
        identity_guardrail = self._require_user_identity(
            user_email, "create a Jira ticket", memory_key, question
        )
        if identity_guardrail is not None:
            return identity_guardrail

        meeting_ticket = await self._maybe_create_ticket_from_confluence_context(
            question, memory_key
        )
        if meeting_ticket is not None:
            self.memory_service.clear_dialogue(memory_key)
            return meeting_ticket

        summary, description, priority = extract_ticket_details(question)

        if not summary or not description:
            self.memory_service.set_awaiting_issue_description(memory_key, question)
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
        self.memory_service.clear_dialogue(memory_key)

        return AskResponse(
            answer=(
                f"Created Jira ticket {ticket['ticket_id']} with {priority.lower()} priority: "
                f"{ticket['summary']}. Requested by {user_email}."
            ),
            action="create_jira_ticket",
            data=ticket,
            source="jira",
        )

    async def _handle_ticket_update(
        self, question: str, user_email: str | None, memory_key: str
    ) -> AskResponse:
        identity_guardrail = self._require_user_identity(
            user_email, "update a Jira ticket", memory_key, question
        )
        if identity_guardrail is not None:
            return identity_guardrail

        ticket_id = extract_ticket_id(question)
        if ticket_id is None:
            self.memory_service.set_awaiting_ticket_id(
                memory_key, "update_jira_ticket", question
            )
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
        self.memory_service.clear_dialogue(memory_key)
        return AskResponse(
            answer=f"Updated Jira ticket {ticket_id}. Requested by {user_email}.",
            action="update_jira_ticket",
            data=ticket,
            source="jira",
        )

    async def _handle_ticket_delete(
        self, question: str, user_email: str | None, memory_key: str
    ) -> AskResponse:
        identity_guardrail = self._require_user_identity(
            user_email, "delete a Jira ticket", memory_key, question
        )
        if identity_guardrail is not None:
            return identity_guardrail

        ticket_id = extract_ticket_id(question)
        if ticket_id is None:
            self.memory_service.set_awaiting_ticket_id(
                memory_key, "delete_jira_ticket", question
            )
            return AskResponse(
                answer="I can delete a Jira ticket, but I need the ticket ID, for example HELP-123.",
                action="needs_clarification",
                data={"missing_fields": ["ticket_id"]},
            )

        ticket = await self.jira_service.delete_ticket(ticket_id)
        self.memory_service.clear_dialogue(memory_key)
        return AskResponse(
            answer=f"Deleted Jira ticket {ticket_id}. Requested by {user_email}.",
            action="delete_jira_ticket",
            data=ticket,
            source="jira",
        )

    async def _handle_rag_question(self, question: str, memory_key: str) -> AskResponse:
        if is_employee_lookup_question(question):
            intent_name = "fetch_employee"
        else:
            intent_name = "read_meeting_docs"

        resolved_date = resolve_date(question)
        all_documents = await self.confluence_service.get_meeting_documents()

        if resolved_date:
            documents = [doc for doc in all_documents if doc.get("date") == resolved_date]
            if not documents:
                return AskResponse(
                    answer=(
                        f"I could not find a meeting document for {resolved_date}. "
                        "Check the date format or try an explicit date such as 02 July 2026."
                    ),
                    action="needs_clarification",
                    data={"missing_fields": ["meeting_date"], "resolved_date": resolved_date},
                )
            documents = [
                doc for doc in documents if "meeting log index" not in doc.get("title", "").lower()
            ] or documents
        else:
            documents = self._filter_documents_for_intent(all_documents, intent_name, question)

        results = self.rag_service.retrieve(question, documents, resolved_date=resolved_date)

        if results:
            results = self.rag_service.resolve_meeting_from_index(
                question, results, all_documents, resolved_date
            )

        if not results:
            return AskResponse(
                answer="I could not find relevant Confluence context. Please add a date, topic, employee name, or issue.",
                action="needs_clarification",
                data={"missing_fields": ["date_or_topic"], "resolved_date": resolved_date},
            )

        fallback_answer = self.rag_service.build_answer(question, results)
        answer, answer_mode = await self.llm_service.answer_with_context(
            question=question,
            context_chunks=results,
            fallback_answer=fallback_answer,
            resolved_date=resolved_date,
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
                "resolved_date": resolved_date,
                "conversation_stage": "idle",
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

        requested_date = resolve_date(question)
        if requested_date:
            all_docs = await self.confluence_service.get_meeting_documents()
            documents = [doc for doc in all_docs if doc.get("date") == requested_date]
        elif self._uses_follow_up_reference(question):
            documents = self.memory_service.get_last_documents(memory_key)
        else:
            documents = self.memory_service.get_last_documents(memory_key)
            if not documents:
                return None

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
            results = last_context if self._uses_follow_up_reference(question) else last_context

        if not results:
            return AskResponse(
                answer="I can create a ticket from Confluence context, but I could not find the relevant document.",
                action="needs_clarification",
                data={"missing_fields": ["meeting_date_or_topic"]},
            )

        doc = results[0]["document"]
        summary = self.rag_service.extract_action_summary(doc)

        description = await self.llm_service.summarize_for_jira(
            context_chunks=results,
            question=question,
        )
        if not description:
            description = self.rag_service.build_ticket_description(doc)

        ticket = await self.jira_service.create_ticket(
            summary=summary[:80],
            description=description,
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

    def _resolve_user_email(self, user_email: str | None, question: str) -> str | None:
        if user_email:
            return user_email.strip().lower()
        return extract_email_from_text(question)

    def _require_user_identity(
        self,
        user_email: str | None,
        action: str,
        memory_key: str,
        question: str,
    ) -> AskResponse | None:
        if user_email:
            return None

        goal = (
            "create_jira_ticket_from_meeting"
            if self._is_contextual_ticket_request(question)
            else "create_jira_ticket"
        )
        self.memory_service.set_awaiting_email(memory_key, goal, question)

        return AskResponse(
            answer=(
                "Please share your email so I can create the Jira ticket. "
                "Reply with: 'Here is my email you@company.com'."
            ),
            action="needs_clarification",
            data={
                "missing_fields": ["user_email"],
                "conversation_stage": "awaiting_user_email",
                "guardrail": "write_action_identity_required",
            },
        )

    def _is_contextual_ticket_request(self, question: str) -> bool:
        text = question.lower()
        phrases = (
            "from this",
            "from it",
            "from that",
            "for it",
            "for this",
            "for that",
            "ticket for it",
            "ticket for this",
            "create a ticket for it",
            "create ticket for it",
            "meeting",
            "confluence",
        )
        return any(keyword in text for keyword in phrases)

    def _uses_follow_up_reference(self, question: str) -> bool:
        text = question.lower()
        return any(keyword in text for keyword in ["this", "that", "it", "above", "previous"])

    def _filter_documents_for_intent(
        self, documents: list[dict], intent_name: str, question: str
    ) -> list[dict]:
        text = question.lower()

        if intent_name == "fetch_employee" or any(
            kw in text for kw in ["employee", "profile", "who is"]
        ):
            target_folder = _EMPLOYEE_FOLDER_ID
        elif any(kw in text for kw in ["policy", "vpn", "process", "workflow"]):
            target_folder = _POLICY_FOLDER_ID
        elif any(kw in text for kw in ["meeting", "standup", "summarize", "sync notes"]):
            target_folder = _MEETING_FOLDER_ID
        else:
            return documents

        filtered = [doc for doc in documents if doc.get("parent_id") == target_folder]
        return filtered if filtered else documents
