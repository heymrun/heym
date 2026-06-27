"""Public, capability-token upload endpoint that triggers a workflow run.

A workflow whose entry node is ``fileUploadTrigger`` mints a single-use upload
slot (see :mod:`app.services.file_intake_service`). The agent uploads a file via
multipart to ``/api/file-intake/u/{token}``; this endpoint validates the slot,
stores the file, runs the workflow synchronously, and returns its output.
"""

import asyncio
import copy
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import ExecutionHistory, FileUploadSlot, User, Workflow
from app.db.session import get_db
from app.services import file_intake_service, file_storage
from app.services.hitl_service import build_public_base_url
from app.services.upload_limits import read_upload_file_limited
from app.services.workflow_executor import execute_workflow

router = APIRouter(prefix="/file-intake", tags=["file-intake"])


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _attach_initial_inputs(nodes: list[dict], node_id: str, initial: dict) -> list[dict]:
    cloned = copy.deepcopy(nodes)
    for node in cloned:
        if node.get("id") == node_id:
            node.setdefault("data", {})["_initial_inputs"] = initial
    return cloned


@router.get("/slots/{slot_id}")
async def get_slot_status(
    slot_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Poll a mint slot so the canvas can advance once the file is uploaded."""
    slot = await db.get(FileUploadSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Upload slot not found")

    workflow = await db.get(Workflow, slot.workflow_id)
    if workflow is None or workflow.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Upload slot not found")

    result: dict = {"status": slot.status, "run_id": slot.run_id, "run": None}
    if slot.status == "consumed" and slot.run_id:
        try:
            history = await db.get(ExecutionHistory, uuid.UUID(slot.run_id))
        except (ValueError, TypeError):
            history = None
        if history is not None:
            result["run"] = {
                "status": history.status,
                "outputs": history.outputs,
                "node_results": history.node_results,
                "execution_time_ms": history.execution_time_ms,
                "execution_history_id": str(history.id),
            }
    return result


@router.post("/u/{token}")
async def upload_to_slot(
    token: str,
    request: Request,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> dict:
    ip = _client_ip(request)
    ua = request.headers.get("user-agent")
    token_hash = file_intake_service.hash_token(token)

    slot = (
        await db.execute(select(FileUploadSlot).where(FileUploadSlot.token_hash == token_hash))
    ).scalar_one_or_none()

    if slot is None:
        await file_intake_service.write_audit(
            db, event="rejected_unknown_token", client_ip=ip, user_agent=ua
        )
        await db.commit()
        raise HTTPException(status_code=404, detail="Invalid or unknown upload link")

    async def reject(
        event: str,
        code: int,
        detail: str,
        *,
        fname: str | None = None,
        fsize: int | None = None,
        fmime: str | None = None,
    ) -> None:
        await file_intake_service.write_audit(
            db,
            event=event,
            slot_id=slot.id,
            workflow_id=slot.workflow_id,
            client_ip=ip,
            user_agent=ua,
            file_name=fname,
            file_size=fsize,
            mime=fmime,
        )
        await db.commit()
        raise HTTPException(status_code=code, detail=detail)

    if slot.status != "pending":
        await reject("rejected_consumed", status.HTTP_409_CONFLICT, "Upload link already used")

    now = datetime.now(timezone.utc)
    expires = slot.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        await reject("rejected_expired", status.HTTP_410_GONE, "Upload link expired")

    # Cap the read at the smaller of the slot limit and the platform-wide limit so
    # file_storage.store_file (which enforces settings.file_max_size_mb) never 500s.
    from app.services.upload_limits import configured_upload_limit_bytes

    effective_max = min(slot.max_size_bytes, configured_upload_limit_bytes())
    try:
        file_bytes = await read_upload_file_limited(file, max_bytes=effective_max)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_413_CONTENT_TOO_LARGE:
            await reject(
                "rejected_oversize",
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"File exceeds {effective_max // (1024 * 1024)} MB limit",
                fname=file.filename,
                fmime=file.content_type,
            )
        raise

    mime = file.content_type or "application/octet-stream"
    if not file_intake_service.is_mime_allowed(slot.allowed_mime, mime, file.filename or ""):
        await reject(
            "rejected_mime",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "File type not allowed",
            fname=file.filename,
            fsize=len(file_bytes),
            fmime=mime,
        )

    # Single-use: only the winner of the atomic flip proceeds.
    if not await file_intake_service.consume_slot(db, slot.id):
        await reject("rejected_consumed", status.HTTP_409_CONFLICT, "Upload link already used")

    workflow = (
        await db.execute(select(Workflow).where(Workflow.id == slot.workflow_id))
    ).scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    stored = await file_storage.store_file(
        db,
        owner_id=workflow.owner_id,
        file_bytes=file_bytes,
        filename=file.filename or "upload.bin",
        mime_type=mime,
        workflow_id=workflow.id,
        source_node_id=slot.trigger_node_id,
        source_node_label=slot.trigger_node_label,
    )

    base = build_public_base_url(request)
    file_payload = {
        "id": str(stored.id),
        "name": stored.filename,
        "mime": stored.mime_type,
        "size": stored.size_bytes,
        "download_url": f"{base}/api/files/{stored.id}",
    }

    nodes = _attach_initial_inputs(
        workflow.nodes,
        slot.trigger_node_id,
        {"file": file_payload, "uploaded_at": now.isoformat()},
    )

    # Lazy imports to avoid import cycles with the workflows/mcp API modules.
    from app.api.mcp import get_credentials_context_for_user
    from app.api.workflows import collect_referenced_workflows
    from app.services.global_variables_service import get_global_variables_context

    credentials_context = await get_credentials_context_for_user(db, workflow.owner_id)
    global_variables_context = await get_global_variables_context(db, workflow.owner_id)
    workflow_cache = await collect_referenced_workflows(db, nodes, actor_user_id=workflow.owner_id)

    execution_result = await asyncio.to_thread(
        execute_workflow,
        workflow_id=workflow.id,
        nodes=nodes,
        edges=workflow.edges,
        inputs={"headers": {}, "query": {}, "body": {}},
        workflow_cache=workflow_cache,
        test_run=False,
        credentials_context=credentials_context,
        global_variables_context=global_variables_context,
        trace_user_id=workflow.owner_id,
        actor_user_id=workflow.owner_id,
        cancel_event=None,
    )

    history = ExecutionHistory(
        workflow_id=workflow.id,
        inputs={"file": file_payload},
        outputs=execution_result.outputs,
        node_results=execution_result.node_results,
        status=execution_result.status,
        execution_time_ms=execution_result.execution_time_ms,
        trigger_source="file_upload",
    )
    db.add(history)
    await db.flush()

    slot.uploaded_file_id = stored.id
    slot.run_id = str(history.id)
    await file_intake_service.write_audit(
        db,
        event="upload_accepted",
        slot_id=slot.id,
        workflow_id=workflow.id,
        client_ip=ip,
        user_agent=ua,
        file_name=stored.filename,
        file_size=stored.size_bytes,
        mime=mime,
    )
    if execution_result.status not in ("success", "completed"):
        await file_intake_service.write_audit(
            db,
            event="run_failed",
            slot_id=slot.id,
            workflow_id=workflow.id,
            client_ip=ip,
        )
    await db.commit()

    return {
        "run_id": str(history.id),
        "status": execution_result.status,
        "file": file_payload,
        "output": execution_result.outputs,
    }
