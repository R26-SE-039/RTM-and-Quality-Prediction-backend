"""GitHub connection status for the Coverage page: prefers the open
project's connection stored in Component 2 (masked metadata only), falling
back to the backend-wide env credentials."""

from fastapi import APIRouter

from app import schemas
from app.coverage import identity
from app.integrations import component2

router = APIRouter(prefix="/api/github", tags=["github"])


@router.get("/status", response_model=schemas.GithubConnectionStatusOut)
async def github_status(project_id: str):
    connection = await component2.get_github_connection(project_id)
    if connection:
        return schemas.GithubConnectionStatusOut(
            connected=True,
            source="project",
            username=connection.get("github_user_login"),
            repo_full=connection.get("repo_full"),
            default_branch=connection.get("default_branch"),
        )

    env_check = identity.check_github_connection()
    return schemas.GithubConnectionStatusOut(
        connected=env_check["connected"],
        source="env" if env_check["connected"] else None,
        reason=env_check["reason"]
        if env_check["connected"]
        else (
            "No GitHub connection for this project. Connect a repository in "
            "Test Script Gen → GitHub Settings, or configure backend credentials."
        ),
        username=env_check["username"],
    )
