from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = "AI Enterprise Assistant"
    jira_base_url: str | None = os.getenv("JIRA_BASE_URL")
    jira_email: str | None = os.getenv("JIRA_EMAIL")
    jira_api_token: str | None = os.getenv("JIRA_API_TOKEN")
    jira_project_key: str = os.getenv("JIRA_PROJECT_KEY", "HELP")
    jira_default_issue_type: str = "Task"
    confluence_base_url: str | None = os.getenv("CONFLUENCE_BASE_URL")
    confluence_email: str | None = os.getenv("CONFLUENCE_EMAIL")
    confluence_api_token: str | None = os.getenv("CONFLUENCE_API_TOKEN")
    confluence_space_id: str | None = os.getenv("CONFLUENCE_SPACE_ID")
    confluence_space_key: str | None = os.getenv("CONFLUENCE_SPACE_KEY")
    confluence_folder_id: str | None = os.getenv("CONFLUENCE_FOLDER_ID")
    confluence_folder_ids: str = os.getenv("CONFLUENCE_FOLDER_IDS", "")
    confluence_page_title_filter: str = os.getenv("CONFLUENCE_PAGE_TITLE_FILTER", "")
    confluence_page_subtype: str = os.getenv("CONFLUENCE_PAGE_SUBTYPE", "")
    enable_llm: bool = os.getenv("ENABLE_LLM", "false").lower() == "true"
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    @property
    def jira_is_configured(self) -> bool:
        return bool(self.jira_base_url and self.jira_email and self.jira_api_token)

    @property
    def confluence_is_configured(self) -> bool:
        return bool(
            self.confluence_base_url
            and self.confluence_email
            and self.confluence_api_token
            and (self.confluence_space_id or self.confluence_space_key)
        )

    @property
    def llm_is_configured(self) -> bool:
        return bool(self.enable_llm and self.openai_api_key and self.openai_model)

    @property
    def confluence_allowed_folder_ids(self) -> set[str]:
        raw_values = []
        if self.confluence_folder_id:
            raw_values.append(self.confluence_folder_id)
        if self.confluence_folder_ids:
            raw_values.extend(self.confluence_folder_ids.split(","))

        return {value.strip() for value in raw_values if value.strip()}


settings = Settings()
