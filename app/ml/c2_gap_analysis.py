"""Risk-based coverage-gap prioritization and AC-specific test-case
generation for the Coverage Gaps page.

Research novelty over the base RTM Matrix / Quality Prediction pipeline:
this module doesn't just report which requirements lack coverage -- it
scores each gap's *risk* from concrete project signals (story priority,
how much of the requirement is covered, whether linked tests are failing,
project-wide code coverage) and can generate a Given/When/Then test case
targeted at one specific uncovered acceptance criterion, using the actual
wording of that criterion rather than a generic template.

Reuses the same word-overlap technique app/ml/c2_features.py already uses
for its `requirement_coverage` feature, applied per acceptance-criterion
instead of per whole-AC-list, so "which ACs are covered" is measured the
same way the quality model measures "how well is this AC covered" -- one
consistent notion of coverage across the app, not two competing ones.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-z']{3,}")

_PRIORITY_SCORE = {"Must": 100.0, "Should": 70.0, "Could": 40.0, "Won't": 10.0}

# Risk-score thresholds (0-100 scale -- see compute_risk below).
_CRITICAL_THRESHOLD = 70.0
_MEDIUM_THRESHOLD = 40.0

# A requirement whose acceptance criteria are all textually covered by a
# linked test case can still be a real gap: the covering test may be
# poorly designed (per the trained Quality Prediction model) or actively
# failing. This threshold is what "covered but risky" means.
QUALITY_GAP_THRESHOLD = 70.0


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _ac_is_covered(ac: str, test_descriptions: list[str], threshold: float = 0.4) -> bool:
    """An acceptance criterion counts as covered if a meaningful fraction of
    its (non-trivial) words appear in at least one linked test case's
    Given/When/Then text -- the same word-overlap notion of "coverage"
    app/ml/c2_features.py's requirement_coverage feature already uses."""
    ac_words = _words(ac)
    if not ac_words:
        return True
    for desc in test_descriptions:
        desc_words = _words(desc)
        overlap = len(ac_words & desc_words) / len(ac_words)
        if overlap >= threshold:
            return True
    return False


def compute_coverage(
    acceptance_criteria: list[str], test_descriptions: list[str]
) -> tuple[list[str], list[str], float]:
    """Returns (covered, missing, coverage_pct)."""
    if not acceptance_criteria:
        return [], [], 100.0
    covered = [ac for ac in acceptance_criteria if _ac_is_covered(ac, test_descriptions)]
    missing = [ac for ac in acceptance_criteria if ac not in covered]
    coverage_pct = round(len(covered) / len(acceptance_criteria) * 100, 1)
    return covered, missing, coverage_pct


def compute_risk(
    priority: str,
    total_acceptance_criteria: int,
    missing_acceptance_criteria: int,
    linked_test_case_count: int,
    coverage_pct: float,
    test_statuses: list[str],
    avg_predicted_quality: float | None,
    project_code_coverage_pct: float | None,
) -> dict:
    """
    Risk Score = average of five 0-100 factors:
      - Business Priority: from the linked user story's MoSCoW priority.
      - Coverage Gap: 100 if the requirement has no linked test case at
        all, else a small residual (some coverage exists, but isn't
        guaranteed complete).
      - Acceptance Criteria Gap: % of this requirement's acceptance
        criteria with no linked test case whose text covers them.
      - Test Failure Rate: % of linked, already-executed test cases that
        failed; when nothing has executed yet, falls back to the trained
        quality model's own risk signal (100 - avg predicted quality) as a
        proxy, since an untested-but-poorly-written test case is itself a
        risk.
      - Code Coverage: 100 - the project's overall statement/branch
        coverage from the most recent GitHub Code Coverage analysis
        (applied as a project-wide risk modifier, since coverage isn't
        tracked per-requirement) -- neutral (50) if no analysis has run
        yet.
    """
    business_priority = _PRIORITY_SCORE.get(priority, 50.0)

    coverage_gap = 100.0 if linked_test_case_count == 0 else round(max(0.0, 20.0 + (100 - coverage_pct) * 0.2), 1)

    acceptance_criteria_gap = (
        round(missing_acceptance_criteria / total_acceptance_criteria * 100, 1) if total_acceptance_criteria else 0.0
    )

    executed = [s for s in test_statuses if s in ("approved", "rejected")]
    if executed:
        failed = sum(1 for s in executed if s == "rejected")
        test_failure_rate = round(failed / len(executed) * 100, 1)
    elif avg_predicted_quality is not None:
        test_failure_rate = round(max(0.0, 100 - avg_predicted_quality), 1)
    else:
        test_failure_rate = 50.0

    code_coverage_gap = round(100 - project_code_coverage_pct, 1) if project_code_coverage_pct is not None else 50.0

    risk_score = round(
        (business_priority + coverage_gap + acceptance_criteria_gap + test_failure_rate + code_coverage_gap) / 5, 1
    )

    if risk_score >= _CRITICAL_THRESHOLD:
        risk_level = "Critical"
    elif risk_score >= _MEDIUM_THRESHOLD:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "factors": {
            "business_priority": business_priority,
            "coverage_gap": coverage_gap,
            "acceptance_criteria_gap": acceptance_criteria_gap,
            "test_failure_rate": test_failure_rate,
            "code_coverage_gap": code_coverage_gap,
        },
    }


def recommended_action(
    missing_acceptance_criteria: list[str],
    linked_test_case_count: int,
    avg_predicted_quality: float | None = None,
    has_failing_test: bool = False,
    all_unverified: bool = False,
) -> str:
    n = max(1, len(missing_acceptance_criteria)) if (missing_acceptance_criteria or linked_test_case_count == 0) else 0
    if n > 0:
        return f"Generate {n} additional test case{'s' if n != 1 else ''} for this requirement."
    if has_failing_test:
        return "Review and fix the failing linked test case(s) — acceptance criteria are textually covered but not passing."
    if avg_predicted_quality is not None and avg_predicted_quality < QUALITY_GAP_THRESHOLD:
        return (
            "Acceptance criteria are covered, but linked test cases score low on predicted quality — "
            "review and improve them (see the Quality Prediction / Test Improvement pages)."
        )
    if all_unverified:
        return "Execute the linked test case(s) — acceptance criteria are covered on paper but not yet verified."
    return "Monitor — coverage is adequate."


# ---------- AC-specific Given/When/Then generation ----------

_PERSONA_RE = re.compile(r"\bas an?\s+([a-zA-Z][a-zA-Z0-9 \-/]{2,40}?)(?:,|\bi want\b|$)", re.IGNORECASE)
_CONDITIONAL_RE = re.compile(r"^(?:if|when)\s+(.+?),\s*(?:then\s+)?(.+)$", re.IGNORECASE)
_CAPABILITY_RE = re.compile(r"^(.*?)\b(?:can|should be able to|must be able to|must|should)\b\s+(.+)$", re.IGNORECASE)


def _extract_persona(user_story_text: str) -> str:
    m = _PERSONA_RE.search(user_story_text or "")
    return m.group(1).strip() if m else "registered user"


def _split_acceptance_criterion(ac: str) -> tuple[str, str]:
    """Best-effort split of one acceptance-criterion sentence into a
    (when-action, then-outcome) pair, grounded in its actual wording."""
    ac = ac.strip().rstrip(".")
    m = _CONDITIONAL_RE.match(ac)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = _CAPABILITY_RE.match(ac)
    if m:
        action = m.group(2).strip()
        outcome = ac[0].lower() + ac[1:] if ac else ac
        return action, outcome
    lowered = ac[0].lower() + ac[1:] if ac else ac
    return lowered, lowered


def generate_gap_test_case(
    requirement_text: str,
    user_story_title: str,
    user_story_text: str,
    acceptance_criterion: str,
) -> str:
    """Generates a Given/When/Then scenario grounded in the specific
    uncovered acceptance criterion (not a generic placeholder): the When
    and Then clauses are derived from the criterion's own wording, the
    persona from the user story's "As a ..." framing when available."""
    persona = _extract_persona(user_story_text)
    subject = user_story_title.strip() or "the feature"
    when_action, then_outcome = _split_acceptance_criterion(acceptance_criterion)

    lines = [f"Feature: {subject}", "", f"  Scenario: {acceptance_criterion.strip().rstrip('.')}"]
    lines.append(f'    Given a {persona} is on the "{subject}" page')
    if requirement_text.strip():
        lines.append(f"    And the system meets the requirement: {requirement_text.strip().rstrip('.')}")
    lines.append(f"    When {when_action}")
    lines.append(f"    Then {then_outcome}")
    lines.append("    And no unrelated errors should occur")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "compute_coverage",
    "compute_risk",
    "recommended_action",
    "generate_gap_test_case",
    "QUALITY_GAP_THRESHOLD",
]
