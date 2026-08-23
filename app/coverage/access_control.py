import httpx

from app import config
from app.coverage import github_client, identity
from app.coverage.github_client import GitHubAPIError


class AccessDenied(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def check_access(repo_url: str) -> dict:
    """Verifies the configured GitHub token may analyze `repo_url`.

    Allowed when the repo's owner matches GITHUB_USERNAME, or when
    GITHUB_USERNAME has explicit collaborator access to the repo. Raises
    AccessDenied (caller maps to HTTP 403) or GitHubAPIError (missing/invalid
    credentials, repo not found, etc.) otherwise. Returns repo metadata on
    success.
    """
    owner, repo = github_client.parse_repo_url(repo_url)

    with httpx.Client(timeout=15.0) as client:
        connection = identity.check_github_connection(client)
        if not connection["connected"]:
            status_code = 500 if connection["reason"] == identity.MISSING_CONFIG_MESSAGE else 401
            raise GitHubAPIError(connection["reason"], status_code=status_code)

        repo_meta = github_client.get_repo(owner, repo, client)
        repo_owner_login = repo_meta.get("owner", {}).get("login", owner)

        if repo_owner_login.lower() == config.settings.github_username.lower():
            return {**repo_meta, "access_reason": "owner"}

        if github_client.is_collaborator(owner, repo, config.settings.github_username, client):
            return {**repo_meta, "access_reason": "collaborator"}

    raise AccessDenied("Access denied: you don't have permission to analyze this repository.")
