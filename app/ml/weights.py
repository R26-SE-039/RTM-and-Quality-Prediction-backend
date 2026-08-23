"""Domain-expert weights used to (a) label the training dataset
(see app/ml/data/generate_dataset.py) and (b) serve as a transparent
fallback scorer if no trained model is present.

The weight ordering is deliberately NOT "coverage above all else". A
well-known empirical finding in software testing research is that code
coverage alone correlates weakly with a test suite's actual fault-detection
ability:

  Inozemtseva, L. & Holmes, R. (2014). "Coverage Is Not Strongly Correlated
  with Test Suite Effectiveness." ICSE 2014.

Mutation testing is generally considered a stronger effectiveness proxy
because it directly measures whether tests catch injected faults, not just
whether code was executed:

  Jia, Y. & Harman, M. (2011). "An Analysis and Survey of the Development
  of Mutation Testing." IEEE Transactions on Software Engineering.

Assertion strength and boundary-value coverage are grounded in classic
test-design guidance (weak/missing assertions are the "Assertion Roulette"
smell in xUnit Test Patterns; boundary value analysis is a core technique
in Myers' "The Art of Software Testing"). Error handling / negative-path
coverage is weighted lowest because it is the narrowest of the five
signals (it only concerns failure paths).

These are still hand-set weights, not weights fit from real-world defect
data (no such labeled dataset exists for this app's exact feature schema
-- see the dataset card). They are the *labeling function* for the
synthetic-but-literature-informed training set; the actual predictive
model is a Random Forest trained on data generated from these weights plus
realistic feature correlation, non-linear interaction effects and noise.
"""

FEATURE_ORDER = [
    "assertion_strength",
    "coverage_percent",
    "boundary_coverage",
    "error_handling",
    "mutation_resistance",
]

WEIGHTS = {
    "mutation_resistance": 0.27,
    "coverage_percent": 0.24,
    "assertion_strength": 0.22,
    "boundary_coverage": 0.17,
    "error_handling": 0.10,
}

QUALITY_REJECT_THRESHOLD = 60.0


def weighted_score(features: dict) -> float:
    score = sum(features[key] * WEIGHTS[key] for key in FEATURE_ORDER)
    return max(0.0, min(100.0, score))
