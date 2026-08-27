import threading
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models

# One coverage run at a time per project. The registry itself is guarded so
# two first-time requests for the same project can't each create a lock.
_locks_guard = threading.Lock()
_run_locks: dict[str, threading.Lock] = {}


def _lock_for(project_id: str) -> threading.Lock:
    with _locks_guard:
        lock = _run_locks.get(project_id)
        if lock is None:
            lock = threading.Lock()
            _run_locks[project_id] = lock
        return lock


def is_run_in_progress(project_id: str) -> bool:
    return _lock_for(project_id).locked()


def try_acquire_run_lock(project_id: str) -> bool:
    return _lock_for(project_id).acquire(blocking=False)


def release_run_lock(project_id: str) -> None:
    lock = _lock_for(project_id)
    if lock.locked():
        lock.release()


def get_or_create_report(db: Session, project_id: str) -> models.CoverageReport:
    """Get-or-create the project's single report row. The UNIQUE constraint
    on project_id makes the create atomic: a concurrent duplicate insert
    fails the constraint instead of producing a second row."""
    report = (
        db.query(models.CoverageReport)
        .filter(models.CoverageReport.project_id == project_id)
        .first()
    )
    if report is not None:
        return report

    report = models.CoverageReport(project_id=project_id)
    db.add(report)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        report = (
            db.query(models.CoverageReport)
            .filter(models.CoverageReport.project_id == project_id)
            .first()
        )
    else:
        db.refresh(report)
    return report


def set_status(
    db: Session,
    project_id: str,
    status: models.CoverageJobStatus,
    repo_url: str | None = None,
    error_message: str | None = None,
) -> models.CoverageReport:
    report = get_or_create_report(db, project_id)
    report.status = status
    if repo_url is not None:
        report.repo_url = repo_url
    report.error_message = error_message
    db.commit()
    db.refresh(report)
    return report


def reset_logs(db: Session, project_id: str) -> models.CoverageReport:
    report = get_or_create_report(db, project_id)
    report.logs = []
    db.commit()
    db.refresh(report)
    return report


def append_log(db: Session, project_id: str, level: str, message: str) -> models.CoverageReport:
    report = get_or_create_report(db, project_id)
    logs = list(report.logs or [])
    logs.append(
        {
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        }
    )
    report.logs = logs
    db.commit()
    db.refresh(report)
    return report


def save_result(
    db: Session,
    project_id: str,
    statement_coverage: float,
    branch_coverage: float,
    overall_coverage: float,
    files: list[dict],
) -> models.CoverageReport:
    report = get_or_create_report(db, project_id)
    report.status = models.CoverageJobStatus.DONE
    report.error_message = None
    report.statement_coverage = statement_coverage
    report.branch_coverage = branch_coverage
    report.overall_coverage = overall_coverage
    report.files = files
    db.commit()
    db.refresh(report)
    return report
