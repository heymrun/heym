"""Leader-gated recovery of workflow executions interrupted by a restart."""

import logging
from typing import Literal

logger = logging.getLogger(__name__)

# Retry once: the original run is attempt 0; the first recovery makes it 1.
MAX_RECOVERY_ATTEMPTS = 1

RecoveryAction = Literal["rerun", "skipped", "failed"]


def decide_recovery_action(
    *, attempt: int, auto_recover: bool, workflow_exists: bool
) -> RecoveryAction:
    """Decide what to do with a claimed orphan. `attempt` is post-claim-increment."""
    if not workflow_exists:
        return "failed"
    if attempt > MAX_RECOVERY_ATTEMPTS:
        return "failed"
    if not auto_recover:
        return "skipped"
    return "rerun"
