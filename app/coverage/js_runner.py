import json
import os
import re
import shutil
import subprocess

from app import config
from app.coverage.coverage_math import overall_from, safe_pct
from app.coverage.errors import CoverageRunError

TEST_FILE_RE = re.compile(r"\.(test|spec)\.[jt]sx?$")
IGNORE_DIRS = {"node_modules", ".git", "dist", "build", ".next", "coverage"}
OTHER_KNOWN_FRAMEWORKS = ["vitest", "jasmine", "ava", "tape", "cypress", "@playwright/test", "karma"]


def _has_test_files(repo_dir: str) -> bool:
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
        if any(TEST_FILE_RE.search(f) for f in files) or "__tests__" in dirs:
            return True
    return False


def _run(cmd: list[str], cwd: str, timeout: int, label: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise CoverageRunError(f"{label} timed out after {timeout}s.") from e


def _parse_coverage_summary(summary_path: str, repo_dir: str) -> dict:
    with open(summary_path) as f:
        data = json.load(f)

    files = []
    total = None
    for path, info in data.items():
        if path == "total":
            total = info
            continue
        stmt = info.get("statements", {})
        branch = info.get("branches", {})
        stmt_pct = safe_pct(stmt.get("covered", 0), stmt.get("total", 0))
        branch_pct = safe_pct(branch.get("covered", 0), branch.get("total", 0))
        rel_path = (
            os.path.relpath(os.path.realpath(path), os.path.realpath(repo_dir))
            if os.path.isabs(path)
            else path
        )
        files.append(
            {
                "file_name": rel_path,
                "statements": stmt.get("total", 0),
                "statement_coverage": stmt_pct,
                "branches": branch.get("total", 0),
                "branch_coverage": branch_pct,
                "overall_coverage": overall_from(stmt_pct, branch_pct),
            }
        )

    total = total or {}
    total_stmt = total.get("statements", {})
    total_branch = total.get("branches", {})
    statement_coverage = safe_pct(total_stmt.get("covered", 0), total_stmt.get("total", 0))
    branch_coverage = safe_pct(total_branch.get("covered", 0), total_branch.get("total", 0))

    return {
        "statement_coverage": statement_coverage,
        "branch_coverage": branch_coverage,
        "overall_coverage": overall_from(statement_coverage, branch_coverage),
        "files": sorted(files, key=lambda f: f["file_name"]),
    }


def run(repo_dir: str, log_fn=lambda level, message: None) -> dict:
    timeout = config.settings.coverage_job_timeout_seconds

    if not shutil.which("npm"):
        raise CoverageRunError("No npm executable found on the backend host.")

    package_json_path = os.path.join(repo_dir, "package.json")
    with open(package_json_path) as f:
        package_json = json.load(f)
    deps = {**package_json.get("dependencies", {}), **package_json.get("devDependencies", {})}

    if "jest" in deps:
        runner = "jest"
    elif "mocha" in deps:
        runner = "mocha"
    else:
        other_framework = next((k for k in OTHER_KNOWN_FRAMEWORKS if k in deps), None)
        has_test_files = _has_test_files(repo_dir)

        if other_framework:
            raise CoverageRunError(
                f"This repo uses '{other_framework}' for testing, but only Jest and Mocha are "
                "wired up for coverage right now."
            )
        if has_test_files:
            raise CoverageRunError(
                "Found test-like files, but no recognized test framework (Jest or Mocha) is "
                "declared in package.json devDependencies — coverage can't run without one."
            )
        raise CoverageRunError(
            "This repository doesn't have any tests: no *.test.*/*.spec.* files and no test "
            "framework (Jest/Mocha/Vitest/etc.) declared in package.json. Code coverage measures "
            "how much of your code your tests exercise — add a test suite first, then re-run."
        )

    log_fn("info", f"Detected {runner} as the test runner — installing npm dependencies...")
    install_cmd = (
        ["npm", "ci", "--no-audit", "--no-fund"]
        if os.path.exists(os.path.join(repo_dir, "package-lock.json"))
        else ["npm", "install", "--no-audit", "--no-fund"]
    )
    result = _run(install_cmd, cwd=repo_dir, timeout=timeout, label="npm install")
    if result.returncode != 0:
        raise CoverageRunError(f"npm install failed: {result.stderr.strip()[-500:]}")

    if runner == "jest":
        log_fn("info", "Running Jest with coverage instrumentation...")
        result = _run(
            [
                "npx",
                "--no-install",
                "jest",
                "--coverage",
                "--coverageReporters=json-summary",
                "--coverageReporters=text",
                "--ci",
            ],
            cwd=repo_dir,
            timeout=timeout,
            label="running jest",
        )
    else:
        # nyc wraps the repo's own `npm test` (mocha) command with istanbul
        # instrumentation — nyc itself doesn't need to be a declared
        # dependency, the same way pytest-cov isn't required from Python repos.
        log_fn("info", "Running Mocha via nyc with coverage instrumentation...")
        result = _run(
            ["npx", "--yes", "nyc", "--reporter=json-summary", "--reporter=text", "npm", "test"],
            cwd=repo_dir,
            timeout=timeout,
            label="running mocha via nyc",
        )

    summary_path = os.path.join(repo_dir, "coverage", "coverage-summary.json")
    if not os.path.exists(summary_path):
        tail = (result.stdout + "\n" + result.stderr).strip()[-800:]
        raise CoverageRunError(f"{runner} did not produce a coverage summary. Output tail:\n{tail}")

    log_fn("success", f"{runner.capitalize()} tests completed — parsing coverage report...")
    return _parse_coverage_summary(summary_path, repo_dir)
