from fastapi import APIRouter

from app import schemas
from app.coverage import identity

router = APIRouter(prefix="/api/github", tags=["github"])


@router.get("/status", response_model=schemas.GithubConnectionStatusOut)
def get_github_status():
    return identity.check_github_connection()
