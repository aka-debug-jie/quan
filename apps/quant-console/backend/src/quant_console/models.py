"""Typed public contracts for the local read-only research console."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class ContractModel(BaseModel):
    """Strict base for every public HTTP contract."""

    model_config = ConfigDict(extra="forbid")


class ConsoleMode(StrEnum):
    """Published snapshot mode."""

    REAL = "real"
    DEMO = "demo"


class DataEvaluability(StrEnum):
    """Whether absolute experiment metrics can be evaluated."""

    VALID = "VALID"
    NOT_EVALUABLE = "NOT_EVALUABLE"
    UNKNOWN = "UNKNOWN"


class BenchmarkComparability(StrEnum):
    """Matched benchmark state, independent from absolute metrics."""

    COMPARABLE = "COMPARABLE"
    SELF_BENCHMARK = "SELF_BENCHMARK"
    MATCHED_BENCHMARK_NOT_EVALUABLE = "MATCHED_BENCHMARK_NOT_EVALUABLE"
    MATCHED_BENCHMARK_MISSING = "MATCHED_BENCHMARK_MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class MetricValidity(StrEnum):
    """Availability of one source metric."""

    VALID = "VALID"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class ComparisonMode(StrEnum):
    """Permitted interpretation for a comparison request."""

    COMPARABLE = "COMPARABLE"
    CONTROLLED_SCENARIO_COMPARISON = "CONTROLLED_SCENARIO_COMPARISON"
    DESCRIPTIVE_ONLY = "DESCRIPTIVE_ONLY"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class ExportFormat(StrEnum):
    """Supported aggregate export encodings."""

    CSV = "csv"
    JSON = "json"


class ExportScope(StrEnum):
    """Rows selected for an aggregate export."""

    SELECTED = "selected"
    FILTERED = "filtered"


class SortDirection(StrEnum):
    """Stable sort direction."""

    ASC = "asc"
    DESC = "desc"


class Period(ContractModel):
    """Exchange-local research period."""

    start: str
    end: str
    sessions: int = Field(ge=0)


class Metric(ContractModel):
    """One metric with explicit validity, unit, and provenance."""

    name: str
    value: float | None
    unit: str
    validity: MetricValidity
    unavailable_reason: str | None = None
    basis: str
    scenario_id: str
    data_use_level: str
    source_evidence_id: str


class SeriesMeta(ContractModel):
    """Identity and semantics for one immutable display series."""

    series_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: str
    unit: str
    start: str
    end: str
    points: int = Field(ge=0)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    derivation: str


class SeriesPoint(ContractModel):
    """One exchange-local dated display observation."""

    date: str
    value: str


class SeriesResponse(ContractModel):
    """Full precision series bound to one snapshot."""

    snapshot_id: str
    meta: SeriesMeta
    points: list[SeriesPoint]


class CompatibilityIdentity(ContractModel):
    """Fields that constrain valid economic comparisons."""

    study_revision: str
    scenario_id: str
    bars_sha256: str | None
    protocol_sha256: str | None
    base_protocol_sha256: str | None = None
    portfolio_sha256: str | None = None
    scores_sha256: str | None = None
    signals_sha256: str | None = None
    initial_cash: str | None
    cost_mode: str | None = None
    execution_delay_sessions: int | None = None


class ExperimentSummary(ContractModel):
    """Small experiment row suitable for filtering and tables."""

    artifact_id: str
    evidence_id: str
    study_id: str
    study_revision: str
    experiment_id: str
    run_identity: str
    strategy_id: str
    family: str
    scenario_id: str
    data_evaluability: DataEvaluability
    benchmark_comparability: BenchmarkComparability
    economic_outcome: str
    engineering_status: str
    research_validity: str
    data_use_level: str
    metrics: dict[str, Metric]
    failure_reason: str | None
    period: Period | None
    matched_benchmark_id: str | None = None
    revision_of: str | None = None
    revision_kind: str | None = None


class ExperimentDetail(ExperimentSummary):
    """Structured detail without embedding large time series."""

    compatibility: CompatibilityIdentity
    execution: dict[str, JsonValue] | None
    turnover_costs: dict[str, JsonValue] | None
    calendar_year_returns: dict[str, float] | None
    identities: dict[str, JsonValue]
    limitations: list[str]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    series: list[SeriesMeta]
    curve_unavailable_reason: str | None = None
    applied_evidence_ids: list[str] = Field(default_factory=list)


class SnapshotMeta(ContractModel):
    """Current immutable display snapshot pointer."""

    schema_version: int
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: ConsoleMode
    published_at: str
    adapter_version: str


class Overview(ContractModel):
    """Research and prospective summary without recommendation language."""

    snapshot_id: str
    current_stage: str
    registered_runs: int
    valid_runs: int
    not_evaluable_runs: int
    retained_candidates: int
    legacy_invalid_engineering_runs: int
    economic_outcome: str
    latest_prospective_date: str | None
    prospective_status: str
    warnings: list[str]
    closure_counts: ClosureCounts | None = None


class ClosureCounts(ContractModel):
    """Revision counts separate from the retained upgrade study."""

    old_registered_runs: int = Field(ge=0)
    old_valid_runs: int = Field(ge=0)
    old_not_evaluable_runs: int = Field(ge=0)
    old_retained_candidates: int = Field(ge=0)
    revised_runs: int = Field(ge=0)
    new_control_runs: int = Field(ge=0)
    conditional_scale_runs: int = Field(ge=0)
    cache_reuse_from_old_study: int = Field(ge=0)
    valid_runs: int = Field(ge=0)
    not_evaluable_runs: int = Field(ge=0)
    retained_candidates: int = Field(ge=0)


class StudySummary(ContractModel):
    """One published research study revision."""

    study_id: str
    study_revision: str
    schema_version: int | None
    code_commit: str | None
    implementation_status: str
    research_validity: str
    economic_outcome: str
    data_use_level: str
    registered_runs: int


class StudyList(ContractModel):
    """Studies bound to one snapshot."""

    snapshot_id: str
    items: list[StudySummary]


class ExperimentFilters(ContractModel):
    """Reusable experiment filters for queries and safe export."""

    q: str = Field(default="", max_length=200)
    study: str | None = Field(default=None, max_length=100)
    family: str | None = Field(default=None, max_length=100)
    status: DataEvaluability | None = None
    economic_outcome: str | None = Field(default=None, max_length=100)


class ExperimentPage(ContractModel):
    """Stable paginated experiment result."""

    snapshot_id: str
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    items: list[ExperimentSummary]


class CompareRequest(ContractModel):
    """Experiments selected for a compatibility check."""

    artifact_ids: list[str] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def unique_ids(self) -> CompareRequest:
        """Reject duplicate rows that would create a false comparison."""
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("comparison artifact ids must be unique")
        return self


class CompatibilityResult(ContractModel):
    """Comparison permission and its explicit limitations."""

    snapshot_id: str
    mode: ComparisonMode
    reasons: list[str]
    changed_fields: list[str]
    economic_inference_allowed: bool
    items: list[ExperimentDetail]


class SignalsSummary(ContractModel):
    """Existing signal diagnostics grouped by their source contract."""

    snapshot_id: str
    historical: dict[str, JsonValue]
    attribution: dict[str, JsonValue]
    measurement: dict[str, JsonValue]
    prospective: dict[str, JsonValue]


class ProspectiveDay(ContractModel):
    """Sanitized published prospective daily record."""

    trading_date: str | None = None
    ENGINEERING_STATUS: str | None = None
    INPUT_STATUS: str | None = None
    DATA_CAPTURE_STATUS: str | None = None
    SHADOW_SIGNAL_STATUS: str | None = None
    PAPER_ACCOUNT_STATUS: str | None = None
    paper_account_phase: str | None = None
    PROFITABILITY_STATUS: str | None = None
    coverage: float | None = None
    nav: str | None = None
    cash: str | None = None
    fills_today: int | None = None
    buy_fills_today: int | None = None
    sell_fills_today: int | None = None
    rejections_today: int | None = None
    mean_ic: float | None = None
    mean_rank_ic: float | None = None
    direction_consistency: float | None = None
    receipt_sha256: str | None = None
    rules_sha256: str | None = None
    calendar_sha256: str | None = None
    top_count: int = 0
    position_count: int = 0
    rejection_count: int = 0


class ProspectiveAccount(ContractModel):
    """One paper phase, kept separate from every other phase."""

    status: str
    latest: ProspectiveDay | None
    observed_days: int = 0


class ProspectiveAccounts(ContractModel):
    """Engineering and fully prospective accounts."""

    engineering_warm_start: ProspectiveAccount
    fully_prospective_v1: ProspectiveAccount


class ProspectiveSummary(ContractModel):
    """Published JSON-only prospective state."""

    snapshot_id: str
    latest_date: str | None
    operations_status: str
    input_status: str
    data_capture_status: str
    profitability_status: str
    days: list[ProspectiveDay]
    accounts: ProspectiveAccounts
    diagnostics: dict[str, JsonValue]
    warnings: list[str]
    evidence_id: str


class SourceHealth(ContractModel):
    """Integrity status for one approved source family."""

    source_id: str
    verification_status: str
    manifest_sha256: str | None = None
    matrix_sha256: str | None = None
    latest_report_date: str | None = None
    acceptance_status: str | None = None
    sqlite_read: bool | None = None


class SystemObservation(ContractModel):
    """Sanitized fixed-target system observation."""

    status: str
    observed_at: str | None
    timer: dict[str, JsonValue] | None = None
    service: dict[str, JsonValue] | None = None
    unit_hashes: dict[str, JsonValue] | None = None


class HealthSummary(ContractModel):
    """Snapshot-bound data and system health."""

    snapshot_id: str
    sources: list[SourceHealth]
    system_observation: SystemObservation
    live_broker: str
    csi500: str


class RuntimeStatus(ContractModel):
    """Current Console runtime status, separate from research evidence."""

    app_version: str
    current_snapshot_id: str | None
    last_refresh: dict[str, JsonValue] | None


class EvidenceSummary(ContractModel):
    """Safe source identity without local paths or restricted payloads."""

    evidence_id: str
    source_kind: str
    study_id: str | None = None
    study_revision: str | None = None
    run_identity: str | None = None
    sha256: str | None = None
    schema_version: int | None = None
    data_use_level: str | None = None
    limitations: list[str] = Field(default_factory=list)
    trading_date: str | None = None
    receipt_sha256: str | None = None
    rules_sha256: str | None = None
    calendar_sha256: str | None = None
    absolute_paths_exposed: bool = False
    source_url: str | None = None
    published_on: str | None = None
    retrieved_at_utc: str | None = None
    pages: list[int] | None = None


class ExportRequest(ContractModel):
    """Safe aggregate export bound to one snapshot and explicit scope."""

    format: ExportFormat = ExportFormat.CSV
    scope: ExportScope
    artifact_ids: list[str] = Field(default_factory=list, max_length=100)
    filters: ExperimentFilters = Field(default_factory=ExperimentFilters)
    sort: str = Field(default="experiment_id", max_length=64)
    direction: SortDirection = SortDirection.ASC

    @model_validator(mode="after")
    def validate_scope(self) -> ExportRequest:
        """Selected exports require ids; filtered exports must not smuggle ids."""
        if self.scope is ExportScope.SELECTED and not self.artifact_ids:
            raise ValueError("selected export requires artifact ids")
        if self.scope is ExportScope.FILTERED and self.artifact_ids:
            raise ValueError("filtered export does not accept artifact ids")
        return self


class ReloadResult(ContractModel):
    """Result of an explicit fixed-source snapshot reload."""

    status: str
    snapshot: SnapshotMeta
    changed: bool


class ErrorDetail(ContractModel):
    """Safe machine-readable API error."""

    code: str
    message: str
    request_id: str
    recoverable: bool


class ErrorEnvelope(ContractModel):
    """Uniform API error body."""

    error: ErrorDetail
