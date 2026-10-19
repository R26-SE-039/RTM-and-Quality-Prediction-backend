# RTM & Quality Prediction — Research Test Suite

Executable tests and evidence for the research component **"ML-Based Quality Prediction and
Requirements Traceability Matrix (RTM) Generation"**. Results are shown on the
**RTM → Testing** page of the frontend (`/rtm/testing`).

Every status in the report is the real pytest outcome of the last run. Expected results are
written in each test; actual results are captured from the system while the test runs.

## Setup (once)

```bash
cd RTM-and-Quality-Prediction-backend
source venv/bin/activate          # or create one: python3.11 -m venv venv
pip install -r requirements-dev.txt
```

The offline tests need nothing else: they use a throwaway SQLite database and in-process fakes
for Component 1 and Component 2, so they never touch the Neon database or modify the other
components.

## Running the tests

| Goal | Command |
|---|---|
| Offline suite (fast, ~3 s, no services needed) | `pytest -m "not live"` |
| Full suite (offline + live end-to-end) | `pytest` |
| One module | `pytest tests/test_quality_prediction.py` |
| Show why tests were blocked | `pytest -rs` |

The live tests read these optional environment variables:

| Variable | Default |
|---|---|
| `RTM_URL` | `http://localhost:8003` |
| `GATEWAY_URL` | `http://localhost:8081` |
| `C1_URL` | `http://localhost:8001` |
| `C2_URL` | `http://localhost:8002/api/v1` |
| `LIVE_PROJECT_ID`, `LIVE_ITERATION_ID` | auto-discovered: first Component 2 project with stories that have Gherkin test cases |

If a service is down, or no project has traceable data, the affected live tests are reported as
**Blocked** (pytest skip with a `BLOCKED:` reason). They are never counted as passed.

Each run writes:

* `tests/reports/latest.json`: the full evidence report read by the dashboard
* `tests/reports/latest.md`: a one-page summary table (useful for the dissertation appendix)
* `tests/reports/history/<timestamp>.json`: a copy of every run
* `tests/reports/manual_results.json`: manual check outcomes recorded on the dashboard

## Live demonstration workflow

1. Start the services: Component 1 (8001), Component 2 (8002), RTM backend (8003),
   auth service (3001), API gateway (8081, with `RTM_SERVICE_URL=http://localhost:8003`) and the
   frontend (5173).
2. Log in, open **RTM → Testing**.
3. Click **Run offline suite** (about 3 s) to show the algorithmic tests, then **Run full suite**
   (about 1–2 min) to add the live end-to-end checks against Components 1 and 2.
4. Use the module chart and summary table for the overview. Filter by module or status and expand a
   row to show its objective, expected result, actual result and evidence (for example the
   generated Gherkin text, the risk factors, or the Component 1 item compared with its RTM row).
5. Walk through the **Manually verified checks** (MAN-01 to MAN-07) on the real RTM pages and
   record Passed/Failed with a note. These stay separate from the automated results.
6. Click **Export JSON** to save the evidence for the report.

## What is covered (73 automated + 7 manual)

| Module | IDs | Level | What is verified |
|---|---|---|---|
| Quality Prediction | QP-01 – QP-15 | unit | Given/When/Then detection, completeness, requirement coverage, specificity, ambiguity, the weighted formula, High/Medium/Low bands, PASS/FAIL excluded from the formula and the dataset labels, model robustness to PASS/FAIL flips, held-out accuracy reproduced from the saved model, formula fallback, empty input |
| RTM Generation | RTM-01 – RTM-12 | API + unit | Component 1 fields carried into RTM rows, Component 2 tests linked by story, unmatched tests, no tests, partial/full coverage, requirements without ACs, summary aggregates, pass/fail derived from Component 2 executions (active suite, latest run), generated tests merged, detail endpoint, shared stories |
| Coverage Gap Detection | GAP-01 – GAP-14 | API + unit | 40% AC-overlap rule, uncovered ACs, untested requirements, healthy requirements excluded, AC coverage vs execution results vs code coverage, risk formula and bands, failure-rate fallback, unexecuted and low-quality coverage, risk ordering, grounded and idempotent test generation, add/validation, bulk generation |
| Intelligent Test Improvement | IMP-01 – IMP-09 | API + unit | Gap identification, generated Given/When/Then structure, score re-measured through the same pipeline, preservation of original steps and title, already-complete tests, no requirement information, request validation |
| API & Integration | API-01 – API-14 | API | Health probe, frontend↔backend contract (every call in `frontend/src/api/rtmApi.ts` resolves to a backend route), response shape, Component 1 outage (503), Component 2 outage (graceful), missing parameters (422), model/dataset endpoints, predictions, dashboard/inventory/portfolio consistency, real C1/C2 clients against an unreachable port, coverage disabled safely, pre-existing routes intact, testing endpoints |
| Live Integration | LIVE-01 – LIVE-09 | live E2E | Running RTM and gateway, Component 1 and Component 2 contracts, live RTM rows equal Component 1 items, live links equal Component 2 stories, live predictions consistent, live gap ranking consistent, dashboard equals matrix |

## Findings from the current implementation

Two tests fail against the current code. They are reported as research findings and the
implementation has not been changed:

* **IMP-04**: the improvement does not preserve the original steps (0 of 6 kept).
  `generate_improved_gherkin()` rebuilds the scenario from a template using only the title, story
  title and acceptance criteria. It never reads the original description, so concrete values are
  replaced rather than extended.
* **IMP-07**: improving an already-complete test lowers its score slightly (94.12 → 94.05),
  because specific quoted values are replaced with generic wording (specificity 100 → 71.4).

Behaviours the tests document (passing, but worth explaining):

* **RTM-07**: a requirement with no acceptance criteria and at least one linked test is shown as
  FULLY COVERED, because there is nothing to check.
* **RTM-03**: Component 2 test cases whose story is not in the Component 1 iteration are not
  shown in the RTM.

## Limitations

* The UI itself is verified manually (MAN-01 – MAN-07). There is no browser-automation framework
  in the frontend project, so UI rendering is not automated. The frontend↔backend contract is
  checked automatically by API-02.
* The training dataset is mostly synthetic. QP-13 proves the reported accuracy is reproducible from
  the saved model, not that it generalises to real projects.
* Code-coverage runs (cloning and building GitHub repositories) are not executed by the tests,
  because they need credentials and toolchains. API-12 verifies the disabled path, and GAP-06
  verifies how coverage results feed the risk score.
* Live results depend on the data in Components 1 and 2 at the time of the run.
* In the Docker image `tests/` is not copied, so the dashboard reports the suite as unavailable
  there. Run it from a source checkout.
