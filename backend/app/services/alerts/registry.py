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
