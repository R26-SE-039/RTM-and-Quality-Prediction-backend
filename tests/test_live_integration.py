"""Module 6 - Live end-to-end integration against the RUNNING services (read-only GET requests only).

Service URLs (override with environment variables):
  RTM_URL      default http://localhost:8003        RTM backend (this service)
  GATEWAY_URL  default http://localhost:8081        NextGen QA API gateway (frontend's entry point)
  C1_URL       default http://localhost:8001        Component 1
  C2_URL       default http://localhost:8002/api/v1 Component 2
  LIVE_PROJECT_ID / LIVE_ITERATION_ID               optional; otherwise auto-discovered from Component 2

If a service is not running, or no project has traceable data, the affected tests are reported as
BLOCKED (not passed).
"""

import os

import httpx
import pytest

from app.ml.c2_features import compute_quality_score, quality_label

pytestmark = pytest.mark.live
M = "Live Integration"
case = pytest.mark.case

RTM = os.getenv("RTM_URL", "http://localhost:8003").rstrip("/")
GATEWAY = os.getenv("GATEWAY_URL", "http://localhost:8081").rstrip("/")
C1 = os.getenv("C1_URL", "http://localhost:8001").rstrip("/")
C2 = os.getenv("C2_URL", "http://localhost:8002/api/v1").rstrip("/")
SLOW = 120.0


_cache: dict = {}


def _get(url, **params):
    """Read-only GET; identical requests within one run are served once (keeps the live demo fast)."""
    key = (url, tuple(sorted(params.items())))
    if key in _cache:
        return _cache[key]
    try:
        r = httpx.get(url, params=params or None, timeout=SLOW)
    except httpx.HTTPError as e:
        pytest.skip(f"BLOCKED: {url} unreachable ({type(e).__name__})")
    _cache[key] = r
    return r


@pytest.fixture(scope="module")
def scope():
    """Find a Component 2 project + iteration that has stories with Gherkin test cases."""
    pid, iid = os.getenv("LIVE_PROJECT_ID"), os.getenv("LIVE_ITERATION_ID")
    try:
        if pid and iid:
            trace = httpx.get(f"{C2}/projects/{pid}/traceability", params={"light": "true", "iteration_id": iid}, timeout=SLOW).json()
            return {"project_id": pid, "iteration_id": iid, "trace": trace}
        projects = httpx.get(f"{C2}/projects", timeout=SLOW).json()
    except httpx.HTTPError as e:
        pytest.skip(f"BLOCKED: Component 2 unreachable at {C2} ({type(e).__name__})")
    for p in projects:
        try:
            trace = httpx.get(f"{C2}/projects/{p['id']}/traceability", params={"light": "true"}, timeout=SLOW).json()
        except httpx.HTTPError:
            continue
        for story in trace.get("stories", []):
            if story.get("iteration_id") and story.get("gherkin_scenarios"):
                iid = story["iteration_id"]
                trace = httpx.get(f"{C2}/projects/{p['id']}/traceability", params={"light": "true", "iteration_id": iid}, timeout=SLOW).json()
                return {"project_id": p["id"], "project_name": p.get("name"), "iteration_id": iid, "trace": trace}
    pytest.skip("BLOCKED: no Component 2 project has stories with Gherkin test cases and an iteration id")


def _params(scope):
    return {"project_id": scope["project_id"], "iteration_id": scope["iteration_id"]}


@case(id="LIVE-01", module=M, level="live", title="RTM service running with its database",
      objective="Verify the deployed RTM backend answers its readiness probe.",
      expected=f"GET {RTM}/api/health -> 200 {{status: ok, database: up}}.")
def test_live_rtm_health(record):
    r = _get(f"{RTM}/api/health")
    record.actual(f"HTTP {r.status_code} {r.text[:120]}")
    assert r.status_code == 200 and r.json()["database"] == "up"


@case(id="LIVE-02", module=M, level="live", title="API gateway routes RTM requests",
      objective="Verify the path the browser uses (gateway /api/rtm prefix) reaches the RTM backend.",
      expected=f"GET {GATEWAY}/api/rtm/api/health -> 200 with database up.")
def test_live_gateway(record):
    r = _get(f"{GATEWAY}/api/rtm/api/health")
    record.actual(f"HTTP {r.status_code} {r.text[:120]}")
    assert r.status_code == 200 and r.json()["database"] == "up"


@case(id="LIVE-03", module=M, level="live", title="Component 1 requirements-with-stories contract",
      objective="Verify Component 1 serves the endpoint and fields the RTM depends on, for a real iteration.",
      expected="HTTP 200 with items[]; every item has requirement_id, requirement_text, user_story_id, priority, acceptance_criteria.")
def test_live_c1_contract(scope, record):
    r = _get(f"{C1}/api/v1/pipeline/iterations/{scope['iteration_id']}/requirements-with-stories")
    items = r.json().get("items", []) if r.status_code == 200 else []
    need = {"requirement_id", "requirement_text", "user_story_id", "priority", "acceptance_criteria"}
    bad = [i.get("requirement_id") for i in items if not need <= set(i)]
    record.actual(f"HTTP {r.status_code}; iteration {scope['iteration_id']}; {len(items)} items; items missing fields: {bad or 'none'}")
    if items:
        record.add("Sample item", items[0])
    assert r.status_code == 200 and not bad


@case(id="LIVE-04", module=M, level="live", title="Component 2 traceability contract",
      objective="Verify Component 2's traceability payload has the stories / gherkin_scenarios / suites / executions structure the RTM parses.",
      expected="Keys stories, suites, executions present; each Gherkin scenario has id and gherkin_text.")
def test_live_c2_contract(scope, record):
    t = scope["trace"]
    gherkins = [g for s in t.get("stories", []) for g in s.get("gherkin_scenarios", [])]
    bad = [g.get("id") for g in gherkins if not {"id", "gherkin_text"} <= set(g)]
    record.actual(f"Project {scope.get('project_name', scope['project_id'])}: {len(t.get('stories', []))} stories, {len(gherkins)} Gherkin test cases, "
                  f"{len(t.get('suites', []))} suites, {len(t.get('executions', []))} executions; malformed: {bad or 'none'}")
    assert {"stories", "suites", "executions"} <= set(t) and gherkins and not bad


@case(id="LIVE-05", module=M, level="live", title="Live RTM rows match Component 1 requirements",
      objective="Verify the live RTM has exactly one row per Component 1 (requirement, user story) item with identical requirement / story fields.",
      expected="One RTM row per Component 1 item, matched on (requirement_id, user_story_id); text, story title and priority identical.")
def test_live_rows_match_c1(scope, record):
    items = _get(f"{C1}/api/v1/pipeline/iterations/{scope['iteration_id']}/requirements-with-stories").json().get("items", [])
    m = _get(f"{RTM}/api/rtm/matrix", **_params(scope))
    assert m.status_code == 200, m.text
    rows = {(r["requirement_id"], r["user_story_id"]): r for r in m.json()["rows"]}
    key = lambda i: (i["requirement_id"], i["user_story_id"])  # a requirement may have several user stories
    mism = [key(i) for i in items if key(i) not in rows or any(
        rows[key(i)][k] != i[k] for k in ("requirement_text", "user_story_title", "priority"))]
    record.actual(f"Component 1 items: {len(items)} ({len({i['requirement_id'] for i in items})} requirements); "
                  f"RTM rows: {len(m.json()['rows'])}; mismatched: {mism or 'none'}")
    record.add("Live summary", m.json()["summary"])
    assert len(m.json()["rows"]) == len(items) and not mism


@case(id="LIVE-06", module=M, level="live", title="Live test-case linkage matches Component 2 stories",
      objective="Verify every test in the live RTM belongs to the same user story in Component 2, and every Component 2 test case whose story is in the iteration appears in the RTM.",
      expected="0 tests linked to the wrong story; 0 Component 2 test cases (for stories present in Component 1) missing from the RTM.")
def test_live_linkage(scope, record):
    story_of = {g["id"]: s["id"] for s in scope["trace"].get("stories", []) for g in s.get("gherkin_scenarios", [])}
    rows = _get(f"{RTM}/api/rtm/matrix", **_params(scope)).json()["rows"]
    wrong = [(t["id"], r["user_story_id"]) for r in rows for t in r["tests"] if t["source"] == "C2" and story_of.get(t["id"]) != r["user_story_id"]]
    rtm_stories = {r["user_story_id"] for r in rows}
    linked = {t["id"] for r in rows for t in r["tests"]}
    missing = [gid for gid, sid in story_of.items() if sid in rtm_stories and gid not in linked]
    unmatched = [gid for gid, sid in story_of.items() if sid not in rtm_stories]
    record.actual(f"{len(linked)} linked tests; wrong-story links: {wrong or 'none'}; missing: {missing or 'none'}; "
                  f"Component 2 tests whose story is not in Component 1 (not shown): {len(unmatched)}")
    assert not wrong and not missing


@case(id="LIVE-07", module=M, level="live", title="Live quality predictions are internally consistent",
      objective="Verify the live predictions endpoint scores every Component 2 test case and that each score equals the formula applied to its returned features.",
      expected="One prediction per Component 2 test case; quality_score == formula(features); formula_label consistent; predicted_label in {High, Medium, Low}.")
def test_live_predictions(scope, record):
    r = _get(f"{RTM}/api/ml/c2-quality/predictions/{scope['project_id']}", iteration_id=scope["iteration_id"])
    assert r.status_code == 200, r.text
    preds = r.json()
    bad = [p["test_case_id"] for p in preds if compute_quality_score(p["features"]) != p["quality_score"]
           or quality_label(p["quality_score"]) != p["formula_label"] or p["predicted_label"] not in ("High", "Medium", "Low")]
    n_c2 = sum(len(s.get("gherkin_scenarios", [])) for s in scope["trace"].get("stories", []))
    record.actual(f"{len(preds)} predictions for {n_c2} Component 2 test cases; inconsistent: {bad or 'none'}; "
                  f"labels: {[p['predicted_label'] for p in preds]}")
    assert len(preds) == n_c2 and not bad


@case(id="LIVE-08", module=M, level="live", title="Live coverage-gap ranking is consistent",
      objective="Verify live gaps carry a risk score equal to the mean of their factors, a matching level, and are sorted by risk.",
      expected="For every gap: risk_score == mean(factors), level from 70/40 bands; list non-increasing by risk.")
def test_live_gaps(scope, record):
    r = _get(f"{RTM}/api/rtm/c2-gaps", **_params(scope))
    assert r.status_code == 200, r.text
    gaps = r.json()
    bad = []
    for g in gaps:
        mean = round(sum(g["risk_factors"].values()) / 5, 1)
        level = "Critical" if mean >= 70 else ("Medium" if mean >= 40 else "Low")
        if g["risk_score"] != mean or g["risk_level"] != level:
            bad.append(g["requirement_id"])
    scores = [g["risk_score"] for g in gaps]
    record.actual(f"{len(gaps)} gaps; risk scores {scores}; inconsistent: {bad or 'none'}")
    if gaps:
        record.add("Top gap", {k: gaps[0][k] for k in ("requirement_text", "risk_score", "risk_level", "risk_factors", "recommended_action")})
    assert not bad and scores == sorted(scores, reverse=True)


@case(id="LIVE-09", module=M, level="live", title="Live dashboard agrees with the live RTM",
      objective="Verify the dashboard summary is built from the same live matrix.",
      expected="Dashboard matrix summary == RTM matrix summary; quality buckets sum to total tests.")
def test_live_dashboard(scope, record):
    d = _get(f"{RTM}/api/dashboard/summary", **_params(scope)).json()
    m = _get(f"{RTM}/api/rtm/matrix", **_params(scope)).json()
    buckets = sum(b["tests"] for b in d["quality_distribution"])
    record.actual(f"dashboard total_tests={d['matrix']['total_tests']}, matrix total_tests={m['summary']['total_tests']}, buckets={buckets}; "
                  f"avg quality {d['avg_quality_score']}")
    assert d["matrix"] == m["summary"] and buckets == m["summary"]["total_tests"]
