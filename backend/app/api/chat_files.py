"""The file tools of one chat turn, on the conversation's workspace.

Offered on every persisted chat turn (the Chat tab, Heym Work's Chat, MCP
``heym_chat``, A2A). Each Drive file mounted for the first time in the
conversation is audited here, in the API layer.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from app.db.models import User
from app.services.audit_log import audit
from app.services.chat_build_mode import BuildToolOutcome
from app.services.chat_progress import ToolProgress
from app.services.file_sandbox.instructions import chat_file_instructions
from app.services.file_sandbox.manifest import DriveFileRef
from app.services.file_sandbox.tools import (
    CLEAR_WORKSPACE_TOOL,
    FILE_TOOL_NAMES,
    INSPECT_FILE_TOOL,
    LIST_FILES_TOOL,
    RUN_PYTHON_TOOL,
    FileToolbox,
    tool_schemas,
)
from app.services.file_sandbox.workspace import FileWorkspace

_MAX_DISPLAY_CODE_CHARS = 4000


class ChatFileTools:
    """``list_files``, ``inspect_file``, ``run_python`` and ``clear_workspace`` for a turn."""

    def __init__(self, *, user: User, conversation_id: uuid.UUID) -> None:
        self.user = user
        self.conversation_id = conversation_id
        self.workspace = FileWorkspace.for_chat(user.id, conversation_id)
        self.toolbox = FileToolbox(
            self.workspace,
            user.id,
            source_label="Chat",
            include_clear=True,
            on_mount=self._audit_mounts,
        )

    @staticmethod
    def instructions() -> str:
        """The static rules block; identical on every turn so it caches."""
        return "\n\n" + chat_file_instructions()

    def workspace_block(self) -> str:
        """What this conversation's workspace holds, for the dynamic end of the prompt."""
        if not self.workspace.exists():
            return ""
        inputs = self.workspace.inputs()
        scratch = self.workspace.work_summary()
        if not inputs and not scratch:
            return ""
        lines = ["", "", "## This conversation's file workspace"]
        for entry in inputs:
            lines.append(
                f"- input: {entry.get('name')} (id {entry.get('id')}) at {entry.get('path')}"
            )
        for entry in scratch:
            lines.append(f"- scratch: {entry['path']} ({entry['size']} bytes)")
        return "\n".join(lines)

    @staticmethod
    def schemas() -> list[dict[str, Any]]:
        return tool_schemas(include_clear=True)

    @staticmethod
    def handles(name: str) -> bool:
        return name in FILE_TOOL_NAMES

    @staticmethod
    def step_label(name: str, args: dict[str, Any] | None = None) -> str:
        args = args or {}
        if name == LIST_FILES_TOOL:
            return "Listing Drive files..."
        if name == INSPECT_FILE_TOOL:
            return f'Inspecting "{args.get("file") or "file"}"...'
        if name == RUN_PYTHON_TOOL:
            count = len(args.get("files") or [])
            return (
                f"Running Python on {count} file{'s' if count != 1 else ''}..."
                if count
                else ("Running Python...")
            )
        return "Clearing the file workspace..."

    @staticmethod
    def display_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Arguments for the step row and the stored message, with long code clipped."""
        if name != RUN_PYTHON_TOOL:
            return args
        code = str(args.get("code") or "")
        if len(code) > _MAX_DISPLAY_CODE_CHARS:
            code = code[:_MAX_DISPLAY_CODE_CHARS] + "\n# ... clipped"
        return {"code": code, "files": args.get("files") or []}

    def _audit_mounts(self, refs: list[DriveFileRef]) -> None:
        for ref in refs:
            audit(
                action="drive.chat_mount",
                actor=self.user,
                target_type="file",
                target_id=ref.id,
                target_name=ref.name,
                conversation_id=str(self.conversation_id),
                shared=ref.shared,
            )

    async def call(
        self, name: str, args: dict[str, Any], *, progress: ToolProgress | None = None
    ) -> BuildToolOutcome:
        """Run one file tool off the event loop."""
        result = await asyncio.to_thread(self.toolbox.call, name, args)
        return BuildToolOutcome(
            result=json.dumps(result, default=str),
            summary=_summary(name, result),
            status="error" if result.get("error") and not result.get("ok") else "success",
        )


def _summary(name: str, result: dict[str, Any]) -> str:
    error = str(result.get("error") or "")
    if error and not result.get("ok"):
        return f"Error: {error.strip().splitlines()[-1][:200]}"
    if name == LIST_FILES_TOOL:
        return f"{result.get('total', 0)} Drive files"
    if name == INSPECT_FILE_TOOL:
        summary = result.get("summary") or {}
        file = result.get("file") or {}
        return f"{file.get('name')} · {summary.get('kind', 'file')}"
    if name == CLEAR_WORKSPACE_TOOL:
        return "Workspace cleared"
    generated = result.get("generated_files") or []
    if generated:
        return f"Done · {len(generated)} file{'s' if len(generated) != 1 else ''} saved to Drive"
    if error:
        return f"Finished with an error: {error.strip().splitlines()[-1][:200]}"
    return "Done"
