from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import CoverageJobStatus


# ---------- Component 1 (requirements + user stories) ----------


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
    runs."""

    id: str
    title: str
    status: str
    framework: str
    duration_ms: int | None = None
    error_message: str | None = None
    executed_at: str | None = None
    fail_rate: float = 0.0


# ---------- RTM Matrix (live, per project + iteration) ----------


class MatrixTestOut(BaseModel):
    """One test case cell of the matrix: a C2 gherkin scenario (with its
    derived execution status) or an RTM-generated gap test case."""

    id: str
    title: str
    description: str = ""
    status: str  # approved | rejected | pending
    source: str  # "C2" | "generated"


class MatrixRowOut(BaseModel):
    """One requirement -> user story -> test cases trace row."""

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
    total_acceptance_criteria: int
    covered_acceptance_criteria: int
    missing_acceptance_criteria: list[str] = []
    coverage_pct: float
    tests: list[MatrixTestOut] = []
    total_tests: int
    passed_tests: int
    failed_tests: int
    pending_tests: int
    coverage_status: str  # FULLY COVERED | PARTIAL | NOT COVERED


class MatrixSummaryOut(BaseModel):
    total_requirements: int
    fully_covered: int
    partially_covered: int
    not_covered: int
    total_tests: int
    passed_tests: int
    failed_tests: int
    pending_tests: int
    pass_rate: float  # of executed tests
    defects: int  # failing tests
    avg_coverage_pct: float


class MatrixOut(BaseModel):
    project_id: str
    iteration_id: str
    summary: MatrixSummaryOut
    rows: list[MatrixRowOut]


# ---------- Dashboard (live) ----------


class RecentRunOut(BaseModel):
    id: str
    status: str
    framework: str
    mode: str
    started_at: str | None = None
    finished_at: str | None = None
    total_count: int
    passed_count: int
    failed_count: int


class QualityBucket(BaseModel):
    label: str
    tests: int


class CodeCoverageSnapshotOut(BaseModel):
    status: CoverageJobStatus
    repo_url: str
    statement_coverage: float
    branch_coverage: float
    overall_coverage: float
    updated_at: datetime | None


class DashboardSummaryOut(BaseModel):
    matrix: MatrixSummaryOut
    avg_quality_score: float
    quality_distribution: list[QualityBucket]
    code_coverage: CodeCoverageSnapshotOut | None = None
    recent_runs: list[RecentRunOut] = []


# ---------- Test Inventory (live) ----------


class InventoryItemOut(BaseModel):
    id: str
    title: str
    description: str = ""
    status: str
    source: str  # "C2" | "generated"
    story_id: str = ""
    user_story_title: str = ""
    requirement_id: str = ""
    requirement_text: str = ""
    priority: str = ""
    quality_score: float | None = None
    predicted_label: str | None = None


# ---------- Portfolio (live) ----------


class PortfolioItemOut(BaseModel):
    test_id: str
    test_title: str
    user_story_title: str = ""
    reason: str


class PortfolioAnalysisOut(BaseModel):
    redundant: list[PortfolioItemOut]
    critical: list[PortfolioItemOut]
    weak: list[PortfolioItemOut]


# ---------- GitHub Code & Branch Coverage (per project) ----------


class CoverageAnalyzeRequest(BaseModel):
    # Optional manual override; when omitted the repo connected to the
    # project in Component 2 is analyzed with its stored credentials.
    repo_url: str = ""


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
    source: str | None = None  # "project" (C2 connection) | "env"
    reason: str | None = None
    username: str | None = None
    repo_full: str | None = None
    default_branch: str | None = None


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


class C2QualityDatasetInfoOut(BaseModel):
    available: bool
    n_rows: int = 0
    label_distribution: list[CategoryCountOut] = []
    feature_stats: list[FeatureStatOut] = []


# ---------- Intelligent Test Improvement & Recommendations ----------


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
    project_id: str
    requirement_id: str
    requirement_text: str = ""
    user_story_id: str = ""
    user_story_title: str = ""
    user_story_text: str = ""
    acceptance_criterion: str


class GeneratedGapTestCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: str
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
