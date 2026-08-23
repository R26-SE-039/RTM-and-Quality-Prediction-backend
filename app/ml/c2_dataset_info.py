"""EDA summary of app/ml/data/c2_quality_dataset.csv for the Quality
Prediction page's C2 dataset panel."""

import os

import pandas as pd

from app.ml.c2_dataset import DATA_PATH
from app.ml.c2_features import FEATURE_LABELS, FEATURE_ORDER, LABEL_ORDER

_LABEL_CODE = {label: i for i, label in enumerate(LABEL_ORDER)}


def get_c2_dataset_info() -> dict:
    if not os.path.exists(DATA_PATH):
        return {"available": False}

    df = pd.read_csv(DATA_PATH)
    label_code = df["quality_label"].map(_LABEL_CODE)

    feature_stats = []
    for key in FEATURE_ORDER:
        col = df[key]
        corr = col.corr(label_code)
        feature_stats.append(
            {
                "feature": key,
                "label": FEATURE_LABELS[key],
                "mean": round(float(col.mean()), 2),
                "std": round(float(col.std()), 2),
                "min": round(float(col.min()), 2),
                "max": round(float(col.max()), 2),
                "correlation_with_target": round(float(corr), 3) if pd.notna(corr) else 0.0,
            }
        )

    label_counts = df["quality_label"].value_counts().to_dict()
    label_distribution = [{"label": label, "count": int(label_counts.get(label, 0))} for label in LABEL_ORDER]

    return {
        "available": True,
        "n_rows": int(len(df)),
        "label_distribution": label_distribution,
        "feature_stats": feature_stats,
    }


__all__ = ["get_c2_dataset_info"]
