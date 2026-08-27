"""Live aggregation over Component 1 (requirements + user stories) and
Component 2 (generated test cases + execution results), scoped to the
project/iteration the user has open in the merged frontend.

This is the single place the RTM Matrix is assembled; the matrix, dashboard,
inventory, and portfolio endpoints all build on `build_matrix()` so every
page shows the same numbers for the same project + iteration.
"""

import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.integrations import component1, component2
from app.integrations.component1 import Component1Unavailable
from app.integrations.component2 import Component2Unavailable
from app.ml.c2_gap_analysis import compute_coverage

STATUS_FULLY = "FULLY COVERED"
STATUS_PARTIAL = "PARTIAL"
STATUS_NOT = "NOT COVERED"


async def fetch_requirements(iteration_id: str) -> list[dict]:
    try:
        return await component1.get_requirements_with_stories(iteration_id)
    except Component1Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


async def fetch_test_cases(project_id: str, iteration_id: str | None) -> list[dict]:
    """C2 test cases; an unreachable C2 degrades to an empty list so the
    matrix still renders its requirements side."""
    try:
        return await component2.get_traceability_test_cases(project_id, iteration_id=iteration_id)
    except Component2Unavailable:
        return []


def _gap_rows(db: Session, project_id: str, flag) -> list[models.GeneratedGapTestCase]:
    return (
        db.query(models.GeneratedGapTestCase)
        .filter(models.GeneratedGapTestCase.project_id == project_id, flag.is_(True))
        .order_by(models.GeneratedGapTestCase.created_at.asc())
        .all()
    )


def _build_row(item: dict, linked: list[dict], gap_rows: list[models.GeneratedGapTestCase]) -> schemas.MatrixRowOut:
    tests = [
        schemas.MatrixTestOut(
            id=tc["id"],
            title=tc["title"],
            description=tc.get("description", ""),
            status=tc.get("status", "pending"),
            source="C2",
        )
        for tc in linked
    ] + [
        schemas.MatrixTestOut(
            id=f"gap-{row.id}",
            title=row.title,
            description=row.description,
            status="pending",
            source="generated",
        )
        for row in gap_rows
    ]

    acceptance_criteria = item.get("acceptance_criteria") or []
    covered, missing, coverage_pct = compute_coverage(
        acceptance_criteria, [t.description for t in tests]
    )

    passed = sum(1 for t in tests if t.status == "approved")
    failed = sum(1 for t in tests if t.status == "rejected")
    pending = len(tests) - passed - failed

    if not tests:
        coverage_status = STATUS_NOT
    elif missing:
        coverage_status = STATUS_PARTIAL
    else:
        coverage_status = STATUS_FULLY

    return schemas.MatrixRowOut(
        requirement_id=item["requirement_id"],
        requirement_text=item["requirement_text"],
        requirement_type=item.get("requirement_type", ""),
        requirement_status=item.get("requirement_status", ""),
        meeting_title=item.get("meeting_title"),
        user_story_id=item["user_story_id"],
        user_story_title=item.get("user_story_title", ""),
        user_story_text=item.get("user_story_text", ""),
        priority=item.get("priority", ""),
        user_story_status=item.get("user_story_status"),
        acceptance_criteria=acceptance_criteria,
        total_acceptance_criteria=len(acceptance_criteria),
        covered_acceptance_criteria=len(covered),
        missing_acceptance_criteria=missing,
        coverage_pct=coverage_pct,
        tests=tests,
        total_tests=len(tests),
        passed_tests=passed,
        failed_tests=failed,
        pending_tests=pending,
        coverage_status=coverage_status,
    )


def _summarize(rows: list[schemas.MatrixRowOut]) -> schemas.MatrixSummaryOut:
    total_tests = sum(r.total_tests for r in rows)
    passed = sum(r.passed_tests for r in rows)
    failed = sum(r.failed_tests for r in rows)
    executed = passed + failed
    return schemas.MatrixSummaryOut(
        total_requirements=len(rows),
        fully_covered=sum(1 for r in rows if r.coverage_status == STATUS_FULLY),
        partially_covered=sum(1 for r in rows if r.coverage_status == STATUS_PARTIAL),
        not_covered=sum(1 for r in rows if r.coverage_status == STATUS_NOT),
        total_tests=total_tests,
        passed_tests=passed,
        failed_tests=failed,
        pending_tests=total_tests - executed,
        pass_rate=round(passed / executed * 100, 1) if executed else 0.0,
        defects=failed,
        avg_coverage_pct=round(sum(r.coverage_pct for r in rows) / len(rows), 1) if rows else 0.0,
    )


async def build_matrix(db: Session, project_id: str, iteration_id: str) -> schemas.MatrixOut:
    requirements = await fetch_requirements(iteration_id)
    test_cases = await fetch_test_cases(project_id, iteration_id)

    tests_by_story: dict[str, list[dict]] = {}
    for tc in test_cases:
        tests_by_story.setdefault(tc["story_id"], []).append(tc)

    gaps_by_requirement: dict[str, list[models.GeneratedGapTestCase]] = {}
    for row in _gap_rows(db, project_id, models.GeneratedGapTestCase.added_to_rtm):
        gaps_by_requirement.setdefault(row.requirement_id, []).append(row)

    rows = [
        _build_row(
            item,
            tests_by_story.get(item["user_story_id"], []),
            gaps_by_requirement.get(item["requirement_id"], []),
        )
        for item in requirements
    ]

    return schemas.MatrixOut(
        project_id=project_id,
        iteration_id=iteration_id,
        summary=_summarize(rows),
        rows=rows,
    )


# ---------- Portfolio (redundant / critical / weak) ----------

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def analyze_portfolio(rows: list[schemas.MatrixRowOut], quality_by_test: dict[str, dict]) -> schemas.PortfolioAnalysisOut:
    """Classify the live test portfolio:

    - redundant: near-duplicate test descriptions within the same user story
      (high word-set overlap) — candidates to merge or retire.
    - critical: sole covering test of a Must/Should requirement, or a test
      currently failing on one — protect and prioritize these.
    - weak: tests the quality model classifies Low (or that score < 50) —
      candidates to strengthen via the Quality Prediction page.
    """
    redundant: list[schemas.PortfolioItemOut] = []
    critical: list[schemas.PortfolioItemOut] = []
    weak: list[schemas.PortfolioItemOut] = []
    seen_redundant: set[str] = set()

    for row in rows:
        high_priority = row.priority.lower() in ("must", "should")
        test_words = [(t, _words(t.description or t.title)) for t in row.tests]

        for i, (test, words) in enumerate(test_words):
            for other, other_words in test_words[i + 1:]:
                if _jaccard(words, other_words) >= 0.8 and other.id not in seen_redundant:
                    seen_redundant.add(other.id)
                    redundant.append(
                        schemas.PortfolioItemOut(
                            test_id=other.id,
                            test_title=other.title,
                            user_story_title=row.user_story_title,
                            reason=f"Nearly identical to \"{test.title}\" on the same user story — consider merging.",
                        )
                    )

        for test in row.tests:
            if high_priority and test.status == "rejected":
                critical.append(
                    schemas.PortfolioItemOut(
                        test_id=test.id,
                        test_title=test.title,
                        user_story_title=row.user_story_title,
                        reason=f"Failing on a {row.priority} requirement — fix before release.",
                    )
                )
            elif high_priority and row.total_tests == 1:
                critical.append(
                    schemas.PortfolioItemOut(
                        test_id=test.id,
                        test_title=test.title,
                        user_story_title=row.user_story_title,
                        reason=f"Only test covering a {row.priority} requirement — protect it.",
                    )
                )

            quality = quality_by_test.get(test.id)
            if quality is not None:
                label = quality.get("predicted_label", "")
                score = quality.get("quality_score", 100.0)
                if label == "Low" or score < 50:
                    weak.append(
                        schemas.PortfolioItemOut(
                            test_id=test.id,
                            test_title=test.title,
                            user_story_title=row.user_story_title,
                            reason=f"Quality model rates this {label or 'weak'} ({score:.0f}/100) — strengthen assertions and coverage.",
                        )
                    )

    return schemas.PortfolioAnalysisOut(redundant=redundant, critical=critical, weak=weak)
