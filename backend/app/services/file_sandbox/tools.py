"""The file tools a model calls, shared by Chat turns and the Agent node.

``FileToolbox.call`` is synchronous: the Agent node runs it on an executor
thread, Chat through ``asyncio.to_thread``. It never raises into the model loop;
failures come back as ``{"error": ...}``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.services.file_sandbox.executor import build_payload, run_in_sandbox
from app.services.file_sandbox.limits import (
    LIST_FILES_DEFAULT_LIMIT,
    LIST_FILES_MAX_LIMIT,
    MAX_CODE_CHARS,
    MAX_FILES_PER_CALL,
    MAX_WORKSPACE_BYTES,
)
from app.services.file_sandbox.manifest import (
    DriveFileRef,
    FileAccessError,
    list_accessible_files,
    resolve_files,
    still_accessible,
)
from app.services.file_sandbox.scope import RunFileScope
from app.services.file_sandbox.workspace import CollectedFile, FileWorkspace, WorkspaceQuotaError

logger = logging.getLogger(__name__)

LIST_FILES_TOOL = "list_files"
INSPECT_FILE_TOOL = "inspect_file"
RUN_PYTHON_TOOL = "run_python"
CLEAR_WORKSPACE_TOOL = "clear_workspace"
FILE_TOOL_NAMES = frozenset(
    {LIST_FILES_TOOL, INSPECT_FILE_TOOL, RUN_PYTHON_TOOL, CLEAR_WORKSPACE_TOOL}
)

_PARAMETERS: dict[str, dict[str, Any]] = {
    LIST_FILES_TOOL: {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Part of a file name to filter by."},
            "limit": {"type": "integer", "description": "Files per page (default 50, max 200)."},
            "offset": {"type": "integer", "description": "Files to skip, for the next page."},
        },
        "required": [],
    },
    INSPECT_FILE_TOOL: {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "Drive file id or exact file name."},
            "sheet": {"type": "string", "description": "Spreadsheets: one sheet to detail."},
            "pages": {"type": "string", "description": 'PDFs: pages to sample, e.g. "1-3,7".'},
            "full": {
                "type": "boolean",
                "description": "CSV: scan every row for exact counts and null ratios (slower).",
            },
        },
        "required": ["file"],
    },
    RUN_PYTHON_TOOL: {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python 3 source to run."},
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Drive file ids or exact names to mount read-only for this call.",
            },
        },
        "required": ["code"],
    },
    CLEAR_WORKSPACE_TOOL: {"type": "object", "properties": {}, "required": []},
}

_DESCRIPTIONS = {
    LIST_FILES_TOOL: (
        "List Heym Drive files you can open (your own and those shared with your teams), "
        "newest first. Metadata only: id, name, mime, size, created_at, source."
    ),
    INSPECT_FILE_TOOL: (
        "First step for any file: its type, metadata and structure (PDF pages, text layer and "
        "language, scanned pages read with OCR; spreadsheet sheets, title rows, the real header row, columns and types, "
        "or label/value cells; CSV encoding, delimiter and columns; "
        "DOCX headings and tables; JSON shape) with a short sample. Reads only what the "
        "summary needs."
    ),
    RUN_PYTHON_TOOL: (
        "Run Python 3 in an isolated sandbox with no network. pandas, openpyxl, xlrd, "
        "pdfplumber, pypdf, python-docx and langdetect are installed; `heym_ocr.pdf_to_text` "
        "reads scanned PDF pages. Files in `files` are "
        "mounted read-only: `import heym_files; heym_files.path('<name or id>')`. /work keeps "
        "files for this session; files written to heym_files.out_dir() are saved to Heym "
        "Drive and returned as links. stdout is capped at 20,000 characters, so print only "
        "what you need."
    ),
    CLEAR_WORKSPACE_TOOL: (
        "Delete this conversation's file workspace: mounted copies and everything under /work. "
        "Drive files are not touched. Only when the user asks to clean up."
    ),
}


def tool_names(*, include_clear: bool) -> list[str]:
    names = [LIST_FILES_TOOL, INSPECT_FILE_TOOL, RUN_PYTHON_TOOL]
    return names + [CLEAR_WORKSPACE_TOOL] if include_clear else names


def tool_schemas(*, include_clear: bool) -> list[dict[str, Any]]:
    """OpenAI function-tool schemas for a Chat turn."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": _DESCRIPTIONS[name],
                "parameters": _PARAMETERS[name],
            },
        }
        for name in tool_names(include_clear=include_clear)
    ]


def agent_tool_defs(toolbox: FileToolbox) -> list[dict[str, Any]]:
    """Agent node tool definitions, dispatched by ``_source == "file_sandbox"``."""
    return [
        {
            "name": name,
            "description": _DESCRIPTIONS[name],
            "parameters": _PARAMETERS[name],
            "_source": "file_sandbox",
            "_file_toolbox": toolbox,
        }
        for name in tool_names(include_clear=False)
    ]


def _string_list(raw: object) -> list[str]:
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item or "").strip()]
    return []


class FileToolbox:
    """The file tools of one workspace, acting as one actor."""

    def __init__(
        self,
        workspace: FileWorkspace,
        actor_id: uuid.UUID,
        *,
        source_label: str,
        workflow_id: uuid.UUID | None = None,
        include_clear: bool = False,
        on_mount: Callable[[list[DriveFileRef]], None] | None = None,
        input_files: list[DriveFileRef] | None = None,
        scope: RunFileScope | None = None,
    ) -> None:
        self.workspace = workspace
        self.actor_id = actor_id
        self.source_label = source_label
        self.workflow_id = workflow_id
        self.include_clear = include_clear
        self.on_mount = on_mount
        # Files the agent's input carried; named in its instructions so it opens them first.
        self.input_files = list(input_files or [])
        # A workflow run's toolbox lists and opens only these files; Chat's has no scope.
        self.scope = scope

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Run one tool; errors are returned to the model, never raised."""
        try:
            if name == LIST_FILES_TOOL:
                return self._list(args)
            if name == INSPECT_FILE_TOOL:
                return self._inspect(args)
            if name == RUN_PYTHON_TOOL:
                return self._run(args)
            if name == CLEAR_WORKSPACE_TOOL and self.include_clear:
                self.workspace.delete()
                return {"cleared": True}
            return {"error": f"Unknown file tool: {name}"}
        except (FileAccessError, WorkspaceQuotaError, TimeoutError, ValueError) as exc:
            return {"error": str(exc)}
        except OSError as exc:
            logger.warning("File sandbox call %s hit a file error: %s", name, exc)
            return {"error": f"The file could not be prepared: {exc.strerror or exc}"}
        except RuntimeError as exc:
            logger.warning("File sandbox call %s failed: %s", name, exc)
            return {"error": str(exc)}

    def _session(self) -> Session:
        from app.db.session import SessionLocal

        return SessionLocal()

    def _list(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            limit = int(args.get("limit") or LIST_FILES_DEFAULT_LIMIT)
            offset = int(args.get("offset") or 0)
        except (TypeError, ValueError):
            limit, offset = LIST_FILES_DEFAULT_LIMIT, 0
        limit = max(1, min(limit, LIST_FILES_MAX_LIMIT))
        with self._session() as db:
            refs, total = list_accessible_files(
                db,
                self.actor_id,
                query=str(args.get("query") or ""),
                limit=limit,
                offset=offset,
                scope=self.scope,
            )
        return {
            "files": [ref.public() for ref in refs],
            "total": total,
            "limit": limit,
            "offset": max(0, offset),
        }

    def _prepare(self, requested: list[str]) -> tuple[list[dict], list[str]]:
        """Resolve, drop copies the actor lost, copy the rest in. Returns entries, pruned."""
        if len(requested) > MAX_FILES_PER_CALL:
            raise ValueError(f"Mount at most {MAX_FILES_PER_CALL} files in one call.")
        with self._session() as db:
            refs = resolve_files(db, self.actor_id, requested, scope=self.scope)
            keep = still_accessible(db, self.actor_id, self.workspace.input_ids())
        self.workspace.ensure()
        pruned = self.workspace.prune(keep)
        known = self.workspace.input_ids()
        entries = self.workspace.add_inputs(refs)
        mounted = [ref for ref in refs if ref.id not in known]
        if mounted and self.on_mount is not None:
            self.on_mount(mounted)
        return entries, pruned

    def _inspect(self, args: dict[str, Any]) -> dict[str, Any]:
        target = str(args.get("file") or "").strip()
        if not target:
            raise ValueError("Pass `file`: a Drive file id or exact file name.")
        options = {key: args[key] for key in ("sheet", "pages", "full") if args.get(key)}
        with self.workspace.lock:
            entries, pruned = self._prepare([target])
            entry = entries[0]
            outcome = run_in_sandbox(
                self.workspace,
                build_payload(
                    "inspect",
                    target={"path": entry["path"], "name": entry["name"], "mime": entry["mime"]},
                    options=options,
                ),
            )
            self.workspace.touch()
        if not outcome.success:
            return {"error": outcome.error or "Inspection failed.", "file": entry}
        result: dict[str, Any] = {
            "untrusted_file_content": True,
            "file": entry,
            "summary": outcome.result,
        }
        if pruned:
            result["removed_inputs"] = pruned
        return result

    def _run(self, args: dict[str, Any]) -> dict[str, Any]:
        code = str(args.get("code") or "")
        if not code.strip():
            raise ValueError("Pass `code`: the Python source to run.")
        if len(code) > MAX_CODE_CHARS:
            raise ValueError(f"Code is limited to {MAX_CODE_CHARS} characters.")
        with self.workspace.lock:
            _entries, pruned = self._prepare(_string_list(args.get("files")))
            outcome = run_in_sandbox(self.workspace, build_payload("python", code=code))
            collected, rejected = self.workspace.collect_outputs()
            self.workspace.touch()
            used = self.workspace.usage_bytes()
        generated, store_rejected = store_outputs(
            collected,
            owner_id=self.actor_id,
            workflow_id=self.workflow_id,
            source_label=self.source_label,
        )
        result: dict[str, Any] = {
            "untrusted_file_content": True,
            "ok": outcome.success,
            "stdout": outcome.stdout,
            "inputs": [{"name": e["name"], "path": e["path"]} for e in self.workspace.inputs()],
        }
        if outcome.error:
            result["error"] = outcome.error
        if outcome.stdout_dropped_chars:
            result["stdout_truncated"] = (
                f"{outcome.stdout_dropped_chars} more characters were not shown. Print less, "
                "or write the full result to /work or heym_files.out_dir()."
            )
        if generated:
            result["generated_files"] = generated
        if rejected or store_rejected:
            result["rejected_outputs"] = rejected + store_rejected
        if pruned:
            result["removed_inputs"] = pruned
        if used > MAX_WORKSPACE_BYTES:
            result["workspace_warning"] = (
                "The workspace is over 2 GB. Delete scratch files under /work before the next "
                "call, or clear the workspace."
            )
        return result


def store_outputs(
    collected: list[CollectedFile],
    *,
    owner_id: uuid.UUID,
    workflow_id: uuid.UUID | None,
    source_label: str,
) -> tuple[list[dict], list[str]]:
    """Save collected outputs to the owner's Drive; the share token never leaves here."""
    if not collected:
        return [], []
    from app.db.session import SessionLocal
    from app.services.file_storage import store_file_sync

    stored: list[dict] = []
    rejected: list[str] = []
    with SessionLocal() as db:
        for item in collected:
            try:
                row, _token = store_file_sync(
                    db,
                    owner_id=owner_id,
                    file_bytes=item.data,
                    filename=item.name,
                    mime_type=item.mime,
                    workflow_id=workflow_id,
                    source_node_label=source_label,
                    context="File analysis",
                )
            except ValueError as exc:
                rejected.append(f"{item.name}: {exc}")
                continue
            stored.append(
                {
                    "id": str(row.id),
                    "name": row.filename,
                    "mime": row.mime_type,
                    "size": row.size_bytes,
                    "download_path": f"/api/files/{row.id}/download",
                }
            )
        db.commit()
    return stored, rejected
