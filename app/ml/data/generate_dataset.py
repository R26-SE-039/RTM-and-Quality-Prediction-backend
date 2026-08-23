"""Builds test_quality_dataset.csv: a curated, reproducible dataset of
software test cases used to train the Quality Prediction model.

No public dataset (Kaggle, NASA/PROMISE, etc.) scores test cases on this
app's exact five test-design features (assertion strength, code coverage,
boundary coverage, error handling, mutation resistance) against a 0-100
quality label -- those public defect-prediction datasets (JM1, KC1, PC1...)
instead use source-code complexity metrics (Halstead, McCabe, LOC) to
predict defect-proneness of MODULES, not the effectiveness of TESTS. Since
this app scores test cases (not modules) on test-design adequacy, we build
a dataset for that exact problem instead of forcing a mismatched one.

Method: this is a *curated synthetic* dataset, not a scraped/reused one.
Feature distributions and correlations are engineered to look like a real
population of test suites (skewed towards "reasonably good" since that's
what most committed test suites look like, with realistic co-variation
between the metrics), and the quality label is generated from the
literature-informed weighted formula in app/ml/weights.py plus:
  - a non-linear "synergy bonus" for test cases strong on every dimension
    (rewards genuinely well-rounded tests beyond what a linear formula
    can express),
  - a "false confidence" penalty when coverage is high but mutation
    resistance is low (per Inozemtseva & Holmes 2014 -- a test can execute
    a line without actually verifying its behaviour), and
  - Gaussian measurement noise (real quality judgements are never
    perfectly deterministic functions of these five numbers).

This keeps the label honest about being formula-derived while giving the
Random Forest real non-linear structure to learn beyond the formula, and
gives every downstream pipeline stage (EDA, preprocessing, train/test
split, cross-validation) genuine data to work with rather than a trivial
one-line closed-form relationship.

Run with:  python -m app.ml.data.generate_dataset
"""

import os

import numpy as np
import pandas as pd

from app.ml.weights import FEATURE_ORDER, WEIGHTS

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "test_quality_dataset.csv")

N_SAMPLES = 6000
SEED = 42

TEST_TYPES = ["Unit", "Integration", "E2E"]
TEST_TYPE_PROBS = [0.6, 0.3, 0.1]
CRITICALITY_LEVELS = ["Low", "Medium", "High", "Critical"]
CRITICALITY_PROBS = [0.30, 0.35, 0.25, 0.10]


def _bucket(score: float) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Fair"
    return "Poor"


def generate(n_samples: int = N_SAMPLES, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    # Coverage is right-skewed: most maintained test suites cluster in the
    # 65-95 range, with a tail of poorly covered ones.
    coverage_percent = np.clip(rng.beta(7, 2, n_samples) * 100, 0, 100)

    # Assertion strength moderately correlates with coverage (teams that
    # invest in coverage often also invest in assertion quality) but has
    # its own independent variation.
    assertion_strength = np.clip(
        0.55 * coverage_percent + 0.45 * (rng.beta(6, 2, n_samples) * 100) + rng.normal(0, 5, n_samples),
        0,
        100,
    )

    # Boundary coverage is more independent of raw line coverage -- teams
    # frequently hit high line coverage via happy-path tests while
    # neglecting edge cases.
    boundary_coverage = np.clip(rng.beta(5, 3, n_samples) * 100 + rng.normal(0, 3, n_samples), 0, 100)

    # Error handling correlates mildly with boundary coverage (both reflect
    # a "thorough tester" mindset) but is otherwise its own signal.
    error_handling = np.clip(
        0.35 * boundary_coverage + 0.65 * (rng.beta(6, 3, n_samples) * 100) + rng.normal(0, 4, n_samples),
        0,
        100,
    )

    # Mutation resistance is only weakly correlated with coverage -- this
    # is the empirical Inozemtseva & Holmes (2014) finding encoded directly
    # into the data: high coverage does not reliably imply the tests would
    # actually catch injected faults.
    mutation_resistance = np.clip(
        0.30 * coverage_percent + 0.70 * (rng.beta(6, 3, n_samples) * 100) + rng.normal(0, 6, n_samples),
        0,
        100,
    )

    features = {
        "assertion_strength": assertion_strength,
        "coverage_percent": coverage_percent,
        "boundary_coverage": boundary_coverage,
        "error_handling": error_handling,
        "mutation_resistance": mutation_resistance,
    }

    base = sum(features[k] * WEIGHTS[k] for k in FEATURE_ORDER)

    stacked = np.stack([features[k] for k in FEATURE_ORDER], axis=1)
    synergy_bonus = np.where(np.all(stacked >= 75, axis=1), 3.0, 0.0)

    false_confidence_penalty = np.where(
        (coverage_percent >= 80) & (mutation_resistance < 35), 6.0, 0.0
    )

    noise = rng.normal(0, 4.0, n_samples)
    quality_score = np.clip(base + synergy_bonus - false_confidence_penalty + noise, 0, 100)

    # Contextual metadata columns: informative for exploratory data
    # analysis and to demonstrate feature-selection reasoning, but NOT fed
    # into the quality-score formula above, and NOT used by the final
    # model -- the app's Quality Prediction form only collects the five
    # core test-design metrics, so the deployed model is trained on those
    # five alone. Kept here so the EDA / dataset-info panel has real
    # categorical structure to report on.
    test_type = rng.choice(TEST_TYPES, size=n_samples, p=TEST_TYPE_PROBS)
    module_criticality = rng.choice(CRITICALITY_LEVELS, size=n_samples, p=CRITICALITY_PROBS)

    # Base LOC by test type, plus noise.
    loc_base = np.select(
        [test_type == "Unit", test_type == "Integration", test_type == "E2E"],
        [25, 60, 110],
    )
    lines_of_code = np.clip(loc_base + rng.normal(0, 12, n_samples), 5, None).round().astype(int)

    df = pd.DataFrame(
        {
            "assertion_strength": np.round(assertion_strength, 2),
            "coverage_percent": np.round(coverage_percent, 2),
            "boundary_coverage": np.round(boundary_coverage, 2),
            "error_handling": np.round(error_handling, 2),
            "mutation_resistance": np.round(mutation_resistance, 2),
            "test_type": test_type,
            "module_criticality": module_criticality,
            "lines_of_code": lines_of_code,
            "quality_score": np.round(quality_score, 2),
        }
    )
    df["quality_label"] = df["quality_score"].apply(_bucket)
    return df


def main():
    df = generate()
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"Wrote {len(df)} rows to {OUTPUT_PATH}")
    print(df["quality_label"].value_counts())


if __name__ == "__main__":
    main()
