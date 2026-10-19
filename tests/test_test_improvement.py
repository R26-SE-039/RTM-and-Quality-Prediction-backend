"""Module 4 - Intelligent Test Improvement (app/ml/c2_improve.py, POST /api/ml/c2-quality/improve)."""

import re

import pytest

from app.ml.c2_features import compute_quality_score, extract_features
from app.ml.c2_improve import analyze_gaps
from app.ml.c2_predict import predict_c2_quality
from tests.sample_data import LOGIN_AC, LOGIN_HIGH, LOGIN_LOW

M = "Intelligent Test Improvement"
case = pytest.mark.case


def _payload(text, title, acs, req_text="", story_title="User Login"):
    feats = extract_features({"id": "T", "title": title, "description": text, "status": "pending"}, bool(acs), acs)
    pred = predict_c2_quality(feats)
    return {"title": title, "description": text, "features": feats, "quality_score": pred["quality_score"],
            "predicted_label": pred["predicted_label"], "probabilities": pred["probabilities"],
            "requirement_text": req_text, "user_story_title": story_title, "acceptance_criteria": acs}


def _steps(text):
    return [ln.strip() for ln in text.splitlines() if re.match(r"\s*(Given|When|Then|And|But)\b", ln)]


@case(id="IMP-01", module=M, title="Quality gaps identified in a deficient test case",
      objective="Verify analyze_gaps reports each weak model feature with a status and a concrete recommendation.",
      expected="Vague When-only test with no linked requirement -> 7 gaps: Preconditions, Expected Result, Specificity, Clarity, Requirement Coverage, Completeness, Requirement Link (Test Steps present, so not flagged).")
def test_gaps_identified(record):
    f = extract_features({"id": "T", "title": "Login", "description": LOGIN_LOW, "status": "pending"}, False, [])
    gaps = analyze_gaps(f)
    labels = [g["label"] for g in gaps]
    record.actual(f"{len(gaps)} gaps: {labels}")
    record.add("Gap details", gaps)
    assert labels == ["Preconditions", "Expected Result", "Specificity", "Clarity", "Requirement Coverage", "Completeness", "Requirement Link"]
    assert all(g["recommendation"] for g in gaps)


@case(id="IMP-02", module=M, title="Improved Given/When/Then scenarios generated",
      objective="Verify the improved test is valid Gherkin with a happy-path and an invalid-input scenario, each with Given/When/Then, and folds in the linked ACs.",
      expected="2 scenarios; each has Given, When, Then; an 'And the result satisfies the linked acceptance criteria' step containing the AC text.")
def test_improved_gherkin_structure(client, record):
    r = client.post("/api/ml/c2-quality/improve", json=_payload(LOGIN_LOW, "Login", LOGIN_AC, "Users shall be able to log in"))
    text = r.json()["improved_description"]
    blocks = re.split(r"\n\s*Scenario:", text)[1:]
    record.add("Improved Gherkin", text)
    record.actual(f"HTTP {r.status_code}; scenarios={len(blocks)}; each has G/W/T: "
                  f"{[all(k in b for k in ('Given', 'When', 'Then')) for b in blocks]}; AC folded in: {LOGIN_AC[0] in text}")
    assert r.status_code == 200 and len(blocks) == 2
    assert all(all(k in b for k in ("Given", "When", "Then")) for b in blocks)
    assert LOGIN_AC[0] in text


@case(id="IMP-03", module=M, title="Quality score recalculated through the same pipeline",
      objective="Verify the 'after' score is measured by re-running feature extraction and the model on the rewritten text, not asserted.",
      expected="improved_quality_score == compute_quality_score(improved_features); improved_features == extract_features(improved_description); score rises from Low to High.")
def test_score_recalculated(client, record):
    p = _payload(LOGIN_LOW, "Login", LOGIN_AC, "Users shall be able to log in")
    out = client.post("/api/ml/c2-quality/improve", json=p).json()
    recomputed = extract_features({"id": "improved", "title": "Login", "description": out["improved_description"], "status": "pending"}, True, LOGIN_AC)
    same_feats = {k: v for k, v in recomputed.items() if k != "test_case"} == {k: v for k, v in out["improved_features"].items() if k != "test_case"}
    record.actual(f"Before {p['quality_score']} ({p['predicted_label']}) -> after {out['improved_quality_score']} "
                  f"({out['improved_formula_label']}/{out['improved_predicted_label']}); features re-extracted identically: {same_feats}")
    assert out["improved_quality_score"] == compute_quality_score(out["improved_features"])
    assert same_feats and out["improved_quality_score"] > p["quality_score"] and out["improved_predicted_label"] == "High"


@case(id="IMP-04", module=M, title="Improvement preserves the original test-case steps",
      objective="Check whether the improvement keeps the original Given/When/Then steps and only adds what is missing (research requirement).",
      expected="Every original step line of the test appears in the improved Gherkin.")
def test_preserves_original_steps(client, record):
    out = client.post("/api/ml/c2-quality/improve", json=_payload(LOGIN_HIGH, "User Login", LOGIN_AC)).json()
    original = _steps(LOGIN_HIGH)
    kept = [s for s in original if s in out["improved_description"]]
    record.actual(f"{len(kept)} of {len(original)} original steps preserved in the improved text")
    record.add("Original steps", original)
    record.add("Improved Gherkin", out["improved_description"])
    record.add("Finding", "generate_improved_gherkin() rebuilds the scenario from a template using only the title, story title and "
                          "acceptance criteria; it never reads the original description, so original steps and concrete values are replaced, not extended.")
    assert kept == original, f"only {len(kept)}/{len(original)} original steps preserved"


@case(id="IMP-05", module=M, title="Improvement preserves the feature title",
      objective="Verify the improved Gherkin keeps the original test-case title as its Feature name.",
      expected="Improved text starts with 'Feature: <original title>'.")
def test_preserves_title(client, record):
    out = client.post("/api/ml/c2-quality/improve", json=_payload(LOGIN_LOW, "Login with email", LOGIN_AC)).json()
    first = out["improved_description"].splitlines()[0]
    record.actual(f"First line: {first!r}")
    assert first == "Feature: Login with email"


@case(id="IMP-06", module=M, title="Already-complete test case: no gaps reported",
      objective="Verify a complete, specific, requirement-linked test produces no quality gaps.",
      expected="analyze_gaps returns an empty list.")
def test_complete_no_gaps(record):
    f = extract_features({"id": "T", "title": "User Login", "description": LOGIN_HIGH, "status": "approved"}, True, LOGIN_AC)
    gaps = analyze_gaps(f)
    record.actual(f"Gaps: {gaps or 'none'}; features: completeness {f['completeness_score']}, specificity {f['specificity_score']}, "
                  f"ambiguity {f['ambiguity_score']}, coverage {f['requirement_coverage']}")
    assert gaps == []


@case(id="IMP-07", module=M, title="Already-complete test case: score not reduced by improvement",
      objective="Check that running the improvement on an already high-quality test does not lower its measured quality.",
      expected="improved_quality_score >= original quality_score.")
def test_complete_not_degraded(client, record):
    p = _payload(LOGIN_HIGH, "User Login", LOGIN_AC)
    out = client.post("/api/ml/c2-quality/improve", json=p).json()
    record.actual(f"Original {p['quality_score']} ({p['predicted_label']}) -> improved {out['improved_quality_score']} ({out['improved_predicted_label']}); "
                  f"specificity {p['features']['specificity_score']} -> {out['improved_features']['specificity_score']}")
    assert out["improved_quality_score"] >= p["quality_score"]


@case(id="IMP-08", module=M, title="No linked requirement information available",
      objective="Verify that without acceptance criteria or requirement text the improvement does not invent requirement coverage and the requirement-link gap remains visible.",
      expected="Improved features: requirement_linked 0 and requirement_coverage 0; gaps include 'Requirement Link'; no 'satisfies the' line in the text.")
def test_no_requirement_info(client, record):
    out = client.post("/api/ml/c2-quality/improve", json=_payload(LOGIN_LOW, "Login", [], "", "")).json()
    f = out["improved_features"]
    record.actual(f"requirement_linked={f['requirement_linked']}, coverage={f['requirement_coverage']}; gaps={[g['label'] for g in out['gaps']]}; "
                  f"score {out['improved_quality_score']} ({out['improved_predicted_label']})")
    record.add("Improved Gherkin", out["improved_description"])
    assert f["requirement_linked"] == 0 and f["requirement_coverage"] == 0.0
    assert "Requirement Link" in [g["label"] for g in out["gaps"]] and "satisfies the" not in out["improved_description"]


@case(id="IMP-09", module=M, title="Invalid improvement request rejected",
      objective="Verify the improve endpoint validates its payload.",
      expected="Missing 'features' -> HTTP 422 with a validation error naming the field.")
def test_improve_validation(client, record):
    r = client.post("/api/ml/c2-quality/improve", json={"title": "x", "description": "y"})
    fields = [e["loc"][-1] for e in r.json().get("detail", [])]
    record.actual(f"HTTP {r.status_code}; missing fields reported: {fields}")
    assert r.status_code == 422 and "features" in fields
