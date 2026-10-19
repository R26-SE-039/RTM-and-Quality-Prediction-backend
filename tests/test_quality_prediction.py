"""Module 1 - Test-Case Quality Prediction (app/ml/c2_features.py, c2_predict.py, c2_train.py)."""

import os

import pandas as pd
import pytest

from app.ml import c2_predict
from app.ml.c2_dataset import DATA_PATH
from app.ml.c2_features import (
    FEATURE_ORDER,
    LABEL_ORDER,
    QUALITY_WEIGHTS,
    compute_quality_score,
    extract_features,
    quality_label,
)
from app.ml.c2_predict import predict_c2_quality
from tests.sample_data import LOGIN_AC, LOGIN_HIGH, LOGIN_LOW

M = "Quality Prediction"
case = pytest.mark.case


def _tc(text, status="pending"):
    return {"id": "T", "title": "t", "description": text, "status": status}


@case(id="QP-01", module=M, title="Gherkin Given/When/Then structure detection",
      objective="Verify that Given (precondition), When (test step) and Then (expected result) are detected from Gherkin text, including Background as a precondition.",
      expected="Complete scenario -> all three flags = 1; scenario with only a When step -> preconditions 0, steps 1, expected result 0; a Background block counts as a precondition.")
def test_gherkin_structure_detection(record):
    hi = extract_features(_tc(LOGIN_HIGH))
    lo = extract_features(_tc(LOGIN_LOW))
    bg = extract_features(_tc("Feature: X\n  Background:\n    * the app is open\n  Scenario: s\n    When x\n    Then y\n"))
    record.actual(f"Complete: Given={hi['has_preconditions']} When={hi['has_test_steps']} Then={hi['has_expected_result']}")
    record.actual(f"When-only: Given={lo['has_preconditions']} When={lo['has_test_steps']} Then={lo['has_expected_result']}")
    record.actual(f"Background block: has_preconditions={bg['has_preconditions']}")
    record.add("Input (complete)", LOGIN_HIGH)
    record.add("Input (When-only)", LOGIN_LOW)
    assert (hi["has_preconditions"], hi["has_test_steps"], hi["has_expected_result"]) == (1, 1, 1)
    assert (lo["has_preconditions"], lo["has_test_steps"], lo["has_expected_result"]) == (0, 1, 0)
    assert bg["has_preconditions"] == 1


@case(id="QP-02", module=M, title="Completeness score calculation",
      objective="Verify completeness = 25 x (Given + When + Then present) + 25 x min(scenarios, 3)/3.",
      expected="Two-scenario complete feature -> 75 + 16.7 = 91.7; one-scenario When-only feature -> 25 + 8.3 = 33.3.")
def test_completeness_score(record):
    hi = extract_features(_tc(LOGIN_HIGH))["completeness_score"]
    lo = extract_features(_tc(LOGIN_LOW))["completeness_score"]
    record.actual(f"Complete two-scenario feature: {hi}; When-only feature: {lo}")
    assert hi == pytest.approx(91.7, abs=0.05)
    assert lo == pytest.approx(33.3, abs=0.05)


@case(id="QP-03", module=M, title="Requirement-coverage metric against acceptance criteria",
      objective="Verify requirement_coverage measures how much of the linked acceptance-criteria vocabulary appears in the test, and is 0 when no criteria are linked.",
      expected="Login test vs login ACs -> high coverage (>60); same test with no ACs -> 0; unrelated checkout test vs login ACs -> low (<40).")
def test_requirement_coverage(record):
    from tests.sample_data import CHECKOUT_TEXT

    linked = extract_features(_tc(LOGIN_HIGH), True, LOGIN_AC)["requirement_coverage"]
    none = extract_features(_tc(LOGIN_HIGH), False, [])["requirement_coverage"]
    unrelated = extract_features(_tc(CHECKOUT_TEXT), True, LOGIN_AC)["requirement_coverage"]
    record.actual(f"Login test vs login ACs: {linked}; no ACs: {none}; checkout test vs login ACs: {unrelated}")
    record.add("Acceptance criteria", LOGIN_AC)
    assert linked > 60
    assert none == 0.0
    assert unrelated < 40


@case(id="QP-04", module=M, title="Specificity score (concrete values in steps)",
      objective="Verify specificity = % of Given/When/Then/And/But steps containing a quoted literal or a number.",
      expected="All steps of the login test use quoted values -> 100; vague step -> 0; 1 of 2 steps specific -> 50.")
def test_specificity_score(record):
    hi = extract_features(_tc(LOGIN_HIGH))["specificity_score"]
    lo = extract_features(_tc(LOGIN_LOW))["specificity_score"]
    half = extract_features(_tc('Feature: X\n  Scenario: s\n    When the user clicks "Save"\n    Then it works\n'))["specificity_score"]
    record.actual(f"Specific test: {hi}; vague test: {lo}; half-specific test: {half}")
    assert (hi, lo, half) == (100.0, 0.0, 50.0)


@case(id="QP-05", module=M, title="Ambiguity score (vague wording)",
      objective="Verify ambiguity counts vague words (e.g. some, properly, appropriate) per 100 words, scaled and capped at 100.",
      expected="Precise login test -> 0; 'When some action is performed properly' -> 100 (capped).")
def test_ambiguity_score(record):
    hi = extract_features(_tc(LOGIN_HIGH))["ambiguity_score"]
    lo = extract_features(_tc(LOGIN_LOW))["ambiguity_score"]
    record.actual(f"Precise test ambiguity: {hi}; vague test ambiguity: {lo}")
    assert hi == 0.0
    assert lo == 100.0


@case(id="QP-06", module=M, title="Weighted quality-score formula",
      objective="Verify the 0-100 quality score equals the documented weighted formula and that the weights sum to 1.",
      expected="score = 0.20*completeness + 0.20*coverage + 0.15*specificity + 15*Then + 10*Given + 10*When + 0.10*(100-ambiguity); weights sum to 1.0.")
def test_weighted_formula(record):
    f = extract_features(_tc(LOGIN_HIGH, "approved"), True, LOGIN_AC)
    manual = (0.20 * f["completeness_score"] + 0.20 * f["requirement_coverage"] + 0.15 * f["specificity_score"]
              + 15 * f["has_expected_result"] + 10 * f["has_preconditions"] + 10 * f["has_test_steps"]
              + 0.10 * (100 - f["ambiguity_score"]))
    got = compute_quality_score(f)
    record.actual(f"Manual formula = {manual:.2f}; compute_quality_score = {got}; sum of weights = {sum(QUALITY_WEIGHTS.values()):.2f}")
    record.add("Weights", QUALITY_WEIGHTS)
    assert got == pytest.approx(manual, abs=0.01)
    assert sum(QUALITY_WEIGHTS.values()) == pytest.approx(1.0)


@case(id="QP-07", module=M, title="High / Medium / Low classification thresholds",
      objective="Verify score-to-label bands: High >= 80, Medium 60-79.99, Low < 60.",
      expected="100->High, 80->High, 79.99->Medium, 60->Medium, 59.99->Low, 0->Low.")
def test_label_thresholds(record):
    pairs = {s: quality_label(s) for s in (100, 80, 79.99, 60, 59.99, 0)}
    record.actual(", ".join(f"{k}->{v}" for k, v in pairs.items()))
    assert pairs == {100: "High", 80: "High", 79.99: "Medium", 60: "Medium", 59.99: "Low", 0: "Low"}


@case(id="QP-08", module=M, title="Well-designed test case classified High",
      objective="Verify the full pipeline (feature extraction -> formula -> Random Forest) rates a complete, specific, requirement-linked test case as High.",
      expected="Formula label High, Random Forest label High, method = random_forest.")
def test_prediction_high(record):
    f = extract_features(_tc(LOGIN_HIGH, "approved"), True, LOGIN_AC)
    p = predict_c2_quality(f)
    record.actual(f"Score {p['quality_score']} ({p['formula_label']}); RF {p['predicted_label']} "
                  f"P(High)={p['probabilities'].get('High', 0):.3f}; method={p['method']}")
    record.add("Extracted features", f)
    assert p["formula_label"] == "High" and p["predicted_label"] == "High"
    assert p["method"] == "random_forest"


@case(id="QP-09", module=M, title="Deficient test case classified Low",
      objective="Verify a vague, incomplete test case with no linked requirement is rated Low by both the formula and the model.",
      expected="Formula label Low, Random Forest label Low.")
def test_prediction_low(record):
    f = extract_features(_tc(LOGIN_LOW), False, [])
    p = predict_c2_quality(f)
    record.actual(f"Score {p['quality_score']} ({p['formula_label']}); RF {p['predicted_label']} P(Low)={p['probabilities'].get('Low', 0):.3f}")
    record.add("Extracted features", f)
    assert p["formula_label"] == "Low" and p["predicted_label"] == "Low"


@case(id="QP-10", module=M, title="PASS/FAIL is not part of the quality-label formula",
      objective="Verify execution outcome (test_result) has no effect on the quality score / label that defines the training labels.",
      expected="Score and formula label identical for test_result = 0 (failed), 0.5 (pending), 1 (passed); test_result is not a formula weight.")
def test_pass_fail_not_in_formula(record):
    f = extract_features(_tc(LOGIN_HIGH, "approved"), True, LOGIN_AC)
    scores = {r: compute_quality_score(dict(f, test_result=r)) for r in (0.0, 0.5, 1.0)}
    record.actual(f"Scores by test_result: {scores}; weight keys: {sorted(QUALITY_WEIGHTS)}")
    assert len(set(scores.values())) == 1
    assert "test_result" not in QUALITY_WEIGHTS


@case(id="QP-11", module=M, title="Training labels derive from the formula, not from PASS/FAIL",
      objective="Verify every row of the training dataset is labelled by the weighted formula over its own features, and that test_result is only weakly correlated with the label.",
      expected="100% of rows: quality_label == formula label; |corr(test_result, label)| < 0.2.")
def test_dataset_labels_from_formula(record):
    if not os.path.exists(DATA_PATH):
        pytest.skip("BLOCKED: training dataset app/ml/data/c2_quality_dataset.csv is missing")
    df = pd.read_csv(DATA_PATH)
    recomputed = df.apply(lambda r: quality_label(compute_quality_score({k: r[k] for k in FEATURE_ORDER})), axis=1)
    agree = float((recomputed == df["quality_label"]).mean())
    corr = float(df["test_result"].corr(df["quality_label"].map({l: i for i, l in enumerate(LABEL_ORDER)})))
    record.actual(f"Rows: {len(df)}; formula-label agreement: {agree:.1%}; corr(test_result, label) = {corr:.3f}")
    record.add("Label distribution", df["quality_label"].value_counts().to_dict())
    assert agree == 1.0
    assert abs(corr) < 0.2


@case(id="QP-12", module=M, title="Model prediction is robust to PASS/FAIL changes",
      objective="Verify the trained Random Forest does not use execution outcome as a shortcut: flipping only test_result should almost never change its prediction.",
      expected="Predicted label unchanged when test_result is flipped (0<->1) for >= 95% of dataset rows.")
def test_model_insensitive_to_pass_fail(record):
    bundle = c2_predict._load_bundle()
    if bundle is None:
        pytest.skip("BLOCKED: trained model c2_quality_model.joblib not found")
    df = pd.read_csv(DATA_PATH)
    X = df[FEATURE_ORDER].copy()
    flipped = X.copy()
    flipped["test_result"] = 1.0 - flipped["test_result"]
    pipe = bundle["pipeline"]
    a, b = pipe.predict(X.values), pipe.predict(flipped.values)
    unchanged = float((a == b).mean())
    record.actual(f"Prediction unchanged for {unchanged:.1%} of {len(df)} rows after flipping test_result")
    assert unchanged >= 0.95


@case(id="QP-13", module=M, title="Reported held-out accuracy is reproducible",
      objective="Re-create the stratified 80/20 split (random_state=42) used in training and re-evaluate the saved model, confirming the accuracy shown in the UI is genuine.",
      expected="Re-computed held-out accuracy equals the stored metadata accuracy and is >= 0.85 (proposal target).")
def test_holdout_accuracy_reproducible(record):
    from sklearn.metrics import accuracy_score
    from sklearn.model_selection import train_test_split

    bundle = c2_predict._load_bundle()
    if bundle is None:
        pytest.skip("BLOCKED: trained model c2_quality_model.joblib not found")
    df = pd.read_csv(DATA_PATH)
    X, y = df[FEATURE_ORDER].values, df["quality_label"].values
    _, X_test, _, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    acc = accuracy_score(y_test, bundle["pipeline"].predict(X_test))
    stored = bundle["metadata"]["accuracy"]
    record.actual(f"Re-computed accuracy {acc:.4f} on {len(y_test)} held-out rows; stored metadata accuracy {stored:.4f}")
    assert acc == pytest.approx(stored, abs=1e-9)
    assert acc >= 0.85


@case(id="QP-14", module=M, title="Formula fallback when no trained model is present",
      objective="Verify the service still scores test cases (method = weighted_formula) if the model file is unavailable.",
      expected="predicted_label == formula_label, empty probabilities, method = weighted_formula.")
def test_formula_fallback(record, monkeypatch):
    monkeypatch.setattr(c2_predict, "_cached", None)
    monkeypatch.setattr(c2_predict, "_load_attempted", True)
    p = predict_c2_quality(extract_features(_tc(LOGIN_HIGH), True, LOGIN_AC))
    record.actual(f"method={p['method']}; predicted={p['predicted_label']}; formula={p['formula_label']}; probabilities={p['probabilities']}")
    assert p["method"] == "weighted_formula"
    assert p["predicted_label"] == p["formula_label"] and p["probabilities"] == {}


@case(id="QP-15", module=M, title="Empty / non-Gherkin description handled safely",
      objective="Verify a test case with an empty or free-text description does not crash feature extraction and is rated Low.",
      expected="No exception; all structure flags 0; label Low.")
def test_empty_description(record):
    out = {}
    for name, text in (("empty", ""), ("free text", "Check the login page works fine.")):
        f = extract_features(_tc(text))
        out[name] = (f["has_preconditions"], f["has_test_steps"], f["has_expected_result"], predict_c2_quality(f)["predicted_label"])
    record.actual(f"(Given, When, Then, label): {out}")
    assert all(v[:3] == (0, 0, 0) and v[3] == "Low" for v in out.values())
