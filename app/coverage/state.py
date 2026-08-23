import threading
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models

_run_lock = threading.Lock()

# CoverageReport is meant to be a singleton row (see its docstring), but
# get_or_create_report() used to do a plain "SELECT ... LIMIT 1, insert if
# none found" without an explicit order or any uniqueness guarantee -- two
# concurrent requests (e.g. the frontend polling /status while a fresh
# /analyze POST lands) could both see "no row" and each insert one,
# producing two rows that then get read inconsistently depending on which
# one an unordered .first() happens to return, making the job look stuck.
# Pinning the row to a fixed primary key makes "get or create" atomic at the
# database level: a second concurrent insert simply fails its PK constraint
# instead of creating a duplicate.
_SINGLETON_ID = 1


def is_run_in_progress() -> bool:
    return _run_lock.locked()


def try_acquire_run_lock() -> bool:
    return _run_lock.acquire(blocking=False)


def release_run_lock() -> None:
    if _run_lock.locked():
        _run_lock.release()


def get_or_create_report(db: Session) -> models.CoverageReport:
    report = db.get(models.CoverageReport, _SINGLETON_ID)
    if report is not None:
        return report

    report = models.CoverageReport(id=_SINGLETON_ID)
    db.add(report)
    try:
        db.commit()
    except IntegrityError:
        # Lost the race to another concurrent request that inserted the
        # singleton row first -- that's fine, just read what it wrote.
        db.rollback()
        report = db.get(models.CoverageReport, _SINGLETON_ID)
    else:
        db.refresh(report)
    return report


def set_status(db: Session, status: models.CoverageJobStatus, repo_url: str | None = None, error_message: str | None = None) -> models.CoverageReport:
    report = get_or_create_report(db)
    report.status = status
    if repo_url is not None:
        report.repo_url = repo_url
    report.error_message = error_message
    db.commit()
    db.refresh(report)
    return report


def reset_logs(db: Session) -> models.CoverageReport:
    report = get_or_create_report(db)
    report.logs = []
    db.commit()
    db.refresh(report)
    return report


def append_log(db: Session, level: str, message: str) -> models.CoverageReport:
    report = get_or_create_report(db)
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
    statement_coverage: float,
    branch_coverage: float,
    overall_coverage: float,
    files: list[dict],
) -> models.CoverageReport:
    report = get_or_create_report(db)
    report.status = models.CoverageJobStatus.DONE
    report.error_message = None
    report.statement_coverage = statement_coverage
    report.branch_coverage = branch_coverage
    report.overall_coverage = overall_coverage
    report.files = files
    db.commit()
    db.refresh(report)
    return report
