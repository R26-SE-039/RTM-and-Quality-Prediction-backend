"""Trains the Quality Prediction model on app/ml/data/test_quality_dataset.csv
and saves the fitted pipeline plus a full training report so the whole
flow (dataset -> preprocessing -> model selection -> tuning -> evaluation)
can be explained and defended in a research viva.

Pipeline
--------
1. Load the curated dataset (see data/DATASET_CARD.md for provenance).
2. EDA: summary statistics, missing-value check, feature/target
   correlations -- surfaced via the /api/ml/dataset-info endpoint rather
   than only printed here, so the frontend "Dataset" panel is backed by
   the same numbers.
3. Preprocessing: an sklearn Pipeline(StandardScaler -> estimator), applied
   identically to every candidate model so the comparison isn't biased by
   scale differences.
4. Model selection: compare a linear baseline, Random Forest, and Gradient
   Boosting via 5-fold cross-validated MAE on the training split, and
   genuinely select whichever wins -- this file does NOT hard-code a
   "favourite" algorithm. (In practice Linear Regression tends to win here,
   because the labeling function in generate_dataset.py is dominated by a
   linear combination of the five features; the non-linear synergy/penalty
   terms are real but affect a minority of rows relative to the noise
   floor. That the comparison surfaces this honestly, rather than
   defaulting to a black-box ensemble, is itself worth reporting in a
   viva: model choice should be justified empirically, not assumed.)
5. Hyperparameter tuning: a small grid search appropriate to whichever
   model family won (Linear Regression has none to tune).
6. Evaluation on a held-out test set never seen during selection/tuning:
   regression metrics (MAE, RMSE, R^2) and, since the app makes a binary
   approve/reject decision at QUALITY_REJECT_THRESHOLD, classification
   metrics (accuracy, precision, recall, F1, confusion matrix) too.

Run with:  python -m app.ml.train_model
"""

import json
import os
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import (
    confusion_matrix,
    mean_absolute_error,
    mean_squared_error,
    precision_recall_fscore_support,
    r2_score,
)
from sklearn.model_selection import GridSearchCV, KFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.weights import FEATURE_ORDER, QUALITY_REJECT_THRESHOLD, WEIGHTS

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "test_quality_dataset.csv")
MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.joblib")
METADATA_PATH = os.path.join(os.path.dirname(__file__), "model_metadata.json")

FEATURE_LABELS = {
    "assertion_strength": "Assertion Strength",
    "coverage_percent": "Code Coverage",
    "boundary_coverage": "Boundary Coverage",
    "error_handling": "Error Handling",
    "mutation_resistance": "Mutation Resistance",
}

CANDIDATES = {
    "LinearRegression": LinearRegression(),
    "RandomForestRegressor": RandomForestRegressor(n_estimators=200, max_depth=8, random_state=42),
    "GradientBoostingRegressor": GradientBoostingRegressor(random_state=42),
}

# Per-family tuning grids, keyed by candidate name. LinearRegression has no
# entry -- it's fit as-is (no hyperparameters worth grid-searching).
PARAM_GRIDS = {
    "RandomForestRegressor": {
        "model__n_estimators": [150, 300],
        "model__max_depth": [6, 10, None],
        "model__min_samples_leaf": [2, 4],
    },
    "GradientBoostingRegressor": {
        "model__n_estimators": [100, 200],
        "model__max_depth": [2, 3, 4],
        "model__learning_rate": [0.05, 0.1],
    },
}


def load_dataset() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    missing = df[FEATURE_ORDER + ["quality_score"]].isna().sum().sum()
    if missing:
        raise ValueError(f"Dataset has {missing} missing values in modeled columns")
    return df


def compare_candidates(X_train, y_train) -> list[dict]:
    """5-fold CV MAE for each candidate model, under identical preprocessing."""
    cv = KFold(n_splits=5, shuffle=True, random_state=42)
    results = []
    for name, estimator in CANDIDATES.items():
        pipeline = Pipeline([("scaler", StandardScaler()), ("model", estimator)])
        scores = -cross_val_score(pipeline, X_train, y_train, cv=cv, scoring="neg_mean_absolute_error")
        results.append({"model": name, "cv_mae_mean": float(scores.mean()), "cv_mae_std": float(scores.std())})
    return sorted(results, key=lambda r: r["cv_mae_mean"])


def fit_winner(winner_name: str, X_train, y_train):
    """Tunes (if applicable) and fits the winning model family. Returns
    (fitted_pipeline, best_params, cv_mae_mean, cv_mae_std)."""
    grid = PARAM_GRIDS.get(winner_name)
    base_pipeline = Pipeline([("scaler", StandardScaler()), ("model", CANDIDATES[winner_name].__class__())])

    if grid is None:
        cv = KFold(n_splits=5, shuffle=True, random_state=42)
        scores = -cross_val_score(base_pipeline, X_train, y_train, cv=cv, scoring="neg_mean_absolute_error")
        base_pipeline.fit(X_train, y_train)
        return base_pipeline, {}, float(scores.mean()), float(scores.std())

    search = GridSearchCV(base_pipeline, grid, cv=5, scoring="neg_mean_absolute_error", n_jobs=-1)
    search.fit(X_train, y_train)
    best_params = {k.replace("model__", ""): v for k, v in search.best_params_.items()}
    cv_std = float(search.cv_results_["std_test_score"][search.best_index_])
    return search.best_estimator_, best_params, float(-search.best_score_), cv_std


def compute_feature_importances(pipeline) -> list[dict]:
    """Returns a comparable [0,1]-normalized importance per feature
    regardless of model family: tree ensembles expose feature_importances_
    directly; the linear model's importance is |standardized coefficient|
    normalized to sum to 1. The linear model's raw signed, standardized
    coefficients are also included since they enable an *exact* per
    prediction contribution breakdown (see app/ml/predict.py), unlike the
    tree-ensemble case which can only approximate one.
    """
    model = pipeline.named_steps["model"]
    rows = []
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
        for idx, feature in enumerate(FEATURE_ORDER):
            rows.append(
                {
                    "feature": feature,
                    "label": FEATURE_LABELS[feature],
                    "importance": float(importances[idx]),
                    "formula_weight": float(WEIGHTS[feature]),
                    "coefficient": None,
                }
            )
    else:
        coefs = model.coef_
        abs_total = float(np.abs(coefs).sum()) or 1.0
        for idx, feature in enumerate(FEATURE_ORDER):
            rows.append(
                {
                    "feature": feature,
                    "label": FEATURE_LABELS[feature],
                    "importance": float(abs(coefs[idx]) / abs_total),
                    "formula_weight": float(WEIGHTS[feature]),
                    "coefficient": float(coefs[idx]),
                }
            )
    return rows


def train():
    df = load_dataset()
    X = df[FEATURE_ORDER].values
    y = df["quality_score"].values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    print("=== Model comparison (5-fold CV MAE on training split) ===")
    comparison = compare_candidates(X_train, y_train)
    for row in comparison:
        print(f"  {row['model']:<26} MAE = {row['cv_mae_mean']:.2f} +/- {row['cv_mae_std']:.2f}")

    winner_name = comparison[0]["model"]
    print(f"\nSelected: {winner_name} (lowest CV MAE)")

    print(f"\n=== Tuning {winner_name} ===")
    best_pipeline, best_params, cv_mae_mean, cv_mae_std = fit_winner(winner_name, X_train, y_train)
    print(f"  Params: {best_params or '(none to tune)'}")
    print(f"  CV MAE: {cv_mae_mean:.2f} +/- {cv_mae_std:.2f}")

    # Held-out test metrics (never touched during selection/tuning).
    preds = best_pipeline.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    rmse = mean_squared_error(y_test, preds) ** 0.5
    r2 = r2_score(y_test, preds)

    # Business-decision framing: approve/reject at QUALITY_REJECT_THRESHOLD.
    y_test_reject = (y_test < QUALITY_REJECT_THRESHOLD).astype(int)
    pred_reject = (preds < QUALITY_REJECT_THRESHOLD).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_test_reject, pred_reject, average="binary", zero_division=0
    )
    accuracy = float((y_test_reject == pred_reject).mean())
    cm = confusion_matrix(y_test_reject, pred_reject, labels=[0, 1]).tolist()

    feature_importances = compute_feature_importances(best_pipeline)

    metadata = {
        "algorithm": f"{winner_name} (scikit-learn), selected via 5-fold CV MAE comparison",
        "hyperparameters": best_params,
        "model_comparison": comparison,
        "dataset_path": "app/ml/data/test_quality_dataset.csv",
        "training_samples": int(len(X_train)),
        "test_samples": int(len(X_test)),
        "mae": float(mae),
        "rmse": float(rmse),
        "r2": float(r2),
        "cv_mae_mean": cv_mae_mean,
        "cv_mae_std": cv_mae_std,
        "feature_importances": feature_importances,
        "quality_reject_threshold": QUALITY_REJECT_THRESHOLD,
        "classification_metrics": {
            "task": f"predict approve/reject at score < {QUALITY_REJECT_THRESHOLD}",
            "accuracy": accuracy,
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(f1),
            "confusion_matrix": cm,
            "confusion_matrix_labels": ["approved", "rejected"],
        },
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "notes": (
            "Trained on a curated synthetic dataset (see data/DATASET_CARD.md) labeled by a "
            "domain-expert weighted formula plus realistic feature correlation, a non-linear "
            "synergy bonus, a coverage/mutation 'false confidence' penalty, and noise. The "
            "winning model was selected empirically via 5-fold cross-validated MAE among Linear "
            "Regression, Random Forest, and Gradient Boosting (see model_comparison), then tuned. "
            "Feature importances tracking the formula weights is a sanity check that the model "
            "learned the intended signal."
        ),
    }

    print("\n=== Held-out test set evaluation ===")
    print(f"MAE:  {mae:.2f}")
    print(f"RMSE: {rmse:.2f}")
    print(f"R^2:  {r2:.3f}")
    print(f"Approve/reject accuracy: {accuracy:.3f}  precision: {precision:.3f}  recall: {recall:.3f}  f1: {f1:.3f}")
    print(f"Confusion matrix (rows=actual, cols=predicted, [approved, rejected]): {cm}")
    print("\nFeature importances (learned vs. hand-designed formula weight):")
    for row in feature_importances:
        print(f"  {row['label']:<20} learned={row['importance']:.3f}  formula={row['formula_weight']:.2f}")

    joblib.dump({"pipeline": best_pipeline, "feature_order": FEATURE_ORDER, "metadata": metadata}, MODEL_PATH)
    print(f"\nSaved model + metadata to {MODEL_PATH}")

    with open(METADATA_PATH, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved human-readable metadata to {METADATA_PATH}")


if __name__ == "__main__":
    train()
