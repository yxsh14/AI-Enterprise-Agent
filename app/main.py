from fastapi import FastAPI

from app.schemas import AskRequest, AskResponse
from app.services.assistant_service import AssistantService

app = FastAPI(
    title="AI Enterprise Assistant",
    description="A FastAPI assistant that answers enterprise questions and calls business tools.",
    version="0.1.0",
)

assistant = AssistantService()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    return await assistant.handle_question(
        request.question,
        request.user_email,
        request.conversation_id,
    )
