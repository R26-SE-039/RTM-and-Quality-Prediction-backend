"""Runtime scoring: uses the trained pipeline (StandardScaler -> model)
saved by app.ml.train_model if available, otherwise falls back to the
weighted-formula baseline. Also exposes the model's training metadata and
a per-prediction feature breakdown so a prediction can be explained rather
than treated as a black box.
"""

import os

import joblib
import numpy as np

from app.ml.weights import FEATURE_ORDER, WEIGHTS, weighted_score

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.joblib")

FEATURE_LABELS = {
    "assertion_strength": "Assertion Strength",
    "coverage_percent": "Code Coverage",
    "boundary_coverage": "Boundary Coverage",
    "error_handling": "Error Handling",
    "mutation_resistance": "Mutation Resistance",
}

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
    """Returns the training report saved by app.ml.train_model, for display
    on the Quality Prediction page's research/model panel."""
    bundle = _load_bundle()
    if bundle is None or "metadata" not in bundle:
        return {"trained": False}
    return {"trained": True, **bundle["metadata"]}


def _ml_contributions(pipeline, order, features) -> tuple[float, float, list[dict]]:
    """Returns (score, model_baseline, contributions) such that
    model_baseline + sum(contribution) approximately equals the raw
    (pre-clip) predicted score -- the same invariant held by the tree and
    formula-fallback paths, so every prediction method is explainable the
    same way regardless of which one produced it.
    """
    scaler = pipeline.named_steps["scaler"]
    model = pipeline.named_steps["model"]
    raw_row = np.array([[features[key] for key in order]])
    score = float(pipeline.predict(raw_row)[0])
    score = max(0.0, min(100.0, score))

    if hasattr(model, "coef_"):
        # Exact decomposition: the pipeline predicts
        # intercept_ + sum(coef_i * scaled_x_i), so each term's own value
        # *is* its contribution in score units, and they sum exactly
        # (before clipping) to the raw prediction alongside the intercept.
        scaled_row = scaler.transform(raw_row)[0]
        terms = model.coef_ * scaled_row
        abs_total = float(np.abs(model.coef_).sum()) or 1.0
        model_baseline = float(model.intercept_)
        contributions = [
            {
                "feature": order[i],
                "label": FEATURE_LABELS[order[i]],
                "value": features[order[i]],
                "importance": float(abs(model.coef_[i]) / abs_total),
                "contribution": round(float(terms[i]), 2),
            }
            for i in range(len(order))
        ]
    else:
        # Tree ensembles have no exact per-sample linear decomposition;
        # approximate by splitting the predicted score across features in
        # proportion to (global feature importance x this sample's value),
        # with a zero baseline (the whole score is attributed to features).
        importances = model.feature_importances_
        raw = [importances[i] * features[order[i]] for i in range(len(order))]
        raw_total = sum(raw) or 1.0
        model_baseline = 0.0
        contributions = [
            {
                "feature": order[i],
                "label": FEATURE_LABELS[order[i]],
                "value": features[order[i]],
                "importance": float(importances[i]),
                "contribution": round(raw[i] / raw_total * score, 2),
            }
            for i in range(len(order))
        ]

    return score, model_baseline, contributions


def predict_quality(features: dict) -> tuple[float, str, float, list[dict]]:
    """Returns (score 0-100, method, model_baseline, feature_contributions).

    method is 'ml_model' or 'weighted_formula'. In all cases,
    model_baseline + sum(c["contribution"] for c in feature_contributions)
    approximately equals the raw (pre-clip) score.
    """
    bundle = _load_bundle()

    if bundle is not None:
        pipeline = bundle["pipeline"]
        order = bundle["feature_order"]
        score, model_baseline, contributions = _ml_contributions(pipeline, order, features)
        return score, "ml_model", model_baseline, contributions

    score = weighted_score(features)
    contributions = [
        {
            "feature": key,
            "label": FEATURE_LABELS[key],
            "value": features[key],
            "importance": WEIGHTS[key],
            "contribution": round(features[key] * WEIGHTS[key], 2),
        }
        for key in FEATURE_ORDER
    ]
    return score, "weighted_formula", 0.0, contributions


__all__ = ["predict_quality", "get_model_info", "FEATURE_ORDER"]
