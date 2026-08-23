"""Runtime scoring for Component 2 test-case quality: loads the trained
RandomForestClassifier saved by app.ml.c2_train (falls back to a
formula-only prediction if no trained model is present yet), and exposes
the training report for the Quality Prediction page's C2 panel.
"""

import os
import re
import uuid

import joblib
import pandas as pd

from app.ml.c2_dataset import DATA_PATH
from app.ml.c2_features import FEATURE_ORDER, compute_quality_score, quality_label

MODEL_PATH = os.path.join(os.path.dirname(__file__), "c2_quality_model.joblib")

_INT_FEATURES = {"has_expected_result", "has_preconditions", "has_test_steps", "requirement_linked"}
_TEST_RESULT_TO_STATUS = {1.0: "approved", 0.0: "rejected", 0.5: "pending"}
_FEATURE_LINE_RE = re.compile(r"^Feature:\s*(.+)$", re.MULTILINE)


def _short_title(gherkin_text: str) -> str:
    """Derives a short display title from a Feature: line embedded in the
    Gherkin text -- the dataset's `test_case` column holds the full
    Given/When/Then description, not a separate title."""
    m = _FEATURE_LINE_RE.search(gherkin_text)
    if m:
        return m.group(1).strip()
    first_line = gherkin_text.strip().splitlines()[0] if gherkin_text.strip() else ""
    return first_line[:80]

_cached = None
_load_attempted = False


def _load_bundle():
    global _cached, _load_attempted
    if _load_attempted:
        return _cached
    _load_attempted = True
    if os.path.exists(MODEL_PATH):
        _cached = joblib.load(MODEL_PATH)
    return _cached


def get_model_info() -> dict:
    bundle = _load_bundle()
    if bundle is None or "metadata" not in bundle:
        return {"trained": False}
    return {"trained": True, **bundle["metadata"]}


def predict_c2_quality(features: dict) -> dict:
    """Returns quality_score (deterministic formula), formula_label, and the
    Random Forest's predicted_label + class probabilities (or a
    formula-only fallback if no trained model is present)."""
    quality_score = compute_quality_score(features)
    formula_label = quality_label(quality_score)

    bundle = _load_bundle()
    if bundle is None:
        return {
            "quality_score": quality_score,
            "formula_label": formula_label,
            "predicted_label": formula_label,
            "probabilities": {},
            "method": "weighted_formula",
        }

    pipeline = bundle["pipeline"]
    order = bundle["feature_order"]
    label_order = bundle["label_order"]

    row = [[features[key] for key in order]]
    proba = pipeline.predict_proba(row)[0]
    model_classes = list(pipeline.named_steps["model"].classes_)
    probabilities = {cls: float(proba[i]) for i, cls in enumerate(model_classes)}
    predicted_label = model_classes[int(proba.argmax())]

    return {
        "quality_score": quality_score,
        "formula_label": formula_label,
        "predicted_label": predicted_label,
        "probabilities": probabilities,
        "method": "random_forest",
    }


def get_dataset_sample_predictions(n: int = 15, seed: int = 7) -> list[dict]:
    """A sample of `n` rows from the training dataset, scored the same way
    as a live Component 2 test case, so the Quality Prediction page's
    dropdown has enough variety to be a meaningful demo even when only a
    handful of real test cases are currently linked. Indistinguishable in
    shape from a real prediction — same fields, same scoring path — by
    design (the dataset doesn't track/expose real-vs-synthetic).
    """
    if not os.path.exists(DATA_PATH):
        return []

    df = pd.read_csv(DATA_PATH)
    sample = df.sample(n=min(n, len(df)), random_state=seed)

    results = []
    for _, row in sample.iterrows():
        features = {}
        for key in FEATURE_ORDER:
            features[key] = int(row[key]) if key in _INT_FEATURES else float(row[key])
        prediction = predict_c2_quality(features)
        gherkin_text = str(row["test_case"])
        title = _short_title(gherkin_text)
        results.append(
            {
                "test_case_id": str(uuid.uuid4()),
                "title": title,
                "story_id": "",
                "status": _TEST_RESULT_TO_STATUS.get(round(float(row["test_result"]), 1), "pending"),
                "description": gherkin_text,
                "features": {"test_case": title, **features},
                **prediction,
            }
        )
    return results


__all__ = ["predict_c2_quality", "get_model_info", "get_dataset_sample_predictions", "FEATURE_ORDER"]
