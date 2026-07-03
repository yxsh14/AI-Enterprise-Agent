"""Conversation dialogue state for multi-turn enterprise assistant flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ConversationStage = Literal[
    "idle",
    "awaiting_user_email",
    "awaiting_ticket_id",
    "awaiting_update_description",
    "awaiting_issue_description",
]

ConversationGoal = Literal[
    "create_jira_ticket",
    "create_jira_ticket_from_meeting",
    "update_jira_ticket",
    "delete_jira_ticket",
]


@dataclass
class ConversationState:
    stage: ConversationStage = "idle"
    goal: ConversationGoal | None = None
    pending_question: str | None = None
    last_documents: list[dict[str, Any]] = field(default_factory=list)
    last_retrieved_context: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.stage != "idle"

    @property
    def is_awaiting_email(self) -> bool:
        return self.stage == "awaiting_user_email"
