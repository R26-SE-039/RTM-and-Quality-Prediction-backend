"""Shallow-clones a repo into a temp directory using a short-lived auth
header (never embedded in the URL, so it can't leak via `ps` or git's own
error output) — the token is passed through `git -c http.extraHeader=...`
rather than `https://<token>@github.com/...`.

GitHub's REST API (api.github.com) accepts `Authorization: Bearer <token>`,
but its git-over-HTTPS smart protocol (github.com/owner/repo.git) expects
HTTP Basic auth with the token as the password — it responds 401 +
`WWW-Authenticate: Basic` to a Bearer header, which otherwise sends git
looking for a credential helper and then, with none configured, failing on
a terminal prompt it can't show from a background thread.
"""

import base64
import os
import shutil
import subprocess
import tempfile

from app import config


class CloneError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def clone_repo(owner: str, repo: str, timeout: int | None = None) -> str:
    timeout = timeout or config.settings.coverage_job_timeout_seconds
    repo_dir = tempfile.mkdtemp(prefix="rtm-coverage-")
    url = f"https://github.com/{owner}/{repo}.git"

    basic_credentials = base64.b64encode(
        f"{config.settings.github_username}:{config.settings.github_token}".encode()
    ).decode()
    auth_header = f"Authorization: Basic {basic_credentials}"

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"  # fail fast with a clear error instead of an unusable tty prompt

    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                f"http.extraHeader={auth_header}",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                url,
                repo_dir,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        shutil.rmtree(repo_dir, ignore_errors=True)
        raise CloneError(f"Cloning {owner}/{repo} timed out after {timeout}s.") from e

    if result.returncode != 0:
        shutil.rmtree(repo_dir, ignore_errors=True)
        stderr = result.stderr
        if config.settings.github_token:
            stderr = stderr.replace(config.settings.github_token, "***")
        stderr = stderr.replace(basic_credentials, "***")
        raise CloneError(f"git clone failed for {owner}/{repo}: {stderr.strip()[-500:]}")

    return repo_dir


def cleanup(repo_dir: str) -> None:
    shutil.rmtree(repo_dir, ignore_errors=True)
