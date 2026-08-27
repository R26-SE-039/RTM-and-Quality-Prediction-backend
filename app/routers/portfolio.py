"""Test Portfolio Optimization over the live test set: redundant (near
duplicates within a story), critical (sole/failing tests on Must-Should
requirements), and weak (model-rated Low) test cases."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas, services
from app.database import get_db
from app.ml.c2_features import extract_features
from app.ml.c2_predict import predict_c2_quality

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/analysis", response_model=schemas.PortfolioAnalysisOut)
async def get_portfolio_analysis(project_id: str, iteration_id: str, db: Session = Depends(get_db)):
    matrix = await services.build_matrix(db, project_id, iteration_id)

    quality_by_test: dict[str, dict] = {}
    for row in matrix.rows:
        for test in row.tests:
            if test.id in quality_by_test:
                continue
            features = extract_features(
                {"id": test.id, "title": test.title, "description": test.description, "status": test.status},
                requirement_linked=True,
                acceptance_criteria=row.acceptance_criteria,
            )
            quality_by_test[test.id] = predict_c2_quality(features)

    return services.analyze_portfolio(matrix.rows, quality_by_test)
