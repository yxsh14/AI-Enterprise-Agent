from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.conversation_state import ConversationGoal, ConversationState, ConversationStage


class MemoryService:
    def __init__(self) -> None:
        self._store: dict[str, ConversationState] = {}

    def get_key(self, conversation_id: str | None, _user_email: str | None = None) -> str:
        """Conversation memory is keyed only by *conversation_id* for stable multi-turn flows."""
        if conversation_id:
            return conversation_id
        return "default"

    def get_state(self, key: str) -> ConversationState:
        return self._store.get(key, ConversationState())

    def _save(self, key: str, state: ConversationState) -> None:
        self._store[key] = state

    def remember_documents(
        self,
        key: str,
        documents: list[dict[str, Any]],
        retrieved_context: list[dict[str, Any]] | None = None,
    ) -> None:
        state = self.get_state(key)
        state.last_documents = documents
        state.last_retrieved_context = retrieved_context or []
        self._save(key, state)

    def get_last_documents(self, key: str) -> list[dict[str, Any]]:
        return self.get_state(key).last_documents

    def get_last_context(self, key: str) -> list[dict[str, Any]]:
        return self.get_state(key).last_retrieved_context

    def set_awaiting_email(
        self,
        key: str,
        goal: ConversationGoal,
        pending_question: str,
    ) -> None:
        state = self.get_state(key)
        state.stage = "awaiting_user_email"
        state.goal = goal
        state.pending_question = pending_question
        self._save(key, state)

    def set_awaiting_ticket_id(self, key: str, goal: ConversationGoal, pending_question: str) -> None:
        state = self.get_state(key)
        state.stage = "awaiting_ticket_id"
        state.goal = goal
        state.pending_question = pending_question
        self._save(key, state)

    def set_awaiting_issue_description(self, key: str, pending_question: str) -> None:
        state = self.get_state(key)
        state.stage = "awaiting_issue_description"
        state.goal = "create_jira_ticket"
        state.pending_question = pending_question
        self._save(key, state)

    def clear_dialogue(self, key: str) -> None:
        state = self.get_state(key)
        state.stage = "idle"
        state.goal = None
        state.pending_question = None
        self._save(key, state)

    def has_meeting_context(self, key: str) -> bool:
        state = self.get_state(key)
        return bool(state.last_retrieved_context or state.last_documents)
