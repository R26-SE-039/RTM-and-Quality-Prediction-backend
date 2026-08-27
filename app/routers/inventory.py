"""Test Inventory: every test case in play for the open project — Component
2's generated gherkin scenarios (with execution status) plus RTM-generated
gap test cases added to the inventory — each scored live by the quality
model and traced back to its requirement/user story."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas, services
from app.database import get_db
from app.ml.c2_features import extract_features
from app.ml.c2_predict import predict_c2_quality

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("", response_model=list[schemas.InventoryItemOut])
async def get_inventory(project_id: str, iteration_id: str, db: Session = Depends(get_db)):
    matrix = await services.build_matrix(db, project_id, iteration_id)

    items: list[schemas.InventoryItemOut] = []
    seen: set[str] = set()
    for row in matrix.rows:
        for test in row.tests:
            if test.id in seen:
                continue
            seen.add(test.id)
            features = extract_features(
                {"id": test.id, "title": test.title, "description": test.description, "status": test.status},
                requirement_linked=True,
                acceptance_criteria=row.acceptance_criteria,
            )
            prediction = predict_c2_quality(features)
            items.append(
                schemas.InventoryItemOut(
                    id=test.id,
                    title=test.title,
                    description=test.description,
                    status=test.status,
                    source=test.source,
                    story_id=row.user_story_id,
                    user_story_title=row.user_story_title,
                    requirement_id=row.requirement_id,
                    requirement_text=row.requirement_text,
                    priority=row.priority,
                    quality_score=prediction["quality_score"],
                    predicted_label=prediction["predicted_label"],
                )
            )

    # Gap test cases added to the inventory but not (yet) to the RTM — the
    # matrix rows above only carry added_to_rtm ones.
    inventory_gaps = (
        db.query(models.GeneratedGapTestCase)
        .filter(
            models.GeneratedGapTestCase.project_id == project_id,
            models.GeneratedGapTestCase.added_to_inventory.is_(True),
        )
        .order_by(models.GeneratedGapTestCase.created_at.asc())
        .all()
    )
    for gap in inventory_gaps:
        gap_id = f"gap-{gap.id}"
        if gap_id in seen:
            continue
        seen.add(gap_id)
        features = extract_features(
            {"id": gap_id, "title": gap.title, "description": gap.description, "status": "pending"},
            requirement_linked=True,
            acceptance_criteria=[gap.acceptance_criterion],
        )
        prediction = predict_c2_quality(features)
        items.append(
            schemas.InventoryItemOut(
                id=gap_id,
                title=gap.title,
                description=gap.description,
                status="pending",
                source="generated",
                story_id=gap.user_story_id,
                user_story_title=gap.user_story_title,
                requirement_id=gap.requirement_id,
                requirement_text=gap.requirement_text,
                quality_score=prediction["quality_score"],
                predicted_label=prediction["predicted_label"],
            )
        )

    return items
