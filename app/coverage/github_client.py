"""Thin wrapper around the GitHub REST API for the code-coverage feature.

The PAT is read from environment variables (app.config) and never leaves
the backend process — it is attached to outgoing requests here and is not
returned in any response body.
"""

import re

import httpx

from app import config

GITHUB_API = "https://api.github.com"

REPO_URL_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


class GitHubAPIError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    match = REPO_URL_RE.match(repo_url.strip())
    if not match:
        raise GitHubAPIError(
            "Could not parse a GitHub owner/repo from that URL. Expected a form like "
            "https://github.com/owner/repo.",
            status_code=400,
        )
    return match.group("owner"), match.group("repo")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_authenticated_user(client: httpx.Client | None = None) -> dict:
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.get(f"{GITHUB_API}/user", headers=_headers())
        if resp.status_code == 401:
            raise GitHubAPIError(
                "GitHub authentication failed — check GITHUB_TOKEN in the backend .env file.",
                status_code=401,
            )
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns_client:
            client.close()


def get_repo(owner: str, repo: str, client: httpx.Client | None = None) -> dict:
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=_headers())
        if resp.status_code == 404:
            raise GitHubAPIError(
                f"Repository '{owner}/{repo}' was not found (or the token has no access to it).",
                status_code=404,
            )
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns_client:
            client.close()


def is_collaborator(owner: str, repo: str, username: str, client: httpx.Client | None = None) -> bool:
    """Returns True only if `username` is an explicit collaborator on the repo.

    Uses GitHub's dedicated collaborator-check endpoint (204 = yes, 404 = no)
    rather than the repo's `permissions.pull` field, since `pull` is true for
    any public repo regardless of collaborator status.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/collaborators/{username}",
            headers=_headers(),
        )
        if resp.status_code == 204:
            return True
        if resp.status_code in (404, 403):
            return False
        resp.raise_for_status()
        return False
    finally:
        if owns_client:
            client.close()
