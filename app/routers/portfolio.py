from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas, services
from app.database import get_db

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/analysis", response_model=schemas.PortfolioAnalysisOut)
def get_portfolio_analysis(db: Session = Depends(get_db)):
    grouped = services.analyze_portfolio(db)

    def to_out(actions):
        return [
            schemas.PortfolioActionOut(
                test_case_id=a.test_case_id,
                test_title=a.test_case.title,
                action_type=a.action_type,
                reason=a.reason,
            )
            for a in actions
        ]

    return schemas.PortfolioAnalysisOut(
        redundant=to_out(grouped["redundant"]),
        critical=to_out(grouped["critical"]),
        weak=to_out(grouped["weak"]),
    )
