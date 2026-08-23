"""Gap analysis + rule-based Given/When/Then rewriting for the "Intelligent
Test Improvement & Recommendations" page.

This is the research-novelty layer on top of the existing C2 quality
pipeline (app/ml/c2_features.py, app/ml/c2_predict.py): instead of only
predicting High/Medium/Low, it explains WHY a test case scored the way it
did (per-feature gap analysis, against the exact features/thresholds the
trained model already uses) and deterministically rewrites the
Given/When/Then text to close those gaps. The "improved" score is never
fabricated -- the rewritten text is run back through the SAME
extract_features() -> predict_c2_quality() pipeline used for every other
prediction on this page, so before/after is a measured result, not a
hardcoded demo number.

No LLM call is involved, consistent with the rest of this research
pipeline (c2_dataset.py's synthetic Gherkin generator uses the same
template-driven approach) and with there being no LLM credentials wired
into this service.
"""

from __future__ import annotations

# Thresholds mirror the qualitative bands already implied by
# c2_features.compute_quality_score()'s weighting -- below these, a feature
# is considered a genuine quality gap worth flagging.
_SPECIFICITY_THRESHOLD = 50.0
_AMBIGUITY_THRESHOLD = 30.0
_COVERAGE_THRESHOLD = 60.0
_COMPLETENESS_THRESHOLD = 70.0


def analyze_gaps(features: dict) -> list[dict]:
    """Given one test case's extracted feature dict (same shape produced by
    c2_features.extract_features), returns the list of detected quality
    gaps with a plain-language status and a specific recommendation."""
    gaps: list[dict] = []

    def add(area: str, label: str, status: str, recommendation: str) -> None:
        gaps.append(
            {"area": area, "label": label, "status": status, "severity": "warning", "recommendation": recommendation}
        )

    if not features.get("has_preconditions"):
        add(
            "has_preconditions",
            "Preconditions",
            "Missing",
            "Add the required initial system/user conditions (a Given step).",
        )
    if not features.get("has_test_steps"):
        add(
            "has_test_steps",
            "Test Steps",
            "Missing",
            "Specify each user action clearly (a When step).",
        )
    if not features.get("has_expected_result"):
        add(
            "has_expected_result",
            "Expected Result",
            "Missing",
            "Define the exact expected system response (a Then step).",
        )

    specificity = float(features.get("specificity_score", 0) or 0)
    if specificity < _SPECIFICITY_THRESHOLD:
        status = "Generic" if specificity == 0 else f"{specificity:.0f}/100"
        add(
            "specificity_score",
            "Specificity",
            status,
            "Use concrete values, field names, and button labels instead of vague wording.",
        )

    ambiguity = float(features.get("ambiguity_score", 0) or 0)
    if ambiguity > _AMBIGUITY_THRESHOLD:
        add(
            "ambiguity_score",
            "Clarity",
            f"{ambiguity:.0f}/100 ambiguous",
            "Replace vague words (e.g. \"some\", \"properly\", \"appropriate\") with precise, testable statements.",
        )

    coverage = float(features.get("requirement_coverage", 0) or 0)
    if coverage < _COVERAGE_THRESHOLD:
        add(
            "requirement_coverage",
            "Requirement Coverage",
            f"{coverage:.0f}%",
            "Add scenario steps that explicitly cover the linked requirement's acceptance criteria.",
        )

    completeness = float(features.get("completeness_score", 0) or 0)
    if completeness < _COMPLETENESS_THRESHOLD:
        add(
            "completeness_score",
            "Completeness",
            f"{completeness:.0f}/100",
            "Ensure the scenario has a clear Given/When/Then structure with enough scenario coverage.",
        )

    if not features.get("requirement_linked"):
        add(
            "requirement_linked",
            "Requirement Link",
            "Not Linked",
            "Link this test case to its source requirement/user story for traceability.",
        )

    return gaps


def _subject(title: str, user_story_title: str) -> str:
    return (user_story_title or title or "the feature").strip() or "the feature"


def generate_improved_gherkin(
    title: str,
    requirement_text: str,
    user_story_title: str,
    acceptance_criteria: list[str],
) -> str:
    """Rewrites a test case into a complete, specific, low-ambiguity
    Given/When/Then feature file: a happy-path scenario plus an
    invalid-input scenario (the same "happy path" / "error handling" shape
    Component 2's own generator produces), with a concrete precondition and
    concrete expected results, and -- when acceptance criteria (or, failing
    that, the linked requirement text) are available -- an explicit
    assertion line that folds in their wording so requirement_coverage is
    measurably higher, not just claimed to be."""
    subject = _subject(title, user_story_title)
    feature_title = title.strip() if title.strip() else subject

    lines = [f"Feature: {feature_title}", ""]

    lines.append(f"  Scenario: Improved — {subject} succeeds")
    lines.append(f'    Given a registered user is authenticated and on the "{subject}" page')
    lines.append(f'    When the user performs the required action for "{subject}" with valid input values')
    lines.append(f'    Then the system completes "{subject}" successfully and returns a confirmation')
    if acceptance_criteria:
        ac_text = " ".join(ac.strip() for ac in acceptance_criteria[:3] if ac.strip())
        if ac_text:
            lines.append(f"    And the result satisfies the linked acceptance criteria: {ac_text}")
    elif requirement_text.strip():
        lines.append(f'    And the result satisfies the requirement: {requirement_text.strip()}')
    lines.append("")

    lines.append(f"  Scenario: Improved — {subject} handles invalid input")
    lines.append(f'    Given a registered user is authenticated and on the "{subject}" page')
    lines.append(
        f'    When the user performs the required action for "{subject}" with invalid or missing input values'
    )
    lines.append("    Then the system rejects the action and displays a specific validation error message")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["analyze_gaps", "generate_improved_gherkin"]
