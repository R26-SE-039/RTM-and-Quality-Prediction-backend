"""Research testing dashboard support: serves the latest pytest evidence report
(tests/reports/latest.json, written by tests/reporting.py), runs the suite on
demand for live demonstrations, and stores manually verified UI checks.

Nothing here fabricates results: the report is exactly what the last pytest
run produced, and manual checks stay "Not verified" until a person records an
outcome. The tests/ folder is not shipped in the Docker image, so in that
deployment these endpoints report the suite as unavailable.
"""

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/testing", tags=["testing"])

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TESTS_DIR = os.path.join(BACKEND_ROOT, "tests")
REPORT_PATH = os.path.join(TESTS_DIR, "reports", "latest.json")
MANUAL_DEFS_PATH = os.path.join(TESTS_DIR, "manual_checks.json")
MANUAL_RESULTS_PATH = os.path.join(TESTS_DIR, "reports", "manual_results.json")
RUN_TIMEOUT_SECONDS = 900

_lock = threading.Lock()
_run_state: dict = {"status": "idle", "suite": None, "started_at": None, "finished_at": None, "exit_code": None, "output_tail": ""}


class RunRequest(BaseModel):
    suite: Literal["offline", "full"] = "full"


class ManualResult(BaseModel):
    status: Literal["Passed", "Failed", "Not verified"]
    notes: str = ""
    verified_by: str = ""


def _read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _manual_checks() -> list[dict]:
    results = _read_json(MANUAL_RESULTS_PATH, {})
    checks = []
    for d in _read_json(MANUAL_DEFS_PATH, []):
        r = results.get(d["id"], {})
        checks.append({**d, "kind": "manual", "status": r.get("status", "Not verified"), "notes": r.get("notes", ""),
                       "verified_by": r.get("verified_by", ""), "verified_at": r.get("verified_at")})
    return checks


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(suite: str) -> None:
    cmd = [sys.executable, "-m", "pytest", "-q", "-rs"]
    if suite == "offline":
        cmd += ["-m", "not live"]
    try:
        proc = subprocess.run(cmd, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=RUN_TIMEOUT_SECONDS)
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-25:]
        _run_state.update(status="done", exit_code=proc.returncode, output_tail="\n".join(tail))
    except subprocess.TimeoutExpired:
        _run_state.update(status="error", exit_code=None, output_tail=f"Test run exceeded {RUN_TIMEOUT_SECONDS}s and was stopped.")
    except Exception as exc:  # pragma: no cover - defensive
        _run_state.update(status="error", exit_code=None, output_tail=str(exc))
    finally:
        _run_state["finished_at"] = _now()
        _lock.release()


@router.get("/report")
def get_report():
    available = os.path.isdir(TESTS_DIR)
    return {
        "suite_available": available,
        "report": _read_json(REPORT_PATH, None),
        "manual_checks": _manual_checks() if available else [],
        "run": dict(_run_state),
    }


@router.post("/run", status_code=202)
def start_run(payload: RunRequest):
    if not os.path.isdir(TESTS_DIR):
        raise HTTPException(status_code=503, detail="The test suite is not available in this deployment.")
    if not _lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A test run is already in progress.")
    _run_state.update(status="running", suite=payload.suite, started_at=_now(), finished_at=None, exit_code=None, output_tail="")
    threading.Thread(target=_run, args=(payload.suite,), daemon=True).start()
    return dict(_run_state)


@router.get("/run")
def get_run_status():
    return dict(_run_state)


@router.put("/manual/{check_id}")
def record_manual_result(check_id: str, payload: ManualResult):
    ids = {d["id"] for d in _read_json(MANUAL_DEFS_PATH, [])}
    if check_id not in ids:
        raise HTTPException(status_code=404, detail="Unknown manual check.")
    results = _read_json(MANUAL_RESULTS_PATH, {})
    results[check_id] = {**payload.model_dump(), "verified_at": _now() if payload.status != "Not verified" else None}
    os.makedirs(os.path.dirname(MANUAL_RESULTS_PATH), exist_ok=True)
    with open(MANUAL_RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)
    return next(c for c in _manual_checks() if c["id"] == check_id)
