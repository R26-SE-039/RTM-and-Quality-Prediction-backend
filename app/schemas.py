from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import ActionType, CoverageJobStatus, CoverageStatus, RiskLevel, TestStatus


# ---------- Requirements ----------


class RequirementCreate(BaseModel):
    title: str
    description: str = ""
    source: str = ""
    req_type: str = ""
    wbs_deliverables: str = ""


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    source: str
    req_type: str
    wbs_deliverables: str
    created_at: datetime


# ---------- Acceptance Criteria ----------


class AcceptanceCriteriaCreate(BaseModel):
    description: str


class AcceptanceCriteriaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requirement_id: int
    description: str
    created_at: datetime


# ---------- Test Cases ----------


class TestCaseCreate(BaseModel):
    title: str
    steps: str = ""
    acceptance_criteria_id: int
    assertion_strength: float = 0.0
    coverage_percent: float = 0.0
    boundary_coverage: float = 0.0
    error_handling: float = 0.0
    mutation_resistance: float = 0.0


class TestCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    steps: str
    acceptance_criteria_id: int
    assertion_strength: float
    coverage_percent: float
    boundary_coverage: float
    error_handling: float
    mutation_resistance: float
    quality_score: float | None
    status: TestStatus
    created_at: datetime


class FeatureContribution(BaseModel):
    feature: str
    label: str
    value: float
    importance: float
    contribution: float


class QualityPredictionOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    test_case_id: int
    quality_score: float
    status: TestStatus
    method: str
    baseline_score: float
    model_baseline: float = 0.0
    feature_contributions: list[FeatureContribution] = []


# ---------- Code Coverage ----------


class CodeCoverageCreate(BaseModel):
    module_name: str
    coverage_percent: float


class CodeCoverageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    test_case_id: int
    module_name: str
    coverage_percent: float
    created_at: datetime


# ---------- RTM ----------


class RTMTestEntry(BaseModel):
    test_case_id: int
    title: str
    status: TestStatus
    quality_score: float | None
    coverage_percent: float


class RTMAcceptanceCriteriaEntry(BaseModel):
    acceptance_criteria_id: int
    description: str
    tests: list[RTMTestEntry]
    covered: bool


class RTMRequirementEntry(BaseModel):
    requirement_id: int
    title: str
    description: str
    source: str
    req_type: str
    wbs_deliverables: str
    acceptance_criteria: list[RTMAcceptanceCriteriaEntry]
    total_acceptance_criteria: int
    covered_acceptance_criteria: int
    total_tests: int
    avg_coverage_percent: float
    status: CoverageStatus


# ---------- Coverage Gaps ----------


class CoverageGapOut(BaseModel):
    requirement_id: int
    requirement_title: str
    status: CoverageStatus
    risk_level: RiskLevel
    recommendation: str


# ---------- Portfolio ----------


class PortfolioActionOut(BaseModel):
    test_case_id: int
    test_title: str
    action_type: ActionType
    reason: str


class PortfolioAnalysisOut(BaseModel):
    redundant: list[PortfolioActionOut]
    critical: list[PortfolioActionOut]
    weak: list[PortfolioActionOut]


# ---------- Project Settings ----------


class ProjectSettingsIn(BaseModel):
    project_name: str = ""
    project_manager: str = ""
    project_description: str = ""
    component2_project_id: str | None = None
    component1_iteration_id: str | None = None


class ProjectSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_name: str
    project_manager: str
    project_description: str
    component2_project_id: str | None = None
    component1_iteration_id: str | None = None


# ---------- Dashboard ----------


class TrendPoint(BaseModel):
    date: str
    avg_quality: float
    avg_coverage: float


class QualityBucket(BaseModel):
    label: str
    tests: int


class ActivityOut(BaseModel):
    activity_type: str
    title: str
    detail: str
    created_at: datetime


class DashboardSummaryOut(BaseModel):
    tests_analyzed: int
    avg_quality_score: float
    coverage_rate: float
    success_rate: float
    quality_trend_pct: float
    trend: list[TrendPoint]
    requirements_covered: int
    requirements_total: int
    quality_distribution: list[QualityBucket]
    recent_activities: list[ActivityOut]


# ---------- ML model info (for the research / viva-facing panel) ----------


class FeatureImportanceOut(BaseModel):
    feature: str
    label: str
    importance: float
    formula_weight: float
    coefficient: float | None = None


class ModelComparisonEntry(BaseModel):
    model: str
    cv_mae_mean: float
    cv_mae_std: float


class ClassificationMetricsOut(BaseModel):
    task: str
    accuracy: float
    precision: float
    recall: float
    f1: float
    confusion_matrix: list[list[int]]
    confusion_matrix_labels: list[str]


class ModelInfoOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    trained: bool
    algorithm: str
    hyperparameters: dict
    model_comparison: list[ModelComparisonEntry] = []
    dataset_path: str = ""
    training_samples: int
    test_samples: int
    mae: float
    rmse: float
    r2: float
    cv_mae_mean: float
    cv_mae_std: float
    feature_importances: list[FeatureImportanceOut]
    quality_reject_threshold: float
    classification_metrics: ClassificationMetricsOut | None = None
    trained_at: datetime | None
    notes: str


# ---------- Dataset info (EDA panel) ----------


class FeatureStatOut(BaseModel):
    feature: str
    label: str
    mean: float
    std: float
    min: float
    max: float
    correlation_with_target: float


class CategoryCountOut(BaseModel):
    label: str
    count: int


class ExcludedFeatureOut(BaseModel):
    feature: str
    correlation_with_target: float
    note: str


class DatasetInfoOut(BaseModel):
    available: bool
    source: str = ""
    n_rows: int = 0
    n_features_used: int = 0
    missing_values: int = 0
    target_mean: float = 0.0
    target_std: float = 0.0
    target_min: float = 0.0
    target_max: float = 0.0
    reject_rate: float = 0.0
    feature_stats: list[FeatureStatOut] = []
    excluded_feature_correlation: ExcludedFeatureOut | None = None
    quality_label_distribution: list[CategoryCountOut] = []
    test_type_distribution: list[CategoryCountOut] = []
    module_criticality_distribution: list[CategoryCountOut] = []


# ---------- GitHub Code & Branch Coverage ----------


class CoverageAnalyzeRequest(BaseModel):
    repo_url: str


class CoverageFileEntry(BaseModel):
    file_name: str
    statements: int
    statement_coverage: float
    branches: int
    branch_coverage: float
    overall_coverage: float


class CoverageLogEntry(BaseModel):
    timestamp: str
    level: str
    message: str


class CoverageStatusOut(BaseModel):
    status: CoverageJobStatus
    repo_url: str
    error_message: str | None
    github_connected: bool
    logs: list[CoverageLogEntry] = []


class CoverageReportOut(BaseModel):
    status: CoverageJobStatus
    repo_url: str
    error_message: str | None
    statement_coverage: float
    branch_coverage: float
    overall_coverage: float
    files: list[CoverageFileEntry]
    logs: list[CoverageLogEntry] = []
    updated_at: datetime | None


class GithubConnectionStatusOut(BaseModel):
    connected: bool
    reason: str | None
    username: str | None


# ---------- Component 2 test-case quality (Random Forest research pipeline) ----------


class C2QualityFeaturesOut(BaseModel):
    test_case: str
    description_length: int
    has_expected_result: int
    has_preconditions: int
    has_test_steps: int
    requirement_linked: int
    requirement_coverage: float
    ambiguity_score: float
    completeness_score: float
    specificity_score: float
    test_result: float


class C2QualityPredictionOut(BaseModel):
    test_case_id: str
    title: str
    story_id: str
    status: str
    description: str = ""
    features: C2QualityFeaturesOut
    quality_score: float
    formula_label: str
    predicted_label: str
    probabilities: dict[str, float]
    method: str


class C2QualityFeatureImportanceOut(BaseModel):
    feature: str
    label: str
    importance: float


class C2QualityPerClassMetricOut(BaseModel):
    label: str
    precision: float
    recall: float
    f1: float
    support: int


class C2QualityModelInfoOut(BaseModel):
    trained: bool
    algorithm: str = ""
    hyperparameters: dict = {}
    dataset_path: str = ""
    label_order: list[str] = []
    training_samples: int = 0
    test_samples: int = 0
    cv_accuracy_mean: float = 0.0
    cv_accuracy_std: float = 0.0
    accuracy: float = 0.0
    precision_macro: float = 0.0
    recall_macro: float = 0.0
    f1_macro: float = 0.0
    per_class_metrics: list[C2QualityPerClassMetricOut] = []
    confusion_matrix: list[list[int]] = []
    confusion_matrix_labels: list[str] = []
    feature_importances: list[C2QualityFeatureImportanceOut] = []
    trained_at: str | None = None
    notes: str = ""


class C2QualityDatasetInfoOut(BaseModel):
    available: bool
    n_rows: int = 0
    label_distribution: list[CategoryCountOut] = []
    feature_stats: list[FeatureStatOut] = []


# ---------- Component 2 (Intelligent-Test-Case-Generation) integration ----------


class C2StatusOut(BaseModel):
    connected: bool
    base_url: str


class C2ProjectOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    created_at: str | None = None


class C2TestSuiteOut(BaseModel):
    id: str
    project_id: str
    framework: str
    language: str
    filename: str
    code: str
    mode: str
    url: str
    version: int
    is_active: bool
    is_stale: bool
    selected_for_run: bool
    updated_at: str | None = None


class C2RunOut(BaseModel):
    id: str
    project_id: str
    suite_id: str | None = None
    framework: str
    mode: str
    status: str
    github_run_url: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    total_count: int
    passed_count: int
    failed_count: int
    log_url: str
    error_message: str | None = None


class C2RiskPredictionOut(BaseModel):
    flow: str
    label: str
    risk: str
    confidence: float
    probabilities: dict[str, float]


class C2RiskResponseOut(BaseModel):
    project_id: str
    source: str
    predictions: list[C2RiskPredictionOut]


class C2FailedTestOut(BaseModel):
    test_name: str
    pipeline: str
    error_message: str
    failure_type: str
    framework: str | None = None
    executed_at: str | None = None


class C2FailedTestsResponseOut(BaseModel):
    project_id: str
    total: int
    failures: list[C2FailedTestOut]


class C1RequirementWithStoryOut(BaseModel):
    """One requirement + its linked user story, as returned by Component 1's
    GET /iterations/{iteration_id}/requirements-with-stories."""

    requirement_id: str
    requirement_text: str
    requirement_type: str
    requirement_status: str
    meeting_title: str | None = None
    user_story_id: str
    user_story_title: str
    user_story_text: str
    priority: str
    user_story_status: str | None = None
    acceptance_criteria: list[str] = []


class C2GherkinTestCaseOut(BaseModel):
    """One test case sourced from Component 2's traceability endpoint —
    a gherkin_scenarios row, carrying its owning user story's id so it can
    be joined to Component 1's requirements-with-stories by user_story_id."""

    story_id: str
    id: str
    title: str
    description: str
    status: str


class C2TestCaseOut(BaseModel):
    """One flattened scenario result, assembled from recent C2 execution
    runs — used to merge Component 2 test cases into the RTM Matrix, Test
    Inventory, and Quality Prediction pages alongside local test cases."""

    id: str
    title: str
    status: str
    framework: str
    duration_ms: int | None = None
    error_message: str | None = None
    executed_at: str | None = None
    fail_rate: float = 0.0


# ---------- Intelligent Test Improvement & Recommendations ----------
# Reuses the RTM Matrix / Quality Prediction / Test Inventory data the
# frontend already has in hand (a C2QualityPredictionOut plus its linked
# C1RequirementWithStoryOut) — this endpoint is a pure computation over
# that context, not a new data source.


class QualityGapOut(BaseModel):
    area: str
    label: str
    status: str
    severity: str
    recommendation: str


class C2ImproveRequest(BaseModel):
    title: str
    description: str
    features: C2QualityFeaturesOut
    quality_score: float
    predicted_label: str
    probabilities: dict[str, float] = {}
    requirement_text: str = ""
    user_story_title: str = ""
    acceptance_criteria: list[str] = []


class C2ImproveResponse(BaseModel):
    gaps: list[QualityGapOut]
    improved_description: str
    improved_features: C2QualityFeaturesOut
    improved_quality_score: float
    improved_formula_label: str
    improved_predicted_label: str
    improved_probabilities: dict[str, float]
    improved_method: str


# ---------- Risk-Based Coverage Gap Prioritization & Resolution ----------
# Built on the same Component 1 requirements-with-stories + Component 2
# traceability data the RTM Matrix / Quality Prediction / Test Inventory
# pages already use -- no duplicate data source.


class GapRiskFactorsOut(BaseModel):
    business_priority: float
    coverage_gap: float
    acceptance_criteria_gap: float
    test_failure_rate: float
    code_coverage_gap: float


class C2CoverageGapOut(BaseModel):
    requirement_id: str
    requirement_text: str
    requirement_type: str
    user_story_id: str
    user_story_title: str
    user_story_text: str
    priority: str
    total_acceptance_criteria: int
    covered_acceptance_criteria: int
    missing_acceptance_criteria: list[str]
    linked_test_case_count: int
    current_coverage_pct: float
    risk_score: float
    risk_level: str
    risk_factors: GapRiskFactorsOut
    recommended_action: str


class GenerateGapTestCaseRequest(BaseModel):
    requirement_id: str
    requirement_text: str = ""
    user_story_id: str = ""
    user_story_title: str = ""
    user_story_text: str = ""
    acceptance_criterion: str


class GeneratedGapTestCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requirement_id: str
    requirement_text: str
    user_story_id: str
    user_story_title: str
    acceptance_criterion: str
    title: str
    description: str
    added_to_inventory: bool
    added_to_rtm: bool


class GeneratedGapTestCasePredictionOut(BaseModel):
    """A GeneratedGapTestCaseOut plus its live quality prediction, scored
    fresh on every read (the trained model may be retrained after the test
    case was generated) as a genuine C2QualityPredictionOut -- so the RTM
    Matrix / Test Inventory pages can merge `prediction` straight into
    their existing rows without any shape-adaptation once added_to_rtm /
    added_to_inventory is set."""

    test_case: GeneratedGapTestCaseOut
    prediction: C2QualityPredictionOut


class AddGapTestCaseRequest(BaseModel):
    target: str  # "inventory" | "rtm"


class GenerateAllGapTestCasesRequest(BaseModel):
    items: list[GenerateGapTestCaseRequest]


class GenerateAllGapTestCasesResponse(BaseModel):
    generated: list[GeneratedGapTestCasePredictionOut]
