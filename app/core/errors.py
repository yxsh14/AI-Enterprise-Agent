class IntegrationError(Exception):
    """Base exception for external enterprise integration failures."""


class IntegrationNotConfiguredError(IntegrationError):
    """Raised when required Jira or Confluence credentials are missing."""


class ExternalToolError(IntegrationError):
    """Raised when an external enterprise API call fails."""
