import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Credential, LLMTrace, User, Workflow
from app.db.session import get_db
from app.models.schemas import LLMTraceDetailResponse, LLMTraceListItem, LLMTraceListResponse

router = APIRouter()


@router.get("", response_model=LLMTraceListResponse)
async def list_traces(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    credential_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    source: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = Query(None),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMTraceListResponse:
    """List LLM traces for the current user with pagination."""
    filters = [LLMTrace.user_id == current_user.id]
    if credential_id:
        filters.append(LLMTrace.credential_id == credential_id)
    if workflow_id:
        filters.append(LLMTrace.workflow_id == workflow_id)
    if source:
        filters.append(LLMTrace.source == source)
    if status_filter == "error":
        filters.append(LLMTrace.error.is_not(None))
    elif status_filter == "success":
        filters.append(LLMTrace.error.is_(None))

    base_query = (
        select(LLMTrace, Credential.name, Workflow.name)
        .outerjoin(Credential, LLMTrace.credential_id == Credential.id)
        .outerjoin(Workflow, LLMTrace.workflow_id == Workflow.id)
        .where(*filters)
    )

    if search:
        pattern = f"%{search}%"
        base_query = base_query.where(
            or_(
                LLMTrace.model.ilike(pattern),
                LLMTrace.node_label.ilike(pattern),
                Workflow.name.ilike(pattern),
                Credential.name.ilike(pattern),
                cast(LLMTrace.request, String).ilike(pattern),
                cast(LLMTrace.response, String).ilike(pattern),
            )
        )

    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    order_by = LLMTrace.created_at.asc() if order == "asc" else LLMTrace.created_at.desc()
    result = await db.execute(base_query.order_by(order_by).limit(limit).offset(offset))

    items: list[LLMTraceListItem] = []
    for trace, credential_name, workflow_name in result.all():
        items.append(
            LLMTraceListItem(
                id=trace.id,
                created_at=trace.created_at,
                source=trace.source,
                request_type=trace.request_type,
                provider=trace.provider,
                model=trace.model,
                credential_id=trace.credential_id,
                credential_name=credential_name,
                workflow_id=trace.workflow_id,
                workflow_name=workflow_name,
                node_id=trace.node_id,
                node_label=trace.node_label,
                status="error" if trace.error else "success",
                elapsed_ms=trace.elapsed_ms,
                prompt_tokens=trace.prompt_tokens,
                completion_tokens=trace.completion_tokens,
                total_tokens=trace.total_tokens,
            )
        )

    return LLMTraceListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{trace_id}", response_model=LLMTraceDetailResponse)
async def get_trace(
    trace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMTraceDetailResponse:
    """Fetch a single trace scoped to the current user."""
    result = await db.execute(
        select(LLMTrace, Credential.name, Workflow.name)
        .outerjoin(Credential, LLMTrace.credential_id == Credential.id)
        .outerjoin(Workflow, LLMTrace.workflow_id == Workflow.id)
        .where(LLMTrace.id == trace_id, LLMTrace.user_id == current_user.id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trace not found")
    trace, credential_name, workflow_name = row

    return LLMTraceDetailResponse(
        id=trace.id,
        created_at=trace.created_at,
        source=trace.source,
        request_type=trace.request_type,
        provider=trace.provider,
        model=trace.model,
        credential_id=trace.credential_id,
        credential_name=credential_name,
        workflow_id=trace.workflow_id,
        workflow_name=workflow_name,
        node_id=trace.node_id,
        node_label=trace.node_label,
        status="error" if trace.error else "success",
        elapsed_ms=trace.elapsed_ms,
        prompt_tokens=trace.prompt_tokens,
        completion_tokens=trace.completion_tokens,
        total_tokens=trace.total_tokens,
        request=trace.request,
        response=trace.response,
        error=trace.error,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_traces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete all LLM traces for the current user."""
    await db.execute(delete(LLMTrace).where(LLMTrace.user_id == current_user.id))
    await db.commit()
