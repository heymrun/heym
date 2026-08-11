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
    #: Each workflow that contributed to the reading, mapped to its own share of it
    #: (error count, run count, slowest ms, spend). Not the scope that was searched.
    #: The evaluator resolves the names and emits one ``workflows`` array, which is
    #: why handlers do not also put a per-workflow split in ``context``.
    contributing_workflows: dict[uuid.UUID, float] = field(default_factory=dict)

    @property
    def breached(self) -> bool:
        if self.observed_value is None:
            return False
        return self.observed_value >= self.threshold_value
