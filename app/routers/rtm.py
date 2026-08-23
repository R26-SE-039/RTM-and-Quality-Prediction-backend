from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app import models, schemas, services
from app.database import get_db

router = APIRouter(tags=["rtm"])


@router.post("/api/requirements", response_model=schemas.RequirementOut, status_code=201)
def create_requirement(payload: schemas.RequirementCreate, db: Session = Depends(get_db)):
    requirement = models.Requirement(**payload.model_dump())
    db.add(requirement)
    db.commit()
    db.refresh(requirement)
    services.recompute_rtm_for_requirement(db, requirement.id)
    return requirement


@router.get("/api/requirements", response_model=list[schemas.RequirementOut])
def list_requirements(db: Session = Depends(get_db)):
    return db.query(models.Requirement).order_by(models.Requirement.id).all()


@router.get("/api/requirements/{requirement_id}", response_model=schemas.RequirementOut)
def get_requirement(requirement_id: int, db: Session = Depends(get_db)):
    requirement = db.query(models.Requirement).get(requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return requirement


@router.post(
    "/api/requirements/{requirement_id}/acceptance-criteria",
    response_model=schemas.AcceptanceCriteriaOut,
    status_code=201,
)
def create_acceptance_criteria(
    requirement_id: int, payload: schemas.AcceptanceCriteriaCreate, db: Session = Depends(get_db)
):
    requirement = db.query(models.Requirement).get(requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found")

    ac = models.AcceptanceCriteria(requirement_id=requirement_id, **payload.model_dump())
    db.add(ac)
    db.commit()
    db.refresh(ac)

    services.recompute_rtm_for_requirement(db, requirement_id)
    return ac


def _build_requirement_entry(requirement: models.Requirement) -> schemas.RTMRequirementEntry:
    status, total_ac, covered_ac, total_tests, avg_coverage = services.compute_requirement_status(
        requirement
    )

    ac_entries = []
    for ac in requirement.acceptance_criteria:
        covered, _ = services.ac_coverage(ac)
        test_entries = [
            schemas.RTMTestEntry(
                test_case_id=t.id,
                title=t.title,
                status=t.status,
                quality_score=t.quality_score,
                coverage_percent=services.get_test_coverage_percent(t),
            )
            for t in ac.test_cases
        ]
        ac_entries.append(
            schemas.RTMAcceptanceCriteriaEntry(
                acceptance_criteria_id=ac.id,
                description=ac.description,
                tests=test_entries,
                covered=covered,
            )
        )

    return schemas.RTMRequirementEntry(
        requirement_id=requirement.id,
        title=requirement.title,
        description=requirement.description,
        source=requirement.source,
        req_type=requirement.req_type,
        wbs_deliverables=requirement.wbs_deliverables,
        acceptance_criteria=ac_entries,
        total_acceptance_criteria=total_ac,
        covered_acceptance_criteria=covered_ac,
        total_tests=total_tests,
        avg_coverage_percent=round(avg_coverage, 2),
        status=status,
    )


@router.post("/api/rtm/regenerate", response_model=list[schemas.RTMRequirementEntry])
def regenerate_rtm(db: Session = Depends(get_db)):
    services.recompute_all_rtm(db)
    requirements = (
        db.query(models.Requirement)
        .options(
            joinedload(models.Requirement.acceptance_criteria)
            .joinedload(models.AcceptanceCriteria.test_cases)
            .joinedload(models.TestCase.code_coverage)
        )
        .order_by(models.Requirement.id)
        .all()
    )
    return [_build_requirement_entry(r) for r in requirements]


@router.get("/api/rtm", response_model=list[schemas.RTMRequirementEntry])
def get_rtm(db: Session = Depends(get_db)):
    requirements = (
        db.query(models.Requirement)
        .options(
            joinedload(models.Requirement.acceptance_criteria)
            .joinedload(models.AcceptanceCriteria.test_cases)
            .joinedload(models.TestCase.code_coverage)
        )
        .order_by(models.Requirement.id)
        .all()
    )
    return [_build_requirement_entry(r) for r in requirements]


@router.get("/api/rtm/{requirement_id}", response_model=schemas.RTMRequirementEntry)
def get_rtm_for_requirement(requirement_id: int, db: Session = Depends(get_db)):
    requirement = (
        db.query(models.Requirement)
        .options(
            joinedload(models.Requirement.acceptance_criteria)
            .joinedload(models.AcceptanceCriteria.test_cases)
            .joinedload(models.TestCase.code_coverage)
        )
        .filter(models.Requirement.id == requirement_id)
        .first()
    )
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return _build_requirement_entry(requirement)
