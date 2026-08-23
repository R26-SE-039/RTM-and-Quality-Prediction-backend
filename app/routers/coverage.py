import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import config, models, schemas
from app.coverage import access_control, state
from app.coverage.access_control import AccessDenied
from app.coverage.github_client import GitHubAPIError
from app.coverage.runner import run_coverage_job
from app.database import get_db

router = APIRouter(prefix="/api/coverage", tags=["coverage"])


@router.post("/analyze", response_model=schemas.CoverageStatusOut, status_code=202)
def analyze(payload: schemas.CoverageAnalyzeRequest, db: Session = Depends(get_db)):
    if not payload.repo_url.strip():
        raise HTTPException(status_code=400, detail="repo_url is required.")

    state.reset_logs(db)
    state.append_log(db, "info", "Initiating GitHub Coverage Analysis Agent...")
    state.append_log(db, "info", f"Repository Target: {payload.repo_url}")
    state.append_log(db, "info", "Authenticating with GitHub credentials...")

    try:
        repo_meta = access_control.check_access(payload.repo_url)
    except AccessDenied as e:
        state.append_log(db, "error", f"Error: {e.message}")
        state.append_log(
            db, "tip", "Tip: you can only analyze repositories you own or have collaborator access to."
        )
        state.set_status(db, models.CoverageJobStatus.ERROR, repo_url=payload.repo_url, error_message=e.message)
        raise HTTPException(status_code=403, detail=e.message) from e
    except GitHubAPIError as e:
        state.append_log(db, "error", f"Error: {e.message}")
        state.set_status(db, models.CoverageJobStatus.ERROR, repo_url=payload.repo_url, error_message=e.message)
        raise HTTPException(status_code=e.status_code, detail=e.message) from e

    state.append_log(db, "success", "Access granted — starting analysis...")

    if not state.try_acquire_run_lock():
        raise HTTPException(status_code=409, detail="An analysis is already running.")

    try:
        report = state.set_status(
            db, models.CoverageJobStatus.RUNNING, repo_url=payload.repo_url, error_message=None
        )
        thread = threading.Thread(
            target=run_coverage_job, args=(payload.repo_url, repo_meta), daemon=True
        )
        thread.start()
    except Exception:
        state.release_run_lock()
        raise

    return schemas.CoverageStatusOut(
        status=report.status,
        repo_url=report.repo_url,
        error_message=report.error_message,
        github_connected=config.settings.github_credentials_configured,
        logs=report.logs,
    )


@router.get("/status", response_model=schemas.CoverageStatusOut)
def get_status(db: Session = Depends(get_db)):
    report = state.get_or_create_report(db)
    return schemas.CoverageStatusOut(
        status=report.status,
        repo_url=report.repo_url,
        error_message=report.error_message,
        github_connected=config.settings.github_credentials_configured,
        logs=report.logs,
    )


@router.get("/report", response_model=schemas.CoverageReportOut)
def get_report(db: Session = Depends(get_db)):
    report = state.get_or_create_report(db)
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
