from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app import models, schemas, services
from app.database import get_db

router = APIRouter(prefix="/api/rtm", tags=["gaps"])

_RISK_ORDER = {
    models.RiskLevel.CRITICAL: 0,
    models.RiskLevel.HIGH: 1,
    models.RiskLevel.MEDIUM: 2,
    models.RiskLevel.LOW: 3,
}


@router.get("/gaps", response_model=list[schemas.CoverageGapOut])
def get_coverage_gaps(db: Session = Depends(get_db)):
    services.recompute_all_gaps(db)

    gaps = (
        db.query(models.CoverageGap)
        .options(joinedload(models.CoverageGap.requirement))
        .all()
    )

    gaps.sort(key=lambda g: _RISK_ORDER[g.risk_level])

    return [
        schemas.CoverageGapOut(
            requirement_id=g.requirement_id,
            requirement_title=g.requirement.title,
            status=services.compute_requirement_status(g.requirement)[0],
            risk_level=g.risk_level,
            recommendation=g.recommendation,
        )
        for g in gaps
    ]
