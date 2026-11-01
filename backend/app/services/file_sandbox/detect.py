"""Turn file analysis on for an Agent node whose input carries a run's file.

An agent's input is upstream data that can come from outside Heym, so it is only
mined for UUID-shaped strings. Each candidate is resolved again for the actor
through the one Drive access rule and the run's ``RunFileScope`` (files uploaded
to this workflow or written by its nodes); only files of a supported type whose
content is on this instance's storage count. The toolbox then lists and opens
those files and nothing else. Anything else leaves the agent unchanged.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import PurePosixPath

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.file_sandbox.manifest import DriveFileRef, accessible_files_by_id
from app.services.file_sandbox.scope import RunFileScope, as_uuid
from app.services.file_sandbox.tools import FileToolbox
from app.services.file_sandbox.workspace import FileWorkspace

logger = logging.getLogger(__name__)

# Mirrors DRIVE_EXTENSIONS in frontend/src/composables/useFileAttachment.ts.
SUPPORTED_EXTENSIONS = frozenset(
    {".pdf", ".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".docx", ".json", ".jsonl", ".txt", ".md"}
)
_SUPPORTED_MIMES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel.sheet.macroenabled.12",
        "application/vnd.ms-excel",
        "text/csv",
        "text/tab-separated-values",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/json",
        "application/x-ndjson",
        "application/jsonl",
        "text/plain",
        "text/markdown",
    }
)

_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
_MAX_DEPTH = 8
_MAX_CANDIDATES = 50
_MAX_SCAN_CHARS = 500_000


def is_analyzable(name: str | None, mime: str | None) -> bool:
    """Whether the sandbox reads this file type (extension first, then mime)."""
    suffix = PurePosixPath(name or "").suffix.lower()
    if suffix:
        return suffix in SUPPORTED_EXTENSIONS
    return (mime or "").split(";")[0].strip().lower() in _SUPPORTED_MIMES


def file_id_candidates(*values: object) -> set[uuid.UUID]:
    """UUID-shaped strings found in ``values``, bounded in depth, size and count."""
    found: set[uuid.UUID] = set()
    budget = [_MAX_SCAN_CHARS]

    def _walk(value: object, depth: int) -> None:
        if depth > _MAX_DEPTH or budget[0] <= 0 or len(found) >= _MAX_CANDIDATES:
            return
        if isinstance(value, str):
            text = value[: budget[0]]
            budget[0] -= len(text)
            for match in _UUID_RE.finditer(text):
                found.add(uuid.UUID(match.group(0)))
                if len(found) >= _MAX_CANDIDATES:
                    return
        elif isinstance(value, uuid.UUID):
            found.add(value)
        elif isinstance(value, dict):
            for item in value.values():
                _walk(item, depth + 1)
        elif isinstance(value, (list, tuple)):
            for item in value:
                _walk(item, depth + 1)

    for value in values:
        _walk(value, 0)
    return found


def analyzable_input_files(
    db: Session, user_id: uuid.UUID, candidates: set[uuid.UUID], scope: RunFileScope
) -> list[DriveFileRef]:
    """Candidates the run may open: reachable, in scope, a supported type, stored here."""
    return [
        ref
        for ref in accessible_files_by_id(db, user_id, candidates, scope=scope)
        if is_analyzable(ref.name, ref.mime)
        and ref.storage_path is not None
        and ref.storage_path.is_file()
    ]


def agent_input_toolbox(
    values: tuple[object, ...],
    actor_id: uuid.UUID | None,
    *,
    scope: RunFileScope,
    source_label: str,
    workflow_id: object,
) -> FileToolbox | None:
    """A toolbox limited to the run files the agent's input carries, else None."""
    if actor_id is None:
        return None
    candidates = file_id_candidates(*values)
    if not candidates:
        return None
    from app.db.session import SessionLocal

    try:
        with SessionLocal() as db:
            files = analyzable_input_files(db, actor_id, candidates, scope)
    except SQLAlchemyError as exc:
        logger.warning("File analysis lookup failed; the agent runs without file tools: %s", exc)
        return None
    if not files:
        return None
    return FileToolbox(
        FileWorkspace.for_run(actor_id),
        actor_id,
        source_label=source_label,
        workflow_id=as_uuid(workflow_id),
        input_files=files,
        scope=RunFileScope(file_ids=frozenset(ref.id for ref in files)),
    )
