# Alerts Tab Implementation Plan (heymrun)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an Alerts tab where users define threshold conditions over a time window across four metric types, build them through an AI-prefillable wizard, and query them from the Chat tab.

**Architecture:** Four new tables (`alerts`, `alert_events`, `alert_shares`, `alert_team_shares`). Metric computation lives in one handler module per alert type behind a registry, mirroring `backend/app/services/node_execution/`. A single evaluator owns claiming, the state machine, event packaging, and notify dispatch. Evaluation runs as a new pass inside the existing leader-gated `CronScheduler` loop. The frontend is a new dashboard tab with a five-step wizard.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 async + Alembic + Pydantic; Vue 3 `<script setup>` + TypeScript strict + Pinia + Bun.

**Spec:** [`docs/superpowers/specs/2026-08-09-alerts-tab-design.md`](../specs/2026-08-09-alerts-tab-design.md)

**Scope note:** Spec §13 (heymweb solutions page, comparison tables, blog post) is a separate
deliverable in a separate repo with no shared code. It has its own plan:
[`2026-08-09-alerts-heymweb-rollout.md`](./2026-08-09-alerts-heymweb-rollout.md). This plan covers
heymrun only and produces working, testable software on its own.

**Known deviation from plan-writing convention:** Tasks 17, 18, and 22-26 specify their work as
precise prose instructions (named helpers, exact status codes, exact validation rules, exact
component boundaries) rather than complete literal code. A FastAPI CRUD router and eleven Vue
components are largely mechanical against existing in-repo templates that each task names, and
transcribing them here would add roughly 1,500 lines of code the implementer should be reading from
the actual reference file instead. Every non-obvious decision in those tasks — access gating, the
re-validation rule on PATCH, the backtest step cap, the lookup-map requirement in `StepCondition` —
is stated explicitly. The TDD-with-literal-code discipline is applied in full to Tasks 1-16 and
19-21, which is where the logic actually lives.

---

## ⚠️ Repository policy for this work

- **No commits. No pushes.** The user explicitly asked for this work to stay uncommitted. Where a plan would normally say "commit", this plan says **Checkpoint** — run the verification and move on, leaving changes in the working tree.
- Work directly on `main` (per AGENTS.md). Do not create branches or worktrees.
- Prefix every full-suite run with `HEYM_OTEL_ENABLED=false` — a `.env` with OTel enabled and no collector hangs pytest forever.
- Never run `./check.sh` and `./run_tests.sh` concurrently; each spawns ~189 parallel pytest workers.
- If `SECRET_KEY` is not exported, prefix with `SECRET_KEY=test-secret-key-for-tests-only-32-bytes`.
- **No Playwright/frontend tests** — standing preference for this repo. Frontend is verified with `bun run lint` and `bun run typecheck`.

Standard single-test command used throughout:

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend && \
  HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_alert_metrics.py -v
```

---

## File Structure

**Backend — created:**

| Path | Responsibility |
|---|---|
| `backend/app/models/alert_schemas.py` | Pydantic request/response models and the config discriminated union |
| `backend/app/services/alerts/__init__.py` | Package marker, re-exports `evaluate_due_alerts` |
| `backend/app/services/alerts/context.py` | `AlertEvaluationContext`, `AlertObservation` dataclasses |
| `backend/app/services/alerts/registry.py` | `alert_type` → handler lookup |
| `backend/app/services/alerts/types/error_threshold.py` | Error-count-in-window metric |
| `backend/app/services/alerts/types/workflow_duration.py` | Duration aggregate metric |
| `backend/app/services/alerts/types/token_cost.py` | Token / USD spend metric |
| `backend/app/services/alerts/types/execution_count.py` | Run-count metric |
| `backend/app/services/alerts/evaluator.py` | Claim, dispatch, state machine, event write, notify |
| `backend/app/services/alerts/cleanup.py` | 90-day `alert_events` retention |
| `backend/app/services/alerts/ai_draft.py` | Natural language → `AlertDraft` |
| `backend/app/services/alert_access.py` | Owner / share / team-share resolution |
| `backend/app/api/alerts.py` | REST router |
| `backend/alembic/versions/108_add_alerts.py` | Migration |

**Backend — modified:**

| Path | Change |
|---|---|
| `backend/app/db/models.py` | Four new ORM classes |
| `backend/app/main.py` | Register the alerts router |
| `backend/app/services/cron_scheduler.py` | `_check_alerts()` + `_check_alert_event_cleanup()` passes |
| `backend/app/api/ai_assistant.py` | Three chat tools + handlers + system prompt rule |

**Frontend — created:** `frontend/src/types/alerts.ts`, `frontend/src/services/alerts.ts`, `frontend/src/stores/alerts.ts`, and `frontend/src/components/Alerts/` (see Tasks 25 and 26).

**Frontend — modified:** `DashboardNav.vue`, `DashboardView.vue`, `router/index.ts`.

**Docs — created:** `frontend/src/docs/content/tabs/alerts-tab.md`.
**Docs — modified:** `manifest.ts`, `reference/features.md`, `tabs/chat-tab.md`, `reference/analytics-tab.md` cross-link, `README.md`, `AGENTS.md`.

---

## Phase 1 — Data model

### Task 1: ORM models

**Files:**
- Modify: `backend/app/db/models.py` (append after `WorkflowAnalyticsSnapshot`, around line 645)

- [ ] **Step 1: Add the four model classes**

Append to `backend/app/db/models.py`. `Float`, `Integer`, `Boolean`, `Index`, `UniqueConstraint`, `Text`, `JSON`, `String`, `ForeignKey`, `func` are all already imported at the top of the file — verify before adding, and add only what is missing.

```python
class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_enabled_next_check", "enabled", "next_check_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="workflow")
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True, index=True
    )
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    notify_workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    renotify_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="on_recovery")
    cooldown_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    check_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    next_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship("User")
    workflow: Mapped["Workflow | None"] = relationship("Workflow", foreign_keys=[workflow_id])
    notify_workflow: Mapped["Workflow | None"] = relationship(
        "Workflow", foreign_keys=[notify_workflow_id]
    )
    events: Mapped[list["AlertEvent"]] = relationship(
        "AlertEvent", back_populates="alert", cascade="all, delete-orphan"
    )
    shares: Mapped[list["AlertShare"]] = relationship(
        "AlertShare", back_populates="alert", cascade="all, delete-orphan"
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_events_alert_triggered", "alert_id", "triggered_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    observed_value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notify_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notify_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    alert: Mapped["Alert"] = relationship("Alert", back_populates="events")


class AlertShare(Base):
    __tablename__ = "alert_shares"
    __table_args__ = (UniqueConstraint("alert_id", "user_id", name="uq_alert_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    alert: Mapped["Alert"] = relationship("Alert", back_populates="shares")
    user: Mapped["User"] = relationship("User")


class AlertTeamShare(Base):
    __tablename__ = "alert_team_shares"
    __table_args__ = (UniqueConstraint("alert_id", "team_id", name="uq_alert_team_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    alert: Mapped["Alert"] = relationship("Alert")
    team: Mapped["Team"] = relationship("Team")
```

> `Alert.workflow` and `Alert.notify_workflow` both point at `workflows`, so `foreign_keys=` is
> mandatory on both — SQLAlchemy cannot disambiguate two FKs to the same table and raises
> `AmbiguousForeignKeysError` at mapper configuration time, which surfaces as an import error in
> every test.

- [ ] **Step 2: Verify the models import cleanly**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend && \
  HEYM_OTEL_ENABLED=false uv run python -c "from app.db import models; print(models.Alert.__tablename__, models.AlertEvent.__tablename__)"
```

Expected: `alerts alert_events`

- [ ] **Step 3: Checkpoint** — `uv run ruff format app/db/models.py && uv run ruff check app/db/models.py`

---

### Task 2: Alembic migration

**Files:**
- Create: `backend/alembic/versions/108_add_alerts.py`

- [ ] **Step 1: Confirm the current head**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend && HEYM_OTEL_ENABLED=false uv run alembic heads
```

Expected: `107_add_heym_events (head)`. If it differs, use the printed value as `down_revision` below.

- [ ] **Step 2: Write the migration**

```python
"""add alerts

Revision ID: 108_add_alerts
Revises: 107_add_heym_events
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "108_add_alerts"
down_revision: str | Sequence[str] | None = "107_add_heym_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False, server_default="workflow"),
        sa.Column("workflow_id", UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default sa.text("true")),
        sa.Column("notify_workflow_id", UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="ok"),
        sa.Column("renotify_mode", sa.String(20), nullable=False, server_default="on_recovery"),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=True),
        sa.Column("check_interval_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observed_value", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_alerts_owner_id", "alerts", ["owner_id"])
    op.create_index("ix_alerts_alert_type", "alerts", ["alert_type"])
    op.create_index("ix_alerts_workflow_id", "alerts", ["workflow_id"])
    op.create_index("ix_alerts_enabled", "alerts", ["enabled"])
    op.create_index("ix_alerts_next_check_at", "alerts", ["next_check_at"])
    op.create_index("ix_alerts_enabled_next_check", "alerts", ["enabled", "next_check_at"])

    op.create_table(
        "alert_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("alert_id", UUID(as_uuid=True), sa.ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("observed_value", sa.Float(), nullable=False),
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notify_execution_id", UUID(as_uuid=True), nullable=True),
        sa.Column("notify_status", sa.String(20), nullable=True),
    )
    op.create_index("ix_alert_events_alert_id", "alert_events", ["alert_id"])
    op.create_index("ix_alert_events_triggered_at", "alert_events", ["triggered_at"])
    op.create_index("ix_alert_events_alert_triggered", "alert_events", ["alert_id", "triggered_at"])

    op.create_table(
        "alert_shares",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("alert_id", UUID(as_uuid=True), sa.ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("alert_id", "user_id", name="uq_alert_share"),
    )

    op.create_table(
        "alert_team_shares",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("alert_id", UUID(as_uuid=True), sa.ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("alert_id", "team_id", name="uq_alert_team_share"),
    )
    op.create_index("ix_alert_team_shares_alert_id", "alert_team_shares", ["alert_id"])
    op.create_index("ix_alert_team_shares_team_id", "alert_team_shares", ["team_id"])


def downgrade() -> None:
    op.drop_table("alert_team_shares")
    op.drop_table("alert_shares")
    op.drop_table("alert_events")
    op.drop_table("alerts")
```

> The `enabled` column line above contains a deliberate typo trap that Python will reject
> (`server_default sa.text("true")`). Write it as `server_default=sa.text("true")`.

- [ ] **Step 2: Apply the migration**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend && HEYM_OTEL_ENABLED=false uv run alembic upgrade head
```

Expected: `Running upgrade 107_add_heym_events -> 108_add_alerts`

- [ ] **Step 3: Verify the existing migration guard test still passes**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend && \
  HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_alembic_migrations.py -v
```

Expected: PASS. This test enforces a single head; a broken `down_revision` fails here.

- [ ] **Step 4: Checkpoint** — `uv run ruff format alembic/versions/108_add_alerts.py`

---

## Phase 2 — Schemas

### Task 3: Pydantic models

**Files:**
- Create: `backend/app/models/alert_schemas.py`
- Test: `backend/tests/test_alert_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
import uuid

from pydantic import ValidationError

from app.models.alert_schemas import AlertCreate, parse_alert_config


class TestAlertConfigUnion(unittest.TestCase):
    def test_error_threshold_config_parses(self):
        cfg = parse_alert_config(
            "error_threshold", {"window_minutes": 10, "threshold_count": 5}
        )
        self.assertEqual(cfg.threshold_count, 5)
        self.assertEqual(cfg.window_minutes, 10)

    def test_duration_config_defaults_to_max(self):
        cfg = parse_alert_config(
            "workflow_duration", {"window_minutes": 30, "threshold_ms": 5000}
        )
        self.assertEqual(cfg.aggregation, "max")
        self.assertEqual(cfg.min_samples, 1)

    def test_token_cost_requires_known_metric(self):
        with self.assertRaises(ValidationError):
            parse_alert_config(
                "token_cost",
                {"window_minutes": 60, "metric": "bananas", "threshold": 1.0},
            )

    def test_unknown_alert_type_raises(self):
        with self.assertRaises(ValueError):
            parse_alert_config("cosmic_rays", {"window_minutes": 5})

    def test_window_minutes_upper_bound(self):
        with self.assertRaises(ValidationError):
            parse_alert_config(
                "execution_count", {"window_minutes": 10081, "threshold_count": 1}
            )


class TestAlertCreateValidation(unittest.TestCase):
    def _base(self, **overrides):
        payload = {
            "name": "Invoice failures",
            "alert_type": "error_threshold",
            "scope": "workflow",
            "workflow_id": str(uuid.uuid4()),
            "config": {"window_minutes": 10, "threshold_count": 5},
        }
        payload.update(overrides)
        return payload

    def test_valid_workflow_scope(self):
        model = AlertCreate(**self._base())
        self.assertEqual(model.scope, "workflow")

    def test_workflow_scope_requires_workflow_id(self):
        with self.assertRaises(ValidationError):
            AlertCreate(**self._base(workflow_id=None))

    def test_system_scope_rejects_workflow_id(self):
        with self.assertRaises(ValidationError):
            AlertCreate(**self._base(scope="system"))

    def test_cooldown_mode_requires_cooldown_minutes(self):
        with self.assertRaises(ValidationError):
            AlertCreate(**self._base(renotify_mode="cooldown"))

    def test_cooldown_mode_with_minutes_is_valid(self):
        model = AlertCreate(**self._base(renotify_mode="cooldown", cooldown_minutes=30))
        self.assertEqual(model.cooldown_minutes, 30)

    def test_check_interval_floor_is_sixty(self):
        with self.assertRaises(ValidationError):
            AlertCreate(**self._base(check_interval_seconds=15))
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend && \
  HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_alert_schemas.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.alert_schemas'`

- [ ] **Step 3: Write the schemas**

```python
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
    def _validate(self) -> "_AlertWritableFields":
        if self.scope == "workflow" and self.workflow_id is None:
            raise ValueError("workflow_id is required when scope is 'workflow'")
        if self.scope == "system" and self.workflow_id is not None:
            raise ValueError("workflow_id must be omitted when scope is 'system'")
        if self.renotify_mode == "cooldown" and self.cooldown_minutes is None:
            raise ValueError("cooldown_minutes is required when renotify_mode is 'cooldown'")
        parse_alert_config(self.alert_type, self.config)
        return self


class AlertCreate(_AlertWritableFields):
    pass


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
    is_owner: bool = True
    created_at: datetime
    updated_at: datetime


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
    def _validate(self) -> "AlertPreviewRequest":
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
    """AI-produced wizard prefill."""

    name: str
    description: str | None = None
    alert_type: AlertType
    scope: AlertScope
    workflow_id: uuid.UUID | None = None
    config: dict[str, Any]
    renotify_mode: RenotifyMode = "on_recovery"
    cooldown_minutes: int | None = None
    notify_workflow_id: uuid.UUID | None = None
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
```

- [ ] **Step 4: Run the tests**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend && \
  HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_alert_schemas.py -v
```

Expected: 11 passed

- [ ] **Step 5: Checkpoint** — `uv run ruff format app/models/alert_schemas.py tests/test_alert_schemas.py && uv run ruff check app/models/alert_schemas.py`

---

## Phase 3 — Metric handlers

### Task 4: Evaluation context

**Files:**
- Create: `backend/app/services/alerts/__init__.py`, `backend/app/services/alerts/context.py`, `backend/app/services/alerts/types/__init__.py`

- [ ] **Step 1: Write `context.py`**

```python
"""Shared value objects passed between the evaluator and the metric handlers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class AlertEvaluationContext:
    """Everything a metric handler needs, and nothing it does not.

    ``workflow_ids`` is already resolved: a single-element list for workflow scope,
    every workflow the owner can access for system scope. Handlers must not
    re-derive scope.
    """

    db: AsyncSession
    owner_id: uuid.UUID
    workflow_ids: list[uuid.UUID]
    window_start: datetime
    window_end: datetime
    config: Any


@dataclass
class AlertObservation:
    """A single metric reading. ``observed_value is None`` means "not enough data"."""

    observed_value: float | None
    threshold_value: float
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def breached(self) -> bool:
        if self.observed_value is None:
            return False
        return self.observed_value >= self.threshold_value
```

- [ ] **Step 2: Write both `__init__.py` files**

`backend/app/services/alerts/types/__init__.py` — empty file.

`backend/app/services/alerts/__init__.py`:

```python
"""Alert evaluation package.

Metric computation lives in ``types/``, one module per alert type, behind
``registry.py``. Claiming, state transitions, event packaging, and notify
dispatch live in ``evaluator.py``. Do not add alert-type branches to the
evaluator — add a handler module and a registry entry.
"""
```

- [ ] **Step 3: Verify import**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend && HEYM_OTEL_ENABLED=false \
  uv run python -c "from app.services.alerts.context import AlertObservation; print(AlertObservation(5.0, 3.0).breached)"
```

Expected: `True`

- [ ] **Step 4: Checkpoint** — `uv run ruff format app/services/alerts/`

---

### Task 5: `error_threshold` handler

**Files:**
- Create: `backend/app/services/alerts/types/error_threshold.py`
- Test: `backend/tests/test_alert_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.models.alert_schemas import parse_alert_config
from app.services.alerts.context import AlertEvaluationContext
from app.services.alerts.types import error_threshold


def _ctx(db, config, workflow_ids=None, window_minutes=10):
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    return AlertEvaluationContext(
        db=db,
        owner_id=uuid.uuid4(),
        workflow_ids=workflow_ids if workflow_ids is not None else [uuid.uuid4()],
        window_start=now - timedelta(minutes=window_minutes),
        window_end=now,
        config=config,
    )


def _scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _rows_result(rows):
    result = MagicMock()
    result.all.return_value = rows
    return result


class TestErrorThresholdHandler(unittest.IsolatedAsyncioTestCase):
    async def test_counts_errors_in_window(self):
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(12),
                _rows_result(
                    [
                        SimpleNamespace(id=uuid.uuid4(), error_message="boom"),
                        SimpleNamespace(id=uuid.uuid4(), error_message="boom"),
                    ]
                ),
            ]
        )
        config = parse_alert_config(
            "error_threshold", {"window_minutes": 10, "threshold_count": 5}
        )
        observation = await error_threshold.evaluate(_ctx(db, config))
        self.assertEqual(observation.observed_value, 12.0)
        self.assertEqual(observation.threshold_value, 5.0)
        self.assertTrue(observation.breached)
        self.assertEqual(observation.context["error_count"], 12)
        self.assertEqual(len(observation.context["sample_execution_ids"]), 2)

    async def test_no_errors_is_not_breached(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_scalar_result(0), _rows_result([])])
        config = parse_alert_config(
            "error_threshold", {"window_minutes": 10, "threshold_count": 5}
        )
        observation = await error_threshold.evaluate(_ctx(db, config))
        self.assertEqual(observation.observed_value, 0.0)
        self.assertFalse(observation.breached)

    async def test_empty_scope_short_circuits_without_querying(self):
        db = MagicMock()
        db.execute = AsyncMock()
        config = parse_alert_config(
            "error_threshold", {"window_minutes": 10, "threshold_count": 5}
        )
        observation = await error_threshold.evaluate(_ctx(db, config, workflow_ids=[]))
        self.assertEqual(observation.observed_value, 0.0)
        db.execute.assert_not_awaited()

    async def test_exact_threshold_counts_as_breach(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_scalar_result(5), _rows_result([])])
        config = parse_alert_config(
            "error_threshold", {"window_minutes": 10, "threshold_count": 5}
        )
        observation = await error_threshold.evaluate(_ctx(db, config))
        self.assertTrue(observation.breached)
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend && \
  HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_alert_metrics.py -v
```

Expected: FAIL — `ImportError: cannot import name 'error_threshold'`

- [ ] **Step 3: Write the handler**

```python
"""Error-count-in-window metric.

Counts failed executions across the window rather than reacting to one failure,
because a single failed run is noise and a burst is an incident.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import ExecutionHistory
from app.services.alerts.context import AlertEvaluationContext, AlertObservation

SAMPLE_LIMIT = 5


async def evaluate(ctx: AlertEvaluationContext) -> AlertObservation:
    threshold = float(ctx.config.threshold_count)
    if not ctx.workflow_ids:
        return AlertObservation(observed_value=0.0, threshold_value=threshold, context={})

    window = (
        ExecutionHistory.workflow_id.in_(ctx.workflow_ids),
        ExecutionHistory.started_at >= ctx.window_start,
        ExecutionHistory.started_at <= ctx.window_end,
        ExecutionHistory.status == "error",
    )

    count_result = await ctx.db.execute(select(func.count()).select_from(ExecutionHistory).where(*window))
    error_count = int(count_result.scalar() or 0)

    sample_result = await ctx.db.execute(
        select(ExecutionHistory.id, ExecutionHistory.outputs)
        .where(*window)
        .order_by(ExecutionHistory.started_at.desc())
        .limit(SAMPLE_LIMIT)
    )
    samples = list(sample_result.all())

    return AlertObservation(
        observed_value=float(error_count),
        threshold_value=threshold,
        context={
            "error_count": error_count,
            "sample_execution_ids": [str(row[0]) for row in samples],
            "sample_errors": [_error_text(row) for row in samples],
        },
    )


def _error_text(row: object) -> str:
    """Best-effort error string from an execution row without exploding on shape."""
    payload = getattr(row, "outputs", None)
    if payload is None and isinstance(row, tuple) and len(row) > 1:
        payload = row[1]
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value[:300]
    message = getattr(row, "error_message", None)
    return str(message)[:300] if message else "Unknown error"
```

- [ ] **Step 4: Run the tests**

Same command as Step 2. Expected: 4 passed.

- [ ] **Step 5: Checkpoint** — `uv run ruff format app/services/alerts/types/error_threshold.py tests/test_alert_metrics.py`

---

### Task 6: `execution_count` handler

**Files:**
- Create: `backend/app/services/alerts/types/execution_count.py`
- Test: append to `backend/tests/test_alert_metrics.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_alert_metrics.py`; add `execution_count` to the existing `from app.services.alerts.types import ...` line)

```python
class TestExecutionCountHandler(unittest.IsolatedAsyncioTestCase):
    async def test_counts_all_statuses(self):
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(2000),
                _rows_result([("cron", 1990), ("manual", 10)]),
            ]
        )
        config = parse_alert_config(
            "execution_count", {"window_minutes": 60, "threshold_count": 100}
        )
        observation = await execution_count.evaluate(_ctx(db, config, window_minutes=60))
        self.assertEqual(observation.observed_value, 2000.0)
        self.assertTrue(observation.breached)
        self.assertEqual(observation.context["by_trigger_source"]["cron"], 1990)

    async def test_under_threshold_not_breached(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_scalar_result(20), _rows_result([("cron", 20)])])
        config = parse_alert_config(
            "execution_count", {"window_minutes": 60, "threshold_count": 100}
        )
        observation = await execution_count.evaluate(_ctx(db, config, window_minutes=60))
        self.assertFalse(observation.breached)

    async def test_empty_scope_short_circuits(self):
        db = MagicMock()
        db.execute = AsyncMock()
        config = parse_alert_config(
            "execution_count", {"window_minutes": 60, "threshold_count": 100}
        )
        observation = await execution_count.evaluate(_ctx(db, config, workflow_ids=[]))
        self.assertEqual(observation.observed_value, 0.0)
        db.execute.assert_not_awaited()
```

- [ ] **Step 2: Run it** (same pytest command) — Expected: FAIL, `NameError: name 'execution_count' is not defined`

- [ ] **Step 3: Write the handler**

```python
"""Execution-count-in-window metric.

Answers "did this run far more often than it should have". The trigger-source
breakdown is in the context because a runaway run count is almost always
explained by which trigger fired it.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import ExecutionHistory
from app.services.alerts.context import AlertEvaluationContext, AlertObservation


async def evaluate(ctx: AlertEvaluationContext) -> AlertObservation:
    threshold = float(ctx.config.threshold_count)
    if not ctx.workflow_ids:
        return AlertObservation(observed_value=0.0, threshold_value=threshold, context={})

    window = (
        ExecutionHistory.workflow_id.in_(ctx.workflow_ids),
        ExecutionHistory.started_at >= ctx.window_start,
        ExecutionHistory.started_at <= ctx.window_end,
    )

    count_result = await ctx.db.execute(select(func.count()).select_from(ExecutionHistory).where(*window))
    total = int(count_result.scalar() or 0)

    breakdown_result = await ctx.db.execute(
        select(ExecutionHistory.trigger_source, func.count())
        .where(*window)
        .group_by(ExecutionHistory.trigger_source)
    )
    by_source = {str(source or "unknown"): int(count) for source, count in breakdown_result.all()}

    return AlertObservation(
        observed_value=float(total),
        threshold_value=threshold,
        context={"execution_count": total, "by_trigger_source": by_source},
    )
```

- [ ] **Step 4: Run the tests** — Expected: 7 passed (4 from Task 5 + 3 new).

- [ ] **Step 5: Checkpoint** — `uv run ruff format app/services/alerts/types/execution_count.py tests/test_alert_metrics.py`

---

### Task 7: `workflow_duration` handler

**Files:**
- Create: `backend/app/services/alerts/types/workflow_duration.py`
- Test: append to `backend/tests/test_alert_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
class TestWorkflowDurationHandler(unittest.IsolatedAsyncioTestCase):
    async def test_max_aggregation(self):
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[_rows_result([(1000.0,), (9000.0,), (3000.0,)])]
        )
        config = parse_alert_config(
            "workflow_duration",
            {"window_minutes": 30, "threshold_ms": 5000, "aggregation": "max"},
        )
        observation = await workflow_duration.evaluate(_ctx(db, config, window_minutes=30))
        self.assertEqual(observation.observed_value, 9000.0)
        self.assertTrue(observation.breached)
        self.assertEqual(observation.context["sample_count"], 3)

    async def test_avg_aggregation(self):
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[_rows_result([(1000.0,), (2000.0,), (3000.0,)])]
        )
        config = parse_alert_config(
            "workflow_duration",
            {"window_minutes": 30, "threshold_ms": 5000, "aggregation": "avg"},
        )
        observation = await workflow_duration.evaluate(_ctx(db, config, window_minutes=30))
        self.assertEqual(observation.observed_value, 2000.0)
        self.assertFalse(observation.breached)

    async def test_p95_matches_analytics_percentile_helper(self):
        from app.api.analytics import calculate_percentile

        values = [float(v) for v in range(1, 101)]
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows_result([(v,) for v in values])])
        config = parse_alert_config(
            "workflow_duration",
            {"window_minutes": 30, "threshold_ms": 1, "aggregation": "p95"},
        )
        observation = await workflow_duration.evaluate(_ctx(db, config, window_minutes=30))
        self.assertEqual(observation.observed_value, calculate_percentile(values, 95))

    async def test_min_samples_suppresses(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows_result([(90000.0,)])])
        config = parse_alert_config(
            "workflow_duration",
            {"window_minutes": 30, "threshold_ms": 5000, "min_samples": 5},
        )
        observation = await workflow_duration.evaluate(_ctx(db, config, window_minutes=30))
        self.assertIsNone(observation.observed_value)
        self.assertFalse(observation.breached)

    async def test_empty_window_is_not_breached(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows_result([])])
        config = parse_alert_config(
            "workflow_duration", {"window_minutes": 30, "threshold_ms": 5000}
        )
        observation = await workflow_duration.evaluate(_ctx(db, config, window_minutes=30))
        self.assertIsNone(observation.observed_value)
        self.assertFalse(observation.breached)
```

- [ ] **Step 2: Run it** — Expected: FAIL, `NameError: name 'workflow_duration' is not defined`

- [ ] **Step 3: Write the handler**

```python
"""Workflow duration metric.

``p95`` delegates to the same ``calculate_percentile`` the Analytics tab uses, so
an alert and the latency chart never disagree about the same window.

Returning ``None`` below ``min_samples`` is deliberate: ``max`` over a single run
in a quiet window is just that run, which fires on noise rather than on a trend.
"""

from __future__ import annotations

from sqlalchemy import select

from app.api.analytics import calculate_percentile
from app.db.models import ExecutionHistory
from app.services.alerts.context import AlertEvaluationContext, AlertObservation


async def evaluate(ctx: AlertEvaluationContext) -> AlertObservation:
    threshold = float(ctx.config.threshold_ms)
    if not ctx.workflow_ids:
        return AlertObservation(observed_value=None, threshold_value=threshold, context={})

    result = await ctx.db.execute(
        select(ExecutionHistory.execution_time_ms).where(
            ExecutionHistory.workflow_id.in_(ctx.workflow_ids),
            ExecutionHistory.started_at >= ctx.window_start,
            ExecutionHistory.started_at <= ctx.window_end,
        )
    )
    values = [float(row[0]) for row in result.all() if row[0] is not None]

    if len(values) < ctx.config.min_samples:
        return AlertObservation(
            observed_value=None,
            threshold_value=threshold,
            context={"sample_count": len(values), "min_samples": ctx.config.min_samples},
        )

    aggregation = ctx.config.aggregation
    if aggregation == "max":
        observed = max(values)
    elif aggregation == "avg":
        observed = sum(values) / len(values)
    else:
        observed = calculate_percentile(values, 95)

    return AlertObservation(
        observed_value=float(observed),
        threshold_value=threshold,
        context={
            "aggregation": aggregation,
            "sample_count": len(values),
            "max_ms": max(values),
            "avg_ms": sum(values) / len(values),
        },
    )
```

- [ ] **Step 4: Run the tests** — Expected: 12 passed.

- [ ] **Step 5: Checkpoint** — `uv run ruff format app/services/alerts/types/workflow_duration.py tests/test_alert_metrics.py`

---

### Task 8: `token_cost` handler

**Files:**
- Create: `backend/app/services/alerts/types/token_cost.py`
- Test: append to `backend/tests/test_alert_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
class TestTokenCostHandler(unittest.IsolatedAsyncioTestCase):
    async def test_total_tokens_metric(self):
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _rows_result([("gpt-5", 1000, 500, 1500), ("gpt-5", 2000, 1000, 3000)])
            ]
        )
        config = parse_alert_config(
            "token_cost",
            {"window_minutes": 60, "metric": "total_tokens", "threshold": 4000},
        )
        observation = await token_cost.evaluate(_ctx(db, config, window_minutes=60))
        self.assertEqual(observation.observed_value, 4500.0)
        self.assertTrue(observation.breached)
        self.assertEqual(observation.context["by_model"]["gpt-5"]["total_tokens"], 4500)

    async def test_usd_metric_uses_pricing_service(self):
        from decimal import Decimal

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows_result([("gpt-5", 1_000_000, 0, 1_000_000)])])
        config = parse_alert_config(
            "token_cost", {"window_minutes": 60, "metric": "usd", "threshold": 1.0}
        )
        with patch(
            "app.services.alerts.types.token_cost.resolve_costs_for_user",
            new=AsyncMock(return_value=[(Decimal("2.50"), True)]),
        ):
            observation = await token_cost.evaluate(_ctx(db, config, window_minutes=60))
        self.assertAlmostEqual(observation.observed_value, 2.50)
        self.assertTrue(observation.breached)

    async def test_no_traces_is_zero(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows_result([])])
        config = parse_alert_config(
            "token_cost",
            {"window_minutes": 60, "metric": "total_tokens", "threshold": 100},
        )
        observation = await token_cost.evaluate(_ctx(db, config, window_minutes=60))
        self.assertEqual(observation.observed_value, 0.0)
        self.assertFalse(observation.breached)

    async def test_unpriced_model_is_flagged_in_context(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows_result([("mystery-model", 100, 100, 200)])])
        config = parse_alert_config(
            "token_cost", {"window_minutes": 60, "metric": "usd", "threshold": 1.0}
        )
        with patch(
            "app.services.alerts.types.token_cost.resolve_costs_for_user",
            new=AsyncMock(return_value=[(None, False)]),
        ):
            observation = await token_cost.evaluate(_ctx(db, config, window_minutes=60))
        self.assertEqual(observation.observed_value, 0.0)
        self.assertIn("mystery-model", observation.context["unpriced_models"])
```

Add `patch` to the `unittest.mock` import at the top of the test file.

- [ ] **Step 2: Run it** — Expected: FAIL, `NameError: name 'token_cost' is not defined`

- [ ] **Step 3: Write the handler**

```python
"""Token and USD spend metric.

USD is resolved through ``resolve_costs_for_user`` — the same path the Traces tab
and the cost page use. A cost alert that disagrees with the cost page is worse
than no cost alert, so this must never grow its own pricing math.

Coding-agent (Codex / OpenCode) usage is intentionally excluded; this reads
``llm_traces`` only.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import LLMTrace
from app.services.alerts.context import AlertEvaluationContext, AlertObservation
from app.services.llm_pricing import resolve_costs_for_user


async def evaluate(ctx: AlertEvaluationContext) -> AlertObservation:
    threshold = float(ctx.config.threshold)

    filters = [
        LLMTrace.user_id == ctx.owner_id,
        LLMTrace.created_at >= ctx.window_start,
        LLMTrace.created_at <= ctx.window_end,
    ]
    if ctx.workflow_ids:
        filters.append(LLMTrace.workflow_id.in_(ctx.workflow_ids))

    result = await ctx.db.execute(
        select(
            LLMTrace.model,
            LLMTrace.prompt_tokens,
            LLMTrace.completion_tokens,
            LLMTrace.total_tokens,
        ).where(*filters)
    )
    rows = list(result.all())

    by_model: dict[str, dict[str, float]] = {}
    pairs: list[tuple[str, int, int]] = []
    for model, prompt_tokens, completion_tokens, total_tokens in rows:
        key = str(model or "unknown")
        bucket = by_model.setdefault(key, {"total_tokens": 0, "usd": 0.0, "calls": 0})
        bucket["total_tokens"] += int(total_tokens or 0)
        bucket["calls"] += 1
        pairs.append((key, int(prompt_tokens or 0), int(completion_tokens or 0)))

    if ctx.config.metric == "total_tokens":
        observed = float(sum(b["total_tokens"] for b in by_model.values()))
        return AlertObservation(
            observed_value=observed,
            threshold_value=threshold,
            context={"metric": "total_tokens", "by_model": by_model, "call_count": len(rows)},
        )

    costs = await resolve_costs_for_user(ctx.db, ctx.owner_id, pairs)
    total_usd = 0.0
    unpriced: set[str] = set()
    for (model, _prompt, _completion), (cost, is_priced) in zip(pairs, costs, strict=False):
        if not is_priced or cost is None:
            unpriced.add(model)
            continue
        total_usd += float(cost)
        by_model[model]["usd"] += float(cost)

    return AlertObservation(
        observed_value=round(total_usd, 6),
        threshold_value=threshold,
        context={
            "metric": "usd",
            "by_model": by_model,
            "call_count": len(rows),
            "unpriced_models": sorted(unpriced),
        },
    )
```

> Note the `if ctx.workflow_ids:` guard rather than an unconditional filter. For system scope the
> evaluator passes every accessible workflow id, but LLM calls made outside a workflow (Dashboard
> Chat, AI Assistant) carry `workflow_id = NULL`. An empty list therefore means "all of this user's
> spend", which is what a system-scope cost alert should measure.

- [ ] **Step 4: Run the tests** — Expected: 16 passed.

- [ ] **Step 5: Checkpoint** — `uv run ruff format app/services/alerts/types/token_cost.py tests/test_alert_metrics.py`

---

### Task 9: Handler registry

**Files:**
- Create: `backend/app/services/alerts/registry.py`
- Test: `backend/tests/test_alert_registry.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from app.models.alert_schemas import _CONFIG_BY_TYPE
from app.services.alerts.registry import ALERT_HANDLERS, get_alert_handler


class TestAlertRegistry(unittest.TestCase):
    def test_every_config_type_has_a_handler(self):
        self.assertEqual(set(ALERT_HANDLERS), set(_CONFIG_BY_TYPE))

    def test_get_handler_returns_callable(self):
        handler = get_alert_handler("error_threshold")
        self.assertTrue(callable(handler))

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            get_alert_handler("cosmic_rays")
```

- [ ] **Step 2: Run it** — Expected: FAIL, `ModuleNotFoundError: app.services.alerts.registry`

- [ ] **Step 3: Write the registry**

```python
"""alert_type -> metric handler.

Adding an alert type means adding a module under ``types/`` and one line here.
Do not branch on ``alert_type`` inside the evaluator.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.services.alerts.context import AlertEvaluationContext, AlertObservation
from app.services.alerts.types import (
    error_threshold,
    execution_count,
    token_cost,
    workflow_duration,
)

AlertHandler = Callable[[AlertEvaluationContext], Awaitable[AlertObservation]]

ALERT_HANDLERS: dict[str, AlertHandler] = {
    "error_threshold": error_threshold.evaluate,
    "workflow_duration": workflow_duration.evaluate,
    "token_cost": token_cost.evaluate,
    "execution_count": execution_count.evaluate,
}


def get_alert_handler(alert_type: str) -> AlertHandler:
    handler = ALERT_HANDLERS.get(alert_type)
    if handler is None:
        raise ValueError(f"No alert handler registered for type: {alert_type}")
    return handler
```

- [ ] **Step 4: Run the tests** — Expected: 3 passed.

- [ ] **Step 5: Checkpoint** — `uv run ruff format app/services/alerts/registry.py tests/test_alert_registry.py`

---

## Phase 4 — Evaluator

### Task 10: Scope resolution and observation

**Files:**
- Create: `backend/app/services/alerts/evaluator.py` (first half)
- Test: `backend/tests/test_alert_evaluator.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.alerts import evaluator

MODULE = "app.services.alerts.evaluator"


def _alert(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "owner_id": uuid.uuid4(),
        "name": "Invoice failures",
        "alert_type": "error_threshold",
        "scope": "workflow",
        "workflow_id": uuid.uuid4(),
        "config": {"window_minutes": 10, "threshold_count": 5},
        "enabled": True,
        "notify_workflow_id": None,
        "state": "ok",
        "renotify_mode": "on_recovery",
        "cooldown_minutes": None,
        "check_interval_seconds": 60,
        "last_triggered_at": None,
        "last_observed_value": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestResolveScope(unittest.IsolatedAsyncioTestCase):
    async def test_workflow_scope_returns_single_id(self):
        alert = _alert()
        db = MagicMock()
        ids = await evaluator.resolve_scope_workflow_ids(db, alert)
        self.assertEqual(ids, [alert.workflow_id])

    async def test_system_scope_uses_accessible_workflow_ids(self):
        alert = _alert(scope="system", workflow_id=None)
        accessible = [uuid.uuid4(), uuid.uuid4()]
        db = MagicMock()
        with patch(
            f"{MODULE}.get_accessible_workflow_ids",
            new=AsyncMock(return_value=accessible),
        ):
            ids = await evaluator.resolve_scope_workflow_ids(db, alert)
        self.assertEqual(ids, accessible)


class TestObserve(unittest.IsolatedAsyncioTestCase):
    async def test_observe_calls_the_registered_handler(self):
        alert = _alert()
        db = MagicMock()
        now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        fake = MagicMock(observed_value=9.0, threshold_value=5.0, breached=True, context={})
        with patch(f"{MODULE}.get_alert_handler", return_value=AsyncMock(return_value=fake)):
            observation, window_start, window_end = await evaluator.observe(db, alert, now=now)
        self.assertEqual(observation.observed_value, 9.0)
        self.assertEqual(window_end, now)
        self.assertEqual(window_start, now - timedelta(minutes=10))
```

- [ ] **Step 2: Run it** — Expected: FAIL, `ModuleNotFoundError: app.services.alerts.evaluator`

- [ ] **Step 3: Write the first half of the evaluator**

```python
"""Alert evaluation: claiming, observation, state machine, notify dispatch.

Metric computation is NOT here — it lives in ``types/`` behind ``registry.py``.
This module owns everything that is the same for every alert type.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import get_accessible_workflow_ids
from app.db.models import Alert, AlertEvent, Workflow
from app.db.session import async_session_maker
from app.models.alert_schemas import describe_condition, parse_alert_config
from app.services.alerts.context import AlertEvaluationContext, AlertObservation
from app.services.alerts.registry import get_alert_handler

logger = logging.getLogger("alert_evaluator")

CLAIM_BATCH_SIZE = 50

# Notify tasks are kept referenced so the event loop does not garbage-collect a
# still-running dispatch. asyncio holds only weak references to bare tasks.
_notify_tasks: set[asyncio.Task] = set()


async def resolve_scope_workflow_ids(db: AsyncSession, alert: Any) -> list[uuid.UUID]:
    """Workflow ids this alert measures.

    System scope resolves to the workflows the OWNER can access, not the whole
    instance — a shared alert must not leak metrics for workflows the viewer
    cannot open.
    """
    if alert.scope == "workflow":
        return [alert.workflow_id] if alert.workflow_id else []
    return await get_accessible_workflow_ids(db, alert.owner_id)


async def observe(
    db: AsyncSession, alert: Any, *, now: datetime | None = None
) -> tuple[AlertObservation, datetime, datetime]:
    """Compute the alert's metric over its window. Does not mutate anything."""
    window_end = now or datetime.now(timezone.utc)
    config = parse_alert_config(alert.alert_type, alert.config)
    window_start = window_end - timedelta(minutes=config.window_minutes)

    ctx = AlertEvaluationContext(
        db=db,
        owner_id=alert.owner_id,
        workflow_ids=await resolve_scope_workflow_ids(db, alert),
        window_start=window_start,
        window_end=window_end,
        config=config,
    )
    handler = get_alert_handler(alert.alert_type)
    observation = await handler(ctx)
    return observation, window_start, window_end
```

- [ ] **Step 4: Run the tests** — Expected: 3 passed.

- [ ] **Step 5: Checkpoint** — `uv run ruff format app/services/alerts/evaluator.py tests/test_alert_evaluator.py`

---

### Task 11: State machine

**Files:**
- Modify: `backend/app/services/alerts/evaluator.py`
- Test: append to `backend/tests/test_alert_evaluator.py`

- [ ] **Step 1: Write the failing test**

```python
class TestShouldFire(unittest.TestCase):
    def _now(self):
        return datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)

    def test_ok_plus_breach_fires(self):
        alert = _alert(state="ok")
        self.assertTrue(evaluator.should_fire(alert, breached=True, now=self._now()))

    def test_ok_without_breach_does_not_fire(self):
        alert = _alert(state="ok")
        self.assertFalse(evaluator.should_fire(alert, breached=False, now=self._now()))

    def test_triggered_on_recovery_stays_silent_while_breached(self):
        alert = _alert(
            state="triggered",
            renotify_mode="on_recovery",
            last_triggered_at=self._now() - timedelta(hours=5),
        )
        self.assertFalse(evaluator.should_fire(alert, breached=True, now=self._now()))

    def test_triggered_cooldown_refires_after_the_interval(self):
        alert = _alert(
            state="triggered",
            renotify_mode="cooldown",
            cooldown_minutes=30,
            last_triggered_at=self._now() - timedelta(minutes=31),
        )
        self.assertTrue(evaluator.should_fire(alert, breached=True, now=self._now()))

    def test_triggered_cooldown_silent_inside_the_interval(self):
        alert = _alert(
            state="triggered",
            renotify_mode="cooldown",
            cooldown_minutes=30,
            last_triggered_at=self._now() - timedelta(minutes=5),
        )
        self.assertFalse(evaluator.should_fire(alert, breached=True, now=self._now()))

    def test_recovery_then_breach_fires_again(self):
        alert = _alert(state="ok", last_triggered_at=self._now() - timedelta(minutes=1))
        self.assertTrue(evaluator.should_fire(alert, breached=True, now=self._now()))


class TestNextState(unittest.TestCase):
    def test_breach_moves_to_triggered(self):
        self.assertEqual(evaluator.next_state(breached=True), "triggered")

    def test_no_breach_moves_to_ok(self):
        self.assertEqual(evaluator.next_state(breached=False), "ok")
```

- [ ] **Step 2: Run it** — Expected: FAIL, `AttributeError: module ... has no attribute 'should_fire'`

- [ ] **Step 3: Add the state machine to `evaluator.py`**

```python
def next_state(*, breached: bool) -> str:
    return "triggered" if breached else "ok"


def should_fire(alert: Any, *, breached: bool, now: datetime) -> bool:
    """Whether this evaluation writes an event and dispatches a notification.

    Without this gate, a 60-second check interval on a genuinely broken workflow
    produces 60 events and 60 notify runs per hour, which is how alerting gets
    muted. The default ``on_recovery`` mode fires once and then holds its tongue
    until the metric drops back under the threshold.
    """
    if not breached:
        return False
    if alert.state != "triggered":
        return True
    if alert.renotify_mode != "cooldown":
        return False
    if alert.cooldown_minutes is None or alert.last_triggered_at is None:
        return False
    elapsed = now - _as_utc(alert.last_triggered_at)
    return elapsed >= timedelta(minutes=alert.cooldown_minutes)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
```

- [ ] **Step 4: Run the tests** — Expected: 11 passed.

- [ ] **Step 5: Checkpoint** — `uv run ruff format app/services/alerts/evaluator.py tests/test_alert_evaluator.py`

---

### Task 12: Notify dispatch

**Files:**
- Modify: `backend/app/services/alerts/evaluator.py`
- Test: append to `backend/tests/test_alert_evaluator.py`

- [ ] **Step 1: Write the failing test**

```python
class TestNotifyPayload(unittest.TestCase):
    def test_payload_carries_condition_and_observation(self):
        alert = _alert()
        payload = evaluator.build_notify_payload(
            alert,
            workflow_name="Invoice Sync",
            observed_value=12.0,
            threshold_value=5.0,
            window_start=datetime(2026, 8, 9, 11, 50, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
            context={"error_count": 12},
        )
        self.assertEqual(payload["alert_name"], "Invoice failures")
        self.assertEqual(payload["observed_value"], 12.0)
        self.assertEqual(payload["threshold_value"], 5.0)
        self.assertEqual(payload["window_minutes"], 10)
        self.assertEqual(payload["condition"], "5+ errors in 10m")
        self.assertEqual(payload["context"]["error_count"], 12)


class TestNotifyGuard(unittest.TestCase):
    def test_self_referential_notify_is_skipped(self):
        wf_id = uuid.uuid4()
        alert = _alert(workflow_id=wf_id, notify_workflow_id=wf_id)
        self.assertFalse(evaluator.should_dispatch_notify(alert))

    def test_distinct_notify_workflow_is_dispatched(self):
        alert = _alert(notify_workflow_id=uuid.uuid4())
        self.assertTrue(evaluator.should_dispatch_notify(alert))

    def test_no_notify_workflow_is_skipped(self):
        self.assertFalse(evaluator.should_dispatch_notify(_alert(notify_workflow_id=None)))
```

- [ ] **Step 2: Run it** — Expected: FAIL, `AttributeError: ... 'build_notify_payload'`

- [ ] **Step 3: Add notify dispatch to `evaluator.py`**

```python
def should_dispatch_notify(alert: Any) -> bool:
    """False when there is no notify workflow, or when it is the alert's own workflow.

    An execution_count alert on workflow A that notifies workflow A is a runaway
    loop — each notification adds an execution, which raises the count.
    """
    if alert.notify_workflow_id is None:
        return False
    return alert.notify_workflow_id != alert.workflow_id


def build_notify_payload(
    alert: Any,
    *,
    workflow_name: str | None,
    observed_value: float,
    threshold_value: float,
    window_start: datetime,
    window_end: datetime,
    context: dict[str, Any],
) -> dict[str, Any]:
    config = parse_alert_config(alert.alert_type, alert.config)
    return {
        "alert_id": str(alert.id),
        "alert_name": alert.name,
        "alert_type": alert.alert_type,
        "condition": describe_condition(alert.alert_type, alert.config),
        "scope": alert.scope,
        "workflow_id": str(alert.workflow_id) if alert.workflow_id else None,
        "workflow_name": workflow_name,
        "observed_value": observed_value,
        "threshold_value": threshold_value,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_minutes": config.window_minutes,
        "context": context,
    }


async def _run_notify_workflow(alert_id: uuid.UUID, event_id: uuid.UUID,
                               notify_workflow_id: uuid.UUID, payload: dict[str, Any]) -> None:
    """Execute the notify workflow and record the outcome on the event row.

    Runs in its own session and swallows every exception. A broken notify
    workflow must never stop the evaluator loop — the record of the firing
    matters more than the delivery of it.
    """
    from app.api.workflows import collect_referenced_workflows, get_credentials_context
    from app.services.global_variables_service import get_global_variables_context
    from app.services.workflow_executor import execute_workflow

    status = "failed"
    execution_id: uuid.UUID | None = None
    try:
        async with async_session_maker() as db:
            wf_result = await db.execute(select(Workflow).where(Workflow.id == notify_workflow_id))
            workflow = wf_result.scalar_one_or_none()
            if workflow is None:
                status = "skipped"
            else:
                credentials = await get_credentials_context(db, workflow.owner_id)
                variables = await get_global_variables_context(db, workflow.owner_id)
                referenced = await collect_referenced_workflows(db, workflow)
                result = await execute_workflow(
                    nodes=workflow.nodes,
                    edges=workflow.edges,
                    inputs={"body": payload},
                    credentials=credentials,
                    global_variables=variables,
                    referenced_workflows=referenced,
                    workflow_id=str(workflow.id),
                    user_id=str(workflow.owner_id),
                )
                execution_id = getattr(result, "execution_id", None)
                status = "succeeded"
    except Exception:
        logger.exception("Alert %s notify workflow failed", alert_id)
        status = "failed"

    try:
        async with async_session_maker() as db:
            await db.execute(
                update(AlertEvent)
                .where(AlertEvent.id == event_id)
                .values(notify_status=status, notify_execution_id=execution_id)
            )
            await db.commit()
    except Exception:
        logger.exception("Could not record notify status for alert event %s", event_id)


def dispatch_notify(alert: Any, event_id: uuid.UUID, payload: dict[str, Any]) -> None:
    """Start the notify workflow in the background, keeping a strong task reference."""
    task = asyncio.create_task(
        _run_notify_workflow(alert.id, event_id, alert.notify_workflow_id, payload)
    )
    _notify_tasks.add(task)
    task.add_done_callback(_notify_tasks.discard)
```

> **Verify the `execute_workflow` signature before writing this.** Run
> `grep -n "async def execute_workflow" -A 20 backend/app/services/workflow_executor.py` and match
> the keyword arguments exactly. `error_workflow_runner.py` is the closest working example of
> calling it from a service and is the reference to copy.

- [ ] **Step 4: Run the tests** — Expected: 15 passed.

- [ ] **Step 5: Checkpoint** — `uv run ruff format app/services/alerts/evaluator.py tests/test_alert_evaluator.py`

---

### Task 13: Claim and the full evaluation pass

**Files:**
- Modify: `backend/app/services/alerts/evaluator.py`
- Test: `backend/tests/test_alert_claiming.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.alerts import evaluator

MODULE = "app.services.alerts.evaluator"


class TestClaimDueAlerts(unittest.IsolatedAsyncioTestCase):
    async def test_claim_advances_next_check_at_and_commits(self):
        alert = SimpleNamespace(id=uuid.uuid4(), check_interval_seconds=60)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [alert]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        claimed = await evaluator.claim_due_alerts(db, now=datetime.now(timezone.utc))

        self.assertEqual(claimed, [alert])
        db.commit.assert_awaited_once()
        self.assertEqual(db.execute.await_count, 1)

    async def test_no_due_alerts_returns_empty(self):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        claimed = await evaluator.claim_due_alerts(db, now=datetime.now(timezone.utc))
        self.assertEqual(claimed, [])


class TestEvaluateAlert(unittest.IsolatedAsyncioTestCase):
    def _alert(self, **overrides):
        defaults = {
            "id": uuid.uuid4(),
            "owner_id": uuid.uuid4(),
            "name": "Cost guard",
            "alert_type": "token_cost",
            "scope": "system",
            "workflow_id": None,
            "config": {"window_minutes": 60, "metric": "usd", "threshold": 10.0},
            "enabled": True,
            "notify_workflow_id": None,
            "state": "ok",
            "renotify_mode": "on_recovery",
            "cooldown_minutes": None,
            "check_interval_seconds": 60,
            "last_triggered_at": None,
            "last_observed_value": None,
            "last_evaluated_at": None,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    async def test_breach_writes_event_and_sets_triggered(self):
        alert = self._alert()
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock()
        observation = SimpleNamespace(
            observed_value=42.0, threshold_value=10.0, breached=True, context={"metric": "usd"}
        )
        now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        with patch(
            f"{MODULE}.observe",
            new=AsyncMock(return_value=(observation, now - timedelta(minutes=60), now)),
        ):
            fired = await evaluator.evaluate_alert(db, alert, now=now)

        self.assertTrue(fired)
        self.assertEqual(alert.state, "triggered")
        self.assertEqual(alert.last_observed_value, 42.0)
        self.assertEqual(alert.last_triggered_at, now)
        db.add.assert_called_once()

    async def test_silent_while_already_triggered(self):
        alert = self._alert(state="triggered", last_triggered_at=datetime(2026, 8, 9, 11, tzinfo=timezone.utc))
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        observation = SimpleNamespace(
            observed_value=42.0, threshold_value=10.0, breached=True, context={}
        )
        now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        with patch(
            f"{MODULE}.observe",
            new=AsyncMock(return_value=(observation, now - timedelta(minutes=60), now)),
        ):
            fired = await evaluator.evaluate_alert(db, alert, now=now)

        self.assertFalse(fired)
        self.assertEqual(alert.state, "triggered")
        db.add.assert_not_called()

    async def test_recovery_resets_to_ok_without_an_event(self):
        alert = self._alert(state="triggered")
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        observation = SimpleNamespace(
            observed_value=1.0, threshold_value=10.0, breached=False, context={}
        )
        now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        with patch(
            f"{MODULE}.observe",
            new=AsyncMock(return_value=(observation, now - timedelta(minutes=60), now)),
        ):
            fired = await evaluator.evaluate_alert(db, alert, now=now)

        self.assertFalse(fired)
        self.assertEqual(alert.state, "ok")
        db.add.assert_not_called()

    async def test_handler_exception_does_not_propagate(self):
        alert = self._alert()
        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        with patch(f"{MODULE}.observe", new=AsyncMock(side_effect=RuntimeError("bad query"))):
            fired = await evaluator.evaluate_alert(db, alert, now=now)
        self.assertFalse(fired)

    async def test_insufficient_data_leaves_state_untouched(self):
        alert = self._alert(state="ok")
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        observation = SimpleNamespace(
            observed_value=None, threshold_value=10.0, breached=False, context={}
        )
        now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        with patch(
            f"{MODULE}.observe",
            new=AsyncMock(return_value=(observation, now - timedelta(minutes=60), now)),
        ):
            fired = await evaluator.evaluate_alert(db, alert, now=now)
        self.assertFalse(fired)
        self.assertEqual(alert.state, "ok")
        self.assertIsNone(alert.last_observed_value)
```

- [ ] **Step 2: Run it** — Expected: FAIL, `AttributeError: ... 'claim_due_alerts'`

- [ ] **Step 3: Add claiming and the evaluation pass to `evaluator.py`**

```python
async def claim_due_alerts(db: AsyncSession, *, now: datetime) -> list[Any]:
    """Atomically claim up to CLAIM_BATCH_SIZE alerts that are due.

    The scheduler loop is leader-gated, but leadership can hand off mid-pass —
    that is exactly what caused the cron duplicate-fire incident. Advancing
    ``next_check_at`` inside the same statement as the selection, under
    ``FOR UPDATE SKIP LOCKED``, means a second worker that briefly believes it is
    leader claims nothing rather than double-firing.
    """
    due_ids = (
        select(Alert.id)
        .where(Alert.enabled.is_(True), Alert.next_check_at <= now)
        .order_by(Alert.next_check_at)
        .limit(CLAIM_BATCH_SIZE)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    result = await db.execute(
        update(Alert)
        .where(Alert.id.in_(due_ids))
        .values(
            next_check_at=now + timedelta(seconds=1) * Alert.check_interval_seconds,
            last_evaluated_at=now,
        )
        .returning(Alert)
        .execution_options(synchronize_session=False)
    )
    claimed = list(result.scalars().all())
    await db.commit()
    return claimed


async def evaluate_alert(db: AsyncSession, alert: Any, *, now: datetime) -> bool:
    """Evaluate one claimed alert. Returns True when it fired.

    Never raises: one broken alert must not stop the batch.
    """
    try:
        observation, window_start, window_end = await observe(db, alert, now=now)
    except Exception:
        logger.exception("Alert %s evaluation failed", getattr(alert, "id", "?"))
        return False

    if observation.observed_value is None:
        # Not enough data to judge. Leave state and last_observed_value alone
        # rather than recording a misleading zero.
        await db.commit()
        return False

    breached = observation.breached
    fired = should_fire(alert, breached=breached, now=now)

    alert.last_observed_value = float(observation.observed_value)
    alert.state = next_state(breached=breached)

    event_id: uuid.UUID | None = None
    if fired:
        event_id = uuid.uuid4()
        alert.last_triggered_at = now
        db.add(
            AlertEvent(
                id=event_id,
                alert_id=alert.id,
                triggered_at=now,
                observed_value=float(observation.observed_value),
                threshold_value=float(observation.threshold_value),
                window_start=window_start,
                window_end=window_end,
                context=observation.context,
                notify_status="queued" if should_dispatch_notify(alert) else "skipped",
            )
        )

    await db.commit()

    # Dispatch only after the event row is committed. The record of the firing
    # must survive even if delivery fails.
    if fired and event_id is not None and should_dispatch_notify(alert):
        workflow_name = None
        if alert.workflow_id:
            wf_result = await db.execute(
                select(Workflow.name).where(Workflow.id == alert.workflow_id)
            )
            workflow_name = wf_result.scalar_one_or_none()
        payload = build_notify_payload(
            alert,
            workflow_name=workflow_name,
            observed_value=float(observation.observed_value),
            threshold_value=float(observation.threshold_value),
            window_start=window_start,
            window_end=window_end,
            context=observation.context,
        )
        dispatch_notify(alert, event_id, payload)

    return fired


async def evaluate_due_alerts() -> int:
    """One full evaluation pass. Returns how many alerts fired."""
    fired = 0
    now = datetime.now(timezone.utc)
    async with async_session_maker() as db:
        claimed = await claim_due_alerts(db, now=now)
        for alert in claimed:
            if await evaluate_alert(db, alert, now=now):
                fired += 1
    return fired
```

> `timedelta(seconds=1) * Alert.check_interval_seconds` is the SQLAlchemy-safe way to multiply an
> interval by a column. If the dialect rejects it, use
> `func.now() + func.make_interval(0, 0, 0, 0, 0, 0, Alert.check_interval_seconds)` instead and
> re-run the claim test.

- [ ] **Step 4: Run the tests**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend && \
  HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_alert_claiming.py tests/test_alert_evaluator.py -v
```

Expected: 22 passed.

- [ ] **Step 5: Export from the package** — add to `backend/app/services/alerts/__init__.py`:

```python
from app.services.alerts.evaluator import evaluate_due_alerts  # noqa: E402,F401
```

- [ ] **Step 6: Checkpoint** — `uv run ruff format app/services/alerts/ tests/test_alert_claiming.py`

---

### Task 14: Event retention

**Files:**
- Create: `backend/app/services/alerts/cleanup.py`
- Test: `backend/tests/test_alert_cleanup.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from app.services.alerts.cleanup import ALERT_EVENT_RETENTION_DAYS, cleanup_old_alert_events


class TestAlertEventCleanup(unittest.IsolatedAsyncioTestCase):
    async def test_retention_is_ninety_days(self):
        self.assertEqual(ALERT_EVENT_RETENTION_DAYS, 90)

    async def test_deletes_and_reports_row_count(self):
        result = MagicMock()
        result.rowcount = 14
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        now = datetime(2026, 8, 9, tzinfo=timezone.utc)
        deleted = await cleanup_old_alert_events(db, now=now)

        self.assertEqual(deleted, 14)
        db.commit.assert_awaited_once()

    async def test_cutoff_is_now_minus_retention(self):
        from app.services.alerts import cleanup as cleanup_module

        captured = {}
        result = MagicMock()
        result.rowcount = 0
        db = MagicMock()

        async def _capture(statement):
            captured["statement"] = statement
            return result

        db.execute = _capture
        db.commit = AsyncMock()
        now = datetime(2026, 8, 9, tzinfo=timezone.utc)
        await cleanup_module.cleanup_old_alert_events(db, now=now)

        rendered = str(captured["statement"].compile(compile_kwargs={"literal_binds": True}))
        expected = (now - timedelta(days=90)).isoformat()
        self.assertIn(expected[:10], rendered)
```

- [ ] **Step 2: Run it** — Expected: FAIL, `ModuleNotFoundError: app.services.alerts.cleanup`

- [ ] **Step 3: Write the cleanup**

```python
"""Retention for alert_events.

One row per firing, on accounts with many alerts, grows without bound. This runs
once a day from the scheduler, following the same shape as the existing portal
session and cron slot claim cleanups.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AlertEvent

logger = logging.getLogger("alert_cleanup")

ALERT_EVENT_RETENTION_DAYS = 90


async def cleanup_old_alert_events(db: AsyncSession, *, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=ALERT_EVENT_RETENTION_DAYS)
    result = await db.execute(delete(AlertEvent).where(AlertEvent.triggered_at < cutoff))
    await db.commit()
    deleted = int(result.rowcount or 0)
    if deleted:
        logger.info("Deleted %s alert events older than %s days", deleted, ALERT_EVENT_RETENTION_DAYS)
    return deleted
```

- [ ] **Step 4: Run the tests** — Expected: 3 passed.

- [ ] **Step 5: Checkpoint** — `uv run ruff format app/services/alerts/cleanup.py tests/test_alert_cleanup.py`

---

## Phase 5 — Scheduler wiring

### Task 15: Hook the evaluator into `CronScheduler`

**Files:**
- Modify: `backend/app/services/cron_scheduler.py:29-77`
- Test: `backend/tests/test_alert_scheduler_integration.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.services.cron_scheduler import CronScheduler

MODULE = "app.services.cron_scheduler"


class TestSchedulerAlertPasses(unittest.IsolatedAsyncioTestCase):
    async def test_check_alerts_delegates_to_the_evaluator(self):
        scheduler = CronScheduler()
        with patch(f"{MODULE}.evaluate_due_alerts", new=AsyncMock(return_value=2)) as evaluate:
            await scheduler._check_alerts()
        evaluate.assert_awaited_once()

    async def test_check_alerts_swallows_errors(self):
        scheduler = CronScheduler()
        with patch(f"{MODULE}.evaluate_due_alerts", new=AsyncMock(side_effect=RuntimeError("db down"))):
            await scheduler._check_alerts()  # must not raise

    async def test_event_cleanup_runs_once_per_day(self):
        scheduler = CronScheduler()
        scheduler._last_alert_event_cleanup_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with patch(f"{MODULE}.cleanup_old_alert_events", new=AsyncMock()) as cleanup:
            await scheduler._check_alert_event_cleanup()
        cleanup.assert_not_awaited()

    async def test_event_cleanup_runs_on_a_new_day(self):
        scheduler = CronScheduler()
        scheduler._last_alert_event_cleanup_date = "2000-01-01"
        with patch(f"{MODULE}.cleanup_old_alert_events", new=AsyncMock(return_value=0)) as cleanup:
            await scheduler._check_alert_event_cleanup()
        cleanup.assert_awaited_once()
```

- [ ] **Step 2: Run it** — Expected: FAIL, `ImportError: cannot import name 'evaluate_due_alerts'` from the scheduler module

- [ ] **Step 3: Wire it in**

Add to the imports at the top of `backend/app/services/cron_scheduler.py`:

```python
from app.services.alerts.cleanup import cleanup_old_alert_events
from app.services.alerts.evaluator import evaluate_due_alerts
```

Add to `CronScheduler.__init__`, alongside the other `_last_*_cleanup_date` fields:

```python
        self._last_alert_event_cleanup_date: str | None = None
```

Add the two passes to `_run_loop`, after `await self._check_and_execute()`:

```python
                await self._check_alerts()
                await self._check_alert_event_cleanup()
```

Add the two methods to the class:

```python
    async def _check_alerts(self) -> None:
        """Evaluate every alert that is due. Never lets one failure stop the loop."""
        try:
            fired = await evaluate_due_alerts()
            if fired:
                logger.info("Alert evaluation pass fired %s alert(s)", fired)
        except Exception as e:
            logger.exception("Error in alert evaluation pass: %s", e)

    async def _check_alert_event_cleanup(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_alert_event_cleanup_date == today:
            return
        self._last_alert_event_cleanup_date = today
        try:
            async with async_session_maker() as db:
                await cleanup_old_alert_events(db)
        except Exception as e:
            logger.exception("Error cleaning up alert events: %s", e)
```

- [ ] **Step 4: Run the tests** — Expected: 4 passed.

- [ ] **Step 5: Checkpoint** — `uv run ruff format app/services/cron_scheduler.py tests/test_alert_scheduler_integration.py`

---

## Phase 6 — Access and API

### Task 16: Access resolution

**Files:**
- Create: `backend/app/services/alert_access.py`
- Test: `backend/tests/test_alert_access.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.alert_access import get_accessible_alert, get_owned_alert


def _result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


class TestAlertAccess(unittest.IsolatedAsyncioTestCase):
    async def test_owner_is_returned_on_the_first_query(self):
        alert = SimpleNamespace(id=uuid.uuid4())
        db = MagicMock()
        db.execute = AsyncMock(return_value=_result(alert))
        found = await get_accessible_alert(db, alert.id, uuid.uuid4())
        self.assertIs(found, alert)
        self.assertEqual(db.execute.await_count, 1)

    async def test_direct_share_is_found_second(self):
        alert = SimpleNamespace(id=uuid.uuid4())
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_result(None), _result(alert)])
        found = await get_accessible_alert(db, alert.id, uuid.uuid4())
        self.assertIs(found, alert)

    async def test_team_share_is_found_third(self):
        alert = SimpleNamespace(id=uuid.uuid4())
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_result(None), _result(None), _result(alert)])
        found = await get_accessible_alert(db, alert.id, uuid.uuid4())
        self.assertIs(found, alert)

    async def test_no_access_returns_none(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_result(None), _result(None), _result(None)])
        found = await get_accessible_alert(db, uuid.uuid4(), uuid.uuid4())
        self.assertIsNone(found)

    async def test_get_owned_alert_only_matches_the_owner(self):
        db = MagicMock()
        db.execute = AsyncMock(return_value=_result(None))
        found = await get_owned_alert(db, uuid.uuid4(), uuid.uuid4())
        self.assertIsNone(found)
        self.assertEqual(db.execute.await_count, 1)
```

- [ ] **Step 2: Run it** — Expected: FAIL, `ModuleNotFoundError: app.services.alert_access`

- [ ] **Step 3: Write the access service**

```python
"""Alert access resolution.

Structurally mirrors ``credential_access.py``: owner, then direct share, then
team membership. Read access comes from any of the three; mutation requires
ownership, which is what ``get_owned_alert`` is for.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alert, AlertShare, AlertTeamShare, TeamMember


async def get_owned_alert(db: AsyncSession, alert_id: UUID, user_id: UUID) -> Alert | None:
    """Only the owner. Use for update, delete, enable/disable, and re-share."""
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.owner_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_accessible_alert(db: AsyncSession, alert_id: UUID, user_id: UUID) -> Alert | None:
    """Owner, direct share, or team share. Use for reads."""
    owned = await get_owned_alert(db, alert_id, user_id)
    if owned is not None:
        return owned

    shared_result = await db.execute(
        select(Alert)
        .join(AlertShare, AlertShare.alert_id == Alert.id)
        .where(Alert.id == alert_id, AlertShare.user_id == user_id)
    )
    shared = shared_result.scalar_one_or_none()
    if shared is not None:
        return shared

    team_result = await db.execute(
        select(Alert)
        .join(AlertTeamShare, AlertTeamShare.alert_id == Alert.id)
        .join(TeamMember, TeamMember.team_id == AlertTeamShare.team_id)
        .where(Alert.id == alert_id, TeamMember.user_id == user_id)
    )
    return team_result.scalar_one_or_none()


def accessible_alerts_filter(user_id: UUID):
    """Reusable WHERE clause for listing: owned OR shared OR team-shared."""
    return Alert.id.in_(
        select(Alert.id)
        .where(Alert.owner_id == user_id)
        .union(
            select(AlertShare.alert_id).where(AlertShare.user_id == user_id),
            select(AlertTeamShare.alert_id)
            .join(TeamMember, TeamMember.team_id == AlertTeamShare.team_id)
            .where(TeamMember.user_id == user_id),
        )
    )
```

- [ ] **Step 4: Run the tests** — Expected: 5 passed.

- [ ] **Step 5: Checkpoint** — `uv run ruff format app/services/alert_access.py tests/test_alert_access.py`

---

### Task 17: CRUD router

**Files:**
- Create: `backend/app/api/alerts.py`
- Modify: `backend/app/main.py` (router registration, near line 353)
- Test: `backend/tests/test_alerts_api.py`

- [ ] **Step 1: Read the reference router first**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && sed -n '1,80p' backend/app/api/global_variables.py
```

Match its import order, `Depends(get_db)` / `Depends(get_current_user)` usage, and `HTTPException` style. Do not invent a new pattern.

- [ ] **Step 2: Write the failing test**

```python
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import alerts as alerts_api
from app.models.alert_schemas import AlertCreate

MODULE = "app.api.alerts"


def _user(user_id=None):
    return SimpleNamespace(id=user_id or uuid.uuid4(), email="a@b.com")


def _alert_row(owner_id, **overrides):
    defaults = {
        "id": uuid.uuid4(),
        "owner_id": owner_id,
        "name": "Invoice failures",
        "description": None,
        "alert_type": "error_threshold",
        "scope": "workflow",
        "workflow_id": uuid.uuid4(),
        "config": {"window_minutes": 10, "threshold_count": 5},
        "enabled": True,
        "notify_workflow_id": None,
        "state": "ok",
        "renotify_mode": "on_recovery",
        "cooldown_minutes": None,
        "check_interval_seconds": 60,
        "last_evaluated_at": None,
        "last_triggered_at": None,
        "last_observed_value": None,
        "created_at": None,
        "updated_at": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestCreateAlert(unittest.IsolatedAsyncioTestCase):
    async def test_create_rejects_a_workflow_the_user_cannot_access(self):
        user = _user()
        payload = AlertCreate(
            name="X",
            alert_type="error_threshold",
            scope="workflow",
            workflow_id=uuid.uuid4(),
            config={"window_minutes": 10, "threshold_count": 5},
        )
        db = MagicMock()
        with patch(f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[])):
            with self.assertRaises(HTTPException) as ctx:
                await alerts_api.create_alert(payload, db=db, current_user=user)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_create_persists_and_returns_the_condition_summary(self):
        user = _user()
        workflow_id = uuid.uuid4()
        payload = AlertCreate(
            name="Invoice failures",
            alert_type="error_threshold",
            scope="workflow",
            workflow_id=workflow_id,
            config={"window_minutes": 10, "threshold_count": 5},
        )
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: "Invoice Sync"))
        with patch(f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[workflow_id])):
            response = await alerts_api.create_alert(payload, db=db, current_user=user)
        self.assertEqual(response.condition_summary, "5+ errors in 10m")
        db.add.assert_called_once()


class TestMutationRequiresOwnership(unittest.IsolatedAsyncioTestCase):
    async def test_delete_by_non_owner_is_404(self):
        db = MagicMock()
        with patch(f"{MODULE}.get_owned_alert", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await alerts_api.delete_alert(uuid.uuid4(), db=db, current_user=_user())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_update_by_non_owner_is_404(self):
        from app.models.alert_schemas import AlertUpdate

        db = MagicMock()
        with patch(f"{MODULE}.get_owned_alert", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await alerts_api.update_alert(
                    uuid.uuid4(), AlertUpdate(name="new"), db=db, current_user=_user()
                )
        self.assertEqual(ctx.exception.status_code, 404)


class TestGetAlert(unittest.IsolatedAsyncioTestCase):
    async def test_shared_viewer_gets_is_owner_false(self):
        owner_id = uuid.uuid4()
        viewer = _user()
        row = _alert_row(owner_id)
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        with patch(f"{MODULE}.get_accessible_alert", new=AsyncMock(return_value=row)):
            response = await alerts_api.get_alert(row.id, db=db, current_user=viewer)
        self.assertFalse(response.is_owner)
```

- [ ] **Step 3: Run it** — Expected: FAIL, `ModuleNotFoundError: app.api.alerts`

- [ ] **Step 4: Write the router**

Create `backend/app/api/alerts.py`. Implement, in this order:

1. `_to_response(alert, *, current_user_id, workflow_name=None, notify_workflow_name=None) -> AlertResponse` — the single place that builds `AlertResponse`, filling `condition_summary` via `describe_condition` and `is_owner` via `alert.owner_id == current_user_id`. Every endpoint returns through this helper; do not build `AlertResponse` inline anywhere else.
2. `async def _assert_workflow_access(db, workflow_id, user_id) -> None` — raises `HTTPException(404, "Workflow not found")` when `workflow_id` is not in `await get_accessible_workflow_ids(db, user_id)`. Called for both `workflow_id` and `notify_workflow_id` on create and update.
3. `GET /` `list_alerts(enabled, alert_type, workflow_id, state, limit=50, offset=0)` — filters with `accessible_alerts_filter(current_user.id)`, returns `AlertListResponse`.
4. `POST /` `create_alert(payload: AlertCreate, ...)` — validates workflow access, inserts, returns `_to_response`.
5. `GET /{alert_id}` `get_alert` — `get_accessible_alert`, 404 when None.
6. `PATCH /{alert_id}` `update_alert(alert_id, payload: AlertUpdate, ...)` — `get_owned_alert`, 404 when None; merge the set fields onto the row, then re-validate the merged result by constructing `AlertCreate(**merged)` so a partial update cannot produce an invalid combination (for example switching to `renotify_mode="cooldown"` without `cooldown_minutes`); on `ValidationError` raise `HTTPException(422, str(e))`. Reset `next_check_at` to `now()` when `enabled` flips to True so a re-enabled alert is checked immediately.
7. `DELETE /{alert_id}` `delete_alert` — `get_owned_alert`, 404 when None, delete, 204.

Registration in `backend/app/main.py`, next to the other routers:

```python
app.include_router(alerts.router, prefix="/api/alerts", tags=["Alerts"])
```

and add `alerts` to the `from app.api import (...)` block at the top.

- [ ] **Step 5: Run the tests** — Expected: 5 passed.

- [ ] **Step 6: Verify the app still boots**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend && HEYM_OTEL_ENABLED=false \
  SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "from app.main import app; print(len(app.routes))"
```

Expected: a number, no traceback.

- [ ] **Step 7: Checkpoint** — `uv run ruff format app/api/alerts.py app/main.py tests/test_alerts_api.py && uv run ruff check app/api/alerts.py`

---

### Task 18: Events, preview, acknowledge, shares

**Files:**
- Modify: `backend/app/api/alerts.py`
- Test: append to `backend/tests/test_alerts_api.py`

- [ ] **Step 1: Write the failing test**

```python
class TestPreview(unittest.IsolatedAsyncioTestCase):
    async def test_preview_backtests_and_reports_fire_count(self):
        from app.models.alert_schemas import AlertPreviewRequest

        workflow_id = uuid.uuid4()
        payload = AlertPreviewRequest(
            alert_type="error_threshold",
            scope="workflow",
            workflow_id=workflow_id,
            config={"window_minutes": 60, "threshold_count": 5},
            lookback_hours=3,
        )
        db = MagicMock()
        observations = [
            SimpleNamespace(observed_value=9.0, threshold_value=5.0, breached=True, context={}),
            SimpleNamespace(observed_value=1.0, threshold_value=5.0, breached=False, context={}),
            SimpleNamespace(observed_value=7.0, threshold_value=5.0, breached=True, context={}),
        ]
        with patch(f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[workflow_id])):
            with patch(
                f"{MODULE}.observe_config",
                new=AsyncMock(side_effect=observations),
            ):
                response = await alerts_api.preview_alert(payload, db=db, current_user=_user())
        self.assertEqual(response.backtest_fire_count, 2)
        self.assertEqual(response.backtest_max_observed, 9.0)
        self.assertTrue(response.would_fire_now)


class TestAcknowledge(unittest.IsolatedAsyncioTestCase):
    async def test_acknowledge_requires_access_to_the_parent_alert(self):
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        with self.assertRaises(HTTPException) as ctx:
            await alerts_api.acknowledge_alert_event(uuid.uuid4(), db=db, current_user=_user())
        self.assertEqual(ctx.exception.status_code, 404)
```

- [ ] **Step 2: Run it** — Expected: FAIL, `AttributeError: ... 'preview_alert'`

- [ ] **Step 3: Implement the endpoints**

Add to `backend/app/api/alerts.py`:

1. `async def observe_config(db, *, owner_id, alert_type, scope, workflow_id, config, window_end) -> AlertObservation` — builds an `AlertEvaluationContext` and calls the registered handler, without needing a persisted `Alert` row. This is what makes an unsaved config testable. Reuse `resolve_scope_workflow_ids`-equivalent logic by calling `get_accessible_workflow_ids` for system scope.
2. `POST /preview` `preview_alert(payload: AlertPreviewRequest, ...)` — calls `observe_config` once at `now` for `would_fire_now`, then walks `lookback_hours` in `window_minutes` steps calling `observe_config` at each step end, counting breaches into `backtest_fire_count` and tracking `backtest_max_observed`. Cap the number of backtest steps at 200 and widen the step size if the range would exceed it, so a 1-minute window over 168 hours cannot issue 10,080 queries.
3. `POST /{alert_id}/test` — `get_accessible_alert`, then `observe` from the evaluator; returns `AlertPreviewResponse` with `lookback_hours` echoed as `0` and both backtest fields zero. Writes nothing.
4. `GET /{alert_id}/events` — `get_accessible_alert` first, then paginated events ordered `triggered_at DESC`.
5. `GET /events` — events across every accessible alert, `unacknowledged: bool = False` filter, returns `AlertEventListResponse` with the `unacknowledged` count populated for the nav badge.
6. `POST /events/{event_id}/acknowledge` — join to the parent alert and re-check access via `get_accessible_alert`; 404 when not accessible; sets `acknowledged_at = now()`.
7. Share endpoints — copy the structure of the credential share endpoints in `backend/app/api/credentials.py` exactly, substituting `AlertShare` / `AlertTeamShare` and gating every one on `get_owned_alert`.

- [ ] **Step 4: Run the tests** — Expected: 7 passed.

- [ ] **Step 5: Checkpoint** — `uv run ruff format app/api/alerts.py tests/test_alerts_api.py`

---

## Phase 7 — AI draft

### Task 19: Natural language → draft

**Files:**
- Create: `backend/app/services/alerts/ai_draft.py`
- Modify: `backend/app/api/alerts.py` (add `POST /ai-draft`)
- Test: `backend/tests/test_alert_ai_draft.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import unittest
import uuid

from app.services.alerts.ai_draft import build_draft_system_prompt, parse_draft_response


class TestParseDraftResponse(unittest.TestCase):
    def test_valid_json_becomes_a_draft(self):
        workflow_id = uuid.uuid4()
        raw = json.dumps(
            {
                "name": "Invoice sync failures",
                "alert_type": "error_threshold",
                "scope": "workflow",
                "workflow_id": str(workflow_id),
                "config": {"window_minutes": 10, "threshold_count": 5},
                "renotify_mode": "on_recovery",
                "filled_fields": ["name", "alert_type", "config"],
            }
        )
        draft, clarification = parse_draft_response(raw)
        self.assertIsNotNone(draft)
        self.assertIsNone(clarification)
        self.assertEqual(draft.config["threshold_count"], 5)

    def test_fenced_json_is_unwrapped(self):
        raw = '```json\n{"name":"X","alert_type":"execution_count","scope":"system","config":{"window_minutes":60,"threshold_count":100}}\n```'
        draft, clarification = parse_draft_response(raw)
        self.assertIsNotNone(draft)
        self.assertEqual(draft.alert_type, "execution_count")

    def test_prose_returns_clarification_not_a_draft(self):
        draft, clarification = parse_draft_response(
            "Which workflow did you mean? You have three with 'invoice' in the name."
        )
        self.assertIsNone(draft)
        self.assertIn("Which workflow", clarification)

    def test_invalid_config_for_the_type_returns_clarification(self):
        raw = json.dumps(
            {
                "name": "X",
                "alert_type": "token_cost",
                "scope": "system",
                "config": {"window_minutes": 60},
            }
        )
        draft, clarification = parse_draft_response(raw)
        self.assertIsNone(draft)
        self.assertIsNotNone(clarification)

    def test_workflow_scope_without_a_workflow_id_returns_clarification(self):
        raw = json.dumps(
            {
                "name": "X",
                "alert_type": "error_threshold",
                "scope": "workflow",
                "config": {"window_minutes": 10, "threshold_count": 5},
            }
        )
        draft, clarification = parse_draft_response(raw)
        self.assertIsNone(draft)
        self.assertIsNotNone(clarification)


class TestDraftSystemPrompt(unittest.TestCase):
    def test_prompt_lists_the_available_workflows(self):
        wf_id = uuid.uuid4()
        prompt = build_draft_system_prompt([(wf_id, "Invoice Sync")])
        self.assertIn("Invoice Sync", prompt)
        self.assertIn(str(wf_id), prompt)

    def test_prompt_names_all_four_alert_types(self):
        prompt = build_draft_system_prompt([])
        for alert_type in ("error_threshold", "workflow_duration", "token_cost", "execution_count"):
            self.assertIn(alert_type, prompt)
```

- [ ] **Step 2: Run it** — Expected: FAIL, `ModuleNotFoundError: app.services.alerts.ai_draft`

- [ ] **Step 3: Write the module**

```python
"""Natural language -> AlertDraft.

Structured JSON rather than tool calling: there is exactly one output shape and
no multi-turn negotiation, so tool calling would add a round trip for nothing.

The parsed result goes through the same Pydantic validation the create endpoint
uses, so an AI draft can never produce a config the API would reject. When the
model produces prose instead of JSON, that prose is surfaced as a clarification
and the wizard stays on step 1 rather than prefilling garbage.
"""

from __future__ import annotations

import json
import re
import uuid

from pydantic import ValidationError

from app.models.alert_schemas import AlertDraft, parse_alert_config

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def build_draft_system_prompt(workflows: list[tuple[uuid.UUID, str]]) -> str:
    listing = "\n".join(f"- {name} (id: {wf_id})" for wf_id, name in workflows) or "- (none)"
    return f"""You turn a plain-English monitoring request into a Heym alert definition.

Reply with ONE JSON object and nothing else. No prose, no code fence, no explanation.

Alert types, and the config each one requires:

1. error_threshold - fires when failed runs in a window reach a count.
   config: {{"window_minutes": int, "threshold_count": int}}
2. workflow_duration - fires when run duration in a window reaches a ceiling.
   config: {{"window_minutes": int, "threshold_ms": number,
             "aggregation": "max"|"avg"|"p95", "min_samples": int}}
3. token_cost - fires when LLM spend in a window reaches a ceiling.
   config: {{"window_minutes": int, "metric": "total_tokens"|"usd", "threshold": number}}
4. execution_count - fires when run count in a window reaches a ceiling.
   config: {{"window_minutes": int, "threshold_count": int}}

Top-level fields:
  name          short, specific, human readable
  description   optional one line
  alert_type    one of the four above
  scope         "workflow" for one workflow, "system" for all of the user's workflows
  workflow_id   REQUIRED when scope is "workflow", omitted when scope is "system"
  config        matching the type above
  renotify_mode "on_recovery" (notify once until it recovers) or "cooldown"
  cooldown_minutes  REQUIRED when renotify_mode is "cooldown"
  filled_fields list of the field names you inferred rather than were told

Workflows this user can pick from:
{listing}

If the request names a workflow you cannot match to exactly one entry above, or is
too vague to pick an alert type, reply in plain prose asking the one question that
would resolve it. Do not guess a workflow_id.
"""


def parse_draft_response(raw: str) -> tuple[AlertDraft | None, str | None]:
    """Return (draft, clarification). Exactly one of the two is not None."""
    text = (raw or "").strip()
    if not text:
        return None, "The model returned an empty response."

    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    if not text.startswith("{"):
        return None, raw.strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, raw.strip()

    if not isinstance(payload, dict):
        return None, raw.strip()

    try:
        draft = AlertDraft(**payload)
    except ValidationError as exc:
        return None, f"Could not build a valid alert from that request: {exc.errors()[0]['msg']}"

    if draft.scope == "workflow" and draft.workflow_id is None:
        return None, "Which workflow should this alert watch?"
    if draft.scope == "system" and draft.workflow_id is not None:
        draft.workflow_id = None
    if draft.renotify_mode == "cooldown" and draft.cooldown_minutes is None:
        return None, "How often should this keep notifying while the problem persists?"

    try:
        parse_alert_config(draft.alert_type, draft.config)
    except (ValidationError, ValueError) as exc:
        return None, f"The suggested condition was not valid: {exc}"

    return draft, None
```

- [ ] **Step 4: Run the tests** — Expected: 7 passed.

- [ ] **Step 5: Add the endpoint**

In `backend/app/api/alerts.py`, add `POST /ai-draft`:

- Resolve the credential with `get_accessible_credential`; 404 when None.
- `decrypt_config` → `get_openai_client(credential.type, config)`, matching the pattern in `backend/app/api/chats.py:_run_chat_turn`.
- Load `(id, name)` for every workflow in `get_accessible_workflow_ids`, pass to `build_draft_system_prompt`.
- One non-streaming completion with the system prompt and the user's `prompt`.
- Return `AlertDraftResponse(**dict(zip(("draft", "clarification"), parse_draft_response(text))))`.
- Verify any returned `workflow_id` and `notify_workflow_id` are in the accessible set; drop them to `None` and append a clarification if not. **The model must not be able to hand back an id the user cannot access.**

- [ ] **Step 6: Checkpoint** — `uv run ruff format app/services/alerts/ai_draft.py app/api/alerts.py tests/test_alert_ai_draft.py`

---

## Phase 8 — Chat integration

### Task 20: Three chat tools

**Files:**
- Modify: `backend/app/api/ai_assistant.py` (`DASHBOARD_CHAT_TOOLS` list ending near line 780, `DASHBOARD_CHAT_SYSTEM_PROMPT` near line 395, and the tool handler dispatch)
- Test: `backend/tests/test_alert_chat_tools.py`

- [ ] **Step 1: Locate the handler dispatch**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && grep -n "get_analytics_stats\|get_active_executions" backend/app/api/ai_assistant.py
```

The tool schema appears in `DASHBOARD_CHAT_TOOLS`; the handler appears in the dispatch block further down. Add the three new tools in both places, following `get_analytics_stats` as the template.

- [ ] **Step 2: Write the failing test**

```python
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.ai_assistant import DASHBOARD_CHAT_TOOLS, handle_get_alert_events, handle_list_alerts

MODULE = "app.api.ai_assistant"


def _tool_names():
    return {t["function"]["name"] for t in DASHBOARD_CHAT_TOOLS}


class TestAlertToolsRegistered(unittest.TestCase):
    def test_all_three_tools_are_declared(self):
        for name in ("list_alerts", "get_alert_detail", "get_alert_events"):
            self.assertIn(name, _tool_names())

    def test_get_alert_events_accepts_a_time_range(self):
        tool = next(
            t for t in DASHBOARD_CHAT_TOOLS if t["function"]["name"] == "get_alert_events"
        )
        props = tool["function"]["parameters"]["properties"]
        self.assertIn("time_range", props)
        self.assertEqual(props["time_range"]["enum"], ["24h", "7d", "30d", "all"])


class TestListAlertsHandler(unittest.IsolatedAsyncioTestCase):
    async def test_returns_condition_summary_and_state(self):
        row = SimpleNamespace(
            id=uuid.uuid4(),
            name="Invoice failures",
            alert_type="error_threshold",
            scope="workflow",
            workflow_id=uuid.uuid4(),
            config={"window_minutes": 10, "threshold_count": 5},
            enabled=True,
            state="triggered",
            last_triggered_at=None,
            last_observed_value=12.0,
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)

        payload = await handle_list_alerts(db, SimpleNamespace(id=uuid.uuid4()), {})

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["alerts"][0]["condition"], "5+ errors in 10m")
        self.assertEqual(payload["alerts"][0]["state"], "triggered")


class TestGetAlertEventsHandler(unittest.IsolatedAsyncioTestCase):
    async def test_returns_observed_versus_threshold_and_context(self):
        event = SimpleNamespace(
            id=uuid.uuid4(),
            alert_id=uuid.uuid4(),
            triggered_at=None,
            observed_value=12.0,
            threshold_value=5.0,
            window_start=None,
            window_end=None,
            context={"error_count": 12, "sample_errors": ["boom"]},
        )
        result = MagicMock()
        result.all.return_value = [(event, "Invoice failures", "error_threshold")]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)

        payload = await handle_get_alert_events(db, SimpleNamespace(id=uuid.uuid4()), {})

        self.assertEqual(payload["count"], 1)
        entry = payload["events"][0]
        self.assertEqual(entry["observed_value"], 12.0)
        self.assertEqual(entry["threshold_value"], 5.0)
        self.assertEqual(entry["context"]["error_count"], 12)
```

- [ ] **Step 3: Run it** — Expected: FAIL, `ImportError: cannot import name 'handle_list_alerts'`

- [ ] **Step 4: Add the tool schemas**

Append to `DASHBOARD_CHAT_TOOLS`:

```python
    {
        "type": "function",
        "function": {
            "name": "list_alerts",
            "description": "List the user's alerts (threshold rules over a time window on errors, duration, LLM cost, or execution count). Use when the user asks what alerts exist, which alerts are configured for a workflow, which alerts are currently firing, or whether an alert is set up for something (e.g. 'what alerts do I have?', 'hangi alertlerim var?', 'is there an alert on the invoice workflow?'). Returns each alert's condition, current state, and last observed value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {
                        "type": "string",
                        "description": "Optional UUID to list only alerts watching that workflow.",
                    },
                    "alert_type": {
                        "type": "string",
                        "enum": ["error_threshold", "workflow_duration", "token_cost", "execution_count"],
                        "description": "Optional filter by alert type.",
                    },
                    "state": {
                        "type": "string",
                        "enum": ["ok", "triggered"],
                        "description": "Optional filter: 'triggered' returns only alerts currently firing.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_alert_detail",
            "description": "Get the full definition of one alert: its condition, window, threshold, scope, notify workflow, sharing, and how many times it fired in the last 7 days. Use after list_alerts when the user asks about a specific alert's setup (e.g. 'what is the threshold on that one?', 'how is the cost alert configured?').",
            "parameters": {
                "type": "object",
                "properties": {
                    "alert_id": {"type": "string", "description": "UUID of the alert."}
                },
                "required": ["alert_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_alert_events",
            "description": "List times alerts actually fired, with the reason. Use whenever the user asks WHY or WHEN an alert triggered (e.g. 'why did the cost alert fire?', 'when did this last trigger?', 'bu alert neden tetiklendi?', 'show me recent alert firings'). Returns the exact window that was evaluated, the observed value versus the threshold, and the contributing detail: failing execution ids and error messages for error alerts, per-model spend for cost alerts, per-trigger-source counts for execution-count alerts. Always cite the observed value and window when explaining a firing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "alert_id": {
                        "type": "string",
                        "description": "Optional UUID to scope to one alert. Omit for firings across all alerts.",
                    },
                    "time_range": {
                        "type": "string",
                        "enum": ["24h", "7d", "30d", "all"],
                        "description": "Time window to look back over. Default 7d.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max firings to return (default 20, max 50).",
                    },
                },
                "required": [],
            },
        },
    },
```

- [ ] **Step 5: Add the handlers**

Implement `handle_list_alerts`, `handle_get_alert_detail`, and `handle_get_alert_events` in `ai_assistant.py`, next to the existing analytics handlers. Each takes `(db, user, args)` and returns a plain dict.

- All three scope their query with `accessible_alerts_filter(user.id)` from `app.services.alert_access`. **Never query `Alert` unfiltered in a chat handler.**
- `handle_list_alerts` builds each entry's `condition` with `describe_condition(alert.alert_type, alert.config)`.
- `handle_get_alert_events` joins `AlertEvent` to `Alert`, applies the time range, orders `triggered_at DESC`, caps `limit` at 50, and returns the stored `context` verbatim — it is a snapshot of the window at firing time and must not be recomputed, because the window has passed and a recomputation can give a different answer.

Register all three in the tool dispatch block alongside `get_analytics_stats`.

- [ ] **Step 6: Add the system prompt rule**

Append to `DASHBOARD_CHAT_SYSTEM_PROMPT`, continuing the numbering after rule 14:

```
15. When the user asks about alerts — what alerts exist, whether something is being monitored, which alerts are firing, or why/when an alert triggered — use list_alerts, get_alert_detail, and get_alert_events. For a "why did it fire" question always call get_alert_events and quote the actual observed value, the threshold, and the time window from the event, plus the contributing detail in its context (failing executions, per-model spend, or trigger source). Do not guess a reason. Respond in the user's language.
```

- [ ] **Step 7: Run the tests** — Expected: 5 passed.

- [ ] **Step 8: Run the existing chat tool tests to check for regressions**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend && \
  HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_ai_assistant_tool_summaries.py tests/test_ai_assistant_board_tools.py tests/test_ai_assistant_active_execution_tool.py -v
```

Expected: all pass. `test_ai_assistant_tool_summaries.py` may assert a tool count — update it if so.

- [ ] **Step 9: Checkpoint** — `uv run ruff format app/api/ai_assistant.py tests/test_alert_chat_tools.py`

---

### Task 21: Full backend suite

- [ ] **Step 1: Run everything**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && \
  HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh
```

Expected: ruff format clean, ruff check clean, full backend suite green.

- [ ] **Step 2: Fix any failures before starting the frontend.** Do not carry a red backend into Phase 9.

---

## Phase 9 — Frontend

### Task 22: Types and API client

**Files:**
- Create: `frontend/src/types/alerts.ts`, `frontend/src/services/alerts.ts`

- [ ] **Step 1: Read the reference service**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && cat frontend/src/services/globalVariables.ts 2>/dev/null || ls frontend/src/services/
```

Match its axios instance import, error handling, and export style.

- [ ] **Step 2: Write `frontend/src/types/alerts.ts`**

```typescript
export type AlertType =
  | "error_threshold"
  | "workflow_duration"
  | "token_cost"
  | "execution_count";
export type AlertScope = "workflow" | "system";
export type AlertState = "ok" | "triggered";
export type RenotifyMode = "on_recovery" | "cooldown";
export type DurationAggregation = "max" | "avg" | "p95";
export type CostMetric = "total_tokens" | "usd";

export interface ErrorThresholdConfig {
  window_minutes: number;
  threshold_count: number;
}

export interface WorkflowDurationConfig {
  window_minutes: number;
  threshold_ms: number;
  aggregation: DurationAggregation;
  min_samples: number;
}

export interface TokenCostConfig {
  window_minutes: number;
  metric: CostMetric;
  threshold: number;
}

export interface ExecutionCountConfig {
  window_minutes: number;
  threshold_count: number;
}

export type AlertConfig =
  | ErrorThresholdConfig
  | WorkflowDurationConfig
  | TokenCostConfig
  | ExecutionCountConfig;

export interface Alert {
  id: string;
  owner_id: string;
  name: string;
  description: string | null;
  alert_type: AlertType;
  scope: AlertScope;
  workflow_id: string | null;
  workflow_name: string | null;
  config: AlertConfig;
  condition_summary: string;
  enabled: boolean;
  notify_workflow_id: string | null;
  notify_workflow_name: string | null;
  state: AlertState;
  renotify_mode: RenotifyMode;
  cooldown_minutes: number | null;
  check_interval_seconds: number;
  last_evaluated_at: string | null;
  last_triggered_at: string | null;
  last_observed_value: number | null;
  is_owner: boolean;
  created_at: string;
  updated_at: string;
}

export interface AlertEvent {
  id: string;
  alert_id: string;
  alert_name: string;
  alert_type: AlertType;
  triggered_at: string;
  observed_value: number;
  threshold_value: number;
  window_start: string;
  window_end: string;
  context: Record<string, unknown>;
  acknowledged_at: string | null;
  notify_execution_id: string | null;
  notify_status: string | null;
}

export interface AlertPreview {
  observed_value: number;
  threshold_value: number;
  would_fire_now: boolean;
  window_start: string;
  window_end: string;
  context: Record<string, unknown>;
  backtest_fire_count: number;
  backtest_max_observed: number;
  lookback_hours: number;
}

export interface AlertDraft {
  name: string;
  description: string | null;
  alert_type: AlertType;
  scope: AlertScope;
  workflow_id: string | null;
  config: AlertConfig;
  renotify_mode: RenotifyMode;
  cooldown_minutes: number | null;
  notify_workflow_id: string | null;
  filled_fields: string[];
}

export interface AlertPayload {
  name: string;
  description?: string | null;
  alert_type: AlertType;
  scope: AlertScope;
  workflow_id?: string | null;
  config: AlertConfig;
  enabled?: boolean;
  notify_workflow_id?: string | null;
  renotify_mode: RenotifyMode;
  cooldown_minutes?: number | null;
  check_interval_seconds?: number;
}
```

- [ ] **Step 3: Write `frontend/src/services/alerts.ts`**

One exported async function per endpoint from Task 17 and Task 18, each with an explicit return type (required by strict mode). Follow the existing service file's axios usage exactly.

- [ ] **Step 4: Typecheck**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend && bun run typecheck
```

Expected: no errors.

---

### Task 23: Pinia store

**Files:**
- Create: `frontend/src/stores/alerts.ts`

- [ ] **Step 1: Write the store**

`defineStore("alerts", ...)` with the composition API, exposing: `alerts`, `events`, `unacknowledgedCount`, `loading`, `error`, and actions `fetchAlerts`, `fetchEvents`, `createAlert`, `updateAlert`, `deleteAlert`, `toggleEnabled`, `acknowledgeEvent`, `previewCondition`, `draftFromPrompt`. Export the typed store interface.

- [ ] **Step 2: Typecheck** — `bun run typecheck`. Expected: no errors.

---

### Task 24: Tab registration

**Files:**
- Modify: `frontend/src/components/Layout/DashboardNav.vue:29-70`
- Modify: `frontend/src/views/DashboardView.vue:97-190` and the tab render block near line 2140
- Modify: `frontend/src/router/index.ts:20-40`

- [ ] **Step 1: Router** — add `"alerts"` to `DASHBOARD_TAB_PATHS`.

- [ ] **Step 2: Nav** — add `BellRing` to the `lucide-vue-next` import, add `{ id: "alerts", label: "Alerts", icon: BellRing }` to the `tabs` array after `traces`, and add `tabParam === "alerts" ||` to the `activeTab` computed.

- [ ] **Step 3: DashboardView** — add `"alerts"` to `validTabs`, add `| "alerts"` to the `TabKey` union, and render `<AlertsTab v-else-if="activeTab === 'alerts'" />` in the tab block. Add `"alerts"` to the palette tab handling in `handleTabSelectFromPalette`.

- [ ] **Step 4: Verify the nav badge hook** — `AlertsTab` mounts and calls `fetchEvents({ unacknowledged: true })`; the nav reads `unacknowledgedCount` from the store.

- [ ] **Step 5: Lint and typecheck**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend && bun run lint && bun run typecheck
```

Expected: both clean.

---

### Task 25: Listing components

**Files:**
- Create: `frontend/src/components/Alerts/AlertsTab.vue`, `AlertList.vue`, `AlertCard.vue`, `AlertEventsPanel.vue`, `AlertShareDialog.vue`

- [ ] **Step 1: `AlertsTab.vue`** — a shell only: header with a "New alert" button, `AlertList`, `AlertEventsPanel`, and the wizard dialog mount. **Under 150 lines.** No alert-type-specific markup here.

- [ ] **Step 2: `AlertCard.vue`** — name, type badge, scope (workflow name or "All workflows"), `condition_summary`, state pill (`ok` / `triggered`), `last_observed_value` as "currently at N", enable/disable toggle, and edit / share / delete actions hidden when `is_owner` is false.

- [ ] **Step 3: `AlertEventsPanel.vue`** — reverse-chronological firings, each showing observed vs threshold, the window, the notify status, and an acknowledge action.

- [ ] **Step 4: `AlertShareDialog.vue`** — copy the credential share dialog's structure.

- [ ] **Step 5: Lint and typecheck** — `bun run lint && bun run typecheck`. Expected: clean. Each file must be under 300 lines per AGENTS.md.

---

### Task 26: Wizard

**Files:**
- Create: `frontend/src/components/Alerts/wizard/AlertWizardDialog.vue`, `AlertAiPrompt.vue`, `StepType.vue`, `StepScope.vue`, `StepCondition.vue`, `StepResponse.vue`, `StepReview.vue`
- Create: `frontend/src/components/Alerts/wizard/fields/ErrorThresholdFields.vue`, `DurationFields.vue`, `CostFields.vue`, `ExecutionCountFields.vue`

- [ ] **Step 1: `AlertWizardDialog.vue`** — holds the draft state, the current step index, Next/Back, and the save call. Steps are rendered by index; no step owns navigation.

- [ ] **Step 2: `StepType.vue`** — `AlertAiPrompt` at the top, then four selectable cards. Each card carries a one-line description of what the type answers.

- [ ] **Step 3: `StepScope.vue`** — "This workflow" with a workflow picker, or "All my workflows".

- [ ] **Step 4: `StepCondition.vue`** — a window control (number + unit selector, normalized to minutes) plus `<component :is="fieldComponentForType">`. **Use a lookup map from `alert_type` to component, not a `v-if` chain** — this is the frontend half of the registry rule, and a `v-if` chain here rots the same way a `node_type` branch rots in the executor.

- [ ] **Step 5: `StepResponse.vue`** — optional notify workflow picker, and the re-notify radio: "Notify once, until it recovers" (default) or "Keep notifying every N minutes" with a `cooldown_minutes` input revealed by the second option.

- [ ] **Step 6: `StepReview.vue`** — full summary plus the backtest. On mount, call `previewCondition` and render: *"Over the last 24 hours this condition would have fired N times. Highest observed value: X."* Include a lookback selector (24h / 7d). When `backtest_fire_count` is large, show a warning that the threshold may be too low — this is the whole point of the step.

- [ ] **Step 7: AI prefill** — `AlertAiPrompt` emits the draft; the dialog applies it to every step's state, records `filled_fields`, jumps to the Review step, and marks AI-filled fields. When the response carries a `clarification` instead, show it inline and stay on step 1.

- [ ] **Step 8: Lint and typecheck** — `bun run lint && bun run typecheck`. Expected: clean.

- [ ] **Step 9: Manual verification** — start the stack with `./run.sh`, open `/?tab=alerts`, and walk the wizard once per alert type. Confirm: the backtest returns a number, saving creates a listing row, the AI prompt prefills, editing loads existing values, and delete removes the row. There are no automated frontend tests for this repo, so this walkthrough is the verification.

---

## Phase 10 — Documentation

### Task 27: Product docs

**Files:**
- Create: `frontend/src/docs/content/tabs/alerts-tab.md`
- Modify: `frontend/src/docs/manifest.ts:140-162`, `frontend/src/docs/content/reference/features.md`, `frontend/src/docs/content/tabs/chat-tab.md`, `frontend/src/docs/content/tabs/analytics-tab.md`

- [ ] **Step 1: Invoke the `heym-documentation` skill.** AGENTS.md requires it for medium/large features. Do not hand-write these docs without it.

- [ ] **Step 2: Write `alerts-tab.md`** covering: the four types and what each answers; window-based evaluation and why it is not per-event; the five wizard steps; the Review backtest; AI drafting; `on_recovery` versus `cooldown`; notify workflows and the payload shape; sharing; and the 90-day event retention.

- [ ] **Step 3: Register in `manifest.ts`** — add `{ slug: "alerts-tab", title: "Alerts" }` to the `tabs.items` array, after `traces-tab`.

- [ ] **Step 4: `features.md`** — add an Alerts section in the tab area with the same cross-linking style as neighbouring sections, and add Alerts to the tab summary list.

- [ ] **Step 5: `chat-tab.md`** — document the three alert questions Chat can now answer.

- [ ] **Step 6: `analytics-tab.md`** — one cross-link to Alerts, since that is where someone looking at an error-rate chart goes next.

- [ ] **Step 7: Verify the docs build** — `cd frontend && bun run typecheck && bun run build`. Expected: clean. A missing manifest slug fails the build, not just a test.

---

### Task 28: README and AGENTS.md

**Files:**
- Modify: `README.md:175-300` and the Observability section near line 551
- Modify: `AGENTS.md`

- [ ] **Step 1: Verify the competitor claims before writing the comparison row.**

Check each competitor's official docs for **user-defined threshold alerts over a time window on cost and duration** — not per-execution failure notification, which all three have. Use `brave_search_api` and `website_loader`. Record the date checked.

- [ ] **Step 2: Add the comparison row** to the Why Heym table in `README.md`, after the `LLM token cost tracking (USD)` row:

```
| Metric alerts (errors, duration, cost, run count) | ✅ | limited²⁵ | limited²⁵ | limited²⁵ |
```

Add footnote 25 below the table in the established style: what Heym does, then what each competitor's official docs say, with the date checked. Adjust `limited` / `partial` / `❌` per competitor based on Step 1 — **do not write the marks before doing the research.**

- [ ] **Step 3: Add an Alerts subsection** under `## 🔍 Observability`, alongside LLM Traces and LLM Cost Tracking. Three to five sentences: the four types, window-based evaluation, the AI wizard, notify workflows, and Chat querying.

- [ ] **Step 4: Add Alerts to Key Capabilities** and to the Platform Overview tab list.

- [ ] **Step 5: Add the AGENTS.md rule.** Insert after the "WorkflowExecutor modularity" section:

```markdown
### Alert type modularity
`backend/app/services/alerts/evaluator.py` owns claiming, the fire/recover state machine, event
packaging, notify dispatch, and error containment. Metric computation for each alert type belongs
under `backend/app/services/alerts/types/`, one module per alert type, registered in
`backend/app/services/alerts/registry.py`.

- Do not add `alert_type` branches to the evaluator. A new alert type is one handler module, one
  registry entry, one config model in `backend/app/models/alert_schemas.py`, and focused tests.
- Handlers compute a metric over a window and return an `AlertObservation`. They must not write
  events, dispatch notifications, mutate alert state, or re-derive scope — `workflow_ids` arrives
  already resolved on the context.
- Cost metrics must resolve USD through `app/services/llm_pricing.py`. An alert that disagrees with
  the Traces tab about the same window is worse than no alert.
- The frontend mirrors this: `StepCondition.vue` selects per-type field components from a lookup
  map, not a `v-if` chain, and node-type-style branching does not belong in `AlertsTab.vue`.
- When adding a new alert type, also update the Alerts tab doc, `reference/features.md`, and the
  chat tool descriptions in `backend/app/api/ai_assistant.py`.
```

- [ ] **Step 6: Final full verification**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && \
  HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh
```

Expected: green.

- [ ] **Step 7: Confirm nothing is committed**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && git status --short | head -40
```

Expected: a list of modified and untracked files, no new commits. `git log --oneline -1` must still show `52f6acc7`.

---

## Verification summary

| Check | Command |
|---|---|
| Backend suite + lint + format | `HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh` |
| Migration head | `cd backend && uv run alembic heads` → `108_add_alerts (head)` |
| Frontend lint | `cd frontend && bun run lint` |
| Frontend types | `cd frontend && bun run typecheck` |
| Frontend build | `cd frontend && bun run build` |
| Manual wizard walkthrough | `./run.sh` → `/?tab=alerts` |
| Nothing committed | `git log --oneline -1` unchanged |

**New backend test files:** `test_alert_schemas.py`, `test_alert_metrics.py`, `test_alert_registry.py`, `test_alert_evaluator.py`, `test_alert_claiming.py`, `test_alert_cleanup.py`, `test_alert_scheduler_integration.py`, `test_alert_access.py`, `test_alerts_api.py`, `test_alert_ai_draft.py`, `test_alert_chat_tools.py`.
