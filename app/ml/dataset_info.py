"""Reads app/ml/data/test_quality_dataset.csv and computes the summary
statistics shown on the Quality Prediction page's Dataset panel: this is
the exploratory data analysis (EDA) step of the pipeline, made available
at runtime rather than only printed during training.
"""

import os

import pandas as pd

from app.ml.weights import FEATURE_ORDER

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "test_quality_dataset.csv")

FEATURE_LABELS = {
    "assertion_strength": "Assertion Strength",
    "coverage_percent": "Code Coverage",
    "boundary_coverage": "Boundary Coverage",
    "error_handling": "Error Handling",
    "mutation_resistance": "Mutation Resistance",
    "lines_of_code": "Lines of Code",
}

_cached = None


def get_dataset_info() -> dict:
    global _cached
    if _cached is not None:
        return _cached

    if not os.path.exists(DATA_PATH):
        _cached = {"available": False}
        return _cached

    df = pd.read_csv(DATA_PATH)

    feature_stats = []
    for key in FEATURE_ORDER:
        col = df[key]
        feature_stats.append(
            {
                "feature": key,
                "label": FEATURE_LABELS[key],
                "mean": round(float(col.mean()), 2),
                "std": round(float(col.std()), 2),
                "min": round(float(col.min()), 2),
                "max": round(float(col.max()), 2),
                "correlation_with_target": round(float(df[[key, "quality_score"]].corr().iloc[0, 1]), 3),
            }
        )

    # lines_of_code is deliberately NOT used by the model -- included to
    # demonstrate the ablation: it has near-zero correlation with quality.
    loc_corr = round(float(df[["lines_of_code", "quality_score"]].corr().iloc[0, 1]), 3)

    label_counts = df["quality_label"].value_counts().to_dict()
    label_order = ["Excellent", "Good", "Fair", "Poor"]
    quality_label_distribution = [
        {"label": label, "count": int(label_counts.get(label, 0))} for label in label_order
    ]

    test_type_counts = df["test_type"].value_counts().to_dict()
    criticality_counts = df["module_criticality"].value_counts().to_dict()

    _cached = {
        "available": True,
        "source": "Curated synthetic dataset (see data/DATASET_CARD.md) -- no public dataset "
        "matches this app's test-design feature schema.",
        "n_rows": int(len(df)),
        "n_features_used": len(FEATURE_ORDER),
        "missing_values": int(df[FEATURE_ORDER + ["quality_score"]].isna().sum().sum()),
        "target_mean": round(float(df["quality_score"].mean()), 2),
        "target_std": round(float(df["quality_score"].std()), 2),
        "target_min": round(float(df["quality_score"].min()), 2),
        "target_max": round(float(df["quality_score"].max()), 2),
        "reject_rate": round(float((df["quality_score"] < 60).mean()), 3),
        "feature_stats": feature_stats,
        "excluded_feature_correlation": {
            "feature": "lines_of_code",
            "correlation_with_target": loc_corr,
            "note": "Explored during EDA but excluded from the model: near-zero correlation with "
            "quality, and not collected by the app's Quality Prediction form.",
        },
        "quality_label_distribution": quality_label_distribution,
        "test_type_distribution": [{"label": k, "count": int(v)} for k, v in test_type_counts.items()],
        "module_criticality_distribution": [
            {"label": k, "count": int(v)} for k, v in criticality_counts.items()
        ],
    }
    return _cached


__all__ = ["get_dataset_info"]
