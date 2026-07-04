# AI Enterprise Assistant

A FastAPI enterprise assistant for the build challenge. It exposes `POST /ask`, retrieves enterprise context from Confluence, keeps short-term conversation context, and performs Jira actions through the Jira Cloud API.

## What It Does

- Answers enterprise questions using Confluence page retrieval.
- Retrieves meeting notes, action items, issue summaries, and employee profile details from Confluence.
- Creates, updates, and deletes Jira tickets through real Jira Cloud APIs.
- Lists and searches Jira tickets through Jira JQL.
- Infers Jira issue type from the user prompt and retrieved Confluence context.
- Keeps conversation memory so follow-ups like "create a ticket from this" use the last retrieved Confluence context.
- Uses simple RAG as the mandatory engineering improvement.
- Keeps guardrails for validation, missing context, ambiguous requests, and audited write actions.

## Architecture

```text
app/
  main.py                 FastAPI app and HTTP endpoints
  schemas.py              Pydantic request and response validation
  core/
    config.py             Environment-based settings
    errors.py             Integration exceptions
  services/
    assistant_service.py  Orchestrates intent -> RAG/tool execution
    confluence_service.py Real Confluence page retrieval
    jira_service.py       Real Jira create/update/delete integration
    llm_service.py        Optional LLM tool planning and synthesis
    memory_service.py     Short-term conversation context
    rag_service.py        Chunking, local embeddings, and retrieval
  utils/
    intent.py             Deterministic fallback intent detection
enterprise_docs/
  meeting_logs/           Source .docs files to upload into Confluence
tests/                    Tests with integration-boundary stubs
```

## Runtime Flow

1. User calls `POST /ask`.
2. The assistant detects intent using optional LLM planning or deterministic fallback.
3. For information requests, it retrieves relevant Confluence pages.
4. RAG chunks the documents, scores them, and answers from the retrieved context.
5. The retrieved context is stored by `conversation_id`.
6. If the user later says "create a ticket from this", the assistant uses the remembered Confluence context.
7. If the user asks to list/search tickets, the assistant performs a read-only Jira JQL search.
8. Jira write actions are executed through the Jira Cloud API.

## Endpoint

`POST /ask`

```json
{
  "question": "What issue was addressed about checkout payments in the meeting?",
  "conversation_id": "demo-conversation"
}
```

Follow-up action using memory:

```json
{
  "question": "Create a Jira ticket from this",
  "user_email": "daniel.chen@example-enterprise.com",
  "conversation_id": "demo-conversation"
}
```

`user_email` is not used for local permission checks. It is kept as an audit guardrail for write actions.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/docs
```

## Jira Configuration

```text
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=your_api_token
JIRA_PROJECT_KEY=HELP
```

Issue type is inferred at runtime:

- `Bug` for failures, errors, timeouts, and broken release behavior.
- `Incident` for outage, security, or missing asset language.
- `Service Request` for access, provisioning, cleanup, and service request language.
- `Task` as the fallback.

The Jira service calls:

- `POST /rest/api/3/issue`
- `PUT /rest/api/3/issue/{issueIdOrKey}`
- `DELETE /rest/api/3/issue/{issueIdOrKey}`
- `POST /rest/api/3/search/jql`

## Confluence Configuration

```text
CONFLUENCE_BASE_URL=https://your-domain.atlassian.net
CONFLUENCE_EMAIL=you@company.com
CONFLUENCE_API_TOKEN=your_api_token
CONFLUENCE_SPACE_ID=
CONFLUENCE_SPACE_KEY=~71202078a62f5998164338bb9ae1ef09699bd9
CONFLUENCE_FOLDER_ID=
CONFLUENCE_FOLDER_IDS=1277953,1638401,1179656
CONFLUENCE_PAGE_TITLE_FILTER=
CONFLUENCE_PAGE_SUBTYPE=live
```

Use either `CONFLUENCE_SPACE_ID` or `CONFLUENCE_SPACE_KEY`. `CONFLUENCE_FOLDER_IDS=1277953,1638401,1179656` searches Meeting Logs, Enterprise Policies, and Employee Profiles together. Leave `CONFLUENCE_PAGE_TITLE_FILTER` blank to search all matching pages in those folders.

The Confluence service calls:

- `GET /wiki/api/v2/pages`

See [CONFLUENCE_UPLOAD_CHECKLIST.md](CONFLUENCE_UPLOAD_CHECKLIST.md) for the data to upload.

## Optional LLM Configuration

The app works without an LLM. When enabled, the LLM can propose the tool route and synthesize the final RAG answer. Guardrails and execution still remain in code.

```text
ENABLE_LLM=true
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-5.5
```

## RAG Engineering Improvement

The basic implementation would directly answer from static local data. This version adds simple RAG:

1. Confluence pages are retrieved from the configured enterprise space.
2. `RagService` chunks each page by section.
3. `RagService` creates simple local token-vector embeddings.
4. The assistant retrieves top chunks using cosine similarity.
5. The answer is generated from retrieved Confluence context.
6. The same retrieved context can be reused in follow-up actions through conversation memory.

## Guardrails

- Empty or incomplete questions are rejected by Pydantic validation.
- Jira create/update/delete requires `user_email` for auditability.
- Jira list/search requests never enter ticket-creation slot filling.
- Ambiguous ticket creation asks for a clearer issue description.
- Update/delete requires an explicit ticket ID.
- Read-only Confluence questions do not trigger Jira writes.
- Follow-up words like "this" require prior conversation context.
- Missing Jira or Confluence credentials return an `integration_error` response instead of silently using local substitute data.

## Tests

Tests stub the Jira and Confluence service boundaries so the production code can stay real-integration-only.

```bash
pytest
```
