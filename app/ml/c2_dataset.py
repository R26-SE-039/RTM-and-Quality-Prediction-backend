"""Builds app/ml/data/c2_quality_dataset.csv: the training set for the
Component 2 test-case quality classifier.

Rows come from two sources, blended without a record of which is which
(this dataset represents test-case *characteristics*, not provenance):
  1. Real Component 2 test cases reachable from the project/iteration
     currently linked in ProjectSettings, feature-extracted via
     c2_features.extract_features and labeled via the weighted formula.
  2. Synthetic test cases, generated because Component 2 only has a
     handful of real test cases at any point in this project's lifecycle --
     nowhere near enough to train a meaningful classifier. Each synthetic
     row is a genuine Given/When/Then Gherkin `description`, generated from
     a per-quality-tier template (a "High" row's text really does include
     specific quoted values, full Given/When/Then coverage, and no vague
     wording; a "Low" row really is vague and incomplete). Every row's
     features -- for BOTH real and synthetic rows -- are then derived from
     that `description` text via the SAME extract_features() used at
     prediction time, and the label is computed from the SAME weighted
     formula used for real rows. So labels are always formula-consistent,
     and the classifier's job is to learn to reproduce/generalize that
     labeling function from Given/When/Then text characteristics -- never
     from a fabricated title alone.

     `test_result` (pass/fail/pending) is sampled with only a weak,
     imperfect correlation to quality tier on purpose -- per the research
     requirement, a test case's quality label must NOT be recoverable from
     its execution outcome alone.

Run with: python -m app.ml.c2_dataset [project_id] [iteration_id]
(defaults to the project/iteration currently linked in ProjectSettings)
"""

from __future__ import annotations

import asyncio
import os
import re
import sys

import numpy as np
import pandas as pd

from app.ml.c2_features import (
    _AMBIGUOUS_WORDS,
    FEATURE_ORDER,
    compute_quality_score,
    extract_features,
    quality_label,
)

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "c2_quality_dataset.csv")
TARGET_ROWS = 1000
RANDOM_SEED = 42

# Subject-area bank x verb-phrase bank, combined like Component 2's own
# Gherkin feature names ("The System <verb phrase> <subject>"), giving
# 9 x 32 = 288 distinct titles before repetition.
_SUBJECT_AREAS = [
    "Windows Server", "Both AWS And Azure Platforms", "Multi-Factor Authentication",
    "The Payment Gateway", "Database Backup And Restore", "Cross-Browser Rendering",
    "The Shopping Cart Checkout Flow", "Password Reset Emails", "Push Notification Delivery",
    "Role-Based Access Control", "The Search Indexing Pipeline", "API Rate Limiting",
    "Session Timeout Handling", "Third-Party Payment Providers", "Data Encryption At Rest",
    "Load Balancer Failover", "Automated Report Generation", "Customer Refund Workflows",
    "Subscription Billing Cycles", "Mobile Responsive Layouts", "Inventory Stock Synchronization",
    "The Audit Logging Subsystem", "Two-Factor SMS Verification", "Order Fulfillment Tracking",
    "Shipping Address Validation", "The Product Catalog Search", "Checkout Tax Calculation",
    "User Profile Photo Uploads", "The Notification Preferences Center", "Bulk CSV Data Import",
    "Single Sign-On Federation", "Offline Mode Data Sync",
]
_VERB_PHRASES = [
    "To Be Compatible With", "Configured For", "To Correctly Support", "To Properly Validate",
    "To Reliably Handle", "To Securely Process", "To Gracefully Recover Failures In",
    "To Accurately Track", "To Consistently Enforce",
]


def _generate_synthetic_title(rng: np.random.Generator) -> tuple[str, str]:
    """Returns (feature_title, subject) -- subject feeds the Given/When/Then
    line templates, feature_title is the Gherkin `Feature:` name."""
    verb = _VERB_PHRASES[rng.integers(0, len(_VERB_PHRASES))]
    subject = _SUBJECT_AREAS[rng.integers(0, len(_SUBJECT_AREAS))]
    return f"The System {verb} {subject}", subject

# Per-tier generation knobs for synthesizing realistic Given/When/Then
# Gherkin text. Rather than sampling numeric feature values directly (the
# old approach), we generate actual Scenario text and run it through the
# SAME extract_features() used for real Component 2 test cases, so every
# row's features are genuinely derived from Given/When/Then wording -- not
# independently fabricated numbers with a generic requirement-style title.
_TIER_SHAPES = {
    "High": {
        "p_expected": 0.95, "p_preconditions": 0.92, "p_steps": 0.95, "p_linked": 0.95,
        "specific_prob": 0.9, "scenario_range": (2, 3), "ac_overlap": 0.8,
    },
    "Medium": {
        "p_expected": 0.8, "p_preconditions": 0.75, "p_steps": 0.8, "p_linked": 0.75,
        "specific_prob": 0.5, "scenario_range": (1, 2), "ac_overlap": 0.4,
    },
    "Low": {
        "p_expected": 0.3, "p_preconditions": 0.25, "p_steps": 0.3, "p_linked": 0.2,
        "specific_prob": 0.1, "scenario_range": (1, 1), "ac_overlap": 0.1,
    },
}

_ACTORS = ["the user", "the administrator", "the API client", "the customer", "the operator"]
_AMBIGUOUS_WORDS_LIST = sorted(_AMBIGUOUS_WORDS)


def _vague_phrase(rng: np.random.Generator, count: int = 2) -> str:
    words = rng.choice(_AMBIGUOUS_WORDS_LIST, size=count, replace=False)
    return " ".join(str(w) for w in words)


def _precondition_line(subject: str, specific: bool, rng: np.random.Generator) -> str:
    actor = _ACTORS[rng.integers(0, len(_ACTORS))]
    if specific:
        n = int(rng.integers(2, 250))
        return f'Given {actor} is authenticated with role "qa_verified" and {n} matching records exist for {subject.lower()}'
    return f"Given {actor} is in {_vague_phrase(rng)} starting state for {subject.lower()}"


def _action_line(subject: str, specific: bool, rng: np.random.Generator) -> str:
    if specific:
        ref = int(rng.integers(1, 9999))
        return f'When the user submits "{subject}" with reference number "{ref}" and confirms the action'
    return f"When {_vague_phrase(rng)} action is performed on {subject.lower()}"


def _result_line(subject: str, specific: bool, rng: np.random.Generator) -> str:
    if specific:
        code = int(rng.choice([200, 201, 202, 204]))
        return f'Then the system returns status code {code} and "{subject}" is updated successfully'
    return f"Then the system responds in a {_vague_phrase(rng)} way"


def _generate_gherkin_text(
    title: str,
    subject: str,
    include_given: bool,
    include_when: bool,
    include_then: bool,
    specific: bool,
    n_scenarios: int,
    rng: np.random.Generator,
) -> str:
    lines = [f"Feature: {title}", ""]
    for i in range(max(1, n_scenarios)):
        lines.append(f"  Scenario: {title} case {i + 1}")
        if include_given:
            lines.append(f"    {_precondition_line(subject, specific, rng)}")
        if include_when:
            lines.append(f"    {_action_line(subject, specific, rng)}")
        if include_then:
            lines.append(f"    {_result_line(subject, specific, rng)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _generate_acceptance_criteria(
    gherkin_text: str, overlap_ratio: float, rng: np.random.Generator
) -> list[str]:
    """Builds acceptance-criteria sentences that share (or deliberately
    don't share) vocabulary with the generated Gherkin text, so
    extract_features's word-overlap requirement_coverage score lands near
    the target overlap_ratio for this tier."""
    text_words = sorted(set(re.findall(r"[a-z']{4,}", gherkin_text.lower())))
    if not text_words:
        return []
    rng.shuffle(text_words)
    k = max(1, round(overlap_ratio * len(text_words)))
    matching = text_words[:k]
    filler = ["stakeholder", "governance", "compliance", "audit", "policy", "review", "committee"]
    sentence = f"The system shall support {' '.join(matching)}"
    if overlap_ratio < 0.6:
        sentence += f" per {' '.join(filler[: max(1, 3 - k)])} requirements"
    return [sentence + "."]


async def _fetch_real_rows(project_id: str | None, iteration_id: str | None) -> list[dict]:
    if not project_id:
        return []
    from app.integrations import component1, component2
    from app.integrations.component1 import Component1Unavailable
    from app.integrations.component2 import Component2Unavailable

    try:
        test_cases = await component2.get_traceability_test_cases(project_id, iteration_id=iteration_id)
    except Component2Unavailable:
        return []

    requirement_by_story: dict[str, list[str]] = {}
    if iteration_id:
        try:
            requirements = await component1.get_requirements_with_stories(iteration_id)
            for item in requirements:
                requirement_by_story.setdefault(item["user_story_id"], []).extend(
                    item.get("acceptance_criteria") or []
                )
        except Component1Unavailable:
            pass

    rows = []
    for tc in test_cases:
        ac = requirement_by_story.get(tc.get("story_id"))
        features = extract_features(tc, requirement_linked=bool(ac), acceptance_criteria=ac)
        score = compute_quality_score(features)
        # Overrides features["test_case"] (extract_features's title) with the
        # full Given/When/Then text -- the dataset's `test_case` column IS the
        # Gherkin description, not a fabricated short title.
        rows.append({**features, "test_case": tc.get("description", ""), "quality_label": quality_label(score)})
    return rows


def _synthesize_rows(n: int, rng: np.random.Generator) -> list[dict]:
    """Generates realistic Given/When/Then Gherkin text per quality tier,
    then derives every feature from that text via the SAME extract_features()
    used for real Component 2 test cases -- so a synthetic "High" row really
    does have high completeness/coverage/specificity because its generated
    scenario text genuinely reads that way, not because those numbers were
    sampled independently of any text."""
    tiers = ["High", "Medium", "Low"]
    rows = []
    for i in range(n):
        tier = tiers[i % 3]  # roughly balanced across the 3 target tiers
        shape = _TIER_SHAPES[tier]

        title, subject = _generate_synthetic_title(rng)
        specific = bool(rng.random() < shape["specific_prob"])
        include_given = bool(rng.random() < shape["p_preconditions"])
        include_when = bool(rng.random() < shape["p_steps"])
        include_then = bool(rng.random() < shape["p_expected"])
        lo, hi = shape["scenario_range"]
        n_scenarios = int(rng.integers(lo, hi + 1))

        gherkin_text = _generate_gherkin_text(
            title, subject, include_given, include_when, include_then, specific, n_scenarios, rng
        )

        requirement_linked = bool(rng.random() < shape["p_linked"])
        acceptance_criteria = (
            _generate_acceptance_criteria(gherkin_text, shape["ac_overlap"], rng)
            if requirement_linked
            else []
        )

        # Deliberately weak tie between test_result and quality tier: a
        # well-designed test case is only slightly more likely to currently
        # be passing than a poorly-designed one -- nowhere near enough for
        # a model to use PASS/FAIL as a proxy label.
        tier_score = {"High": 0.58, "Medium": 0.5, "Low": 0.42}[tier]
        roll = rng.random()
        status = "approved" if roll < tier_score else ("rejected" if roll < tier_score + 0.35 else "pending")

        test_case = {"id": f"SYN-{i:04d}", "title": title, "description": gherkin_text, "status": status}
        features = extract_features(
            test_case, requirement_linked=requirement_linked, acceptance_criteria=acceptance_criteria
        )
        score = compute_quality_score(features)
        rows.append({**features, "test_case": gherkin_text, "quality_label": quality_label(score)})
    return rows


def build_dataset(project_id: str | None = None, iteration_id: str | None = None) -> pd.DataFrame:
    real_rows = asyncio.run(_fetch_real_rows(project_id, iteration_id))
    rng = np.random.default_rng(RANDOM_SEED)
    synthetic_rows = _synthesize_rows(max(0, TARGET_ROWS - len(real_rows)), rng)

    df = pd.DataFrame(real_rows + synthetic_rows)
    columns = ["test_case"] + FEATURE_ORDER + ["quality_label"]
    df = df[columns]

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    df.to_csv(DATA_PATH, index=False)
    print(f"Saved {len(df)} rows to {DATA_PATH}")
    print(df["quality_label"].value_counts())
    return df


if __name__ == "__main__":
    project_id = sys.argv[1] if len(sys.argv) > 1 else None
    iteration_id = sys.argv[2] if len(sys.argv) > 2 else None

    if project_id is None:
        # Default to whatever project/iteration is currently linked in
        # ProjectSettings, same as the RTM Matrix page uses.
        from app.database import SessionLocal
        from app.models import ProjectSettings

        db = SessionLocal()
        try:
            settings = db.query(ProjectSettings).first()
            if settings:
                project_id = settings.component2_project_id
                iteration_id = settings.component1_iteration_id
        finally:
            db.close()

    build_dataset(project_id, iteration_id)
