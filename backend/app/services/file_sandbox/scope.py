"""Which Drive files a workflow run may open in the file sandbox.

Chat opens every Drive file its user reaches. A workflow run does not: its Code
node Files, its agents and its Slack Send files open only files that came into the
workflow, uploaded through its File Upload trigger, written by its own nodes
(``workflow_id`` on the Drive row) or fetched by its Drive node's Get, and in a run
Chat starts, the sample file Chat handed to the trigger. A Drive id typed into an
input or assembled into a prompt opens nothing else, so a workflow cannot be used to
read its actor's Drive without a visible Drive step.
"""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace


def as_uuid(value: object) -> uuid.UUID | None:
    """A UUID from a UUID or its text, else None."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def file_refs(value: object) -> list[str]:
    """Drive file refs from a resolved value: an id, ids separated by commas or lines, a
    list, or objects with an ``id`` (a Drive file, ``$Upload.file``). Order kept, no repeats."""
    if isinstance(value, dict):
        value = value.get("id") or value.get("file_id") or ""
    if isinstance(value, list):
        ids: list[str] = []
        for item in value:
            ids.extend(file_refs(item))
        return list(dict.fromkeys(ids))
    text = str(value or "")
    return list(dict.fromkeys(part.strip() for part in re.split(r"[,\n]", text) if part.strip()))


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

    def including_files(self, file_ids: Iterable[object]) -> RunFileScope:
        """This scope plus these files, for files a node of the run brought in."""
        added = {uuid_ for uuid_ in map(as_uuid, file_ids) if uuid_ is not None}
        if added <= self.file_ids:
            return self
        return replace(self, file_ids=self.file_ids | added)


_GRANT_LOCK = threading.Lock()


def grant_run_files(executor: object, file_ids: Iterable[object]) -> None:
    """Let the run's later nodes open these files (a Drive node fetched them).

    Parallel branches share the executor, so reading and replacing its scope hold one lock.
    """
    with _GRANT_LOCK:
        current = getattr(executor, "file_scope", None) or RunFileScope()
        executor.file_scope = current.including_files(file_ids)
