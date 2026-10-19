"""pytest plugin that turns each test run into the evidence report shown on the
RTM "Testing" dashboard (tests/reports/latest.json).

Every research test is tagged with ``@pytest.mark.case(...)`` (ID, module,
objective, expected result) and records what the system actually returned via
the ``record`` fixture. Nothing in the report is hand-written: the status is
pytest's own outcome, and the "actual" text is captured at run time.

Status mapping:
  passed                         -> "Passed"
  failed / error                 -> "Failed"
  skipped, reason "BLOCKED: ..." -> "Blocked"      (a dependency was unavailable)
  any other skip                 -> "Not executed"
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from datetime import datetime, timezone

import pytest

REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
STATUS_ORDER = ["Passed", "Failed", "Blocked", "Not executed"]


class Record:
    """Run-time evidence for one test case."""

    def __init__(self) -> None:
        self.actual_lines: list[str] = []
        self.evidence: list[dict] = []

    def actual(self, text: str) -> None:
        self.actual_lines.append(str(text))

    def add(self, label: str, value) -> None:
        if not isinstance(value, str):
            value = json.dumps(value, indent=2, default=str)
        self.evidence.append({"label": label, "value": value})


@pytest.fixture
def record(request) -> Record:
    rec = Record()
    request.node._rtm_record = rec
    return rec


_results: dict[str, dict] = {}
_session_start = 0.0


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "case(id, module, title, objective, expected, level='unit'): research test-case metadata for the dashboard",
    )
    config.addinivalue_line("markers", "live: needs the running RTM, Component 1 and Component 2 services")


def pytest_sessionstart(session):
    global _session_start
    _session_start = time.time()
    _results.clear()


def _case_meta(item) -> dict:
    marker = item.get_closest_marker("case")
    meta = dict(marker.kwargs) if marker else {}
    meta.setdefault("id", item.name)
    meta.setdefault("module", "Other")
    meta.setdefault("title", item.name)
    meta.setdefault("objective", (item.function.__doc__ or "").strip())
    meta.setdefault("expected", "")
    if item.get_closest_marker("live"):
        level = "live"
    elif "client" in getattr(item, "fixturenames", ()):
        level = "api"  # exercised through the FastAPI HTTP layer
    else:
        level = "unit"
    meta["level"] = level
    return meta


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    nodeid = item.nodeid
    entry = _results.get(nodeid)
    if entry is None:
        entry = {**_case_meta(item), "nodeid": nodeid, "status": "Passed", "duration_ms": 0.0,
                 "failure": None, "actual": "", "evidence": []}
        _results[nodeid] = entry
    entry["duration_ms"] += round(rep.duration * 1000, 2)

    if rep.skipped:
        reason = rep.longrepr[2] if isinstance(rep.longrepr, tuple) else str(rep.longrepr)
        reason = reason.replace("Skipped: ", "")
        entry["status"] = "Blocked" if reason.startswith("BLOCKED") else "Not executed"
        entry["failure"] = reason
    elif rep.failed:
        entry["status"] = "Failed"
        text = rep.longreprtext or ""
        lines = [ln for ln in text.splitlines() if ln.strip()]
        entry["failure"] = "\n".join(lines[-14:])

    rec = getattr(item, "_rtm_record", None)
    if rec is not None and rep.when in ("call", "teardown"):
        entry["actual"] = "\n".join(rec.actual_lines)
        entry["evidence"] = rec.evidence


def _environment() -> dict:
    env = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "pytest": pytest.__version__,
    }
    try:
        from app.ml.c2_predict import get_model_info

        info = get_model_info()
        if info.get("trained"):
            env["model"] = f"{info['algorithm']} {info['hyperparameters']} (trained {info['trained_at'][:10]})"
            env["model_holdout_accuracy"] = round(info["accuracy"], 4)
    except Exception as exc:  # pragma: no cover - informational only
        env["model"] = f"unavailable: {exc}"
    return env


def pytest_sessionfinish(session, exitstatus):
    if not _results:
        return
    cases = sorted(_results.values(), key=lambda c: c["id"])
    summary = {s: sum(1 for c in cases if c["status"] == s) for s in STATUS_ORDER}
    modules: dict[str, dict] = {}
    for c in cases:
        m = modules.setdefault(c["module"], {"module": c["module"], "total": 0, **{s: 0 for s in STATUS_ORDER}})
        m["total"] += 1
        m[c["status"]] += 1
    markexpr = session.config.getoption("markexpr", "") or ""
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(time.time() - _session_start, 2),
        "suite": "offline (live tests deselected)" if "not live" in markexpr else "full (offline + live integration)",
        "command": "pytest " + " ".join(session.config.invocation_params.args),
        "environment": _environment(),
        "summary": {"total": len(cases), **summary},
        "modules": list(modules.values()),
        "cases": cases,
    }
    os.makedirs(os.path.join(REPORT_DIR, "history"), exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path in (os.path.join(REPORT_DIR, "latest.json"), os.path.join(REPORT_DIR, "history", f"{stamp}.json")):
        with open(path, "w") as f:
            json.dump(report, f, indent=2, default=str)
    _write_markdown(report, os.path.join(REPORT_DIR, "latest.md"))


def _write_markdown(report: dict, path: str) -> None:
    s = report["summary"]
    lines = [
        "# RTM & Quality Prediction - Test Report",
        "",
        f"Generated: {report['generated_at']}  ",
        f"Suite: {report['suite']}  ",
        f"Command: `{report['command']}`",
        "",
        f"**Total {s['total']} | Passed {s['Passed']} | Failed {s['Failed']} | Blocked {s['Blocked']} | Not executed {s['Not executed']}**",
        "",
        "| ID | Module | Title | Status |",
        "|---|---|---|---|",
    ]
    for c in report["cases"]:
        lines.append(f"| {c['id']} | {c['module']} | {c['title']} | {c['status']} |")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
