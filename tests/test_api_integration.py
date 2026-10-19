"""Module 5 - API & Integration (offline): REST contract, frontend<->backend contract, error handling,
and Component 1 / Component 2 client behaviour. Components 1/2 are faked or pointed at a closed port;
their real implementations are never modified."""

import asyncio
import json
import os
import re

import pytest

from app.integrations import component1, component2
from tests.sample_data import LOCKOUT_AC, LOGIN_AC, LOGIN_HIGH, LOGIN_LOW, make_test_case, requirement

M = "API & Integration"
case = pytest.mark.case
SCOPE = {"project_id": "P1", "iteration_id": "IT1"}
FRONTEND_API = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "api", "rtmApi.ts")
CLOSED_PORT_URL = "http://127.0.0.1:9"  # discard port - nothing listens, connection is refused immediately


@case(id="API-01", module=M, title="Health / readiness probe",
      objective="Verify /api/health reports ok only when the database is reachable.",
      expected="HTTP 200 {status: ok, database: up} (test SQLite database).")
def test_health(client, record):
    r = client.get("/api/health")
    record.actual(f"HTTP {r.status_code} {r.json()}")
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": "up"}


def src_count():
    """Number of request<...>(...) call sites in rtmApi.ts (excluding the helper's own definition)."""
    return len(re.findall(r"request<[^(]*\(\s*`", open(FRONTEND_API).read()))


def _frontend_calls():
    src = open(FRONTEND_API).read()
    calls = []
    for m in re.finditer(r"request<[^(]*\(\s*`([^`]*)`(?=(.{0,160}))", src, re.S):
        path = m.group(1).split("?")[0]
        window = m.group(2).split("request<")[0]  # only this call's options, not the next call
        found = re.search(r'method:\s*"(POST|PUT|PATCH|DELETE)"', window)
        method = found.group(1) if found else "GET"
        calls.append((method, re.sub(r"\$\{[^}]+\}", "{x}", path)))
    return calls


@case(id="API-02", module=M, title="Frontend-to-backend endpoint contract",
      objective="Parse every request in frontend/src/api/rtmApi.ts and verify a backend route exists with the same path and HTTP method.",
      expected="All frontend RTM calls resolve to an existing FastAPI route (0 unmatched).")
def test_frontend_contract(client, record):
    if not os.path.exists(FRONTEND_API):
        pytest.skip("BLOCKED: frontend/src/api/rtmApi.ts not found next to the backend folder")
    from app.main import app

    routes = []
    for r in app.routes:
        if hasattr(r, "methods"):
            rx = "^" + re.sub(r"\{[^}]+\}", "[^/]+", r.path) + "$"
            routes.append((rx, r.methods))
    calls = _frontend_calls()
    unmatched = [c for c in calls if not any(re.match(rx, c[1]) and c[0] in methods for rx, methods in routes)]
    record.actual(f"{len(calls)} frontend calls checked; unmatched: {unmatched or 'none'}")
    record.add("Frontend calls", [f"{m} {p}" for m, p in calls])
    assert len(calls) == src_count() and unmatched == []


@case(id="API-03", module=M, title="Response shape matches the frontend Matrix type",
      objective="Verify the matrix response contains every field the RTM Matrix page reads (types/rtm.ts Matrix / MatrixRow).",
      expected="Top-level keys project_id, iteration_id, summary, rows; each row has requirement, story, AC, coverage and test fields.")
def test_matrix_shape(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", acs=LOGIN_AC)]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH, "approved")]
    m = client.get("/api/rtm/matrix", params=SCOPE).json()
    row_keys = {"requirement_id", "requirement_text", "user_story_id", "user_story_title", "priority", "acceptance_criteria",
                "missing_acceptance_criteria", "coverage_pct", "tests", "total_tests", "passed_tests", "failed_tests",
                "pending_tests", "coverage_status"}
    missing = row_keys - set(m["rows"][0])
    record.actual(f"Top-level keys: {sorted(m)}; missing row keys: {sorted(missing) or 'none'}; test keys: {sorted(m['rows'][0]['tests'][0])}")
    assert {"project_id", "iteration_id", "summary", "rows"} <= set(m) and not missing


@case(id="API-04", module=M, title="Component 1 unavailable -> clear 503 error",
      objective="Verify the RTM endpoints return HTTP 503 with an explanatory message (shown in the UI banner) when Component 1 is down.",
      expected="Matrix, gaps, dashboard, inventory and portfolio -> 503 with 'Component 1' in detail.")
def test_c1_down(client, fake_components, record):
    fake_components.c1_down = True
    paths = ["/api/rtm/matrix", "/api/rtm/c2-gaps", "/api/dashboard/summary", "/api/inventory", "/api/portfolio/analysis"]
    res = {p: client.get(p, params=SCOPE) for p in paths}
    record.actual("; ".join(f"{p} -> {r.status_code}" for p, r in res.items()) + f"; detail: {res[paths[0]].json()['detail']}")
    assert all(r.status_code == 503 and "Component 1" in r.json()["detail"] for r in res.values())


@case(id="API-05", module=M, title="Component 2 unavailable -> graceful degradation",
      objective="Verify the RTM still renders requirements (with no tests) when Component 2 is down, instead of failing the page.",
      expected="Matrix HTTP 200; requirement rows present; total_tests 0; rows NOT COVERED.")
def test_c2_down(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", acs=LOGIN_AC)]
    fake_components.c2_down = True
    r = client.get("/api/rtm/matrix", params=SCOPE)
    m = r.json()
    record.actual(f"HTTP {r.status_code}; rows {len(m['rows'])}; total_tests {m['summary']['total_tests']}; status {m['rows'][0]['coverage_status']}")
    assert r.status_code == 200 and len(m["rows"]) == 1 and m["summary"]["total_tests"] == 0


@case(id="API-06", module=M, title="Missing required query parameters rejected",
      objective="Verify project-scoped endpoints reject requests without project_id / iteration_id.",
      expected="HTTP 422 for matrix, gaps, dashboard, inventory, portfolio when iteration_id is omitted.")
def test_missing_params(client, fake_components, record):
    paths = ["/api/rtm/matrix", "/api/rtm/c2-gaps", "/api/dashboard/summary", "/api/inventory", "/api/portfolio/analysis"]
    codes = {p: client.get(p, params={"project_id": "P1"}).status_code for p in paths}
    record.actual(f"{codes}")
    assert set(codes.values()) == {422}


@case(id="API-07", module=M, title="Model and dataset transparency endpoints",
      objective="Verify model-info and dataset-info return the real trained-model report and dataset statistics used on the Quality Prediction page.",
      expected="model-info: trained true, RandomForest, matches c2_quality_model_metadata.json; dataset-info: 1,000 rows, labels Low/Medium/High.")
def test_model_dataset_info(client, record):
    mi = client.get("/api/ml/c2-quality/model-info").json()
    di = client.get("/api/ml/c2-quality/dataset-info").json()
    meta = json.load(open(os.path.join(os.path.dirname(__file__), "..", "app", "ml", "c2_quality_model_metadata.json")))
    record.actual(f"trained={mi['trained']}; algorithm={mi['algorithm']}; accuracy={mi['accuracy']}; dataset rows={di['n_rows']}; "
                  f"labels={di['label_distribution']}")
    assert mi["trained"] and mi["accuracy"] == meta["accuracy"] and mi["hyperparameters"] == meta["hyperparameters"]
    assert di["available"] and di["n_rows"] == 1000 and [d["label"] for d in di["label_distribution"]] == ["Low", "Medium", "High"]


@case(id="API-08", module=M, title="Quality predictions endpoint for a project",
      objective="Verify every Component 2 test case of a project gets features, score, formula label and model label, using the linked ACs from Component 1.",
      expected="One prediction per test case; requirement_linked = 1 when its story has ACs; labels within {High, Medium, Low}.")
def test_predictions_endpoint(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", acs=LOGIN_AC)]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH, "approved"), make_test_case("T2", "S9", LOGIN_LOW)]
    preds = client.get("/api/ml/c2-quality/predictions/P1", params={"iteration_id": "IT1"}).json()
    out = {p["test_case_id"]: (p["features"]["requirement_linked"], p["quality_score"], p["predicted_label"]) for p in preds}
    record.actual(f"(linked, score, label): {out}")
    assert out["T1"][0] == 1 and out["T2"][0] == 0 and {v[2] for v in out.values()} <= {"High", "Medium", "Low"}


@case(id="API-09", module=M, title="Dashboard, inventory and portfolio consistency",
      objective="Verify the dashboard, inventory and portfolio endpoints are built from the same matrix and agree with each other.",
      expected="Dashboard quality buckets sum to matrix total_tests; inventory lists each test once with a quality score; portfolio flags the duplicate, the failing Must test and the vague test.")
def test_dashboard_inventory_portfolio(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", "Must", LOGIN_AC), requirement("R2", "S2", "Should", LOGIN_AC + [LOCKOUT_AC])]
    fake_components.test_cases = [make_test_case("A", "S1", LOGIN_HIGH, "approved"), make_test_case("B", "S1", LOGIN_HIGH, "approved"),
                                  make_test_case("C", "S2", LOGIN_HIGH, "rejected"), make_test_case("D", "S2", LOGIN_LOW, "pending")]
    dash = client.get("/api/dashboard/summary", params=SCOPE).json()
    inv = client.get("/api/inventory", params=SCOPE).json()
    port = client.get("/api/portfolio/analysis", params=SCOPE).json()
    buckets = sum(b["tests"] for b in dash["quality_distribution"])
    cats = {k: [i["test_id"] for i in port[k]] for k in ("redundant", "critical", "weak")}
    record.actual(f"dashboard buckets={buckets}, matrix tests={dash['matrix']['total_tests']}; inventory={[(i['id'], i['predicted_label']) for i in inv]}; portfolio={cats}")
    assert buckets == dash["matrix"]["total_tests"] == len(inv) == 4
    assert all(i["quality_score"] is not None for i in inv)
    assert cats["redundant"] == ["B"] and "C" in cats["critical"] and "D" in cats["weak"]


@case(id="API-10", module=M, title="Component 2 client: unreachable service raises a typed error",
      objective="Verify the real Component 2 HTTP client converts connection failures into Component2Unavailable (pointed at a closed local port; Component 2 itself is not modified).",
      expected="get_traceability_test_cases raises Component2Unavailable; is_reachable() returns False.")
def test_c2_client_unreachable(monkeypatch, record):
    monkeypatch.setattr(component2, "COMPONENT2_API_URL", CLOSED_PORT_URL)
    with pytest.raises(component2.Component2Unavailable) as exc:
        asyncio.run(component2.get_traceability_test_cases("P1"))
    reachable = asyncio.run(component2.is_reachable())
    record.actual(f"Raised: {type(exc.value).__name__}: {str(exc.value)[:120]}; is_reachable={reachable}")
    assert reachable is False


@case(id="API-11", module=M, title="Component 1 client: unreachable service raises a typed error",
      objective="Verify the real Component 1 HTTP client converts connection failures into Component1Unavailable.",
      expected="get_requirements_with_stories raises Component1Unavailable; the external proxy endpoint returns 503.")
def test_c1_client_unreachable(client, monkeypatch, record):
    monkeypatch.setattr(component1, "COMPONENT1_API_URL", CLOSED_PORT_URL)
    with pytest.raises(component1.Component1Unavailable):
        asyncio.run(component1.get_requirements_with_stories("IT1"))
    r = client.get("/api/external/component1/iterations/IT1/requirements-with-stories")
    record.actual(f"Client raised Component1Unavailable; proxy endpoint -> HTTP {r.status_code}")
    assert r.status_code == 503


@case(id="API-12", module=M, title="Code-coverage analysis disabled safely",
      objective="Verify POST /api/coverage/analyze returns 503 (no clone, no build) when COVERAGE_ENABLED=false, as in the test and Docker deployments.",
      expected="HTTP 503 with 'disabled' in the detail; report endpoint still answers.")
def test_coverage_disabled(client, record):
    r = client.post("/api/coverage/analyze", params={"project_id": "P1"}, json={"repo_url": ""})
    rep = client.get("/api/coverage/report", params={"project_id": "P1"})
    record.actual(f"analyze -> HTTP {r.status_code}: {r.json()['detail'][:80]}; report -> HTTP {rep.status_code} status={rep.json().get('status')}")
    assert r.status_code == 503 and "disabled" in r.json()["detail"] and rep.status_code == 200


@case(id="API-13", module=M, title="Existing functionality unaffected by the testing component",
      objective="Verify all pre-existing RTM routes are still registered after adding the testing endpoints.",
      expected="All 17 pre-existing RTM route paths present in the application.")
def test_existing_routes_intact(record):
    from app.main import app

    expected = ["/api/health", "/api/rtm/matrix", "/api/rtm/matrix/requirements/{requirement_id}", "/api/dashboard/summary",
                "/api/inventory", "/api/portfolio/analysis", "/api/rtm/c2-gaps", "/api/rtm/c2-gaps/generate-test-case",
                "/api/rtm/c2-gaps/generate-all", "/api/rtm/c2-gaps/{gap_test_case_id}/add", "/api/rtm/c2-gaps/generated",
                "/api/ml/c2-quality/model-info", "/api/ml/c2-quality/predictions/{project_id}", "/api/ml/c2-quality/improve",
                "/api/coverage/analyze", "/api/coverage/report", "/api/github/status"]
    paths = {getattr(r, "path", None) for r in app.routes}
    missing = [p for p in expected if p not in paths]
    record.actual(f"{len(expected) - len(missing)}/{len(expected)} pre-existing routes present; missing: {missing or 'none'}")
    assert missing == []


@case(id="API-14", module=M, title="Testing-dashboard endpoints",
      objective="Verify the dashboard can read the evidence report and manual checks, and that unknown manual checks are rejected.",
      expected="GET /api/testing/report -> 200 with suite_available true and 7 manual checks; PUT to an unknown check -> 404.")
def test_testing_endpoints(client, record):
    r = client.get("/api/testing/report").json()
    bad = client.put("/api/testing/manual/NOPE", json={"status": "Passed"})
    record.actual(f"suite_available={r['suite_available']}; manual checks={len(r['manual_checks'])}; "
                  f"run status={r['run']['status']}; unknown check -> HTTP {bad.status_code}")
    assert r["suite_available"] and len(r["manual_checks"]) == 7 and bad.status_code == 404
