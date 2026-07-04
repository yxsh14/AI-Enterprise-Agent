from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.errors import ExternalToolError, IntegrationNotConfiguredError


class JiraService:
    @property
    def project_key(self) -> str:
        return settings.jira_project_key

    async def create_ticket(
        self,
        summary: str,
        description: str,
        priority: str = "Medium",
        issue_type: str | None = None,
    ) -> dict:
        inferred_issue_type = issue_type or self.infer_issue_type(summary, description)

        if not settings.jira_is_configured:
            raise IntegrationNotConfiguredError(
                "Jira is not configured. Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, "
                "and JIRA_PROJECT_KEY."
            )

        jira_issue_type = await self._resolve_supported_issue_type(inferred_issue_type)

        payload = {
            "fields": {
                "project": {"key": settings.jira_project_key},
                "summary": summary,
                "description": self._jira_doc(description),
                "issuetype": {"name": jira_issue_type},
                "priority": {"name": priority},
            }
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{settings.jira_base_url.rstrip('/')}/rest/api/3/issue",
                    auth=(settings.jira_email, settings.jira_api_token),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
                created = response.json()
        except httpx.HTTPError as exc:
            raise ExternalToolError(f"Jira API call failed: {exc.__class__.__name__}") from exc

        return {
            "ticket_id": created.get("key"),
            "ticket_url": f"{settings.jira_base_url.rstrip('/')}/browse/{created.get('key')}",
            "summary": summary,
            "description": description,
            "priority": priority,
            "issue_type": jira_issue_type,
            "inferred_issue_type": inferred_issue_type,
            "mode": "jira",
        }

    async def update_ticket(
        self,
        ticket_id: str,
        summary: str | None = None,
        description: str | None = None,
        priority: str | None = None,
    ) -> dict:
        if not settings.jira_is_configured:
            raise IntegrationNotConfiguredError(
                "Jira is not configured. Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, "
                "and JIRA_PROJECT_KEY."
            )

        fields = {}
        if summary:
            fields["summary"] = summary
        if description:
            fields["description"] = self._jira_doc(description)
        if priority:
            fields["priority"] = {"name": priority}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.put(
                    f"{settings.jira_base_url.rstrip('/')}/rest/api/3/issue/{ticket_id}",
                    auth=(settings.jira_email, settings.jira_api_token),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    json={"fields": fields},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalToolError(f"Jira API call failed: {exc.__class__.__name__}") from exc

        return {
            "ticket_id": ticket_id,
            "updated_fields": {
                "summary": summary,
                "description": description,
                "priority": priority,
            },
            "mode": "jira",
        }

    async def delete_ticket(self, ticket_id: str) -> dict:
        if not settings.jira_is_configured:
            raise IntegrationNotConfiguredError(
                "Jira is not configured. Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, "
                "and JIRA_PROJECT_KEY."
            )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(
                    f"{settings.jira_base_url.rstrip('/')}/rest/api/3/issue/{ticket_id}",
                    auth=(settings.jira_email, settings.jira_api_token),
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalToolError(f"Jira API call failed: {exc.__class__.__name__}") from exc

        return {
            "ticket_id": ticket_id,
            "deleted": True,
            "mode": "jira",
        }

    async def list_tickets(self, max_results: int = 10) -> dict:
        jql = f"project = {settings.jira_project_key} ORDER BY created DESC"
        return await self.search_tickets(jql=jql, max_results=max_results)

    async def search_tickets(self, jql: str, max_results: int = 10) -> dict:
        if not settings.jira_is_configured:
            raise IntegrationNotConfiguredError(
                "Jira is not configured. Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, "
                "and JIRA_PROJECT_KEY."
            )

        payload = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ["summary", "status", "issuetype", "priority", "created", "updated"],
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{settings.jira_base_url.rstrip('/')}/rest/api/3/search/jql",
                    auth=(settings.jira_email, settings.jira_api_token),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
        except httpx.HTTPError as exc:
            raise ExternalToolError(f"Jira search API call failed: {exc.__class__.__name__}") from exc

        issues = []
        for issue in result.get("issues", []):
            fields = issue.get("fields", {})
            issues.append(
                {
                    "ticket_id": issue.get("key"),
                    "ticket_url": f"{settings.jira_base_url.rstrip('/')}/browse/{issue.get('key')}",
                    "summary": fields.get("summary"),
                    "status": (fields.get("status") or {}).get("name"),
                    "issue_type": (fields.get("issuetype") or {}).get("name"),
                    "priority": (fields.get("priority") or {}).get("name"),
                    "created": fields.get("created"),
                    "updated": fields.get("updated"),
                }
            )

        return {
            "jql": jql,
            "total": result.get("total", len(issues)),
            "tickets": issues,
            "mode": "jira",
        }

    def infer_issue_type(self, summary: str, description: str) -> str:
        text = f"{summary} {description}".lower()

        if any(
            keyword in text
            for keyword in ["bug", "error", "failed", "failing", "failure", "timeout"]
        ):
            return "Bug"
        if any(keyword in text for keyword in ["service request", "access", "provisioning", "cleanup"]):
            return "Service Request"
        if any(keyword in text for keyword in ["incident", "outage", "security", "missing laptop"]):
            return "Incident"
        if any(keyword in text for keyword in ["task", "tracking", "follow up", "review"]):
            return "Task"

        return settings.jira_default_issue_type

    async def _resolve_supported_issue_type(self, inferred_issue_type: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{settings.jira_base_url.rstrip('/')}/rest/api/3/project/{settings.jira_project_key}",
                    auth=(settings.jira_email, settings.jira_api_token),
                    headers={"Accept": "application/json"},
                    params={"expand": "issueTypes"},
                )
                response.raise_for_status()
                project = response.json()
        except httpx.HTTPError as exc:
            raise ExternalToolError(f"Jira project metadata call failed: {exc.__class__.__name__}") from exc

        allowed_types = [issue_type["name"] for issue_type in project.get("issueTypes", [])]
        if inferred_issue_type in allowed_types:
            return inferred_issue_type
        if settings.jira_default_issue_type in allowed_types:
            return settings.jira_default_issue_type
        if "Task" in allowed_types:
            return "Task"
        if allowed_types:
            return allowed_types[0]

        raise ExternalToolError(f"No Jira issue types are available for project {settings.jira_project_key}.")

    def _jira_doc(self, text: str) -> dict:
        return {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": text}],
                }
            ],
        }
