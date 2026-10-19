"""Module 2 - Requirements Traceability Matrix (app/services.py build_matrix, routers/rtm.py,
integrations/component2.get_traceability_test_cases)."""

import asyncio

import pytest

from app import models
from app.database import SessionLocal
from app.integrations import component2
from tests.sample_data import LOCKOUT_AC, LOGIN_AC, LOGIN_HIGH, LOGIN_LOW, CHECKOUT_TEXT, make_test_case, requirement

M = "RTM Generation"
case = pytest.mark.case
SCOPE = {"project_id": "P1", "iteration_id": "IT1"}


def _matrix(client):
    r = client.get("/api/rtm/matrix", params=SCOPE)
    assert r.status_code == 200, r.text
    return r.json()


@case(id="RTM-01", module=M, title="Component 1 requirement and user-story fields shown in the RTM",
      objective="Verify every requirement / user-story field received from Component 1 is carried into the matching RTM row unchanged.",
      expected="Row fields (requirement id/text/type/status, meeting, story id/title/text, priority, ACs) equal the Component 1 item.")
def test_c1_fields_mapped(client, fake_components, record):
    item = requirement("R1", "S1", "Must", LOGIN_AC, text="Users shall log in", title="User Login")
    fake_components.requirements = [item]
    row = _matrix(client)["rows"][0]
    keys = ["requirement_id", "requirement_text", "requirement_type", "requirement_status", "meeting_title",
            "user_story_id", "user_story_title", "user_story_text", "priority", "user_story_status", "acceptance_criteria"]
    mismatched = [k for k in keys if row[k] != item[k]]
    record.actual(f"{len(keys)} fields compared; mismatched: {mismatched or 'none'}")
    record.add("Component 1 item", item)
    record.add("RTM row (fields)", {k: row[k] for k in keys})
    assert mismatched == []
    assert fake_components.calls[0] == ("c1.requirements_with_stories", "IT1")


@case(id="RTM-02", module=M, title="Component 2 test cases linked to the correct requirement",
      objective="Verify each Component 2 test case is attached only to the requirement whose user_story_id equals the test's story_id.",
      expected="R1 (story S1) gets T1 and T2; R2 (story S2) gets only T3; no test appears under the wrong requirement.")
def test_c2_tests_linked_by_story(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", acs=LOGIN_AC), requirement("R2", "S2", acs=["Pay with a saved card"])]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH, "approved"),
                                  make_test_case("T2", "S1", LOGIN_LOW, "pending"),
                                  make_test_case("T3", "S2", CHECKOUT_TEXT, "rejected")]
    rows = {r["requirement_id"]: [t["id"] for t in r["tests"]] for r in _matrix(client)["rows"]}
    record.actual(f"Links: {rows}")
    assert rows == {"R1": ["T1", "T2"], "R2": ["T3"]}


@case(id="RTM-03", module=M, title="Unmatched test case (story not in Component 1)",
      objective="Verify a Component 2 test case whose story_id does not exist in the Component 1 iteration is not linked to any requirement and is not counted.",
      expected="Orphan test absent from all rows; summary total_tests counts only linked tests.")
def test_unmatched_test_case(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", acs=LOGIN_AC)]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH), make_test_case("ORPHAN", "S-unknown", LOGIN_HIGH)]
    m = _matrix(client)
    linked = [t["id"] for r in m["rows"] for t in r["tests"]]
    record.actual(f"Linked tests: {linked}; summary.total_tests = {m['summary']['total_tests']}")
    assert "ORPHAN" not in linked and m["summary"]["total_tests"] == 1


@case(id="RTM-04", module=M, title="Requirement with no linked test case",
      objective="Verify a requirement with no Component 2 test case is reported as NOT COVERED.",
      expected="coverage_status = NOT COVERED, total_tests = 0, coverage_pct = 0, every AC listed as missing.")
def test_requirement_without_tests(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", acs=LOGIN_AC)]
    row = _matrix(client)["rows"][0]
    record.actual(f"status={row['coverage_status']}; tests={row['total_tests']}; coverage={row['coverage_pct']}; missing={len(row['missing_acceptance_criteria'])}")
    assert row["coverage_status"] == "NOT COVERED" and row["total_tests"] == 0
    assert row["coverage_pct"] == 0.0 and row["missing_acceptance_criteria"] == LOGIN_AC


@case(id="RTM-05", module=M, title="Partially covered requirement",
      objective="Verify a requirement whose tests cover only some acceptance criteria is PARTIAL and lists the uncovered criteria.",
      expected="2 of 3 ACs covered -> PARTIAL, coverage 66.7%, missing = the account-lockout criterion.")
def test_partial_coverage(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", acs=LOGIN_AC + [LOCKOUT_AC])]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH, "approved")]
    row = _matrix(client)["rows"][0]
    record.actual(f"status={row['coverage_status']}; covered {row['covered_acceptance_criteria']}/{row['total_acceptance_criteria']} "
                  f"({row['coverage_pct']}%); missing={row['missing_acceptance_criteria']}")
    assert row["coverage_status"] == "PARTIAL" and row["coverage_pct"] == 66.7
    assert row["missing_acceptance_criteria"] == [LOCKOUT_AC]


@case(id="RTM-06", module=M, title="Fully covered requirement",
      objective="Verify a requirement whose linked tests cover every acceptance criterion is FULLY COVERED.",
      expected="coverage_status = FULLY COVERED, coverage_pct = 100, no missing ACs.")
def test_full_coverage(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", acs=LOGIN_AC)]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH, "approved")]
    row = _matrix(client)["rows"][0]
    record.actual(f"status={row['coverage_status']}; coverage={row['coverage_pct']}; missing={row['missing_acceptance_criteria']}")
    assert row["coverage_status"] == "FULLY COVERED" and row["coverage_pct"] == 100.0


@case(id="RTM-07", module=M, title="Requirement with no acceptance criteria (incomplete traceability data)",
      objective="Document how the RTM treats a requirement that arrives from Component 1 with an empty acceptance-criteria list.",
      expected="Implemented behaviour: with >=1 linked test the row is FULLY COVERED at 100% (nothing to miss); with no test it is NOT COVERED.")
def test_requirement_without_acs(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", acs=[]), requirement("R2", "S2", acs=[])]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH)]
    rows = {r["requirement_id"]: (r["coverage_status"], r["coverage_pct"], r["total_acceptance_criteria"]) for r in _matrix(client)["rows"]}
    record.actual(f"(status, coverage%, #ACs): {rows}")
    record.add("Note", "A requirement with no acceptance criteria cannot be checked at AC level, so any linked test makes it 'fully covered'. "
                       "Reviewers should treat such rows as a data-quality issue in Component 1.")
    assert rows == {"R1": ("FULLY COVERED", 100.0, 0), "R2": ("NOT COVERED", 100.0, 0)}


@case(id="RTM-08", module=M, title="RTM summary aggregates",
      objective="Verify the matrix summary counts requirements by status, tests by result, pass rate over executed tests, and average coverage.",
      expected="3 requirements (1 full, 1 partial, 1 not covered); 3 tests: 1 passed, 1 failed, 1 pending; pass rate 50%; defects 1; avg coverage = mean of row coverage.")
def test_summary_aggregates(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", acs=LOGIN_AC), requirement("R2", "S2", acs=LOGIN_AC + [LOCKOUT_AC]),
                                    requirement("R3", "S3", acs=["Pay with a saved card"])]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH, "approved"), make_test_case("T2", "S2", LOGIN_HIGH, "rejected"),
                                  make_test_case("T3", "S2", LOGIN_LOW, "pending")]
    m = _matrix(client)
    s = m["summary"]
    expected_avg = round(sum(r["coverage_pct"] for r in m["rows"]) / 3, 1)
    record.actual(f"Summary: {s}")
    assert (s["total_requirements"], s["fully_covered"], s["partially_covered"], s["not_covered"]) == (3, 1, 1, 1)
    assert (s["total_tests"], s["passed_tests"], s["failed_tests"], s["pending_tests"]) == (3, 1, 1, 1)
    assert s["pass_rate"] == 50.0 and s["defects"] == 1 and s["avg_coverage_pct"] == expected_avg


@case(id="RTM-09", module=M, title="Execution status derived from Component 2 results",
      objective="Verify Component 2's traceability payload is mapped to test status using only ACTIVE suites and only the LATEST execution, matching scenario titles by word overlap.",
      expected="Gherkin A: latest run of active suite passed -> approved (older failure ignored); Gherkin B: failed in latest run -> rejected; "
               "Gherkin C: only in an inactive suite -> pending; Gherkin D: no matching result -> pending.")
def test_status_mapping_from_c2(monkeypatch, record):
    def g(gid, scen):
        return {"id": gid, "feature_name": f"Feature {gid}", "gherkin_text": f"Feature: {gid}\n  Scenario: {scen}\n    Given x\n    When y\n    Then z\n"}

    payload = {
        "stories": [{"id": "S1", "gherkin_scenarios": [g("A", "user logs in successfully"), g("B", "user resets password"),
                                                        g("C", "user deletes account"), g("D", "user exports report")]}],
        "suites": [{"id": "SU1", "is_active": True, "source_scenario_ids": ["A", "B", "D"]},
                   {"id": "SU0", "is_active": False, "source_scenario_ids": ["C"]}],
        "executions": [  # newest first, as Component 2 returns them
            {"suite_id": "SU1", "scenario_results": [{"scenario_name": "test_user_logs_in_successfully", "result": "PASS"},
                                                     {"scenario_name": "test_user_resets_password", "result": "FAIL"}]},
            {"suite_id": "SU1", "scenario_results": [{"scenario_name": "test_user_logs_in_successfully", "result": "FAIL"}]},
            {"suite_id": "SU0", "scenario_results": [{"scenario_name": "test_user_deletes_account", "result": "FAIL"}]},
        ],
    }
    seen = {}

    async def fake_get(path, params=None, headers=None):
        seen["path"], seen["params"] = path, params
        return payload

    monkeypatch.setattr(component2, "_get", fake_get)
    tcs = asyncio.run(component2.get_traceability_test_cases("P1", iteration_id="IT1"))
    status = {t["id"]: t["status"] for t in tcs}
    record.actual(f"Statuses: {status}; request: {seen['path']} {seen['params']}")
    record.add("Component 2 payload (abridged)", payload["suites"])
    assert status == {"A": "approved", "B": "rejected", "C": "pending", "D": "pending"}
    assert all(t["story_id"] == "S1" for t in tcs)
    assert seen["path"] == "/projects/P1/traceability" and seen["params"]["iteration_id"] == "IT1"


@case(id="RTM-10", module=M, title="Generated gap test cases merged into the RTM",
      objective="Verify a gap test case added to the RTM appears in its requirement row with source = generated and contributes to coverage.",
      expected="Row contains the generated test (id gap-<n>, source generated); lockout AC becomes covered.")
def test_generated_tests_merged(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", acs=LOGIN_AC + [LOCKOUT_AC], title="User Login")]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH, "approved")]
    before = _matrix(client)["rows"][0]
    body = {"project_id": "P1", "requirement_id": "R1", "requirement_text": "Accounts lock", "user_story_id": "S1",
            "user_story_title": "User Login", "user_story_text": "As a registered user, I want to log in", "acceptance_criterion": LOCKOUT_AC}
    gen = client.post("/api/rtm/c2-gaps/generate-test-case", json=body).json()
    client.post(f"/api/rtm/c2-gaps/{gen['test_case']['id']}/add", json={"target": "rtm"})
    after = _matrix(client)["rows"][0]
    record.actual(f"Before: {before['coverage_status']} {before['coverage_pct']}% tests={[t['id'] for t in before['tests']]}; "
                  f"After: {after['coverage_status']} {after['coverage_pct']}% tests={[(t['id'], t['source']) for t in after['tests']]}")
    assert any(t["source"] == "generated" for t in after["tests"])
    assert after["coverage_status"] == "FULLY COVERED" and before["coverage_status"] == "PARTIAL"


@case(id="RTM-11", module=M, title="Requirement detail lookup",
      objective="Verify the requirement-detail endpoint returns the matching row and 404 for an unknown requirement.",
      expected="Known id -> 200 with that requirement; unknown id -> 404 'Requirement not found in this iteration'.")
def test_requirement_detail(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", acs=LOGIN_AC)]
    ok = client.get("/api/rtm/matrix/requirements/R1", params=SCOPE)
    missing = client.get("/api/rtm/matrix/requirements/NOPE", params=SCOPE)
    record.actual(f"R1 -> {ok.status_code} ({ok.json()['requirement_id']}); NOPE -> {missing.status_code} {missing.json()}")
    assert ok.status_code == 200 and ok.json()["requirement_id"] == "R1"
    assert missing.status_code == 404


@case(id="RTM-12", module=M, title="Two requirements sharing one user story",
      objective="Document the implemented behaviour when Component 1 links two requirements to the same user story.",
      expected="Both requirement rows list the story's test cases (traceability is via the shared story).")
def test_shared_story(client, fake_components, record):
    fake_components.requirements = [requirement("R1", "S1", acs=LOGIN_AC), requirement("R2", "S1", acs=[LOCKOUT_AC])]
    fake_components.test_cases = [make_test_case("T1", "S1", LOGIN_HIGH)]
    rows = {r["requirement_id"]: ([t["id"] for t in r["tests"]], r["coverage_status"]) for r in _matrix(client)["rows"]}
    record.actual(f"Rows: {rows}")
    assert rows["R1"][0] == ["T1"] and rows["R2"][0] == ["T1"]
