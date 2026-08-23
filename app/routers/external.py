from fastapi import APIRouter, HTTPException

from app import schemas
from app.integrations import component1, component2
from app.integrations.component1 import Component1Unavailable
from app.integrations.component2 import Component2Unavailable

router = APIRouter(prefix="/api/external/component2", tags=["component2"])
component1_router = APIRouter(prefix="/api/external/component1", tags=["component1"])


@component1_router.get(
    "/iterations/{iteration_id}/requirements-with-stories",
    response_model=list[schemas.C1RequirementWithStoryOut],
)
async def get_requirements_with_stories(iteration_id: str):
    try:
        return await component1.get_requirements_with_stories(iteration_id)
    except Component1Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/status", response_model=schemas.C2StatusOut)
async def get_status():
    connected = await component2.is_reachable()
    return schemas.C2StatusOut(connected=connected, base_url=component2.COMPONENT2_API_URL)


@router.get("/projects", response_model=list[schemas.C2ProjectOut])
async def list_projects():
    try:
        return await component2.list_projects()
    except Component2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/projects/{project_id}/test-suites", response_model=list[schemas.C2TestSuiteOut])
async def get_test_suites(project_id: str):
    try:
        return await component2.get_test_suites(project_id)
    except Component2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/projects/{project_id}/test-runs", response_model=list[schemas.C2RunOut])
async def get_test_runs(project_id: str, limit: int = 20):
    try:
        return await component2.get_test_runs(project_id, limit=limit)
    except Component2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/projects/{project_id}/risk", response_model=schemas.C2RiskResponseOut)
async def get_risk(project_id: str):
    try:
        return await component2.get_risk(project_id)
    except Component2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/projects/{project_id}/failed-tests", response_model=schemas.C2FailedTestsResponseOut)
async def get_failed_tests(project_id: str, limit: int = 20):
    try:
        return await component2.get_failed_tests(project_id, limit=limit)
    except Component2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/projects/{project_id}/test-cases", response_model=list[schemas.C2TestCaseOut])
async def get_test_cases(project_id: str, run_sample: int = 3):
    try:
        return await component2.get_test_cases(project_id, run_sample=run_sample)
    except Component2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get(
    "/projects/{project_id}/traceability-test-cases",
    response_model=list[schemas.C2GherkinTestCaseOut],
)
async def get_traceability_test_cases(project_id: str, iteration_id: str | None = None):
    try:
        return await component2.get_traceability_test_cases(project_id, iteration_id=iteration_id)
    except Component2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
