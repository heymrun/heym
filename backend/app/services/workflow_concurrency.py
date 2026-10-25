"""Per-workflow concurrency limit. Filled in by the following tasks."""

import uuid


async def promote(workflow_id: uuid.UUID) -> int:
    """Start held runs that now fit under the limit."""
    return 0
