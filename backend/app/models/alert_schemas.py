"""Pydantic models for the Alerts feature.

Alert conditions are a discriminated union keyed on ``alert_type``. Validating at
the API boundary means the evaluator never has to defend against a config shape
that does not match its handler.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

AlertType = Literal["error_threshold", "workflow_duration", "token_cost", "execution_count"]
AlertScope = Literal["workflow", "system"]
AlertState = Literal["ok", "triggered"]
RenotifyMode = Literal["on_recovery", "cooldown"]

MAX_WINDOW_MINUTES = 10_080  # 7 days
MIN_CHECK_INTERVAL_SECONDS = 60


class _BaseAlertConfig(BaseModel):
    window_minutes: int = Field(ge=1, le=MAX_WINDOW_MINUTES)


class ErrorThresholdConfig(_BaseAlertConfig):
    alert_type: Literal["error_threshold"] = "error_threshold"
    threshold_count: int = Field(ge=1)


class WorkflowDurationConfig(_BaseAlertConfig):
    alert_type: Literal["workflow_duration"] = "workflow_duration"
    threshold_ms: float = Field(gt=0)
    aggregation: Literal["max", "avg", "p95"] = "max"
    min_samples: int = Field(default=1, ge=1)


class TokenCostConfig(_BaseAlertConfig):
    alert_type: Literal["token_cost"] = "token_cost"
    metric: Literal["total_tokens", "usd"]
    threshold: float = Field(gt=0)


class ExecutionCountConfig(_BaseAlertConfig):
    alert_type: Literal["execution_count"] = "execution_count"
    threshold_count: int = Field(ge=1)


AlertConfig = Annotated[
    ErrorThresholdConfig | WorkflowDurationConfig | TokenCostConfig | ExecutionCountConfig,
    Field(discriminator="alert_type"),
]

_CONFIG_BY_TYPE: dict[str, type[_BaseAlertConfig]] = {
    "error_threshold": ErrorThresholdConfig,
    "workflow_duration": WorkflowDurationConfig,
    "token_cost": TokenCostConfig,
    "execution_count": ExecutionCountConfig,
}


# Mirrors ALERT_TYPE_LABELS in frontend/src/types/alerts.ts.
ALERT_TYPE_LABELS: dict[str, str] = {
    "error_threshold": "Error threshold",
    "workflow_duration": "Workflow duration",
    "token_cost": "Token / USD cost",
    "execution_count": "Execution count",
}

# Mirrors defaultConfigForType() in frontend/src/types/alerts.ts. Used to complete a
# partial AI config: a model that names only the window still yields a usable draft.
DEFAULT_CONFIG_BY_TYPE: dict[str, dict[str, Any]] = {
    "error_threshold": {"window_minutes": 15, "threshold_count": 5},
    "workflow_duration": {
        "window_minutes": 30,
        "threshold_ms": 60000,
        "aggregation": "max",
        "min_samples": 3,
    },
    "token_cost": {"window_minutes": 1440, "metric": "usd", "threshold": 25},
    "execution_count": {"window_minutes": 60, "threshold_count": 100},
}


def parse_alert_config(alert_type: str, config: dict[str, Any]) -> Any:
    """Parse a raw config dict into the model matching ``alert_type``."""
    model = _CONFIG_BY_TYPE.get(alert_type)
    if model is None:
        raise ValueError(f"Unknown alert_type: {alert_type}")
    return model(**{**config, "alert_type": alert_type})


def describe_condition(alert_type: str, config: dict[str, Any]) -> str:
    """One-line human summary used by the listing, chat tools, and notify payloads."""
    cfg = parse_alert_config(alert_type, config)
    window = f"{cfg.window_minutes}m"
    if alert_type == "error_threshold":
        return f"{cfg.threshold_count}+ errors in {window}"
    if alert_type == "workflow_duration":
        return f"{cfg.aggregation} duration over {cfg.threshold_ms:.0f}ms in {window}"
    if alert_type == "token_cost":
        unit = "tokens" if cfg.metric == "total_tokens" else "USD"
        return f"{cfg.threshold:g} {unit} spent in {window}"
    return f"{cfg.threshold_count}+ executions in {window}"


class _AlertWritableFields(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    alert_type: AlertType
    scope: AlertScope = "workflow"
    workflow_id: uuid.UUID | None = None
    config: dict[str, Any]
    enabled: bool = True
    notify_workflow_id: uuid.UUID | None = None
    renotify_mode: RenotifyMode = "on_recovery"
    cooldown_minutes: int | None = Field(default=None, ge=1)
    check_interval_seconds: int = Field(default=60, ge=MIN_CHECK_INTERVAL_SECONDS)

    @model_validator(mode="after")
    def _validate(self) -> _AlertWritableFields:
        if self.scope == "workflow" and self.workflow_id is None:
            raise ValueError("workflow_id is required when scope is 'workflow'")
        if self.scope == "system" and self.workflow_id is not None:
            raise ValueError("workflow_id must be omitted when scope is 'system'")
        if self.renotify_mode == "cooldown" and self.cooldown_minutes is None:
            raise ValueError("cooldown_minutes is required when renotify_mode is 'cooldown'")
        parse_alert_config(self.alert_type, self.config)
        return self


class AlertCreate(_AlertWritableFields):
    # When true the API creates an empty workflow named after the alert and links it
    # as the notify target, so the user leaves the wizard with somewhere to add
    # their Slack or email nodes. Ignored when notify_workflow_id is already set.
    create_notify_workflow: bool = False


class AlertUpdate(BaseModel):
    """Every field optional; the router re-validates the merged result as AlertCreate."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    scope: AlertScope | None = None
    workflow_id: uuid.UUID | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    notify_workflow_id: uuid.UUID | None = None
    renotify_mode: RenotifyMode | None = None
    cooldown_minutes: int | None = Field(default=None, ge=1)
    check_interval_seconds: int | None = Field(default=None, ge=MIN_CHECK_INTERVAL_SECONDS)
    create_notify_workflow: bool = False


class AlertResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    alert_type: AlertType
    scope: AlertScope
    workflow_id: uuid.UUID | None
    workflow_name: str | None = None
    config: dict[str, Any]
    condition_summary: str
    enabled: bool
    notify_workflow_id: uuid.UUID | None
    notify_workflow_name: str | None = None
    state: AlertState
    renotify_mode: RenotifyMode
    cooldown_minutes: int | None
    check_interval_seconds: int
    last_evaluated_at: datetime | None
    last_triggered_at: datetime | None
    last_observed_value: float | None
    # Firings the reader has not acknowledged. Drives the "Firing" vs "Acknowledged"
    # badge: a triggered alert whose firings are all acknowledged has been seen.
    unacknowledged_count: int = 0
    is_owner: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
    total: int


class AlertEventResponse(BaseModel):
    id: uuid.UUID
    alert_id: uuid.UUID
    alert_name: str
    alert_type: AlertType
    triggered_at: datetime
    observed_value: float
    threshold_value: float
    window_start: datetime
    window_end: datetime
    context: dict[str, Any]
    acknowledged_at: datetime | None
    notify_execution_id: uuid.UUID | None
    notify_status: str | None


class AlertEventListResponse(BaseModel):
    items: list[AlertEventResponse]
    total: int
    unacknowledged: int


class AlertPreviewRequest(BaseModel):
    """Backtest an unsaved condition. Mirrors AlertCreate minus the naming fields."""

    alert_type: AlertType
    scope: AlertScope = "workflow"
    workflow_id: uuid.UUID | None = None
    config: dict[str, Any]
    lookback_hours: int = Field(default=24, ge=1, le=168)

    @model_validator(mode="after")
    def _validate(self) -> AlertPreviewRequest:
        if self.scope == "workflow" and self.workflow_id is None:
            raise ValueError("workflow_id is required when scope is 'workflow'")
        parse_alert_config(self.alert_type, self.config)
        return self


class AlertPreviewResponse(BaseModel):
    observed_value: float
    threshold_value: float
    would_fire_now: bool
    window_start: datetime
    window_end: datetime
    context: dict[str, Any]
    backtest_fire_count: int
    backtest_max_observed: float
    lookback_hours: int


class AlertDraft(BaseModel):
    """AI-produced wizard prefill. Every field is optional on purpose.

    A vague request should still move the wizard forward with whatever the model
    could work out, rather than throwing the whole answer away and making the
    user retype it. Nothing here bypasses validation: the wizard fills its own
    defaults for what is missing, and ``AlertCreate`` re-validates on save.
    """

    name: str | None = None
    description: str | None = None
    alert_type: AlertType | None = None
    scope: AlertScope | None = None
    workflow_id: uuid.UUID | None = None
    config: dict[str, Any] | None = None
    renotify_mode: RenotifyMode | None = None
    cooldown_minutes: int | None = None
    notify_workflow_id: uuid.UUID | None = None
    # None = the model did not say, so the wizard keeps its own default. True asks
    # for a new notify workflow, False asks for none at all.
    create_notify_workflow: bool | None = None
    filled_fields: list[str] = Field(default_factory=list)


class AlertDraftRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    credential_id: uuid.UUID
    model: str


class AlertDraftResponse(BaseModel):
    draft: AlertDraft | None = None
    clarification: str | None = None


class AlertShareRequest(BaseModel):
    user_email: str


class AlertTeamShareRequest(BaseModel):
    team_id: uuid.UUID


class AlertShareEntry(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str


class AlertTeamShareEntry(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    team_name: str
