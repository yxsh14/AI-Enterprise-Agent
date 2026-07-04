# Assignment Checklist

## Requirement 1: Working Demo

- [x] Python API using FastAPI.
- [x] `POST /ask` endpoint.
- [x] Accepts input with `question`.
- [x] Processes the question using custom workflow logic, RAG retrieval, and optional LLM planning.
- [x] Returns a meaningful response.
- [x] Supports business action: create Jira ticket.
- [x] Supports additional business actions: update Jira ticket and delete Jira ticket.
- [x] Supports Jira ticket listing/search through JQL.
- [x] Supports enterprise information retrieval from Confluence.
- [x] Supports employee information retrieval from Confluence employee profile pages.

## Requirement 2: One Real Engineering Improvement

Chosen improvement:

- [x] Retrieval from documents: simple RAG.

Additional improvements implemented:

- [x] Conversation memory.
- [x] API/tool calling with Jira and Confluence.
- [x] Request validation and guardrails.
- [x] Error handling for missing or failed integrations.

What changed from the basic implementation:

- Basic version: `/ask` could route simple questions and actions.
- Improved version: `/ask` retrieves relevant Confluence pages, chunks them, scores them with local vector similarity, answers from retrieved context, remembers the last context by `conversation_id`, and can create a Jira ticket from that remembered context.

## Requirement 3: Two Test Inputs

Normal business query:

```json
{
  "question": "What issue was addressed about checkout payments in the meeting?",
  "conversation_id": "demo-conversation"
}
```

Expected behavior:

- Searches Confluence.
- Retrieves the relevant meeting log.
- Summarizes the issue and action items.

Challenging/action query:

```json
{
  "question": "Create a Jira ticket from this",
  "user_email": "daniel.chen@example-enterprise.com",
  "conversation_id": "demo-conversation"
}
```

Expected behavior:

- Uses the previous Confluence context remembered under `demo-conversation`.
- Infers priority and issue type.
- Creates a Jira ticket.

Ambiguous query fallback:

```json
{
  "question": "Create a ticket",
  "user_email": "daniel.chen@example-enterprise.com"
}
```

Expected behavior:

- Asks for a short issue description because the request is incomplete.

## Remaining Manual Setup

- [x] Upload meeting log live docs to Confluence.
- [x] Upload `meeting-log-index.docs` to Confluence.
- [x] Upload enterprise policy docs to Confluence.
- [x] Upload employee profile docs to Confluence.
- [x] If docs are in separate folders, update `CONFLUENCE_FOLDER_IDS`.
- [x] Run a live `/ask` query against Confluence.
- [x] Add API-readable content to Confluence page: `Enterprise VPN and Remote Access Policy Guidelines`.
- [x] Add content to empty Confluence page: `2026-07-02-customer-escalation-review`.
- [x] Run a live Jira ticket creation request.
