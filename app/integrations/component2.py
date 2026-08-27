"""Thin client for Component 2 (Intelligent-Test-Case-Generation)'s live API.

Component 2 owns test-case generation, DOM crawling, execution, and its own
ML risk model, scoped by its own `project_id`. This RTM component has no
foreign key into that data, so we call its API directly (base URL from
COMPONENT2_API_URL) and surface the results as read-only supplementary data.
"""

import os
import re
from collections import defaultdict

import httpx

COMPONENT2_API_URL = os.getenv("COMPONENT2_API_URL", "http://localhost:8002/api/v1")
# Shared secret for C2's internal endpoints (must match NEXTGENQA_INTERNAL_KEY
# in Component 2's backend .env) — used only to fetch the decrypted GitHub
# credentials of the open project for the code-coverage clone.
C2_INTERNAL_KEY = os.getenv("C2_INTERNAL_KEY", "")
# C2 runs on the same host but its DB is Neon Cloud — multi-table reads like
# /traceability take seconds, not milliseconds.
_TIMEOUT = 30.0
_SCENARIO_TITLE_RE = re.compile(r"^\s*Scenario(?: Outline)?:\s*(.+)$", re.MULTILINE)


class Component2Unavailable(Exception):
    """Raised when Component 2's API can't be reached or returns an error."""


async def _get(path: str, params: dict | None = None, headers: dict | None = None):
    url = f"{COMPONENT2_API_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        raise Component2Unavailable(f"Component 2 request failed ({url}): {e}") from e


async def is_reachable() -> bool:
    try:
        await _get("/projects")
        return True
    except Component2Unavailable:
        return False


async def list_projects() -> list[dict]:
    return await _get("/projects")


async def get_test_suites(project_id: str) -> list[dict]:
    return await _get("/code/suites", params={"project_id": project_id})


async def get_test_runs(project_id: str, limit: int = 20) -> list[dict]:
    return await _get("/runs", params={"project_id": project_id, "limit": limit})


async def get_risk(project_id: str) -> dict:
    return await _get(f"/projects/{project_id}/risk")


async def get_failed_tests(project_id: str, limit: int = 20) -> dict:
    return await _get(f"/projects/{project_id}/failed-tests", params={"limit": limit})


async def get_github_connection(project_id: str) -> dict | None:
    """Public (masked) metadata of the project's GitHub connection in C2 —
    owner/repo/branch/token_preview, never the token. None when the project
    has no connection or C2 is unreachable."""
    try:
        return await _get(f"/projects/{project_id}/github/connection")
    except Component2Unavailable:
        return None


async def get_github_credentials(project_id: str) -> dict | None:
    """Decrypted clone credentials from C2's internal endpoint (guarded by
    the shared X-Internal-Key). Returns {owner, repo, repo_full,
    default_branch, token} or None when there is no connection, the key is
    not configured/accepted, or C2 is unreachable."""
    if not C2_INTERNAL_KEY:
        return None
    try:
        return await _get(
            f"/projects/{project_id}/github/credentials",
            headers={"X-Internal-Key": C2_INTERNAL_KEY},
        )
    except Component2Unavailable:
        return None


async def get_test_cases(project_id: str, run_sample: int = 3) -> list[dict]:
    """
    Flatten recent execution runs into individual test-case rows.

    C2 has no single "list all test cases" endpoint — the closest real data
    is per-scenario results nested inside GET /runs/{run_id} (RunDetailOut).
    We sample the `run_sample` most recent runs and flatten their scenario
    lists, since a scenario itself has no stable id in C2 (only a name), we
    synthesize one from the run id + position so the frontend has something
    stable to key/link on.
    """
    runs = await get_test_runs(project_id, limit=run_sample)

    cases: list[dict] = []
    for run in runs:
        run_id = run["id"]
        try:
            detail = await _get(f"/runs/{run_id}")
        except Component2Unavailable:
            continue
        for idx, scenario in enumerate(detail.get("scenarios", [])):
            cases.append(
                {
                    "id": f"C2-{run_id[:8]}-{idx:02d}",
                    "title": scenario["scenario_name"],
                    "status": "approved" if scenario["status"] == "passed" else "rejected",
                    "framework": run.get("framework", ""),
                    "duration_ms": scenario.get("duration_ms"),
                    "error_message": scenario.get("error_message"),
                    "executed_at": run.get("finished_at") or run.get("started_at"),
                    "run_id": run_id,
                }
            )

    # Fail rate per scenario name across the sampled runs, so the frontend
    # can turn execution history into a rough quality-feature estimate.
    history: dict[str, list[bool]] = {}
    for case in cases:
        history.setdefault(case["title"], []).append(case["status"] == "approved")
    for case in cases:
        passes = history[case["title"]]
        case["fail_rate"] = round(1 - (sum(passes) / len(passes)), 3)

    return cases


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _match_gherkin_status(gherkin_text: str, scenario_results: list[dict]) -> str:
    """
    Best-effort pass/fail for one gherkin_scenarios row.

    C2's schema has no foreign key from an executed scenario_result back to
    the gherkin_scenarios row that produced it — only a free-text
    scenario_name (the generated test function's name). We match it against
    the "Scenario:"/"Scenario Outline:" titles embedded in this gherkin
    feature's text by word overlap, since generated test names are derived
    from those titles. Returns "approved" | "rejected" | "pending".
    """
    titles = [_words(t) for t in _SCENARIO_TITLE_RE.findall(gherkin_text)]
    titles = [t for t in titles if t]
    matched = []
    for result in scenario_results:
        name_words = _words(result["scenario_name"].replace("_", " "))
        if any(len(title & name_words) / len(title) >= 0.5 for title in titles):
            matched.append(result)
    if not matched:
        return "pending"
    return "rejected" if any(m["result"] == "FAIL" for m in matched) else "approved"


async def get_traceability_test_cases(project_id: str, iteration_id: str | None = None) -> list[dict]:
    """
    Test cases sourced from Component 2's GET /projects/{id}/traceability,
    joined the way RTM needs: one row per gherkin_scenarios row (the actual
    generated test case), carrying the owning user story's id so the RTM
    Matrix page can match it to Component 1's user_story_id.

    Pass/fail per test case is derived by tracing gherkin_scenario -> the
    suite(s) whose source_scenario_ids include it (an exact id match C2
    provides) -> that suite's executions' scenario_results (matched to this
    gherkin's scenario titles — see _match_gherkin_status).
    """
    # light=true skips suite source code / raw logs / artifacts server-side —
    # this join only needs ids, gherkin texts, and scenario results.
    params: dict = {"light": "true"}
    if iteration_id:
        params["iteration_id"] = iteration_id
    data = await _get(f"/projects/{project_id}/traceability", params=params)

    suite_scenario_ids: dict[str, set[str]] = {
        suite["id"]: set(suite.get("source_scenario_ids") or []) for suite in data.get("suites", [])
    }
    results_by_suite: dict[str, list[dict]] = defaultdict(list)
    for execution in data.get("executions", []):
        suite_id = execution.get("suite_id")
        if suite_id:
            results_by_suite[suite_id].extend(execution.get("scenario_results") or [])

    test_cases: list[dict] = []
    for story in data.get("stories", []):
        for gherkin in story.get("gherkin_scenarios", []):
            candidate_results = [
                result
                for suite_id, scenario_ids in suite_scenario_ids.items()
                if gherkin["id"] in scenario_ids
                for result in results_by_suite.get(suite_id, [])
            ]
            test_cases.append(
                {
                    "story_id": story["id"],
                    "id": gherkin["id"],
                    "title": gherkin.get("feature_name") or gherkin["id"],
                    "description": gherkin["gherkin_text"],
                    "status": _match_gherkin_status(gherkin["gherkin_text"], candidate_results),
                }
            )
    return test_cases
