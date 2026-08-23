"""Trains the Component 2 test-case quality classifier on
app/ml/data/c2_quality_dataset.csv (see c2_dataset.py for how it's built)
and saves the fitted pipeline + a full training report, so the flow
(dataset -> preprocessing -> model -> evaluation) can be explained and
defended in a research viva.

Deliberately a CLASSIFIER (High/Medium/Low), not a regressor: the research
requirement is to predict test-case *quality*, not re-derive the continuous
formula score (that's already available deterministically from
c2_features.compute_quality_score for display alongside the model's
prediction).

Random Forest is used as the primary/only model family here (per the
research spec) -- tabular data, mixed feature types (binary + continuous),
doesn't need a huge dataset, and its feature_importances_ are easy to
explain in a viva. A held-out test set + 5-fold stratified CV are still
used for honest evaluation, and a small grid search tunes it.

Run with: python -m app.ml.c2_train
"""

import json
import os
from datetime import datetime, timezone

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)
from sklearn.model_selection import GridSearchCV, StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.c2_dataset import DATA_PATH, build_dataset
from app.ml.c2_features import FEATURE_LABELS, FEATURE_ORDER, LABEL_ORDER

MODEL_PATH = os.path.join(os.path.dirname(__file__), "c2_quality_model.joblib")
METADATA_PATH = os.path.join(os.path.dirname(__file__), "c2_quality_model_metadata.json")

PARAM_GRID = {
    "model__n_estimators": [150, 300],
    "model__max_depth": [6, 10, None],
    "model__min_samples_leaf": [2, 4],
}


def load_dataset() -> pd.DataFrame:
    if not os.path.exists(DATA_PATH):
        build_dataset()
    df = pd.read_csv(DATA_PATH)
    missing = df[FEATURE_ORDER + ["quality_label"]].isna().sum().sum()
    if missing:
        raise ValueError(f"Dataset has {missing} missing values in modeled columns")
    return df


def compute_feature_importances(pipeline) -> list[dict]:
    model = pipeline.named_steps["model"]
    importances = model.feature_importances_
    return [
        {"feature": f, "label": FEATURE_LABELS[f], "importance": float(importances[i])}
        for i, f in enumerate(FEATURE_ORDER)
    ]


def train():
    df = load_dataset()
    X = df[FEATURE_ORDER].values
    y = df["quality_label"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    base_pipeline = Pipeline([("scaler", StandardScaler()), ("model", RandomForestClassifier(random_state=42))])

    print("=== 5-fold stratified CV accuracy (pre-tuning) ===")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(base_pipeline, X_train, y_train, cv=cv, scoring="accuracy")
    print(f"  Accuracy = {cv_scores.mean():.3f} +/- {cv_scores.std():.3f}")

    print("\n=== Tuning RandomForestClassifier ===")
    search = GridSearchCV(base_pipeline, PARAM_GRID, cv=5, scoring="accuracy", n_jobs=-1)
    search.fit(X_train, y_train)
    best_pipeline = search.best_estimator_
    best_params = {k.replace("model__", ""): v for k, v in search.best_params_.items()}
    cv_std = float(search.cv_results_["std_test_score"][search.best_index_])
    print(f"  Params: {best_params}")
    print(f"  CV accuracy: {search.best_score_:.3f} +/- {cv_std:.3f}")

    # Held-out test metrics (never touched during tuning).
    preds = best_pipeline.predict(X_test)
    accuracy = float(accuracy_score(y_test, preds))
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_test, preds, labels=LABEL_ORDER, average="macro", zero_division=0
    )
    per_class_precision, per_class_recall, per_class_f1, per_class_support = precision_recall_fscore_support(
        y_test, preds, labels=LABEL_ORDER, zero_division=0
    )
    cm = confusion_matrix(y_test, preds, labels=LABEL_ORDER).tolist()

    feature_importances = compute_feature_importances(best_pipeline)

    metadata = {
        "algorithm": "RandomForestClassifier (scikit-learn)",
        "hyperparameters": best_params,
        "dataset_path": "app/ml/data/c2_quality_dataset.csv",
        "label_order": LABEL_ORDER,
        "training_samples": int(len(X_train)),
        "test_samples": int(len(X_test)),
        "cv_accuracy_mean": float(search.best_score_),
        "cv_accuracy_std": cv_std,
        "accuracy": accuracy,
        "precision_macro": float(precision),
        "recall_macro": float(recall),
        "f1_macro": float(f1),
        "per_class_metrics": [
            {
                "label": LABEL_ORDER[i],
                "precision": float(per_class_precision[i]),
                "recall": float(per_class_recall[i]),
                "f1": float(per_class_f1[i]),
                "support": int(per_class_support[i]),
            }
            for i in range(len(LABEL_ORDER))
        ],
        "confusion_matrix": cm,
        "confusion_matrix_labels": LABEL_ORDER,
        "feature_importances": feature_importances,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "notes": (
            "Trained to predict test-case QUALITY (High/Medium/Low), not test execution outcome: "
            "the label comes from a weighted formula over completeness, requirement coverage, "
            "specificity, expected-result/precondition/step presence, and (low) ambiguity -- never "
            "from PASS/FAIL. PASS/FAIL is included only as the `test_result` feature, deliberately "
            "given a weak, imperfect correlation with quality in the synthetic portion of the "
            "dataset so the model cannot use it as a shortcut label proxy."
        ),
    }

    print("\n=== Held-out test set evaluation ===")
    print(f"Accuracy: {accuracy:.3f}")
    print(f"Macro precision: {precision:.3f}  recall: {recall:.3f}  f1: {f1:.3f}")
    print(f"Confusion matrix (rows=actual, cols=predicted, order={LABEL_ORDER}): {cm}")
    print("\nFeature importances:")
    for row in sorted(feature_importances, key=lambda r: -r["importance"]):
        print(f"  {row['label']:<24} {row['importance']:.3f}")

    joblib.dump(
        {"pipeline": best_pipeline, "feature_order": FEATURE_ORDER, "label_order": LABEL_ORDER, "metadata": metadata},
        MODEL_PATH,
    )
    print(f"\nSaved model + metadata to {MODEL_PATH}")

    with open(METADATA_PATH, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved human-readable metadata to {METADATA_PATH}")


if __name__ == "__main__":
    train()
