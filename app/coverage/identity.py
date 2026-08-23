"""Verifies that the configured GitHub credentials actually work, with a
distinct reason for each failure mode — missing config, an invalid/expired
token, or a GITHUB_USERNAME that doesn't match the token's real identity.
"""

import httpx

from app import config
from app.coverage import github_client
from app.coverage.github_client import GitHubAPIError

MISSING_CONFIG_MESSAGE = (
    "GitHub credentials are not configured on the backend. Set GITHUB_USERNAME "
    "and GITHUB_TOKEN in backend/.env and restart the server."
)
INVALID_TOKEN_MESSAGE = "GitHub authentication failed. Check that your token is valid and has not expired."


def check_github_connection(client: httpx.Client | None = None) -> dict:
    """Returns {"connected": bool, "reason": str | None, "username": str | None}."""
    if not config.settings.github_credentials_configured:
        return {"connected": False, "reason": MISSING_CONFIG_MESSAGE, "username": None}

    try:
        user = github_client.get_authenticated_user(client)
    except GitHubAPIError as e:
        if e.status_code == 401:
            return {"connected": False, "reason": INVALID_TOKEN_MESSAGE, "username": None}
        return {"connected": False, "reason": f"Could not verify GitHub credentials: {e.message}", "username": None}

    login = user.get("login", "")
    if login.lower() != config.settings.github_username.lower():
        return {
            "connected": False,
            "reason": (
                f"Username mismatch: the token belongs to '{login}', but GITHUB_USERNAME "
                f"is set to '{config.settings.github_username}'."
            ),
            "username": login,
        }

    return {"connected": True, "reason": None, "username": login}
