"""Dashboard summary for the open project + iteration: the matrix roll-up,
average predicted test quality, the project's last code-coverage run, and
recent Component 2 executions — all live."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas, services
from app.database import get_db
from app.integrations import component2
from app.integrations.component2 import Component2Unavailable
from app.ml.c2_features import extract_features
from app.ml.c2_predict import predict_c2_quality

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=schemas.DashboardSummaryOut)
async def get_dashboard_summary(project_id: str, iteration_id: str, db: Session = Depends(get_db)):
    matrix = await services.build_matrix(db, project_id, iteration_id)

    ac_by_story = {row.user_story_id: row.acceptance_criteria for row in matrix.rows}
    scores: list[float] = []
    buckets = {"High": 0, "Medium": 0, "Low": 0}
    for row in matrix.rows:
        for test in row.tests:
            ac = ac_by_story.get(row.user_story_id)
            features = extract_features(
                {"id": test.id, "title": test.title, "description": test.description, "status": test.status},
                requirement_linked=bool(ac),
                acceptance_criteria=ac,
            )
            prediction = predict_c2_quality(features)
            scores.append(prediction["quality_score"])
            label = prediction.get("predicted_label") or "Medium"
            buckets[label] = buckets.get(label, 0) + 1

    report = (
        db.query(models.CoverageReport)
        .filter(models.CoverageReport.project_id == project_id)
        .first()
    )
    code_coverage = (
        schemas.CodeCoverageSnapshotOut(
            status=report.status,
            repo_url=report.repo_url,
            statement_coverage=report.statement_coverage,
            branch_coverage=report.branch_coverage,
            overall_coverage=report.overall_coverage,
            updated_at=report.updated_at,
        )
        if report is not None
        else None
    )

    try:
        runs = await component2.get_test_runs(project_id, limit=5)
    except Component2Unavailable:
        runs = []
    recent_runs = [
        schemas.RecentRunOut(
            id=run["id"],
            status=run.get("status", ""),
            framework=run.get("framework", ""),
            mode=run.get("mode", ""),
            started_at=run.get("started_at"),
            finished_at=run.get("finished_at"),
            total_count=run.get("total_count", 0),
            passed_count=run.get("passed_count", 0),
            failed_count=run.get("failed_count", 0),
        )
        for run in runs
    ]

    return schemas.DashboardSummaryOut(
        matrix=matrix.summary,
        avg_quality_score=round(sum(scores) / len(scores), 1) if scores else 0.0,
        quality_distribution=[
            schemas.QualityBucket(label=label, tests=count) for label, count in buckets.items()
        ],
        code_coverage=code_coverage,
        recent_runs=recent_runs,
    )
