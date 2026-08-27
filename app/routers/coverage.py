"""GitHub code-coverage analysis, scoped per project.

Credential resolution for the clone, in order:
1. The open project's GitHub connection stored in Component 2 (fetched
   decrypted via C2's internal credentials endpoint) — zero manual input.
2. Fallback: a manual repo_url in the request body, cloned with the
   backend-wide GITHUB_USERNAME/GITHUB_TOKEN env credentials (with the
   original owner/collaborator access check).
"""

import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import config, models, schemas
from app.coverage import access_control, state
from app.coverage import github_client
from app.coverage.access_control import AccessDenied
from app.coverage.github_client import GitHubAPIError
from app.coverage.runner import run_coverage_job
from app.database import get_db
from app.integrations import component2

router = APIRouter(prefix="/api/coverage", tags=["coverage"])


def _fail(db: Session, project_id: str, repo_url: str, message: str, status_code: int):
    state.append_log(db, project_id, "error", f"Error: {message}")
    state.set_status(db, project_id, models.CoverageJobStatus.ERROR, repo_url=repo_url, error_message=message)
    raise HTTPException(status_code=status_code, detail=message)


@router.post("/analyze", response_model=schemas.CoverageStatusOut, status_code=202)
async def analyze(project_id: str, payload: schemas.CoverageAnalyzeRequest, db: Session = Depends(get_db)):
    state.reset_logs(db, project_id)
    state.append_log(db, project_id, "info", "Initiating GitHub Coverage Analysis Agent...")

    credentials = await component2.get_github_credentials(project_id)
    manual_url = payload.repo_url.strip()

    username: str | None = None
    token: str | None = None

    if credentials and not manual_url:
        # The project's connected repo, cloned with its own stored PAT. The
        # token was validated against this exact repo when it was connected
        # in Test Script Gen, so no ownership re-check is needed here.
        owner, repo = credentials["owner"], credentials["repo"]
        repo_url = f"https://github.com/{credentials['repo_full']}"
        username, token = owner, credentials["token"]
        state.append_log(db, project_id, "info", f"Repository Target: {credentials['repo_full']} (project GitHub connection)")
        try:
            repo_meta = github_client.get_repo(owner, repo, token=token)
        except GitHubAPIError as e:
            _fail(db, project_id, repo_url, e.message, e.status_code)
    elif manual_url:
        repo_url = manual_url
        state.append_log(db, project_id, "info", f"Repository Target: {repo_url}")
        if credentials:
            try:
                owner, repo = github_client.parse_repo_url(repo_url)
            except GitHubAPIError as e:
                _fail(db, project_id, repo_url, e.message, e.status_code)
            if f"{owner}/{repo}".lower() == credentials["repo_full"].lower():
                # Manual URL that matches the connected repo — reuse its PAT.
                username, token = credentials["owner"], credentials["token"]
                try:
                    repo_meta = github_client.get_repo(owner, repo, token=token)
                except GitHubAPIError as e:
                    _fail(db, project_id, repo_url, e.message, e.status_code)
            else:
                credentials = None
        if not credentials:
            state.append_log(db, project_id, "info", "Authenticating with backend GitHub credentials...")
            try:
                repo_meta = access_control.check_access(repo_url)
            except AccessDenied as e:
                state.append_log(db, project_id, "tip", "Tip: you can only analyze repositories you own or have collaborator access to.")
                _fail(db, project_id, repo_url, e.message, 403)
            except GitHubAPIError as e:
                _fail(db, project_id, repo_url, e.message, e.status_code)
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "This project has no GitHub connection in Test Script Gen. "
                "Connect one there, or provide a repository URL to analyze."
            ),
        )

    state.append_log(db, project_id, "success", "Access granted — starting analysis...")

    if not state.try_acquire_run_lock(project_id):
        raise HTTPException(status_code=409, detail="An analysis is already running for this project.")

    try:
        report = state.set_status(
            db, project_id, models.CoverageJobStatus.RUNNING, repo_url=repo_url, error_message=None
        )
        thread = threading.Thread(
            target=run_coverage_job,
            args=(project_id, repo_url, repo_meta),
            kwargs={"username": username, "token": token},
            daemon=True,
        )
        thread.start()
    except Exception:
        state.release_run_lock(project_id)
        raise

    return schemas.CoverageStatusOut(
        status=report.status,
        repo_url=report.repo_url,
        error_message=report.error_message,
        github_connected=bool(credentials) or config.settings.github_credentials_configured,
        logs=report.logs,
    )


@router.get("/status", response_model=schemas.CoverageStatusOut)
async def get_status(project_id: str, db: Session = Depends(get_db)):
    report = state.get_or_create_report(db, project_id)
    connection = await component2.get_github_connection(project_id)
    return schemas.CoverageStatusOut(
        status=report.status,
        repo_url=report.repo_url,
        error_message=report.error_message,
        github_connected=connection is not None or config.settings.github_credentials_configured,
        logs=report.logs,
    )


@router.get("/report", response_model=schemas.CoverageReportOut)
def get_report(project_id: str, db: Session = Depends(get_db)):
    report = state.get_or_create_report(db, project_id)
    return schemas.CoverageReportOut(
        status=report.status,
        repo_url=report.repo_url,
        error_message=report.error_message,
        statement_coverage=report.statement_coverage,
        branch_coverage=report.branch_coverage,
        overall_coverage=report.overall_coverage,
        files=report.files,
        logs=report.logs,
        updated_at=report.updated_at,
    )
