import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ToolExpect = Literal["called", "not_called"]
ToolKind = Literal["tool", "mcp", "sub_agent", "sub_workflow", "skill", "node", "review"]
BaselineSource = Literal["latest_runs", "suite_run", "manual"]


class ToolAssertion(BaseModel):
    """``name`` identifies the call within its kind: a sub-agent's label, a sub-workflow's id."""

    kind: ToolKind = "tool"
    name: str = Field(min_length=1, max_length=255)
    label: str | None = Field(None, max_length=255)
    expect: ToolExpect


class AgentThresholdsModel(BaseModel):
    """Upper bounds per run; leave a field empty to turn that check off."""

    latency_ms: float | None = Field(None, gt=0)
    cost_usd: float | None = Field(None, ge=0)
    total_tokens: int | None = Field(None, gt=0)
    tool_calls: int | None = Field(None, ge=0)

    class Config:
        from_attributes = True


class AgentBaselineResponse(BaseModel):
    run_count: int = 0
    error_count: int = 0
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    cost_avg_usd: float | None = None
    cost_p95_usd: float | None = None
    tokens_avg: float | None = None
    tokens_p95: float | None = None
    tool_calls_avg: float | None = None
    tool_calls_max: int | None = None
    unpriced_models: list[str] = []
    captured_at: datetime | None = None
    source: BaselineSource = "latest_runs"
    suite_run_id: uuid.UUID | None = None

    class Config:
        from_attributes = True


class AgentToolCallResponse(BaseModel):
    kind: ToolKind
    name: str
    label: str
    status: str
    elapsed_ms: float | None = None
    server: str | None = None

    class Config:
        from_attributes = True


class AgentRunResponse(BaseModel):
    trace_id: uuid.UUID
    created_at: datetime
    model: str | None
    latency_ms: float
    model_ms: float
    tool_ms: float
    cost_usd: float | None
    total_tokens: int
    tool_count: int
    tool_calls: list[AgentToolCallResponse]
    error: str | None

    class Config:
        from_attributes = True


class AgentToolUsageResponse(BaseModel):
    kind: ToolKind
    name: str
    label: str
    server: str | None
    configured: bool
    runs_called: int
    call_count: int
    error_count: int
    avg_ms: float | None

    class Config:
        from_attributes = True


class AgentCandidateResponse(BaseModel):
    """An agent node to pick; one without runs has nothing to read yet."""

    workflow_id: uuid.UUID
    workflow_name: str
    node_id: str
    node_label: str
    run_count: int
    last_run_at: datetime | None

    class Config:
        from_attributes = True


class AgentMetricsResponse(BaseModel):
    """Endpoint 1: an agent's latest runs and the numbers derived from them."""

    workflow_id: uuid.UUID
    workflow_name: str
    node_id: str
    node_label: str
    runs: list[AgentRunResponse]
    baseline: AgentBaselineResponse
    tools: list[AgentToolUsageResponse]
    suggested_thresholds: AgentThresholdsModel


class AgentBaselineValues(BaseModel):
    """Baseline numbers the user states instead of measuring them from runs."""

    latency_p50_ms: float | None = Field(None, gt=0)
    latency_p95_ms: float | None = Field(None, gt=0)
    cost_avg_usd: float | None = Field(None, ge=0)
    cost_p95_usd: float | None = Field(None, ge=0)
    tokens_avg: float | None = Field(None, gt=0)
    tokens_p95: float | None = Field(None, gt=0)
    tool_calls_avg: float | None = Field(None, ge=0)
    tool_calls_max: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _at_least_one_value(self) -> "AgentBaselineValues":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("Give at least one baseline value")
        return self


class AgentBaselineSource(BaseModel):
    """Where a suite's baseline comes from: the agent's latest runs, one suite run, or numbers."""

    source: BaselineSource = "latest_runs"
    run_id: uuid.UUID | None = None
    values: AgentBaselineValues | None = None

    @model_validator(mode="after")
    def _source_needs_its_input(self) -> "AgentBaselineSource":
        if self.source == "suite_run" and self.run_id is None:
            raise ValueError("A suite_run baseline needs run_id")
        if self.source == "manual" and self.values is None:
            raise ValueError("A manual baseline needs values")
        return self


class AgentSuiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    workflow_id: uuid.UUID
    node_id: str = Field(min_length=1, max_length=64)
    tool_assertions: list[ToolAssertion] = Field(default_factory=list, max_length=100)
    thresholds: AgentThresholdsModel = Field(default_factory=AgentThresholdsModel)
    baseline: AgentBaselineSource = Field(default_factory=AgentBaselineSource)

    @model_validator(mode="after")
    def _a_new_suite_has_no_runs(self) -> "AgentSuiteCreate":
        if self.baseline.source == "suite_run":
            raise ValueError(
                "A new suite has no runs yet. Create it, run it, then use that run as its baseline."
            )
        return self


class AgentSuiteUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    tool_assertions: list[ToolAssertion] | None = Field(None, max_length=100)
    thresholds: AgentThresholdsModel | None = None
    # Re-reads the agent's latest runs into the stored baseline.
    refresh_baseline: bool = False
    baseline: AgentBaselineSource | None = None

    @model_validator(mode="after")
    def _one_baseline_change(self) -> "AgentSuiteUpdate":
        if self.refresh_baseline and self.baseline is not None:
            raise ValueError("Send refresh_baseline or baseline, not both")
        return self


class AgentSuiteResponse(BaseModel):
    id: uuid.UUID
    name: str
    workflow_id: uuid.UUID
    workflow_name: str
    node_id: str
    node_label: str
    tool_assertions: list[ToolAssertion]
    thresholds: AgentThresholdsModel
    baseline: AgentBaselineResponse
    created_at: datetime
    updated_at: datetime


class AgentCheckResultResponse(BaseModel):
    key: str
    label: str
    kind: Literal["run", "assertion", "threshold"]
    status: Literal["pass", "fail", "skip"]
    detail: str | None = None

    class Config:
        from_attributes = True


class AgentRunEvaluationResponse(AgentRunResponse):
    passed: bool
    checks: list[AgentCheckResultResponse]


class AgentCheckSummaryResponse(BaseModel):
    key: str
    label: str
    kind: Literal["run", "assertion", "threshold"]
    passed: int
    failed: int
    skipped: int

    class Config:
        from_attributes = True


class AgentMetricDeltaResponse(BaseModel):
    metric: Literal["latency_p95_ms", "cost_avg_usd", "tokens_avg", "tool_calls_avg"]
    baseline: float | None
    current: float | None
    delta_pct: float | None

    class Config:
        from_attributes = True


class AgentSuiteReportResponse(BaseModel):
    """Endpoint 2: the suite's checks applied to the agent's latest runs."""

    suite_id: uuid.UUID
    run_count: int
    passed_count: int
    pass_rate: float | None
    checks: list[AgentCheckSummaryResponse]
    current: AgentBaselineResponse
    baseline: AgentBaselineResponse
    deltas: list[AgentMetricDeltaResponse]
    runs: list[AgentRunEvaluationResponse]


class AgentSuiteRunInputsResponse(BaseModel):
    """What the Run form starts from: the workflow's input fields and its last run's values."""

    fields: list[str]
    previous_inputs: dict[str, Any] | None
    previous_run_at: datetime | None


class AgentSuiteRunCreate(BaseModel):
    count: int = Field(1, ge=1, le=20)
    inputs: dict[str, Any] = Field(default_factory=dict)
    # A model writes a different input for each run, shaped like the previous run's.
    generate_inputs: bool = False
    credential_id: uuid.UUID | None = None
    model: str | None = Field(None, max_length=255)
    # One input per run, in order; the run count is its length.
    inputs_list: list[dict[str, Any]] | None = Field(None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def _generation_needs_a_model(self) -> "AgentSuiteRunCreate":
        if self.generate_inputs and (self.credential_id is None or not (self.model or "").strip()):
            raise ValueError("Pick a credential and a model to generate inputs")
        return self

    @model_validator(mode="after")
    def _inputs_list_is_not_generated(self) -> "AgentSuiteRunCreate":
        if self.inputs_list is not None and self.generate_inputs:
            raise ValueError("Send inputs_list or generate_inputs, not both")
        return self


class AgentSuiteRunResult(BaseModel):
    execution_id: str | None = None
    status: str
    trace_ids: list[str] = []
    error: str | None = None


AgentSuiteRunStatus = Literal["running", "completed", "failed", "cancelled"]


class AgentSuiteRunResponse(BaseModel):
    id: uuid.UUID
    suite_id: uuid.UUID
    status: AgentSuiteRunStatus
    requested_count: int
    generate_inputs: bool
    inputs: list[dict[str, Any]]
    results: list[AgentSuiteRunResult]
    error: str | None
    created_at: datetime
    completed_at: datetime | None

    class Config:
        from_attributes = True


class AgentSuiteRunSummary(BaseModel):
    """One suite run in the suite's history, without its inputs and results."""

    id: uuid.UUID
    status: AgentSuiteRunStatus
    requested_count: int
    finished_count: int
    generate_inputs: bool
    error: str | None
    created_at: datetime
    completed_at: datetime | None
