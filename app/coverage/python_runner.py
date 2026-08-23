import json
import os
import shutil
import subprocess

from app import config
from app.coverage.coverage_math import overall_from, safe_pct
from app.coverage.errors import CoverageRunError


def _find_python() -> str:
    for candidate in ("python3.11", "python3"):
        path = shutil.which(candidate)
        if path:
            return path
    raise CoverageRunError("No python3 interpreter found on the backend host.")


def _run(cmd: list[str], cwd: str, timeout: int, label: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise CoverageRunError(f"{label} timed out after {timeout}s.") from e


def run(repo_dir: str, log_fn=lambda level, message: None) -> dict:
    timeout = config.settings.coverage_job_timeout_seconds
    venv_dir = os.path.join(repo_dir, ".rtm_venv")

    log_fn("info", "Setting up an isolated Python virtual environment...")
    base_python = _find_python()
    result = _run([base_python, "-m", "venv", venv_dir], cwd=repo_dir, timeout=timeout, label="venv creation")
    if result.returncode != 0:
        raise CoverageRunError(f"Failed to create a virtualenv: {result.stderr.strip()[-500:]}")

    venv_python = os.path.join(venv_dir, "bin", "python")
    venv_pip = os.path.join(venv_dir, "bin", "pip")

    log_fn("info", "Installing pytest/pytest-cov tooling...")
    result = _run(
        [venv_pip, "install", "--quiet", "--disable-pip-version-check", "pytest", "pytest-cov", "coverage"],
        cwd=repo_dir,
        timeout=timeout,
        label="installing pytest/pytest-cov",
    )
    if result.returncode != 0:
        raise CoverageRunError(f"Failed to install pytest tooling: {result.stderr.strip()[-500:]}")

    requirements_path = os.path.join(repo_dir, "requirements.txt")
    if os.path.exists(requirements_path):
        log_fn("info", "Installing repository dependencies (requirements.txt)...")
        result = _run(
            [venv_pip, "install", "--quiet", "--disable-pip-version-check", "-r", "requirements.txt"],
            cwd=repo_dir,
            timeout=timeout,
            label="installing requirements.txt",
        )
        if result.returncode != 0:
            raise CoverageRunError(f"Failed to install requirements.txt: {result.stderr.strip()[-500:]}")
    elif os.path.exists(os.path.join(repo_dir, "pyproject.toml")) or os.path.exists(
        os.path.join(repo_dir, "setup.py")
    ):
        # Best-effort: some repos need to be installed for their own tests to
        # import them. Not fatal if this fails — pytest will surface any
        # resulting import errors instead.
        log_fn("info", "Installing the package itself (pyproject.toml/setup.py found)...")
        _run([venv_pip, "install", "--quiet", "."], cwd=repo_dir, timeout=timeout, label="installing package")

    log_fn("info", "Running pytest with coverage instrumentation...")
    coverage_json = os.path.join(repo_dir, "coverage.json")
    result = _run(
        [
            venv_python,
            "-m",
            "pytest",
            "--cov=.",
            "--cov-branch",
            f"--cov-report=json:{coverage_json}",
            "-q",
        ],
        cwd=repo_dir,
        timeout=timeout,
        label="running pytest",
    )

    if not os.path.exists(coverage_json):
        tail = (result.stdout + "\n" + result.stderr).strip()[-800:]
        raise CoverageRunError(f"pytest did not produce a coverage report. Output tail:\n{tail}")

    log_fn("success", "Tests completed — parsing coverage report...")
    with open(coverage_json) as f:
        data = json.load(f)

    files = []
    for path, info in data.get("files", {}).items():
        summary = info.get("summary", {})
        statements = summary.get("num_statements", 0)
        branches = summary.get("num_branches", 0)
        stmt_pct = safe_pct(summary.get("covered_lines", 0), statements)
        branch_pct = safe_pct(summary.get("covered_branches", 0), branches)
        files.append(
            {
                "file_name": path,
                "statements": statements,
                "statement_coverage": stmt_pct,
                "branches": branches,
                "branch_coverage": branch_pct,
                "overall_coverage": overall_from(stmt_pct, branch_pct),
            }
        )

    totals = data.get("totals", {})
    statement_coverage = safe_pct(totals.get("covered_lines", 0), totals.get("num_statements", 0))
    branch_coverage = safe_pct(totals.get("covered_branches", 0), totals.get("num_branches", 0))

    return {
        "statement_coverage": statement_coverage,
        "branch_coverage": branch_coverage,
        "overall_coverage": overall_from(statement_coverage, branch_coverage),
        "files": sorted(files, key=lambda f: f["file_name"]),
    }
