from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ConversationState:
    last_documents: list[dict[str, Any]] = field(default_factory=list)
    last_retrieved_context: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MemoryService:
    def __init__(self) -> None:
        self._store: dict[str, ConversationState] = {}

    def get_key(self, conversation_id: str | None, user_email: str | None) -> str:
        if conversation_id:
            return conversation_id
        if user_email:
            return user_email
        return "default"

    def remember_documents(
        self,
        key: str,
        documents: list[dict[str, Any]],
        retrieved_context: list[dict[str, Any]] | None = None,
    ) -> None:
        self._store[key] = ConversationState(
            last_documents=documents,
            last_retrieved_context=retrieved_context or [],
        )

    def get_last_documents(self, key: str) -> list[dict[str, Any]]:
        state = self._store.get(key)
        return state.last_documents if state else []

    def get_last_context(self, key: str) -> list[dict[str, Any]]:
        state = self._store.get(key)
        return state.last_retrieved_context if state else []
