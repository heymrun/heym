"""Alert evaluation package.

Metric computation lives in ``types/``, one module per alert type, behind
``registry.py``. Claiming, state transitions, event packaging, and notify
dispatch live in ``evaluator.py``. Do not add alert-type branches to the
evaluator - add a handler module and a registry entry.
"""

from app.services.alerts.cleanup import cleanup_old_alert_events  # noqa: E402,F401
from app.services.alerts.evaluator import evaluate_due_alerts  # noqa: E402,F401
