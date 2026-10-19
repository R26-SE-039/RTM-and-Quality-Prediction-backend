"""Module 3 - Coverage-Gap Detection & Risk Prioritisation (app/ml/c2_gap_analysis.py, routers/coverage_gaps.py)."""

import pytest

from app import models
from app.database import SessionLocal
from app.ml.c2_gap_analysis import compute_coverage, compute_risk, generate_gap_test_case
from tests.sample_data import LOCKOUT_AC, LOGIN_AC, LOGIN_HIGH, LOGIN_LOW, make_test_case, requirement

M = "Coverage Gap Detection"
case = pytest.mark.case
SCOPE = {"project_id": "P1", "iteration_id": "IT1"}


def _gaps(client):
    r = client.get("/api/rtm/c2-gaps", params=SCOPE)
    assert r.status_code == 200, r.text
    return {g["requirement_id"]: g for g in r.json()}, r.json()


@case(id="GAP-01", module=M, title="Acceptance-criterion coverage threshold (40% word overlap)",
      objective="Verify an AC counts as covered only when >= 40% of its words (3+ letters) appear in at least one linked test.",
      expected="AC with 2 of 5 words present (40%) -> covered; AC with 1 of 5 words (20%) -> missing.")
def test_ac_threshold(record):
    ac = "Admin exports monthly sales report"  # words: admin exports monthly sales report
    covered, missing, pct = compute_coverage([ac], ["Given admin user\nWhen they open the sales page"])
    covered2, missing2, _ = compute_coverage([ac], ["Given admin user\nWhen they open the dashboard"])
    record.actual(f"2/5 words -> covered={bool(covered)}; 1/5 words -> covered={bool(covered2)}")
    assert covered == [ac] and missing2 == [ac]


@case(id="GAP-02", module=M, title="Uncovered acceptance criterion identified",
      objective="Verify the Coverage Gaps API lists a requirement whose tests miss one acceptance criterion and names that criterion.",
      expected="Gap listed; missing_acceptance_criteria = [lockout AC]; covered 2/3; current_coverage_pct 66.7; action 'Generate 1 additional test case'.")
def test_uncovered_ac(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", "Should", LOGIN_AC + [LOCKOUT_AC])]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH, "approved")]
    g = _gaps(client)[0]["R1"]
    record.actual(f"missing={g['missing_acceptance_criteria']}; covered {g['covered_acceptance_criteria']}/{g['total_acceptance_criteria']}; "
                  f"coverage {g['current_coverage_pct']}%; risk {g['risk_score']} ({g['risk_level']}); action: {g['recommended_action']}")
    record.add("Risk factors", g["risk_factors"])
    assert g["missing_acceptance_criteria"] == [LOCKOUT_AC] and g["current_coverage_pct"] == 66.7
    assert g["recommended_action"].startswith("Generate 1 additional test case")


@case(id="GAP-03", module=M, title="Requirement with no linked test cases",
      objective="Verify an untested Must requirement is reported as a Critical gap with the maximum coverage-gap factor.",
      expected="business_priority 100, coverage_gap 100, AC gap 100; risk >= 70 -> Critical; action 'Generate 2 additional test cases'.")
def test_no_tests_gap(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", "Must", LOGIN_AC)]
    g = _gaps(client)[0]["R1"]
    f = g["risk_factors"]
    record.actual(f"factors={f}; risk {g['risk_score']} ({g['risk_level']}); action: {g['recommended_action']}")
    assert (f["business_priority"], f["coverage_gap"], f["acceptance_criteria_gap"]) == (100.0, 100.0, 100.0)
    assert g["risk_level"] == "Critical" and g["recommended_action"].startswith("Generate 2 additional test cases")


@case(id="GAP-04", module=M, title="Healthy requirement is not reported as a gap",
      objective="Verify a requirement that is fully covered, passing, and covered by a high-quality test does not appear in the gap list.",
      expected="R1 absent from the Coverage Gaps response.")
def test_healthy_not_gap(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", "Must", LOGIN_AC)]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH, "approved")]
    by_id, raw = _gaps(client)
    record.actual(f"Gap list requirement ids: {list(by_id) or 'none'}")
    assert "R1" not in by_id


@case(id="GAP-05", module=M, title="AC coverage is independent of test execution results",
      objective="Verify a failing test still counts as textually covering its ACs in the RTM, while the gap analysis separately flags it through the test-failure factor.",
      expected="RTM row: FULLY COVERED, failed_tests 1. Gap: listed, test_failure_rate 100, AC gap 0, action 'Review and fix the failing linked test case(s)'.")
def test_ac_coverage_vs_execution(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", "Must", LOGIN_AC)]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH, "rejected")]
    row = client.get("/api/rtm/matrix", params=SCOPE).json()["rows"][0]
    g = _gaps(client)[0]["R1"]
    record.actual(f"RTM: {row['coverage_status']}, coverage {row['coverage_pct']}%, failed {row['failed_tests']}. "
                  f"Gap factors: AC gap {g['risk_factors']['acceptance_criteria_gap']}, failure rate {g['risk_factors']['test_failure_rate']}; "
                  f"action: {g['recommended_action']}")
    assert row["coverage_status"] == "FULLY COVERED" and row["failed_tests"] == 1
    assert g["risk_factors"]["acceptance_criteria_gap"] == 0.0 and g["risk_factors"]["test_failure_rate"] == 100.0
    assert g["recommended_action"].startswith("Review and fix the failing")


@case(id="GAP-06", module=M, title="Code coverage is a separate, project-level risk factor",
      objective="Verify GitHub code coverage only feeds the code_coverage_gap factor (100 - overall%) and never changes requirement AC coverage.",
      expected="No coverage report -> factor 50 (neutral); DONE report with overall 80% -> factor 20; RTM coverage_pct unchanged (66.7) in both cases.")
def test_code_coverage_separate(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", "Should", LOGIN_AC + [LOCKOUT_AC])]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH, "approved")]
    before_g = _gaps(client)[0]["R1"]
    before_row = client.get("/api/rtm/matrix", params=SCOPE).json()["rows"][0]
    db = SessionLocal()
    db.add(models.CoverageReport(project_id="P1", status=models.CoverageJobStatus.DONE, statement_coverage=85.0,
                                 branch_coverage=75.0, overall_coverage=80.0, files=[], logs=[]))
    db.commit(); db.close()
    after_g = _gaps(client)[0]["R1"]
    after_row = client.get("/api/rtm/matrix", params=SCOPE).json()["rows"][0]
    record.actual(f"code_coverage_gap: {before_g['risk_factors']['code_coverage_gap']} -> {after_g['risk_factors']['code_coverage_gap']}; "
                  f"RTM coverage_pct: {before_row['coverage_pct']} -> {after_row['coverage_pct']}")
    assert before_g["risk_factors"]["code_coverage_gap"] == 50.0 and after_g["risk_factors"]["code_coverage_gap"] == 20.0
    assert before_row["coverage_pct"] == after_row["coverage_pct"] == 66.7


@case(id="GAP-07", module=M, title="Risk score and risk-level boundaries",
      objective="Verify risk = mean of the five factors, with Critical >= 70, Medium 40-69.9, Low < 40.",
      expected="Each scenario's risk_score equals the factor mean; levels follow the 70 / 40 boundaries.")
def test_risk_formula_and_levels(record):
    scenarios = {
        "untested Must": compute_risk("Must", 3, 3, 0, 0.0, [], None, 62.5),
        "partial Should": compute_risk("Should", 3, 1, 1, 66.7, ["approved"], 85.0, 62.5),
        "covered Could": compute_risk("Could", 2, 0, 2, 100.0, ["approved", "approved"], 90.0, 85.0),
    }
    out = {}
    for name, r in scenarios.items():
        mean = round(sum(r["factors"].values()) / 5, 1)
        out[name] = (r["risk_score"], mean, r["risk_level"])
        assert r["risk_score"] == mean
        expected_level = "Critical" if mean >= 70 else ("Medium" if mean >= 40 else "Low")
        assert r["risk_level"] == expected_level
    record.actual(f"(risk, factor mean, level): {out}")


@case(id="GAP-08", module=M, title="Failure-rate fallback when nothing has been executed",
      objective="Verify the test-failure factor uses 100 - average predicted quality when no linked test has run, and 50 when no prediction is available.",
      expected="Unexecuted tests with avg quality 30 -> factor 70; no tests and no quality -> factor 50.")
def test_failure_rate_fallback(record):
    a = compute_risk("Should", 2, 0, 1, 100.0, ["pending"], 30.0, None)["factors"]["test_failure_rate"]
    b = compute_risk("Should", 2, 2, 0, 0.0, [], None, None)["factors"]["test_failure_rate"]
    record.actual(f"pending + quality 30 -> {a}; no data -> {b}")
    assert (a, b) == (70.0, 50.0)


@case(id="GAP-09", module=M, title="Covered but never executed",
      objective="Verify a requirement whose ACs are covered by a high-quality but unexecuted test is still flagged, with an 'execute' recommendation.",
      expected="Gap listed with action 'Execute the linked test case(s) ...'.")
def test_unverified_tests(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", "Must", LOGIN_AC)]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH, "pending")]
    g = _gaps(client)[0].get("R1")
    record.actual(f"Listed: {g is not None}; action: {g and g['recommended_action']}")
    assert g is not None and g["recommended_action"].startswith("Execute the linked test case")


@case(id="GAP-10", module=M, title="Low-quality covering test flagged as a gap",
      objective="Verify textual AC coverage is not enough when the covering test's predicted quality is below 70.",
      expected="Requirement with only a vague test listed; recommendation refers to improving low-quality tests or generating tests.")
def test_low_quality_gap(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", "Should", ["login"])]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_LOW, "approved")]
    g = _gaps(client)[0].get("R1")
    record.actual(f"Listed: {g is not None}; coverage {g and g['current_coverage_pct']}%; action: {g and g['recommended_action']}")
    assert g is not None and "quality" in g["recommended_action"].lower()


@case(id="GAP-11", module=M, title="Gaps sorted by risk (highest first)",
      objective="Verify the Coverage Gaps API returns gaps in descending order of risk score.",
      expected="risk_score sequence is non-increasing; untested Must requirement first.")
def test_sorted_by_risk(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", "Could", LOGIN_AC + [LOCKOUT_AC]), requirement("R2", "S2", "Must", LOGIN_AC),
                                    requirement("R3", "S3", "Should", LOGIN_AC)]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH, "approved"), make_test_case("T3", "S3", LOGIN_HIGH, "rejected")]
    _, raw = _gaps(client)
    seq = [(g["requirement_id"], g["risk_score"]) for g in raw]
    record.actual(f"Order: {seq}")
    assert [s for _, s in seq] == sorted([s for _, s in seq], reverse=True) and seq[0][0] == "R2"


@case(id="GAP-12", module=M, title="Test generation for an uncovered AC is grounded and idempotent",
      objective="Verify the generated Gherkin uses the criterion's own wording and the story persona, is scored by the model, and repeated requests reuse the same row.",
      expected="Text contains Given/When/Then, the AC wording and persona 'registered user'; requirement_coverage 100; same id on second call.")
def test_generate_gap_test(client, fake_components, record):
    body = {"project_id": "P1", "requirement_id": "R1", "requirement_text": "The system shall lock accounts after repeated failures",
            "user_story_id": "S1", "user_story_title": "User Login", "user_story_text": "As a registered user, I want to log in securely",
            "acceptance_criterion": LOCKOUT_AC}
    a = client.post("/api/rtm/c2-gaps/generate-test-case", json=body).json()
    b = client.post("/api/rtm/c2-gaps/generate-test-case", json=body).json()
    text = a["test_case"]["description"]
    record.add("Generated Gherkin", text)
    record.actual(f"ids {a['test_case']['id']} / {b['test_case']['id']}; coverage {a['prediction']['features']['requirement_coverage']}; "
                  f"score {a['prediction']['quality_score']} ({a['prediction']['formula_label']}), RF {a['prediction']['predicted_label']}")
    assert a["test_case"]["id"] == b["test_case"]["id"]
    assert all(k in text for k in ("Given", "When", "Then")) and "locked after five failed login attempts" in text
    assert "registered user" in text and a["prediction"]["features"]["requirement_coverage"] == 100.0


@case(id="GAP-13", module=M, title="Add generated test: validation of target and id",
      objective="Verify adding a generated test accepts only 'inventory' or 'rtm' and rejects unknown ids.",
      expected="target=rtm -> 200 with added_to_rtm true; target=bogus -> 400; unknown id -> 404.")
def test_add_generated_validation(client, fake_components, record):
    body = {"project_id": "P1", "requirement_id": "R1", "acceptance_criterion": LOCKOUT_AC, "user_story_title": "User Login"}
    gid = client.post("/api/rtm/c2-gaps/generate-test-case", json=body).json()["test_case"]["id"]
    ok = client.post(f"/api/rtm/c2-gaps/{gid}/add", json={"target": "rtm"})
    bad = client.post(f"/api/rtm/c2-gaps/{gid}/add", json={"target": "bogus"})
    missing = client.post("/api/rtm/c2-gaps/999999/add", json={"target": "rtm"})
    record.actual(f"rtm -> {ok.status_code} added_to_rtm={ok.json()['test_case']['added_to_rtm']}; bogus -> {bad.status_code}; unknown -> {missing.status_code}")
    assert ok.status_code == 200 and ok.json()["test_case"]["added_to_rtm"] is True
    assert bad.status_code == 400 and missing.status_code == 404


@case(id="GAP-14", module=M, title="Bulk generation for critical gaps",
      objective="Verify generate-all creates one test per (requirement, missing AC) pair in a single request.",
      expected="2 items -> 2 generated tests with distinct ids, each scored.")
def test_generate_all(client, fake_components, record):
    items = [{"project_id": "P1", "requirement_id": "R1", "acceptance_criterion": ac, "user_story_title": "User Login"} for ac in LOGIN_AC]
    r = client.post("/api/rtm/c2-gaps/generate-all", json={"items": items})
    gen = r.json()["generated"]
    record.actual(f"HTTP {r.status_code}; generated {len(gen)}; ids {[g['test_case']['id'] for g in gen]}; labels {[g['prediction']['predicted_label'] for g in gen]}")
    assert r.status_code == 200 and len({g["test_case"]["id"] for g in gen}) == 2
