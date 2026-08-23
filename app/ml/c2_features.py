"""Feature extraction + the hand-designed quality-score formula for
Component 2 (Intelligent-Test-Case-Generation) Gherkin test cases.

This is a SEPARATE research pipeline from app/ml/{weights,train_model,predict}.py
(which scores manually-entered local TestCase rows on 5 sliders). This one
scores real Gherkin feature text pulled live from Component 2, on 10 features
extracted from that text plus its linkage to a Component 1 requirement.

Design constraint (explicit research requirement): the label is NEVER derived
from PASS/FAIL execution outcome — that would make the model predict test
*execution* success rather than test *design* quality. PASS/FAIL is only fed
in as the `test_result` feature.
"""

from __future__ import annotations

import re

FEATURE_ORDER = [
    "description_length",
    "has_expected_result",
    "has_preconditions",
    "has_test_steps",
    "requirement_linked",
    "requirement_coverage",
    "ambiguity_score",
    "completeness_score",
    "specificity_score",
    "test_result",
]

FEATURE_LABELS = {
    "description_length": "Description Length",
    "has_expected_result": "Has Expected Result",
    "has_preconditions": "Has Preconditions",
    "has_test_steps": "Has Test Steps",
    "requirement_linked": "Requirement Linked",
    "requirement_coverage": "Requirement Coverage",
    "ambiguity_score": "Ambiguity Score",
    "completeness_score": "Completeness Score",
    "specificity_score": "Specificity Score",
    "test_result": "Test Result (Pass/Fail)",
}

LABEL_ORDER = ["Low", "Medium", "High"]

# Quality-score formula weights (given by the research spec). Each factor is
# a 0-100 sub-score; the weighted sum is the "initial" label-generating
# score used both to build training labels and to display an explainable
# score alongside the model's own classification.
QUALITY_WEIGHTS = {
    "completeness_score": 0.20,
    "requirement_coverage": 0.20,
    "specificity_score": 0.15,
    "has_expected_result": 0.15,  # scaled x100
    "has_preconditions": 0.10,  # scaled x100
    "has_test_steps": 0.10,  # scaled x100
    "low_ambiguity": 0.10,  # 100 - ambiguity_score
}

_AMBIGUOUS_WORDS = {
    "some", "many", "several", "various", "appropriate", "properly", "correctly",
    "etc", "reasonable", "adequate", "sufficient", "normal", "usual", "typical",
    "acceptable", "suitable", "certain", "few", "most", "quickly", "efficiently",
    "easily", "effectively", "generally", "usually", "occasionally",
}

_STEP_PREFIXES = ("given", "when", "then", "and", "but")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def _step_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().lower().startswith(_STEP_PREFIXES)
    ]


def extract_features(
    test_case: dict,
    requirement_linked: bool = False,
    acceptance_criteria: list[str] | None = None,
) -> dict:
    """
    test_case: {id, title, description (gherkin_text), status, ...}
    requirement_linked / acceptance_criteria: context from joining this test
    case's story_id against Component 1's requirements-with-stories (RTM's
    existing join — see routers/ml.py).
    """
    text = test_case.get("description") or ""
    description_length = len(text)

    has_expected_result = 1 if re.search(r"\bThen\b", text) else 0
    has_preconditions = 1 if re.search(r"\b(Given|Background)\b", text) else 0
    has_test_steps = 1 if re.search(r"\bWhen\b", text) else 0

    scenario_count = len(re.findall(r"^\s*Scenario(?: Outline)?:", text, re.MULTILINE))

    steps = _step_lines(text)
    specific_steps = sum(1 for line in steps if re.search(r'"[^"]+"|\d', line))
    specificity_score = round((specific_steps / len(steps)) * 100, 1) if steps else 0.0

    words = _words(text)
    ambiguous_hits = sum(1 for w in words if w in _AMBIGUOUS_WORDS)
    # Ambiguous-word density per 100 words, capped at 100.
    ambiguity_score = round(min(100.0, (ambiguous_hits / max(1, len(words))) * 1000), 1)

    acceptance_criteria = acceptance_criteria or []
    if acceptance_criteria:
        ac_words: set[str] = set()
        for ac in acceptance_criteria:
            ac_words |= set(_words(ac))
        text_words = set(words)
        overlap = len(ac_words & text_words)
        requirement_coverage = round(min(100.0, (overlap / max(1, len(ac_words))) * 100), 1)
    else:
        requirement_coverage = 0.0

    completeness_score = round(
        has_preconditions * 25
        + has_test_steps * 25
        + has_expected_result * 25
        + (min(scenario_count, 3) / 3) * 25,
        1,
    )

    test_result_map = {"approved": 1.0, "rejected": 0.0, "pending": 0.5}
    test_result = test_result_map.get(test_case.get("status"), 0.5)

    return {
        "test_case": test_case.get("title") or test_case.get("id", ""),
        "description_length": description_length,
        "has_expected_result": has_expected_result,
        "has_preconditions": has_preconditions,
        "has_test_steps": has_test_steps,
        "requirement_linked": int(bool(requirement_linked)),
        "requirement_coverage": requirement_coverage,
        "ambiguity_score": ambiguity_score,
        "completeness_score": completeness_score,
        "specificity_score": specificity_score,
        "test_result": test_result,
    }


def compute_quality_score(features: dict) -> float:
    score = (
        features["completeness_score"] * QUALITY_WEIGHTS["completeness_score"]
        + features["requirement_coverage"] * QUALITY_WEIGHTS["requirement_coverage"]
        + features["specificity_score"] * QUALITY_WEIGHTS["specificity_score"]
        + (features["has_expected_result"] * 100) * QUALITY_WEIGHTS["has_expected_result"]
        + (features["has_preconditions"] * 100) * QUALITY_WEIGHTS["has_preconditions"]
        + (features["has_test_steps"] * 100) * QUALITY_WEIGHTS["has_test_steps"]
        + (100 - features["ambiguity_score"]) * QUALITY_WEIGHTS["low_ambiguity"]
    )
    return round(max(0.0, min(100.0, score)), 2)


def quality_label(score: float) -> str:
    if score >= 80:
        return "High"
    if score >= 60:
        return "Medium"
    return "Low"


__all__ = [
    "FEATURE_ORDER",
    "FEATURE_LABELS",
    "LABEL_ORDER",
    "QUALITY_WEIGHTS",
    "extract_features",
    "compute_quality_score",
    "quality_label",
]
