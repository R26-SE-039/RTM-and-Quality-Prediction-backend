# RTM & Quality Prediction - Test Report

Generated: 2026-10-10T04:58:35.813827+00:00  
Suite: full (offline + live integration)  
Command: `pytest -q -rs`

**Total 73 | Passed 71 | Failed 2 | Blocked 0 | Not executed 0**

| ID | Module | Title | Status |
|---|---|---|---|
| API-01 | API & Integration | Health / readiness probe | Passed |
| API-02 | API & Integration | Frontend-to-backend endpoint contract | Passed |
| API-03 | API & Integration | Response shape matches the frontend Matrix type | Passed |
| API-04 | API & Integration | Component 1 unavailable -> clear 503 error | Passed |
| API-05 | API & Integration | Component 2 unavailable -> graceful degradation | Passed |
| API-06 | API & Integration | Missing required query parameters rejected | Passed |
| API-07 | API & Integration | Model and dataset transparency endpoints | Passed |
| API-08 | API & Integration | Quality predictions endpoint for a project | Passed |
| API-09 | API & Integration | Dashboard, inventory and portfolio consistency | Passed |
| API-10 | API & Integration | Component 2 client: unreachable service raises a typed error | Passed |
| API-11 | API & Integration | Component 1 client: unreachable service raises a typed error | Passed |
| API-12 | API & Integration | Code-coverage analysis disabled safely | Passed |
| API-13 | API & Integration | Existing functionality unaffected by the testing component | Passed |
| API-14 | API & Integration | Testing-dashboard endpoints | Passed |
| GAP-01 | Coverage Gap Detection | Acceptance-criterion coverage threshold (40% word overlap) | Passed |
| GAP-02 | Coverage Gap Detection | Uncovered acceptance criterion identified | Passed |
| GAP-03 | Coverage Gap Detection | Requirement with no linked test cases | Passed |
| GAP-04 | Coverage Gap Detection | Healthy requirement is not reported as a gap | Passed |
| GAP-05 | Coverage Gap Detection | AC coverage is independent of test execution results | Passed |
| GAP-06 | Coverage Gap Detection | Code coverage is a separate, project-level risk factor | Passed |
| GAP-07 | Coverage Gap Detection | Risk score and risk-level boundaries | Passed |
| GAP-08 | Coverage Gap Detection | Failure-rate fallback when nothing has been executed | Passed |
| GAP-09 | Coverage Gap Detection | Covered but never executed | Passed |
| GAP-10 | Coverage Gap Detection | Low-quality covering test flagged as a gap | Passed |
| GAP-11 | Coverage Gap Detection | Gaps sorted by risk (highest first) | Passed |
| GAP-12 | Coverage Gap Detection | Test generation for an uncovered AC is grounded and idempotent | Passed |
| GAP-13 | Coverage Gap Detection | Add generated test: validation of target and id | Passed |
| GAP-14 | Coverage Gap Detection | Bulk generation for critical gaps | Passed |
| IMP-01 | Intelligent Test Improvement | Quality gaps identified in a deficient test case | Passed |
| IMP-02 | Intelligent Test Improvement | Improved Given/When/Then scenarios generated | Passed |
| IMP-03 | Intelligent Test Improvement | Quality score recalculated through the same pipeline | Passed |
| IMP-04 | Intelligent Test Improvement | Improvement preserves the original test-case steps | Failed |
| IMP-05 | Intelligent Test Improvement | Improvement preserves the feature title | Passed |
| IMP-06 | Intelligent Test Improvement | Already-complete test case: no gaps reported | Passed |
| IMP-07 | Intelligent Test Improvement | Already-complete test case: score not reduced by improvement | Failed |
| IMP-08 | Intelligent Test Improvement | No linked requirement information available | Passed |
| IMP-09 | Intelligent Test Improvement | Invalid improvement request rejected | Passed |
| LIVE-01 | Live Integration | RTM service running with its database | Passed |
| LIVE-02 | Live Integration | API gateway routes RTM requests | Passed |
| LIVE-03 | Live Integration | Component 1 requirements-with-stories contract | Passed |
| LIVE-04 | Live Integration | Component 2 traceability contract | Passed |
| LIVE-05 | Live Integration | Live RTM rows match Component 1 requirements | Passed |
| LIVE-06 | Live Integration | Live test-case linkage matches Component 2 stories | Passed |
| LIVE-07 | Live Integration | Live quality predictions are internally consistent | Passed |
| LIVE-08 | Live Integration | Live coverage-gap ranking is consistent | Passed |
| LIVE-09 | Live Integration | Live dashboard agrees with the live RTM | Passed |
| QP-01 | Quality Prediction | Gherkin Given/When/Then structure detection | Passed |
| QP-02 | Quality Prediction | Completeness score calculation | Passed |
| QP-03 | Quality Prediction | Requirement-coverage metric against acceptance criteria | Passed |
| QP-04 | Quality Prediction | Specificity score (concrete values in steps) | Passed |
| QP-05 | Quality Prediction | Ambiguity score (vague wording) | Passed |
| QP-06 | Quality Prediction | Weighted quality-score formula | Passed |
| QP-07 | Quality Prediction | High / Medium / Low classification thresholds | Passed |
| QP-08 | Quality Prediction | Well-designed test case classified High | Passed |
| QP-09 | Quality Prediction | Deficient test case classified Low | Passed |
| QP-10 | Quality Prediction | PASS/FAIL is not part of the quality-label formula | Passed |
| QP-11 | Quality Prediction | Training labels derive from the formula, not from PASS/FAIL | Passed |
| QP-12 | Quality Prediction | Model prediction is robust to PASS/FAIL changes | Passed |
| QP-13 | Quality Prediction | Reported held-out accuracy is reproducible | Passed |
| QP-14 | Quality Prediction | Formula fallback when no trained model is present | Passed |
| QP-15 | Quality Prediction | Empty / non-Gherkin description handled safely | Passed |
| RTM-01 | RTM Generation | Component 1 requirement and user-story fields shown in the RTM | Passed |
| RTM-02 | RTM Generation | Component 2 test cases linked to the correct requirement | Passed |
| RTM-03 | RTM Generation | Unmatched test case (story not in Component 1) | Passed |
| RTM-04 | RTM Generation | Requirement with no linked test case | Passed |
| RTM-05 | RTM Generation | Partially covered requirement | Passed |
| RTM-06 | RTM Generation | Fully covered requirement | Passed |
| RTM-07 | RTM Generation | Requirement with no acceptance criteria (incomplete traceability data) | Passed |
| RTM-08 | RTM Generation | RTM summary aggregates | Passed |
| RTM-09 | RTM Generation | Execution status derived from Component 2 results | Passed |
| RTM-10 | RTM Generation | Generated gap test cases merged into the RTM | Passed |
| RTM-11 | RTM Generation | Requirement detail lookup | Passed |
| RTM-12 | RTM Generation | Two requirements sharing one user story | Passed |
