"""The Requirements Traceability Matrix, assembled live per request from
Component 1 (requirements + user stories for the open iteration) and
Component 2 (generated test cases + execution results for the open project),
plus RTM's own generated gap test cases. Nothing here is stored — the matrix
is always as fresh as its sources.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas, services
from app.database import get_db

router = APIRouter(prefix="/api/rtm", tags=["rtm"])


@router.get("/matrix", response_model=schemas.MatrixOut)
async def get_matrix(project_id: str, iteration_id: str, db: Session = Depends(get_db)):
    return await services.build_matrix(db, project_id, iteration_id)


@router.get("/matrix/requirements/{requirement_id}", response_model=schemas.MatrixRowOut)
async def get_matrix_requirement(
    requirement_id: str, project_id: str, iteration_id: str, db: Session = Depends(get_db)
):
    matrix = await services.build_matrix(db, project_id, iteration_id)
    for row in matrix.rows:
        if row.requirement_id == requirement_id:
            return row
    raise HTTPException(status_code=404, detail="Requirement not found in this iteration")
