"""Which Drive files a workflow run may open in the file sandbox.

Chat opens every Drive file its user reaches. A workflow run does not: its Code
node Files and its agents open only files that came into the workflow, uploaded
through its File Upload trigger or written by its own nodes (``workflow_id`` on
the Drive row), and in a run Chat starts, the sample file Chat handed to the
trigger. A Drive id typed into an input or assembled into a prompt opens nothing
else, so a workflow cannot be used to read its actor's Drive.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace


def as_uuid(value: object) -> uuid.UUID | None:
    """A UUID from a UUID or its text, else None."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


@dataclass(frozen=True)
class RunFileScope:
    """Files of these workflows, plus these file ids. Empty opens nothing."""

    workflow_ids: frozenset[uuid.UUID] = frozenset()
    file_ids: frozenset[uuid.UUID] = frozenset()

    def including_workflow(self, workflow_id: object) -> RunFileScope:
        """This scope plus one more workflow, for the run or sub-workflow it now covers."""
        workflow_uuid = as_uuid(workflow_id)
        if workflow_uuid is None or workflow_uuid in self.workflow_ids:
            return self
        return replace(self, workflow_ids=self.workflow_ids | {workflow_uuid})
