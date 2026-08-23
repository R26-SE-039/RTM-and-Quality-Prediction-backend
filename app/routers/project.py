from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/project-settings", tags=["project-settings"])


def _get_or_create(db: Session) -> models.ProjectSettings:
    settings = db.query(models.ProjectSettings).first()
    if settings is None:
        settings = models.ProjectSettings(
            project_name="Untitled Project", project_manager="", project_description=""
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.get("", response_model=schemas.ProjectSettingsOut)
def get_project_settings(db: Session = Depends(get_db)):
    return _get_or_create(db)


@router.put("", response_model=schemas.ProjectSettingsOut)
def update_project_settings(payload: schemas.ProjectSettingsIn, db: Session = Depends(get_db)):
    settings = _get_or_create(db)
    settings.project_name = payload.project_name
    settings.project_manager = payload.project_manager
    settings.project_description = payload.project_description
    settings.component2_project_id = payload.component2_project_id
    settings.component1_iteration_id = payload.component1_iteration_id
    db.commit()
    db.refresh(settings)
    return settings
