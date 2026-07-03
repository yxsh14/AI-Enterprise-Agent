from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ActionName = Literal[
    "answer",
    "create_jira_ticket",
    "update_jira_ticket",
    "delete_jira_ticket",
    "read_meeting_docs",
    "fetch_employee",
    "integration_error",
    "needs_clarification",
]


class AskRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="User question or business action request.",
    )
    user_email: str | None = Field(
        default=None,
        max_length=255,
        description="Enterprise user identity used for audit context on write actions.",
    )
    conversation_id: str | None = Field(
        default=None,
        max_length=120,
        description="Conversation key used for short-term follow-up context.",
    )

    @field_validator("question")
    @classmethod
    def question_must_have_words(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question cannot be empty.")
        if len(cleaned.split()) < 2:
            raise ValueError("Please ask a complete business question.")
        return cleaned

    @field_validator("user_email")
    @classmethod
    def normalize_user_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        return cleaned or None

    @field_validator("conversation_id")
    @classmethod
    def normalize_conversation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AskResponse(BaseModel):
    answer: str
    action: ActionName = "answer"
    data: dict[str, Any] | None = None
    source: str = "assistant"
