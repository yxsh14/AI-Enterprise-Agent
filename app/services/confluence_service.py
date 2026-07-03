from __future__ import annotations

import re

import httpx

from app.core.config import settings
from app.core.errors import ExternalToolError, IntegrationNotConfiguredError


class ConfluenceService:
    async def get_meeting_documents(self) -> list[dict]:
        if not settings.confluence_is_configured:
            raise IntegrationNotConfiguredError(
                "Confluence is not configured. Set CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL, "
                "CONFLUENCE_API_TOKEN, and CONFLUENCE_SPACE_ID."
            )

        return await self._fetch_confluence_pages()

    async def get_meeting_docs_by_date(self, requested_date: str) -> list[dict]:
        docs = await self.get_meeting_documents()
        return [doc for doc in docs if doc["date"] == requested_date]

    async def search_meeting_docs(self, query: str) -> list[dict]:
        docs = await self.get_meeting_documents()
        terms = set(query.lower().replace("?", " ").replace(".", " ").split())
        matches = []

        for doc in docs:
            searchable = " ".join(
                [doc["date"], doc["title"], doc["content"], " ".join(doc["attendees"])]
            ).lower()
            score = sum(1 for term in terms if term in searchable)
            if score > 0:
                match = dict(doc)
                match["score"] = score
                matches.append(match)

        return sorted(matches, key=lambda doc: doc["score"], reverse=True)

    async def _fetch_confluence_pages(self) -> list[dict]:
        space_id = await self._resolve_space_id()
        params = {
            "space-id": space_id,
            "limit": 25,
            "body-format": "storage",
        }
        if settings.confluence_page_subtype:
            params["subtype"] = settings.confluence_page_subtype

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{settings.confluence_base_url.rstrip('/')}/wiki/api/v2/pages",
                    auth=(settings.confluence_email, settings.confluence_api_token),
                    headers={"Accept": "application/json"},
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ExternalToolError(f"Confluence API call failed: {exc.__class__.__name__}") from exc

        docs = []
        for page in payload.get("results", []):
            title = page.get("title", "")
            title_filter = settings.confluence_page_title_filter.lower()
            if title_filter and title_filter not in title.lower():
                continue
            allowed_folder_ids = settings.confluence_allowed_folder_ids
            if allowed_folder_ids and str(page.get("parentId")) not in allowed_folder_ids:
                continue

            storage = page.get("body", {}).get("storage", {}).get("value", "")
            content = self._strip_html(storage)
            docs.append(
                {
                    "id": str(page.get("id")),
                    "date": self._extract_date(content) or self._extract_date(title) or "unknown",
                    "title": title,
                    "subtype": page.get("subtype", ""),
                    "parent_id": str(page.get("parentId", "")),
                    "attendees": self._extract_attendees(content),
                    "content": content,
                    "source": "confluence",
                    "source_url": f"{settings.confluence_base_url.rstrip('/')}{page.get('_links', {}).get('webui', '')}",
                }
            )

        return docs

    async def _resolve_space_id(self) -> str:
        if settings.confluence_space_id:
            return settings.confluence_space_id

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{settings.confluence_base_url.rstrip('/')}/wiki/api/v2/spaces",
                    auth=(settings.confluence_email, settings.confluence_api_token),
                    headers={"Accept": "application/json"},
                    params={"keys": settings.confluence_space_key},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ExternalToolError(f"Confluence space lookup failed: {exc.__class__.__name__}") from exc

        results = payload.get("results", [])
        if not results:
            raise ExternalToolError(f"Could not resolve Confluence space key: {settings.confluence_space_key}")

        return str(results[0]["id"])

    def _extract_title(self, content: str) -> str | None:
        for line in content.splitlines():
            if line.startswith("# "):
                return line.replace("# ", "", 1).strip()
        return None

    def _extract_date(self, content: str) -> str | None:
        match = re.search(r"(?:Date:\s*)?(\d{4}-\d{2}-\d{2})", content)
        return match.group(1) if match else None

    def _extract_attendees(self, content: str) -> list[str]:
        match = re.search(r"Attendees:\s*(.+)", content)
        if not match:
            return []
        return [name.strip() for name in match.group(1).split(",") if name.strip()]

    def _strip_html(self, value: str) -> str:
        text = re.sub(r"<h1[^>]*>", "# ", value)
        text = re.sub(r"</h1>", "\n\n", text)
        text = re.sub(r"<h2[^>]*>", "## ", text)
        text = re.sub(r"</h2>", "\n\n", text)
        text = re.sub(r"<h3[^>]*>", "### ", text)
        text = re.sub(r"</h3>", "\n\n", text)
        text = re.sub(r"<li[^>]*>", "- ", text)
        text = re.sub(r"</li>", "\n", text)
        text = re.sub(r"<br\s*/?>", "\n", text)
        text = re.sub(r"</p>", "\n", text)
        text = re.sub(r"</tr>", "\n", text)
        text = re.sub(r"</td>", " | ", text)
        text = re.sub(r"</th>", " | ", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"[ \t]+", " ", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
