"""Risk-based coverage-gap prioritization and resolution, built on the same
Component 1 (requirements-with-stories) and Component 2 (traceability test
cases) data the RTM Matrix / Quality Prediction / Test Inventory pages
already use -- see app/ml/c2_gap_analysis.py for the scoring/generation
logic itself.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.integrations import component1, component2
from app.integrations.component1 import Component1Unavailable
from app.integrations.component2 import Component2Unavailable
from app.ml.c2_features import extract_features
from app.ml.c2_gap_analysis import (
    QUALITY_GAP_THRESHOLD,
    compute_coverage,
    compute_risk,
    generate_gap_test_case,
    recommended_action,
)
from app.ml.c2_predict import predict_c2_quality

router = APIRouter(prefix="/api/rtm/c2-gaps", tags=["coverage-gaps"])


def _latest_code_coverage_pct(db: Session, project_id: str) -> float | None:
    report = (
        db.query(models.CoverageReport)
        .filter(models.CoverageReport.project_id == project_id)
        .first()
    )
    if report is None or report.status != models.CoverageJobStatus.DONE:
        return None
    return report.overall_coverage


@router.get("", response_model=list[schemas.C2CoverageGapOut])
async def list_coverage_gaps(project_id: str, iteration_id: str, db: Session = Depends(get_db)):
    try:
        requirements = await component1.get_requirements_with_stories(iteration_id)
    except Component1Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        test_cases = await component2.get_traceability_test_cases(project_id, iteration_id=iteration_id)
    except Component2Unavailable:
        test_cases = []

    tests_by_story: dict[str, list[dict]] = {}
    for tc in test_cases:
        tests_by_story.setdefault(tc["story_id"], []).append(tc)

    code_coverage_pct = _latest_code_coverage_pct(db, project_id)

    results = []
    for item in requirements:
        story_id = item["user_story_id"]
        linked = tests_by_story.get(story_id, [])
        descriptions = [tc.get("description", "") for tc in linked]
        acceptance_criteria = item.get("acceptance_criteria") or []

        covered, missing, coverage_pct = compute_coverage(acceptance_criteria, descriptions)

        avg_predicted_quality = None
        if linked:
            scores = []
            for tc in linked:
                features = extract_features(tc, requirement_linked=True, acceptance_criteria=acceptance_criteria)
                scores.append(predict_c2_quality(features)["quality_score"])
            avg_predicted_quality = round(sum(scores) / len(scores), 1) if scores else None
        has_failing_test = any(tc.get("status") == "rejected" for tc in linked)
        all_unverified = bool(linked) and all(tc.get("status") == "pending" for tc in linked)

        # A requirement is a genuine gap if: it has no linked test at all,
        # some acceptance criteria aren't textually covered, a linked test
        # is actively failing, the trained Quality Prediction model's own
        # classification isn't "High" for the covering test(s), or every
        # covering test is still unexecuted/unverified. Text coverage
        # alone isn't enough: a test can quote every acceptance-criterion
        # word, score decently on the formula, and still never have been
        # run, or still be classified Medium/Low by the model -- all real
        # risk worth surfacing here, not just "does the wording match."
        is_quality_gap = avg_predicted_quality is not None and avg_predicted_quality < QUALITY_GAP_THRESHOLD
        if linked and not missing and not has_failing_test and not is_quality_gap and not all_unverified:
            continue

        risk = compute_risk(
            priority=item.get("priority", ""),
            total_acceptance_criteria=len(acceptance_criteria),
            missing_acceptance_criteria=len(missing),
            linked_test_case_count=len(linked),
            coverage_pct=coverage_pct,
            test_statuses=[tc.get("status", "pending") for tc in linked],
            avg_predicted_quality=avg_predicted_quality,
            project_code_coverage_pct=code_coverage_pct,
        )

        results.append(
            schemas.C2CoverageGapOut(
                requirement_id=item["requirement_id"],
                requirement_text=item["requirement_text"],
                requirement_type=item.get("requirement_type", ""),
                user_story_id=story_id,
                user_story_title=item.get("user_story_title", ""),
                user_story_text=item.get("user_story_text", ""),
                priority=item.get("priority", ""),
                total_acceptance_criteria=len(acceptance_criteria),
                covered_acceptance_criteria=len(covered),
                missing_acceptance_criteria=missing,
                linked_test_case_count=len(linked),
                current_coverage_pct=coverage_pct,
                risk_score=risk["risk_score"],
                risk_level=risk["risk_level"],
                risk_factors=schemas.GapRiskFactorsOut(**risk["factors"]),
                recommended_action=recommended_action(
                    missing, len(linked), avg_predicted_quality, has_failing_test, all_unverified
                ),
            )
        )

    results.sort(key=lambda g: g.risk_score, reverse=True)
    return results


def _score_generated(db_row: models.GeneratedGapTestCase) -> schemas.GeneratedGapTestCasePredictionOut:
    test_case = {"id": str(db_row.id), "title": db_row.title, "description": db_row.description, "status": "pending"}
    features = extract_features(test_case, requirement_linked=True, acceptance_criteria=[db_row.acceptance_criterion])
    prediction = predict_c2_quality(features)
    return schemas.GeneratedGapTestCasePredictionOut(
        test_case=schemas.GeneratedGapTestCaseOut.model_validate(db_row),
        prediction=schemas.C2QualityPredictionOut(
            test_case_id=f"gap-{db_row.id}",
            title=db_row.title,
            story_id=db_row.user_story_id,
            status="pending",
            description=db_row.description,
            features=schemas.C2QualityFeaturesOut(**features),
            **prediction,
        ),
    )


def _get_or_create_generated(db: Session, payload: schemas.GenerateGapTestCaseRequest) -> models.GeneratedGapTestCase:
    existing = (
        db.query(models.GeneratedGapTestCase)
        .filter(
            models.GeneratedGapTestCase.project_id == payload.project_id,
            models.GeneratedGapTestCase.requirement_id == payload.requirement_id,
            models.GeneratedGapTestCase.acceptance_criterion == payload.acceptance_criterion,
        )
        .first()
    )
    if existing:
        return existing

    description = generate_gap_test_case(
        requirement_text=payload.requirement_text,
        user_story_title=payload.user_story_title,
        user_story_text=payload.user_story_text,
        acceptance_criterion=payload.acceptance_criterion,
    )
    row = models.GeneratedGapTestCase(
        project_id=payload.project_id,
        requirement_id=payload.requirement_id,
        requirement_text=payload.requirement_text,
        user_story_id=payload.user_story_id,
        user_story_title=payload.user_story_title,
        acceptance_criterion=payload.acceptance_criterion,
        title=f"{payload.user_story_title or 'Generated'} — {payload.acceptance_criterion.strip().rstrip('.')}"[:500],
        description=description,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with a concurrent identical request -- read back
        # whichever row won instead of creating a duplicate.
        db.rollback()
        row = (
            db.query(models.GeneratedGapTestCase)
            .filter(
                models.GeneratedGapTestCase.project_id == payload.project_id,
                models.GeneratedGapTestCase.requirement_id == payload.requirement_id,
                models.GeneratedGapTestCase.acceptance_criterion == payload.acceptance_criterion,
            )
            .first()
        )
    else:
        db.refresh(row)
    return row


@router.post("/generate-test-case", response_model=schemas.GeneratedGapTestCasePredictionOut)
def generate_test_case(payload: schemas.GenerateGapTestCaseRequest, db: Session = Depends(get_db)):
    row = _get_or_create_generated(db, payload)
    return _score_generated(row)


@router.post("/generate-all", response_model=schemas.GenerateAllGapTestCasesResponse)
def generate_all_test_cases(payload: schemas.GenerateAllGapTestCasesRequest, db: Session = Depends(get_db)):
    """Bulk resolution: generates (or reuses, idempotently) a test case for
    every (requirement, missing acceptance criterion) pair the caller sends
    -- used by the Coverage Gaps page's "Generate All for Critical Gaps"
    action, so a whole batch of high-risk gaps can be resolved in one step
    instead of one AC at a time."""
    rows = [_get_or_create_generated(db, item) for item in payload.items]
    return schemas.GenerateAllGapTestCasesResponse(generated=[_score_generated(r) for r in rows])


@router.post("/{gap_test_case_id}/add", response_model=schemas.GeneratedGapTestCasePredictionOut)
def add_generated_test_case(gap_test_case_id: int, payload: schemas.AddGapTestCaseRequest, db: Session = Depends(get_db)):
    row = db.get(models.GeneratedGapTestCase, gap_test_case_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Generated test case not found.")
    if payload.target == "inventory":
        row.added_to_inventory = True
    elif payload.target == "rtm":
        row.added_to_rtm = True
    else:
        raise HTTPException(status_code=400, detail="target must be 'inventory' or 'rtm'.")
    db.commit()
    db.refresh(row)
    return _score_generated(row)


@router.get("/generated", response_model=list[schemas.GeneratedGapTestCasePredictionOut])
def list_generated_test_cases(project_id: str, db: Session = Depends(get_db)):
    """Generated test cases that have been added to at least one of Test
    Inventory / RTM — consumed by those pages to merge them in alongside
    their live Component 1/2 data."""
    rows = (
        db.query(models.GeneratedGapTestCase)
        .filter(
            models.GeneratedGapTestCase.project_id == project_id,
            or_(models.GeneratedGapTestCase.added_to_inventory.is_(True), models.GeneratedGapTestCase.added_to_rtm.is_(True)),
        )
        .order_by(models.GeneratedGapTestCase.created_at.desc())
        .all()
    )
    return [_score_generated(r) for r in rows]
