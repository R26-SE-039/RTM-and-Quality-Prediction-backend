"""Business logic for RTM generation, coverage-gap detection, and test
portfolio analysis. Kept separate from the routers so the same recompute
logic can be triggered both by API handlers and by internal write paths.
"""

import re
from collections import defaultdict
from datetime import date, timedelta
from difflib import SequenceMatcher

from sqlalchemy.orm import Session, joinedload

from app import models

FULL_COVERAGE_THRESHOLD = 80.0
WEAK_QUALITY_THRESHOLD = 60.0
REDUNDANCY_SIMILARITY_THRESHOLD = 0.6

CRITICAL_KEYWORDS = [
    "payment", "checkout", "billing", "transaction", "auth", "login",
    "password", "security", "encrypt", "credential", "compliance",
    "pci", "gdpr", "authorization", "refund",
]
HIGH_KEYWORDS = [
    "error handling", "exception", "validation", "data loss", "integrity",
    "api", "database", "session", "concurrency", "critical",
]
MEDIUM_KEYWORDS = [
    "performance", "ui", "usability", "report", "export", "import",
    "notification", "search", "filter",
]


def log_activity(db: Session, activity_type: models.ActivityType, title: str, detail: str = "") -> None:
    db.add(models.ActivityLog(activity_type=activity_type, title=title, detail=detail))
    db.commit()


def classify_risk(requirement: models.Requirement) -> models.RiskLevel:
    text = f"{requirement.title} {requirement.description}".lower()
    if any(kw in text for kw in CRITICAL_KEYWORDS):
        return models.RiskLevel.CRITICAL
    if any(kw in text for kw in HIGH_KEYWORDS):
        return models.RiskLevel.HIGH
    if any(kw in text for kw in MEDIUM_KEYWORDS):
        return models.RiskLevel.MEDIUM
    return models.RiskLevel.LOW


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:max_len] or "case"


def get_test_coverage_percent(test: models.TestCase) -> float:
    if test.code_coverage:
        values = [c.coverage_percent for c in test.code_coverage]
        return sum(values) / len(values)
    return test.coverage_percent


def ac_coverage(ac: models.AcceptanceCriteria) -> tuple[bool, float]:
    tests = ac.test_cases
    approved = [t for t in tests if t.status == models.TestStatus.APPROVED]
    covered = len(approved) > 0
    if tests:
        avg_cov = sum(get_test_coverage_percent(t) for t in tests) / len(tests)
    else:
        avg_cov = 0.0
    return covered, avg_cov


def compute_requirement_status(
    requirement: models.Requirement,
) -> tuple[models.CoverageStatus, int, int, int, float]:
    ac_list = requirement.acceptance_criteria
    total_ac = len(ac_list)
    total_tests = sum(len(ac.test_cases) for ac in ac_list)

    if total_ac == 0:
        return models.CoverageStatus.NOT_COVERED, 0, 0, 0, 0.0

    covered_count = 0
    coverage_values = []
    for ac in ac_list:
        covered, avg_cov = ac_coverage(ac)
        if covered:
            covered_count += 1
        coverage_values.append(avg_cov)

    avg_coverage = sum(coverage_values) / len(coverage_values) if coverage_values else 0.0

    if covered_count == 0:
        status = models.CoverageStatus.NOT_COVERED
    elif covered_count == total_ac and avg_coverage >= FULL_COVERAGE_THRESHOLD:
        status = models.CoverageStatus.FULLY_COVERED
    else:
        status = models.CoverageStatus.PARTIAL

    return status, total_ac, covered_count, total_tests, avg_coverage


def _load_requirement(db: Session, requirement_id: int) -> models.Requirement | None:
    return (
        db.query(models.Requirement)
        .options(
            joinedload(models.Requirement.acceptance_criteria)
            .joinedload(models.AcceptanceCriteria.test_cases)
            .joinedload(models.TestCase.code_coverage)
        )
        .filter(models.Requirement.id == requirement_id)
        .first()
    )


def recompute_rtm_for_requirement(db: Session, requirement_id: int) -> None:
    requirement = _load_requirement(db, requirement_id)
    if requirement is None:
        return

    db.query(models.RTMEntry).filter(models.RTMEntry.requirement_id == requirement_id).delete()

    for ac in requirement.acceptance_criteria:
        covered, avg_cov = ac_coverage(ac)
        if ac.test_cases:
            ac_status = (
                models.CoverageStatus.FULLY_COVERED
                if covered and avg_cov >= FULL_COVERAGE_THRESHOLD
                else (models.CoverageStatus.PARTIAL if covered else models.CoverageStatus.NOT_COVERED)
            )
            for test in ac.test_cases:
                db.add(
                    models.RTMEntry(
                        requirement_id=requirement.id,
                        acceptance_criteria_id=ac.id,
                        test_case_id=test.id,
                        coverage_percent=get_test_coverage_percent(test),
                        status=ac_status,
                    )
                )
        else:
            db.add(
                models.RTMEntry(
                    requirement_id=requirement.id,
                    acceptance_criteria_id=ac.id,
                    test_case_id=None,
                    coverage_percent=0.0,
                    status=models.CoverageStatus.NOT_COVERED,
                )
            )

    db.commit()
    recompute_gaps_for_requirement(db, requirement_id)


def _generate_recommendation(
    requirement: models.Requirement,
    status: models.CoverageStatus,
) -> str:
    if not requirement.acceptance_criteria:
        return (
            f"Define acceptance criteria for requirement '{requirement.title}' — "
            "none exist yet, so no tests can be traced to it."
        )

    uncovered = [ac for ac in requirement.acceptance_criteria if not ac_coverage(ac)[0]]
    if not uncovered:
        return (
            f"Increase coverage depth for '{requirement.title}': acceptance criteria "
            "have tests, but average code coverage is below the 80% target."
        )

    suggestions = [f"test_{_slugify(ac.description)}_should_pass" for ac in uncovered[:3]]
    ac_preview = "; ".join(ac.description[:60] for ac in uncovered[:3])
    return (
        f"Add test cases for uncovered acceptance criteria on '{requirement.title}': "
        f"{ac_preview}. Suggested test names: {', '.join(suggestions)}."
    )


def recompute_gaps_for_requirement(db: Session, requirement_id: int) -> None:
    requirement = _load_requirement(db, requirement_id)
    if requirement is None:
        return

    had_gap_before = (
        db.query(models.CoverageGap).filter(models.CoverageGap.requirement_id == requirement_id).first()
        is not None
    )
    db.query(models.CoverageGap).filter(models.CoverageGap.requirement_id == requirement_id).delete()

    status, *_ = compute_requirement_status(requirement)
    if status != models.CoverageStatus.FULLY_COVERED:
        risk = classify_risk(requirement)
        recommendation = _generate_recommendation(requirement, status)
        db.add(
            models.CoverageGap(
                requirement_id=requirement.id,
                risk_level=risk,
                recommendation=recommendation,
            )
        )
        # Only log an activity when a gap newly appears (not on every
        # recompute of an already-known gap), so the feed doesn't flood.
        if not had_gap_before and risk in (models.RiskLevel.CRITICAL, models.RiskLevel.HIGH):
            db.add(
                models.ActivityLog(
                    activity_type=models.ActivityType.GAP_DETECTED,
                    title="Coverage gap detected",
                    detail=f"{risk.value.title()} risk on '{requirement.title}'",
                )
            )

    db.commit()


def recompute_all_gaps(db: Session) -> None:
    requirement_ids = [r.id for r in db.query(models.Requirement.id).all()]
    for requirement_id in requirement_ids:
        recompute_gaps_for_requirement(db, requirement_id)


def recompute_all_rtm(db: Session) -> None:
    requirement_ids = [r.id for r in db.query(models.Requirement.id).all()]
    for requirement_id in requirement_ids:
        recompute_rtm_for_requirement(db, requirement_id)


# ---------- Portfolio analysis ----------


def analyze_portfolio(db: Session) -> dict[str, list[models.PortfolioAction]]:
    db.query(models.PortfolioAction).delete()

    tests = (
        db.query(models.TestCase)
        .options(
            joinedload(models.TestCase.acceptance_criteria).joinedload(
                models.AcceptanceCriteria.requirement
            )
        )
        .all()
    )

    groups: dict[int, list[models.TestCase]] = defaultdict(list)
    for t in tests:
        groups[t.acceptance_criteria_id].append(t)

    flagged_redundant_ids: set[int] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                similarity = SequenceMatcher(None, a.title.lower(), b.title.lower()).ratio()
                if similarity >= REDUNDANCY_SIMILARITY_THRESHOLD:
                    keep, drop = (
                        (a, b) if (a.quality_score or 0) >= (b.quality_score or 0) else (b, a)
                    )
                    if drop.id in flagged_redundant_ids:
                        continue
                    flagged_redundant_ids.add(drop.id)
                    reason = (
                        f"Redundant with '{keep.title}' (title similarity {similarity:.0%}); "
                        f"both cover the same acceptance criteria. Keep '{keep.title}' "
                        f"(quality {keep.quality_score or 0:.0f}) and review/retire '{drop.title}'."
                    )
                    db.add(
                        models.PortfolioAction(
                            test_case_id=drop.id,
                            action_type=models.ActionType.REDUNDANT,
                            reason=reason,
                        )
                    )

    for t in tests:
        requirement = t.acceptance_criteria.requirement
        risk = classify_risk(requirement)
        if risk in (models.RiskLevel.CRITICAL, models.RiskLevel.HIGH) and t.status == models.TestStatus.APPROVED:
            reason = (
                f"Covers a {risk.value}-risk requirement ('{requirement.title}') with an "
                f"approved quality score of {t.quality_score:.0f}/100 — treat as a portfolio priority."
            )
            db.add(
                models.PortfolioAction(
                    test_case_id=t.id,
                    action_type=models.ActionType.CRITICAL,
                    reason=reason,
                )
            )

    for t in tests:
        if t.quality_score is not None and t.quality_score < WEAK_QUALITY_THRESHOLD:
            requirement = t.acceptance_criteria.requirement
            risk = classify_risk(requirement)
            reason = (
                f"Low quality score ({t.quality_score:.0f}/100) on a {risk.value}-risk "
                f"requirement ('{requirement.title}'); strengthen assertions/coverage or remove."
            )
            db.add(
                models.PortfolioAction(
                    test_case_id=t.id,
                    action_type=models.ActionType.WEAK,
                    reason=reason,
                )
            )

    db.commit()

    actions = (
        db.query(models.PortfolioAction)
        .options(joinedload(models.PortfolioAction.test_case))
        .all()
    )
    result: dict[str, list[models.PortfolioAction]] = {"redundant": [], "critical": [], "weak": []}
    for action in actions:
        result[action.action_type.value].append(action)
    return result


# ---------- Dashboard summary ----------


def compute_dashboard_summary(db: Session) -> dict:
    tests = (
        db.query(models.TestCase)
        .options(joinedload(models.TestCase.code_coverage))
        .all()
    )
    requirements = (
        db.query(models.Requirement)
        .options(joinedload(models.Requirement.acceptance_criteria).joinedload(models.AcceptanceCriteria.test_cases))
        .all()
    )

    scored = [t for t in tests if t.quality_score is not None]
    tests_analyzed = len(scored)
    avg_quality_score = sum(t.quality_score for t in scored) / len(scored) if scored else 0.0

    approved = [t for t in scored if t.status == models.TestStatus.APPROVED]
    success_rate = (len(approved) / len(scored) * 100) if scored else 0.0

    coverage_values = [get_test_coverage_percent(t) for t in tests]
    coverage_rate = sum(coverage_values) / len(coverage_values) if coverage_values else 0.0

    requirements_total = len(requirements)
    requirements_covered = sum(
        1 for r in requirements if compute_requirement_status(r)[0] == models.CoverageStatus.FULLY_COVERED
    )

    by_day: dict[str, list[models.TestCase]] = defaultdict(list)
    for t in scored:
        by_day[t.created_at.date().isoformat()].append(t)

    trend = []
    for day in sorted(by_day.keys()):
        day_tests = by_day[day]
        trend.append(
            {
                "date": day,
                "avg_quality": sum(t.quality_score for t in day_tests) / len(day_tests),
                "avg_coverage": sum(get_test_coverage_percent(t) for t in day_tests) / len(day_tests),
            }
        )

    if len(trend) >= 2:
        quality_trend_pct = trend[-1]["avg_quality"] - trend[0]["avg_quality"]
    else:
        quality_trend_pct = 0.0

    if len(trend) == 1:
        # Only one day of data exists — duplicate it a day earlier so the
        # trend chart can render a (flat) line instead of a single point.
        only_point = trend[0]
        earlier_date = (date.fromisoformat(only_point["date"]) - timedelta(days=1)).isoformat()
        trend = [{**only_point, "date": earlier_date}, only_point]

    buckets = [
        ("Excellent", 90, 100),
        ("Good", 70, 90),
        ("Fair", 50, 70),
        ("Poor", 0, 50),
    ]
    quality_distribution = [
        {
            "label": label,
            "tests": sum(1 for t in scored if lo <= t.quality_score < hi or (hi == 100 and t.quality_score == 100)),
        }
        for label, lo, hi in buckets
    ]

    recent_activities = (
        db.query(models.ActivityLog).order_by(models.ActivityLog.created_at.desc()).limit(5).all()
    )

    return {
        "tests_analyzed": tests_analyzed,
        "avg_quality_score": round(avg_quality_score, 1),
        "coverage_rate": round(coverage_rate, 1),
        "success_rate": round(success_rate, 1),
        "quality_trend_pct": round(quality_trend_pct, 1),
        "trend": trend,
        "requirements_covered": requirements_covered,
        "requirements_total": requirements_total,
        "quality_distribution": quality_distribution,
        "recent_activities": [
            {
                "activity_type": a.activity_type.value,
                "title": a.title,
                "detail": a.detail,
                "created_at": a.created_at,
            }
            for a in recent_activities
        ],
    }
