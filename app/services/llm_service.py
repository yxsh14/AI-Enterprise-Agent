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
            "Use read_meeting_docs for questions about meeting issues, action items, or Confluence notes.\n\n"
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
    ) -> tuple[str, str]:
        if not settings.llm_is_configured:
            return fallback_answer, "deterministic_rag"

        context = "\n\n".join(
            f"Source: {chunk['document']['title']} ({chunk['document']['date']})\n{chunk['text']}"
            for chunk in context_chunks
        )
        prompt = (
            "You are an enterprise assistant. Answer using only the provided meeting context. "
            "If the context does not answer the question, say what is missing.\n\n"
            f"Question: {question}\n\nContext:\n{context}"
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
