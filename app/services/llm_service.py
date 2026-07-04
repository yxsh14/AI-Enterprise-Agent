from __future__ import annotations

from dataclasses import dataclass
import json

import httpx

from app.core.config import settings


@dataclass(frozen=True)
class ToolPlan:
    tool_name: str
    arguments: dict
    confidence: float


class LLMService:
    async def plan_tool_call(self, question: str) -> ToolPlan | None:
        if not settings.llm_is_configured:
            return None

        tools = [
            {
                "type": "function",
                "name": "create_jira_ticket",
                "description": "Create a Jira ticket from a user issue or retrieved meeting context.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "priority": {"type": "string", "enum": ["Low", "Medium", "High"]},
                    },
                    "required": ["summary"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "update_jira_ticket",
                "description": "Update an existing Jira ticket when a ticket key and update are provided.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "required": ["ticket_id", "summary"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "delete_jira_ticket",
                "description": "Delete an existing Jira ticket only when explicitly requested.",
                "parameters": {
                    "type": "object",
                    "properties": {"ticket_id": {"type": "string"}},
                    "required": ["ticket_id"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "list_jira_tickets",
                "description": "List or search Jira tickets without creating a new ticket.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "read_meeting_docs",
                "description": "Retrieve meeting documents or answer questions from meeting context.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "date": {"type": "string"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "fetch_employee",
                "description": "Fetch employee details from the enterprise directory.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        ]

        prompt = (
            "Choose the single safest tool for the user request. "
            "Never choose delete_jira_ticket unless the user explicitly asks to delete/remove a ticket. "
            "Use read_meeting_docs for questions about meeting issues, action items, or Confluence notes. "
            "If the user is only providing an email address to continue a previous ticket action, "
            "choose create_jira_ticket. "
            "The user may include their email inside the message text; treat that as identity for write actions.\n\n"
            f"User request: {question}"
        )

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.openai_model,
                        "input": prompt,
                        "tools": tools,
                        "tool_choice": "auto",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError:
            return None

        return self._extract_tool_plan(payload)

    async def answer_with_context(
        self,
        question: str,
        context_chunks: list[dict],
        fallback_answer: str,
        resolved_date: str | None = None,
    ) -> tuple[str, str]:
        """Synthesize a polished answer from RAG context using the LLM.

        Falls back to *fallback_answer* when the LLM is not configured or
        the API call fails.
        """
        if not settings.llm_is_configured:
            return fallback_answer, "deterministic_rag"

        context = "\n\n".join(
            f"Source: {chunk['document']['title']} ({chunk['document']['date']})\n{chunk['text']}"
            for chunk in context_chunks
        )

        date_hint = f"\nRequested meeting date: {resolved_date}" if resolved_date else ""

        prompt = (
            "You are an enterprise assistant. Answer using ONLY the provided context.\n\n"
            f"User question: {question}{date_hint}\n\n"
            "Rules:\n"
            "- If the user asks for a summary, write 3-5 clear sentences.\n"
            "- Include: meeting title, date, key issues, and action items.\n"
            "- Do NOT return index usage instructions or meta-documentation.\n"
            "- If context is insufficient, say what is missing.\n"
            "- Do not invent facts not in the context.\n\n"
            f"Context:\n{context}"
        )

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.openai_model,
                        "input": prompt,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError:
            return fallback_answer, "deterministic_rag_fallback"

        answer = self._extract_text(payload)
        return (answer or fallback_answer), "llm_rag"

    async def summarize_for_jira(
        self,
        context_chunks: list[dict],
        question: str = "",
    ) -> str | None:
        """Generate a concise Jira ticket description from meeting context.

        Returns ``None`` when the LLM is unavailable so the caller can fall
        back to a deterministic description.
        """
        if not settings.llm_is_configured:
            return None

        context = "\n\n".join(
            f"Source: {chunk['document']['title']} ({chunk['document']['date']})\n{chunk['text']}"
            for chunk in context_chunks
        )

        prompt = (
            "Write a Jira ticket description from this meeting context.\n\n"
            "Format:\n"
            "- 1 line: source meeting title and date\n"
            "- Bullet list: Issues addressed\n"
            "- Bullet list: Action items\n"
            "- Max 400 characters total\n"
            "- Professional tone, no fluff\n\n"
            f"Context:\n{context}"
        )

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.openai_model,
                        "input": prompt,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError:
            return None

        return self._extract_text(payload)

    def _extract_tool_plan(self, payload: dict) -> ToolPlan | None:
        for item in payload.get("output", []):
            if item.get("type") != "function_call":
                continue
            name = item.get("name")
            raw_arguments = item.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments = {}
            if name:
                return ToolPlan(tool_name=name, arguments=arguments, confidence=0.8)
        return None

    def _extract_text(self, payload: dict) -> str | None:
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"].strip()

        output = payload.get("output", [])
        for item in output:
            for content in item.get("content", []):
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return None
