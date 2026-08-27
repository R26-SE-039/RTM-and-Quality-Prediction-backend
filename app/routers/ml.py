from fastapi import APIRouter, HTTPException

from app import schemas
from app.integrations import component1, component2
from app.integrations.component1 import Component1Unavailable
from app.integrations.component2 import Component2Unavailable
from app.ml.c2_dataset_info import get_c2_dataset_info
from app.ml.c2_features import extract_features
from app.ml.c2_improve import analyze_gaps, generate_improved_gherkin
from app.ml.c2_predict import get_dataset_sample_predictions
from app.ml.c2_predict import get_model_info as get_c2_model_info
from app.ml.c2_predict import predict_c2_quality

router = APIRouter(prefix="/api/ml", tags=["ml"])


# ---------- Component 2 test-case quality (Random Forest research pipeline) ----------


@router.get("/c2-quality/model-info", response_model=schemas.C2QualityModelInfoOut)
def c2_quality_model_info():
    info = get_c2_model_info()
    if not info.get("trained"):
        return schemas.C2QualityModelInfoOut(
            trained=False,
            notes="Run `python -m app.ml.c2_train` to train and persist the model.",
        )
    return schemas.C2QualityModelInfoOut(**info)


@router.get("/c2-quality/dataset-info", response_model=schemas.C2QualityDatasetInfoOut)
def c2_quality_dataset_info():
    return schemas.C2QualityDatasetInfoOut(**get_c2_dataset_info())


@router.get("/c2-quality/dataset-samples", response_model=list[schemas.C2QualityPredictionOut])
def c2_quality_dataset_samples(n: int = 15):
    """Extra dropdown options for the Predict panel, drawn from the training
    dataset and scored the same way as a live test case, so there's enough
    variety to demo even when only a few real Component 2 test cases are
    linked."""
    return get_dataset_sample_predictions(n=n)


@router.get("/c2-quality/predictions/{project_id}", response_model=list[schemas.C2QualityPredictionOut])
async def c2_quality_predictions(project_id: str, iteration_id: str | None = None):
    """
    Full flow for every test case in the linked Component 2 project: Test
    Case -> Feature Extraction -> Feature Preprocessing (inside the trained
    pipeline) -> Random Forest -> Quality Score -> High/Medium/Low.
    """
    try:
        test_cases = await component2.get_traceability_test_cases(project_id, iteration_id=iteration_id)
    except Component2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    requirement_by_story: dict[str, list[str]] = {}
    if iteration_id:
        try:
            requirements = await component1.get_requirements_with_stories(iteration_id)
            for item in requirements:
                requirement_by_story.setdefault(item["user_story_id"], []).extend(
                    item.get("acceptance_criteria") or []
                )
        except Component1Unavailable:
            pass

    results = []
    for tc in test_cases:
        ac = requirement_by_story.get(tc.get("story_id"))
        features = extract_features(tc, requirement_linked=bool(ac), acceptance_criteria=ac)
        prediction = predict_c2_quality(features)
        results.append(
            schemas.C2QualityPredictionOut(
                test_case_id=tc["id"],
                title=tc["title"],
                story_id=tc["story_id"],
                status=tc["status"],
                description=tc.get("description", ""),
                features=schemas.C2QualityFeaturesOut(**features),
                **prediction,
            )
        )
    return results


@router.post("/c2-quality/improve", response_model=schemas.C2ImproveResponse)
def c2_quality_improve(payload: schemas.C2ImproveRequest):
    """
    Intelligent Test Improvement & Recommendations: identifies which of the
    model's own input features are weak for the given test case, then
    deterministically rewrites its Given/When/Then text to close those
    gaps, and re-runs the rewritten text through the SAME
    extract_features -> predict_c2_quality pipeline used everywhere else on
    this page, so the "improved" score is measured, not asserted.
    """
    gaps = analyze_gaps(payload.features.model_dump())

    coverage_source = payload.acceptance_criteria or ([payload.requirement_text] if payload.requirement_text else [])
    improved_description = generate_improved_gherkin(
        title=payload.title,
        requirement_text=payload.requirement_text,
        user_story_title=payload.user_story_title,
        acceptance_criteria=coverage_source,
    )

    improved_test_case = {"id": "improved", "title": payload.title, "description": improved_description, "status": "pending"}
    improved_features = extract_features(
        improved_test_case,
        requirement_linked=bool(coverage_source),
        acceptance_criteria=coverage_source,
    )
    improved_prediction = predict_c2_quality(improved_features)

    return schemas.C2ImproveResponse(
        gaps=[schemas.QualityGapOut(**g) for g in gaps],
        improved_description=improved_description,
        improved_features=schemas.C2QualityFeaturesOut(**improved_features),
        improved_quality_score=improved_prediction["quality_score"],
        improved_formula_label=improved_prediction["formula_label"],
        improved_predicted_label=improved_prediction["predicted_label"],
        improved_probabilities=improved_prediction["probabilities"],
        improved_method=improved_prediction["method"],
    )
