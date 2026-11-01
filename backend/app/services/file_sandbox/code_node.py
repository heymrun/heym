"""Code node runs that read Drive files (``codeFiles``).

The files are resolved for the run's actor and mounted read-only at ``/input``;
``/work`` is scratch for this one execution and ``/work/out`` comes back as Drive
files. Everything else matches a plain Code node run: ``main(params)``, the
dependency install phase and the network toggle.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.services.code_python_executor import (
    _DOCKER_START_FAILURE_CODES,
    _install_dependencies,
    _parse_envelope,
    _runner_source,
    docker_available,
    hardening_args,
    resolve_mount,
    resolve_sandbox_image,
    run_sandbox_container,
)
from app.services.file_sandbox import executor as sandbox
from app.services.file_sandbox.limits import CALL_TIMEOUT_SECONDS, CPU_LIMIT, MEMORY_LIMIT, TMPFS
from app.services.file_sandbox.manifest import resolve_files
from app.services.file_sandbox.scope import RunFileScope
from app.services.file_sandbox.tools import store_outputs
from app.services.file_sandbox.workspace import INPUT_MOUNT, WORK_MOUNT, FileWorkspace

_DEPS_PATH = f"{WORK_MOUNT}/.deps"


@dataclass
class CodeFilesResult:
    """Outcome of a Code node run with files."""

    result: object = None
    logs: str = ""
    install_tool: str = "none"
    install_log: str = ""
    files: list[dict] = field(default_factory=list)
    rejected_files: list[str] = field(default_factory=list)


def execute_code_with_files(
    *,
    code: str,
    requirements: str,
    params: dict[str, Any],
    allow_network: bool,
    file_refs: list[str],
    actor_id: uuid.UUID,
    scope: RunFileScope,
    workflow_id: uuid.UUID | None,
    source_label: str,
) -> CodeFilesResult:
    """Run Code node Python with the run's Drive files mounted.

    Only files ``scope`` covers open: uploaded to this workflow, written by its
    nodes, or handed to it by Chat. Any other Drive file fails like a missing one.

    Raises:
        FileAccessError: a file is missing, outside the run's scope, or unreachable.
        RuntimeError: no Docker, no image, install failed, or the sandbox never started.
        TimeoutError: install or execution ran past its limit.
        ValueError: the code raised or returned something unreadable.
    """
    if not docker_available():
        raise RuntimeError(
            "The Code node requires Docker to run Python in an isolated sandbox, but no "
            "working Docker daemon is reachable."
        )
    image = resolve_sandbox_image()
    if image is None:
        raise RuntimeError(
            "The Code node sandbox image could not be resolved. Set HEYM_PYTHON_TOOL_IMAGE "
            "to the backend image."
        )

    from app.db.session import SessionLocal

    workspace = FileWorkspace.for_run(actor_id)
    try:
        with SessionLocal() as db:
            refs = resolve_files(db, actor_id, file_refs, scope=scope)
        workspace.ensure()
        entries = workspace.add_inputs(refs)
        run_params = dict(params)
        run_params.setdefault("files", entries)

        install_tool, install_log = "none", ""
        if requirements.strip():
            install_tool, install_log = _install_dependencies(
                image, workspace.work_dir, requirements
            )

        name = f"heym-code-{uuid.uuid4().hex}"
        cmd = hardening_args(
            name, "bridge" if allow_network else "none", TMPFS, memory=MEMORY_LIMIT, cpus=CPU_LIMIT
        )
        cmd.extend(resolve_mount(workspace.in_dir, INPUT_MOUNT, readonly=True))
        cmd.extend(resolve_mount(workspace.work_dir, WORK_MOUNT, readonly=False))
        if requirements.strip():
            cmd.extend(["--env", f"PYTHONPATH={_DEPS_PATH}"])
        cmd.extend(
            ["--workdir", WORK_MOUNT, "--entrypoint", "python", image, "-c", sandbox._BOOTSTRAP]
        )
        payload = sandbox.build_payload(
            "code_node", code_runner=_runner_source(), code=code, params=run_params
        )
        with sandbox._containers:
            returncode, stdout, stderr = run_sandbox_container(
                cmd, json.dumps(payload, default=str), CALL_TIMEOUT_SECONDS, name, "execution"
            )
        if returncode in _DOCKER_START_FAILURE_CODES:
            raise RuntimeError(
                f"Code node sandbox failed to start (docker exit {returncode}): "
                f"{stderr.strip()[:500]}"
            )
        result, logs = _parse_envelope(stdout)
        collected, rejected = workspace.collect_outputs()
        stored, store_rejected = store_outputs(
            collected, owner_id=actor_id, workflow_id=workflow_id, source_label=source_label
        )
        return CodeFilesResult(
            result=result,
            logs=logs,
            install_tool=install_tool,
            install_log=install_log,
            files=stored,
            rejected_files=rejected + store_rejected,
        )
    finally:
        workspace.delete()
