"""Background execution of the actual coverage tool, run in a thread after
the (synchronous, fast) access-control gate in the router has already passed.
"""

import logging
import os

from app import models
from app.coverage import clone, java_runner, js_runner, language, python_runner, state
from app.coverage.errors import CoverageRunError
from app.coverage.language import UnsupportedLanguage
from app.database import SessionLocal

logger = logging.getLogger(__name__)


def _relative_prefix(project_dir: str, repo_dir: str) -> str:
    rel = os.path.relpath(project_dir, repo_dir)
    return "" if rel in (".", "") else f"{rel}/"


def _aggregate(results: list[dict]) -> dict:
    """Merges per-project results into one report using weighted (not
    simply-averaged) statement/branch percentages, so a large project
    doesn't get diluted by a tiny one.
    """
    all_files = [f for r in results for f in r["files"]]

    stmt_weighted = sum(f["statements"] * f["statement_coverage"] for f in all_files)
    stmt_total = sum(f["statements"] for f in all_files)
    branch_weighted = sum(f["branches"] * f["branch_coverage"] for f in all_files)
    branch_total = sum(f["branches"] for f in all_files)

    statement_coverage = round(stmt_weighted / stmt_total, 2) if stmt_total else 100.0
    branch_coverage = round(branch_weighted / branch_total, 2) if branch_total else 100.0

    return {
        "statement_coverage": statement_coverage,
        "branch_coverage": branch_coverage,
        "overall_coverage": round((statement_coverage + branch_coverage) / 2, 2),
        "files": sorted(all_files, key=lambda f: f["file_name"]),
    }


def _run_coverage_tool(repo_url: str, repo_meta: dict, log_fn) -> dict:
    owner = repo_meta.get("owner", {}).get("login")
    repo = repo_meta.get("name")

    log_fn("info", "Step 1: Cloning repository...")
    repo_dir = clone.clone_repo(owner, repo)
    log_fn("success", "Repository cloned successfully.")

    try:
        log_fn("info", "Step 2: Detecting project structure (checking repo root and subdirectories)...")
        projects = language.find_project_dirs(repo_dir)
        total_projects = len(projects["python"]) + len(projects["javascript"]) + len(projects["java"])

        if total_projects == 0:
            raise UnsupportedLanguage(
                "Unable to detect a supported project in this repository (checked repo root and "
                "one level of subdirectories) — no package.json, requirements.txt, pyproject.toml, "
                "setup.py/cfg, Pipfile, pom.xml, build.gradle/.kts, or settings.gradle/.kts found. "
                "Supported stacks: Python (pytest), JavaScript/TypeScript (Jest or Mocha), Java (Maven "
                "or Gradle, via JaCoCo)."
            )

        if total_projects > 1:
            names = [
                _relative_prefix(d, repo_dir).rstrip("/") or "."
                for d in projects["python"] + projects["javascript"] + projects["java"]
            ]
            log_fn("success", f"Detected {total_projects} projects: {', '.join(names)}")
        else:
            kind = "Python" if projects["python"] else "JavaScript/TypeScript" if projects["javascript"] else "Java"
            log_fn("success", f"Detected a {kind} project.")

        results = []

        for project_dir in projects["python"]:
            prefix = _relative_prefix(project_dir, repo_dir)
            if prefix:
                log_fn("info", f"Analyzing Python project in '{prefix.rstrip('/')}'...")
            result = python_runner.run(project_dir, log_fn)
            for f in result["files"]:
                f["file_name"] = prefix + f["file_name"]
            results.append(result)

        for project_dir in projects["javascript"]:
            prefix = _relative_prefix(project_dir, repo_dir)
            if prefix:
                log_fn("info", f"Analyzing JavaScript/TypeScript project in '{prefix.rstrip('/')}'...")
            result = js_runner.run(project_dir, log_fn)
            for f in result["files"]:
                f["file_name"] = prefix + f["file_name"]
            results.append(result)

        for project_dir in projects["java"]:
            prefix = _relative_prefix(project_dir, repo_dir)
            if prefix:
                log_fn("info", f"Analyzing Java project in '{prefix.rstrip('/')}'...")
            result = java_runner.run(project_dir, log_fn)
            for f in result["files"]:
                f["file_name"] = prefix + f["file_name"]
            results.append(result)

        return _aggregate(results)
    finally:
        clone.cleanup(repo_dir)


def run_coverage_job(repo_url: str, repo_meta: dict) -> None:
    db = SessionLocal()

    def log_fn(level: str, message: str) -> None:
        state.append_log(db, level, message)

    try:
        try:
            result = _run_coverage_tool(repo_url, repo_meta, log_fn)
        except (clone.CloneError, UnsupportedLanguage, CoverageRunError) as e:
            logger.info("Coverage run failed for %s: %s", repo_url, e.message)
            log_fn("error", f"Error: {e.message}")
            log_fn("tip", "Tip: check the repository has a recognizable Python, JS/TS, or Java test setup.")
            state.set_status(db, models.CoverageJobStatus.ERROR, repo_url=repo_url, error_message=e.message)
            return
        except Exception as e:  # noqa: BLE001 - surface any unexpected tool failure to the UI
            logger.exception("Coverage run failed unexpectedly for %s", repo_url)
            log_fn("error", f"Unexpected error: {e}")
            state.set_status(db, models.CoverageJobStatus.ERROR, repo_url=repo_url, error_message=str(e))
            return

        log_fn(
            "success",
            f"Coverage analysis complete — {result['overall_coverage']:.1f}% overall coverage.",
        )
        state.save_result(
            db,
            result["statement_coverage"],
            result["branch_coverage"],
            result["overall_coverage"],
            result["files"],
        )
    finally:
        db.close()
        state.release_run_lock()
