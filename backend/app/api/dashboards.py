"""Dashboards: several per user, shared with users and teams like boards.

Every widget renders from a hidden ``dashboard_widget`` workflow owned by the
dashboard owner, and always runs as that owner, whoever is looking.
"""

import copy
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.ai_assistant import (
    WORKFLOW_BUILDER_TEMPERATURE,
    _extract_generated_workflow_config,
    _record_chat_workflow_edit_version,
    get_credential_for_user,
)
from app.api.deps import get_current_user
from app.db.models import (
    LLM_CREDENTIAL_TYPES,
    Dashboard,
    DashboardShare,
    DashboardTeamShare,
    DashboardWidget,
    Team,
    TeamMember,
    User,
    Workflow,
)
from app.db.session import get_db
from app.models.dashboard_schemas import (
    AiRefineRequest,
    AiWidgetRequest,
    DashboardCreateRequest,
    DashboardResponse,
    DashboardShareRequest,
    DashboardShareResponse,
    DashboardSummaryResponse,
    DashboardTeamShareRequest,
    DashboardTeamShareResponse,
    DashboardUpdateRequest,
    DashboardWidgetResponse,
    MarkdownTaskToggleRequest,
    MarkdownTaskUpdateRequest,
    WidgetCreateRequest,
    WidgetDataResponse,
    WidgetUpdateRequest,
)
from app.services.audit_log import audit
from app.services.dashboard_access import (
    PERMISSION_OWNER,
    PERMISSION_READ,
    PERMISSION_WRITE,
    dashboard_permission,
    shared_dashboard_permissions,
)
from app.services.dashboard_data import compute_widget_data
from app.services.dashboard_widget_policy import dashboard_widget_blocked_nodes_error
from app.services.encryption import decrypt_config
from app.services.llm_provider import is_reasoning_model
from app.services.llm_service import execute_llm
from app.services.llm_trace import LLMTraceContext
from app.services.markdown_task_list import (
    has_task_items,
    toggle_task_item,
    update_or_remove_task_item,
)
from app.services.model_router import build_router_for_credential
from app.services.workflow_access import revoke_execution_tokens_without_access
from app.services.workflow_dsl_prompt import build_assistant_prompt

router = APIRouter()

DEFAULT_DASHBOARD_NAME = "Dashboard"

_AI_WIDGET_SUFFIX = (
    " The workflow MUST end with a single chartOutput node that produces the chart. "
    "Choose an appropriate chartType (pie, bar, line, area, table, numeric, gauge, scatter, "
    "proportion, barGauge, or text) and set "
    "labelField/valueField (or series for multi-series line/area, or xField/yField for scatter, "
    "or min/max for gauge, or text for a markdown message) on the "
    "chartOutput node so it renders the requested metric. When the user only describes example or "
    "sample data, produce the upstream rows with a set node using "
    "$array(dict(key=value, ...), ...) — never use ${...} or bare {...} object literals. "
    "For markdown checklists / task lists, use chartType text and put GFM task list lines "
    "(- [ ] / - [x]) directly in chartOutput text (not only in upstream rows). "
    "For numbered markdown lines (especially descending lists), prefix each line with the "
    "explicit number to display (e.g. 9. Title\\n8. Title); use a loop with total - index "
    "to count down and join lines before chartOutput valueField. Do not include trigger, "
    "input, error-handler, or RabbitMQ nodes in dashboard widget workflows."
)


async def generate_widget_dsl(
    prompt: str,
    *,
    credential: Any,
    model: str,
    user: User,
    current_workflow: dict[str, Any] | None = None,
    workflow_id: uuid.UUID | None = None,
    node_label: str | None = None,
) -> dict[str, Any]:
    """Generate a widget workflow DSL (nodes + edges) ending in a chartOutput node.

    When ``current_workflow`` is provided the model edits that existing widget
    workflow (used by the per-widget AI refine action) instead of building a new one.
    """
    config = decrypt_config(credential.encrypted_config)
    router = build_router_for_credential(
        credential_id=str(credential.id),
        credential_name=credential.name,
        credential_type=credential.type.value,
        config=config,
    )
    api_key = str(config.get("api_key") or "")
    raw_base_url = config.get("base_url")
    base_url = str(raw_base_url) if raw_base_url else None
    system_prompt = build_assistant_prompt(current_workflow, [], getattr(user, "user_rules", None))
    trace_context = LLMTraceContext(
        user_id=user.id,
        credential_id=credential.id,
        workflow_id=workflow_id,
        source="dashboard_widget_ai",
        node_label=node_label
        or ("AI Widget Fine-tune" if current_workflow else "AI Widget Create"),
    )
    result = await execute_llm(
        credential_type=credential.type.value,
        api_key=api_key,
        base_url=base_url,
        model=model,
        system_instruction=system_prompt,
        user_message=prompt + _AI_WIDGET_SUFFIX,
        temperature=None if is_reasoning_model(model) else WORKFLOW_BUILDER_TEMPERATURE,
        trace_context=trace_context,
        router=router,
    )
    content = str(result.get("text") or "")
    return _extract_generated_workflow_config(content, prompt)


async def _ensure_own_dashboard(db: AsyncSession, user: User) -> None:
    """Give a user who owns no dashboard the default one, as the tab always did."""
    owned = await db.execute(select(Dashboard.id).where(Dashboard.owner_id == user.id).limit(1))
    if owned.scalar_one_or_none() is None:
        db.add(Dashboard(owner_id=user.id, name=DEFAULT_DASHBOARD_NAME))
        await db.commit()


async def _get_dashboard_for_user(
    db: AsyncSession, dashboard_id: uuid.UUID, user: User, *, write: bool
) -> tuple[Dashboard, str]:
    """A dashboard the caller owns or has been given access to (directly or through a team)."""
    dashboard = (
        await db.execute(select(Dashboard).where(Dashboard.id == dashboard_id))
    ).scalar_one_or_none()
    permission = await dashboard_permission(db, dashboard, user.id) if dashboard else None
    if dashboard is None or permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found")
    if write and permission == PERMISSION_READ:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Read-only access to this dashboard"
        )
    return dashboard, permission


async def _get_owned_dashboard(db: AsyncSession, dashboard_id: uuid.UUID, user: User) -> Dashboard:
    """Owner-only access: renaming, deleting and sharing."""
    result = await db.execute(
        select(Dashboard).where(Dashboard.id == dashboard_id, Dashboard.owner_id == user.id)
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found")
    return dashboard


def _dashboard_summary(
    dashboard: Dashboard, owner: User | None, permission: str
) -> DashboardSummaryResponse:
    shared = permission != PERMISSION_OWNER and owner is not None
    return DashboardSummaryResponse(
        id=dashboard.id,
        name=dashboard.name,
        permission=permission,
        owner_name=owner.name if shared else None,
        shared_by=owner.email if shared else None,
        updated_at=dashboard.updated_at,
    )


async def _revoke_widget_tokens_without_access(db: AsyncSession, dashboard_id: uuid.UUID) -> None:
    """Revoke widget-workflow execution tokens whose minter lost write access.

    Call after the share change has been flushed. Token checks already re-verify
    access on every use; this keeps the stored state honest, as workflow shares do.
    """
    result = await db.execute(
        select(Workflow)
        .join(DashboardWidget, DashboardWidget.workflow_id == Workflow.id)
        .where(DashboardWidget.dashboard_id == dashboard_id)
    )
    for workflow in result.scalars().all():
        await revoke_execution_tokens_without_access(db, workflow)


def _seed_widget_nodes(chart_type: str) -> tuple[list, list]:
    # Dashboard widgets have no trigger/input — they start with a data-producing
    # node (a `set` node) that feeds the chartOutput. Replace it with a real data
    # source (http, bigquery, rag, ...) when building the widget.
    src_id = str(uuid.uuid4())
    chart_id = str(uuid.uuid4())
    chart_data: dict = {"label": "chart", "chartType": chart_type, "dataPath": "rows"}
    if chart_type == "text":
        chart_data["valueField"] = "text"
    elif chart_type == "scatter":
        chart_data["xField"] = "x"
        chart_data["yField"] = "y"
    elif chart_type == "gauge":
        chart_data["valueField"] = "value"
        chart_data["min"] = 0
        chart_data["max"] = 100
    elif chart_type not in ("table",):
        chart_data["labelField"] = "label"
        chart_data["valueField"] = "value"
    nodes = [
        {
            "id": src_id,
            "type": "set",
            "position": {"x": 0, "y": 0},
            "data": {"label": "data", "mappings": [{"key": "rows", "value": ""}]},
        },
        {
            "id": chart_id,
            "type": "chartOutput",
            "position": {"x": 320, "y": 0},
            "data": chart_data,
        },
    ]
    edges = [{"id": str(uuid.uuid4()), "source": src_id, "target": chart_id}]
    return nodes, edges


def _clone_workflow_graph(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deep-copy a workflow graph while assigning fresh node and edge IDs."""
    node_id_map: dict[str, str] = {}
    cloned_nodes = copy.deepcopy(nodes)
    for node in cloned_nodes:
        old_id = str(node.get("id") or "")
        if not old_id or old_id in node_id_map:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Widget workflow contains invalid node IDs",
            )
        new_id = str(uuid.uuid4())
        node_id_map[old_id] = new_id
        node["id"] = new_id

    cloned_edges = copy.deepcopy(edges)
    for edge in cloned_edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in node_id_map or target not in node_id_map:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Widget workflow contains an edge with an invalid node reference",
            )
        edge["id"] = str(uuid.uuid4())
        edge["source"] = node_id_map[source]
        edge["target"] = node_id_map[target]
    return cloned_nodes, cloned_edges


def _widget_to_response(widget: DashboardWidget) -> DashboardWidgetResponse:
    return DashboardWidgetResponse(
        id=widget.id,
        workflow_id=widget.workflow_id,
        title=widget.title,
        description=widget.description,
        chart_type=widget.chart_type,
        layout=widget.layout,
        cache_ttl_seconds=widget.cache_ttl_seconds,
        position=widget.position,
        updated_at=widget.updated_at,
    )


async def _load_widget_for_user(
    db: AsyncSession, widget_id: uuid.UUID, user: User, *, write: bool
) -> tuple[DashboardWidget, Dashboard, str]:
    """A widget on a dashboard the caller can reach, with that dashboard and the caller's access."""
    row = (
        await db.execute(
            select(DashboardWidget, Dashboard)
            .join(Dashboard, DashboardWidget.dashboard_id == Dashboard.id)
            .where(DashboardWidget.id == widget_id)
        )
    ).one_or_none()
    permission = await dashboard_permission(db, row[1], user.id) if row is not None else None
    if row is None or permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget not found")
    if write and permission == PERMISSION_READ:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Read-only access to this dashboard"
        )
    widget, dashboard = row
    return widget, dashboard, permission


def _find_chart_output_node(workflow: Workflow) -> dict[str, Any] | None:
    for node in workflow.nodes or []:
        if isinstance(node, dict) and node.get("type") == "chartOutput":
            return node
    return None


async def _load_widget_workflow(db: AsyncSession, widget: DashboardWidget) -> Workflow:
    wf_result = await db.execute(select(Workflow).where(Workflow.id == widget.workflow_id))
    workflow = wf_result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return workflow


def _validate_text_task_widget(workflow: Workflow, payload: dict[str, Any]) -> str:
    chart_node = _find_chart_output_node(workflow)
    if chart_node is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Widget workflow has no chartOutput node",
        )

    chart_data = chart_node.get("data") or {}
    if chart_data.get("chartType") != "text":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Checkbox toggling is only supported for text chart widgets",
        )

    displayed_text = payload.get("text")
    if not displayed_text or not str(displayed_text).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Widget has no markdown text to toggle",
        )
    if not payload.get("text_interactive"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Checkbox toggling is only supported for markdown task lists",
        )
    if not has_task_items(str(displayed_text)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Checkbox toggling is only supported for markdown task lists",
        )
    return str(displayed_text)


async def _apply_markdown_text_to_widget(
    db: AsyncSession,
    widget: DashboardWidget,
    workflow: Workflow,
    run_as_user_id: uuid.UUID,
    updated_text: str,
) -> WidgetDataResponse:
    nodes = list(workflow.nodes or [])
    for index, node in enumerate(nodes):
        if isinstance(node, dict) and node.get("type") == "chartOutput":
            node_data = dict(node.get("data") or {})
            node_data["text"] = updated_text
            node_data.pop("valueField", None)
            nodes[index] = {**node, "data": node_data}
            break
    workflow.nodes = nodes
    flag_modified(workflow, "nodes")
    widget.cached_payload = None
    widget.cached_at = None
    widget.cached_workflow_version = None
    await db.commit()
    await db.refresh(widget)
    return await compute_widget_data(db, widget, run_as_user_id, force=True)


def _widget_data_for(response: WidgetDataResponse, permission: str) -> WidgetDataResponse:
    # Highlights carry every node's raw output; a viewer was shared the chart, not those.
    if permission == PERMISSION_READ and response.highlight is not None:
        return response.model_copy(update={"highlight": None})
    return response


@router.get("", response_model=list[DashboardSummaryResponse])
async def list_dashboards(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DashboardSummaryResponse]:
    """The caller's own dashboards (in creation order), then the ones shared with them."""
    await _ensure_own_dashboard(db, current_user)
    shared = await shared_dashboard_permissions(db, current_user.id)
    reachable = Dashboard.owner_id == current_user.id
    if shared:
        reachable = or_(reachable, Dashboard.id.in_(list(shared)))
    rows = (
        await db.execute(
            select(Dashboard, User)
            .join(User, Dashboard.owner_id == User.id)
            .where(reachable)
            .order_by(Dashboard.created_at, Dashboard.id)
        )
    ).all()
    summaries = [
        _dashboard_summary(
            dashboard,
            owner,
            PERMISSION_OWNER
            if dashboard.owner_id == current_user.id
            else shared.get(dashboard.id, PERMISSION_READ),
        )
        for dashboard, owner in rows
    ]
    return sorted(summaries, key=lambda summary: summary.permission != PERMISSION_OWNER)


@router.post("", response_model=DashboardSummaryResponse, status_code=status.HTTP_201_CREATED)
async def create_dashboard(
    body: DashboardCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    dashboard = Dashboard(owner_id=current_user.id, name=body.name)
    db.add(dashboard)
    await db.commit()
    await db.refresh(dashboard)
    audit(
        action="dashboard.create",
        actor=current_user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
    )
    return _dashboard_summary(dashboard, current_user, PERMISSION_OWNER)


@router.get("/{dashboard_id}", response_model=DashboardResponse)
async def get_dashboard(
    dashboard_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    dashboard, permission = await _get_dashboard_for_user(
        db, dashboard_id, current_user, write=False
    )
    owner = (
        current_user
        if permission == PERMISSION_OWNER
        else (await db.execute(select(User).where(User.id == dashboard.owner_id))).scalar_one()
    )
    result = await db.execute(
        select(DashboardWidget)
        .where(DashboardWidget.dashboard_id == dashboard.id)
        .order_by(DashboardWidget.position)
    )
    widgets = result.scalars().all()
    summary = _dashboard_summary(dashboard, owner, permission)
    return DashboardResponse(
        **summary.model_dump(),
        widgets=[_widget_to_response(w) for w in widgets],
    )


@router.patch("/{dashboard_id}", response_model=DashboardSummaryResponse)
async def update_dashboard(
    dashboard_id: uuid.UUID,
    body: DashboardUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    dashboard = await _get_owned_dashboard(db, dashboard_id, current_user)
    dashboard.name = body.name
    await db.commit()
    await db.refresh(dashboard)
    audit(
        action="dashboard.update",
        actor=current_user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
    )
    return _dashboard_summary(dashboard, current_user, PERMISSION_OWNER)


@router.delete("/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard(
    dashboard_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a dashboard with its widgets and their hidden workflows."""
    dashboard = await _get_owned_dashboard(db, dashboard_id, current_user)
    owned_count = (
        await db.execute(
            select(func.count(Dashboard.id)).where(Dashboard.owner_id == current_user.id)
        )
    ).scalar() or 0
    if owned_count <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot delete your only dashboard",
        )
    widget_workflows = (
        (
            await db.execute(
                select(Workflow)
                .join(DashboardWidget, DashboardWidget.workflow_id == Workflow.id)
                .where(
                    DashboardWidget.dashboard_id == dashboard.id,
                    Workflow.kind == "dashboard_widget",
                )
            )
        )
        .scalars()
        .all()
    )
    audit(
        action="dashboard.delete",
        actor=current_user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
        widgets=len(widget_workflows),
    )
    for workflow in widget_workflows:
        await db.delete(workflow)
    await db.delete(dashboard)
    await db.commit()


@router.post(
    "/{dashboard_id}/widgets",
    response_model=DashboardWidgetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_widget(
    dashboard_id: uuid.UUID,
    body: WidgetCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardWidgetResponse:
    dashboard, _ = await _get_dashboard_for_user(db, dashboard_id, current_user, write=True)
    nodes, edges = _seed_widget_nodes(body.chart_type)
    workflow = Workflow(
        name=body.title,
        description=body.description,
        owner_id=dashboard.owner_id,
        kind="dashboard_widget",
        nodes=nodes,
        edges=edges,
    )
    db.add(workflow)
    await db.flush()
    widget = DashboardWidget(
        dashboard_id=dashboard.id,
        workflow_id=workflow.id,
        title=body.title,
        description=body.description,
        chart_type=body.chart_type,
        layout=body.layout.model_dump(),
        cache_ttl_seconds=body.cache_ttl_seconds,
    )
    db.add(widget)
    await db.commit()
    await db.refresh(widget)
    audit(
        action="dashboard.widget_create",
        actor=current_user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
        widget_id=widget.id,
        widget_title=widget.title,
    )
    return _widget_to_response(widget)


@router.post(
    "/widgets/{widget_id}/clone",
    response_model=DashboardWidgetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def clone_widget(
    widget_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardWidgetResponse:
    """Clone a dashboard widget and its private workflow graph."""
    widget, dashboard, _ = await _load_widget_for_user(db, widget_id, current_user, write=True)
    workflow = await _load_widget_workflow(db, widget)
    cloned_nodes, cloned_edges = _clone_workflow_graph(
        list(workflow.nodes or []), list(workflow.edges or [])
    )
    clone_title = f"{widget.title[:248]} (Copy)"
    cloned_workflow = Workflow(
        name=clone_title,
        description=workflow.description,
        owner_id=dashboard.owner_id,
        kind="dashboard_widget",
        nodes=cloned_nodes,
        edges=cloned_edges,
    )
    db.add(cloned_workflow)
    await db.flush()

    layout = copy.deepcopy(widget.layout or {"x": 0, "y": 0, "w": 4, "h": 4})
    layout["y"] = int(layout.get("y", 0)) + int(layout.get("h", 4))
    cloned_widget = DashboardWidget(
        dashboard_id=widget.dashboard_id,
        workflow_id=cloned_workflow.id,
        title=clone_title,
        description=widget.description,
        chart_type=widget.chart_type,
        layout=layout,
        cache_ttl_seconds=widget.cache_ttl_seconds,
        position=widget.position + 1,
    )
    db.add(cloned_widget)
    await db.commit()
    await db.refresh(cloned_widget)
    audit(
        action="dashboard.widget_create",
        actor=current_user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
        widget_id=cloned_widget.id,
        widget_title=cloned_widget.title,
        cloned_from=widget.id,
    )
    return _widget_to_response(cloned_widget)


@router.patch("/widgets/{widget_id}", response_model=DashboardWidgetResponse)
async def update_widget(
    widget_id: uuid.UUID,
    body: WidgetUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardWidgetResponse:
    widget, _, _ = await _load_widget_for_user(db, widget_id, current_user, write=True)
    sync_title = body.title is not None and body.title != widget.title
    sync_description = body.description is not None and body.description != widget.description
    if body.title is not None:
        widget.title = body.title
    if body.description is not None:
        widget.description = body.description
    if body.chart_type is not None:
        widget.chart_type = body.chart_type
    if body.layout is not None:
        widget.layout = body.layout.model_dump()
    if body.cache_ttl_seconds is not None:
        widget.cache_ttl_seconds = body.cache_ttl_seconds

    # Propagate title/description onto the widget's hidden workflow so the canvas reflects them.
    if sync_title or sync_description:
        wf_result = await db.execute(select(Workflow).where(Workflow.id == widget.workflow_id))
        workflow = wf_result.scalar_one_or_none()
        if workflow is not None:
            if sync_title:
                workflow.name = widget.title
            if sync_description:
                workflow.description = widget.description

    await db.commit()
    await db.refresh(widget)
    return _widget_to_response(widget)


@router.delete("/widgets/{widget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_widget(
    widget_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    widget, dashboard, _ = await _load_widget_for_user(db, widget_id, current_user, write=True)
    audit(
        action="dashboard.widget_delete",
        actor=current_user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
        widget_id=widget.id,
        widget_title=widget.title,
    )
    workflow_id = widget.workflow_id
    await db.delete(widget)
    wf_result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = wf_result.scalar_one_or_none()
    if workflow is not None and workflow.kind == "dashboard_widget":
        await db.delete(workflow)
    await db.commit()


@router.get("/widgets/{widget_id}/data", response_model=WidgetDataResponse)
async def get_widget_data(
    widget_id: uuid.UUID,
    force: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetDataResponse:
    widget, dashboard, permission = await _load_widget_for_user(
        db, widget_id, current_user, write=False
    )
    response = await compute_widget_data(db, widget, dashboard.owner_id, force=force)
    return _widget_data_for(response, permission)


@router.patch("/widgets/{widget_id}/markdown-task-toggle", response_model=WidgetDataResponse)
async def toggle_markdown_task(
    widget_id: uuid.UUID,
    body: MarkdownTaskToggleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetDataResponse:
    widget, dashboard, _ = await _load_widget_for_user(db, widget_id, current_user, write=True)
    workflow = await _load_widget_workflow(db, widget)

    current = await compute_widget_data(db, widget, dashboard.owner_id, force=False)
    payload = current.payload or {}
    displayed_text = _validate_text_task_widget(workflow, payload)

    try:
        updated_text = toggle_task_item(displayed_text, body.line_index)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return await _apply_markdown_text_to_widget(
        db, widget, workflow, dashboard.owner_id, updated_text
    )


@router.patch("/widgets/{widget_id}/markdown-task-update", response_model=WidgetDataResponse)
async def update_markdown_task(
    widget_id: uuid.UUID,
    body: MarkdownTaskUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetDataResponse:
    widget, dashboard, _ = await _load_widget_for_user(db, widget_id, current_user, write=True)
    workflow = await _load_widget_workflow(db, widget)

    current = await compute_widget_data(db, widget, dashboard.owner_id, force=False)
    payload = current.payload or {}
    displayed_text = _validate_text_task_widget(workflow, payload)

    try:
        updated_text = update_or_remove_task_item(displayed_text, body.line_index, body.text)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return await _apply_markdown_text_to_widget(
        db, widget, workflow, dashboard.owner_id, updated_text
    )


@router.post(
    "/{dashboard_id}/widgets/ai-generate",
    response_model=DashboardWidgetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ai_generate_widget(
    dashboard_id: uuid.UUID,
    body: AiWidgetRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardWidgetResponse:
    dashboard, _ = await _get_dashboard_for_user(db, dashboard_id, current_user, write=True)
    credential = await get_credential_for_user(body.credential_id, current_user, db)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    if credential.type not in LLM_CREDENTIAL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    dsl = await generate_widget_dsl(
        body.prompt,
        credential=credential,
        model=body.model,
        user=current_user,
        node_label="AI Widget Create",
    )
    nodes = dsl.get("nodes", [])
    edges = dsl.get("edges", [])
    blocked_error = dashboard_widget_blocked_nodes_error(nodes)
    if blocked_error is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=blocked_error,
        )
    chart_nodes = [n for n in nodes if n.get("type") == "chartOutput"]
    if not chart_nodes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AI did not produce a chartOutput node",
        )
    chart_type = chart_nodes[-1].get("data", {}).get("chartType", "bar")
    title = (dsl.get("name") or body.prompt[:60]).strip()[:255]
    description = dsl.get("description") or None
    workflow = Workflow(
        name=title,
        description=description,
        owner_id=dashboard.owner_id,
        kind="dashboard_widget",
        nodes=nodes,
        edges=edges,
    )
    db.add(workflow)
    await db.flush()
    widget = DashboardWidget(
        dashboard_id=dashboard.id,
        workflow_id=workflow.id,
        title=title,
        description=description,
        chart_type=chart_type,
        layout={"x": 0, "y": 0, "w": 4, "h": 4},
        cache_ttl_seconds=300,
    )
    db.add(widget)
    await db.commit()
    await db.refresh(widget)
    audit(
        action="dashboard.widget_create",
        actor=current_user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
        widget_id=widget.id,
        widget_title=widget.title,
    )
    return _widget_to_response(widget)


@router.post("/widgets/{widget_id}/ai-refine", response_model=DashboardWidgetResponse)
async def ai_refine_widget(
    widget_id: uuid.UUID,
    body: AiRefineRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardWidgetResponse:
    widget, _, _ = await _load_widget_for_user(db, widget_id, current_user, write=True)
    credential = await get_credential_for_user(body.credential_id, current_user, db)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    if credential.type not in LLM_CREDENTIAL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    wf_result = await db.execute(select(Workflow).where(Workflow.id == widget.workflow_id))
    workflow = wf_result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Widget workflow not found"
        )

    current_workflow = {
        "name": workflow.name,
        "description": workflow.description,
        "nodes": workflow.nodes,
        "edges": workflow.edges,
    }
    dsl = await generate_widget_dsl(
        body.prompt,
        credential=credential,
        model=body.model,
        user=current_user,
        current_workflow=current_workflow,
        workflow_id=widget.workflow_id,
        node_label="AI Widget Fine-tune",
    )
    nodes = dsl.get("nodes", [])
    edges = dsl.get("edges", [])
    blocked_error = dashboard_widget_blocked_nodes_error(nodes)
    if blocked_error is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=blocked_error,
        )
    chart_nodes = [n for n in nodes if n.get("type") == "chartOutput"]
    if not chart_nodes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AI did not produce a chartOutput node",
        )

    # Snapshot the pre-edit workflow so the AI fine-tune shows up in Edit History.
    await _record_chat_workflow_edit_version(
        db=db,
        workflow=workflow,
        user_id=current_user.id,
        old_nodes=workflow.nodes or [],
        old_edges=workflow.edges or [],
    )

    workflow.nodes = nodes
    workflow.edges = edges
    widget.chart_type = chart_nodes[-1].get("data", {}).get("chartType", widget.chart_type)
    # Invalidate the widget cache so the next load recomputes with the new workflow.
    widget.cached_payload = None
    widget.cached_at = None
    widget.cached_workflow_version = None
    await db.commit()
    await db.refresh(widget)
    return _widget_to_response(widget)


# ─── Sharing ────────────────────────────────────────────────────────────────────────


@router.get("/{dashboard_id}/shares", response_model=list[DashboardShareResponse])
async def list_dashboard_shares(
    dashboard_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DashboardShareResponse]:
    dashboard = await _get_owned_dashboard(db, dashboard_id, current_user)
    result = await db.execute(
        select(DashboardShare, User)
        .join(User, DashboardShare.user_id == User.id)
        .where(DashboardShare.dashboard_id == dashboard.id)
        .order_by(DashboardShare.created_at)
    )
    return [
        DashboardShareResponse(
            id=share.id,
            user_id=user.id,
            email=user.email,
            name=user.name,
            permission=share.permission,
            shared_at=share.created_at,
        )
        for share, user in result.all()
    ]


@router.post("/{dashboard_id}/shares", response_model=DashboardShareResponse)
async def create_dashboard_share(
    dashboard_id: uuid.UUID,
    body: DashboardShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardShareResponse:
    """Share with a user, or change the permission of an existing share."""
    dashboard = await _get_owned_dashboard(db, dashboard_id, current_user)
    target = (
        await db.execute(select(User).where(User.email == body.email.strip()))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot share with yourself"
        )
    share = (
        await db.execute(
            select(DashboardShare).where(
                DashboardShare.dashboard_id == dashboard.id, DashboardShare.user_id == target.id
            )
        )
    ).scalar_one_or_none()
    downgraded = share is not None and share.permission == PERMISSION_WRITE
    if share is None:
        share = DashboardShare(dashboard_id=dashboard.id, user_id=target.id)
        db.add(share)
    share.permission = body.permission
    await db.flush()
    if downgraded and body.permission == PERMISSION_READ:
        await _revoke_widget_tokens_without_access(db, dashboard.id)
    await db.commit()
    await db.refresh(share)
    audit(
        action="dashboard.share_add",
        actor=current_user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
        grantee_id=target.id,
        grantee_email=target.email,
        permission=share.permission,
    )
    return DashboardShareResponse(
        id=share.id,
        user_id=target.id,
        email=target.email,
        name=target.name,
        permission=share.permission,
        shared_at=share.created_at,
    )


@router.delete("/{dashboard_id}/shares/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard_share(
    dashboard_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    dashboard = await _get_owned_dashboard(db, dashboard_id, current_user)
    share = (
        await db.execute(
            select(DashboardShare).where(
                DashboardShare.dashboard_id == dashboard.id, DashboardShare.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    audit(
        action="dashboard.share_remove",
        actor=current_user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
        grantee_id=user_id,
    )
    await db.delete(share)
    await db.flush()
    await _revoke_widget_tokens_without_access(db, dashboard.id)
    await db.commit()


@router.get("/{dashboard_id}/team-shares", response_model=list[DashboardTeamShareResponse])
async def list_dashboard_team_shares(
    dashboard_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DashboardTeamShareResponse]:
    dashboard = await _get_owned_dashboard(db, dashboard_id, current_user)
    result = await db.execute(
        select(DashboardTeamShare, Team)
        .join(Team, DashboardTeamShare.team_id == Team.id)
        .where(DashboardTeamShare.dashboard_id == dashboard.id)
        .order_by(DashboardTeamShare.created_at)
    )
    return [
        DashboardTeamShareResponse(
            id=share.id,
            team_id=team.id,
            team_name=team.name,
            permission=share.permission,
            shared_at=share.created_at,
        )
        for share, team in result.all()
    ]


@router.post("/{dashboard_id}/team-shares", response_model=DashboardTeamShareResponse)
async def create_dashboard_team_share(
    dashboard_id: uuid.UUID,
    body: DashboardTeamShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardTeamShareResponse:
    """Share with a team the owner belongs to, or change that share's permission."""
    dashboard = await _get_owned_dashboard(db, dashboard_id, current_user)
    team = (
        await db.execute(
            select(Team)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .where(Team.id == body.team_id, TeamMember.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    share = (
        await db.execute(
            select(DashboardTeamShare).where(
                DashboardTeamShare.dashboard_id == dashboard.id,
                DashboardTeamShare.team_id == team.id,
            )
        )
    ).scalar_one_or_none()
    downgraded = share is not None and share.permission == PERMISSION_WRITE
    if share is None:
        share = DashboardTeamShare(dashboard_id=dashboard.id, team_id=team.id)
        db.add(share)
    share.permission = body.permission
    await db.flush()
    if downgraded and body.permission == PERMISSION_READ:
        await _revoke_widget_tokens_without_access(db, dashboard.id)
    await db.commit()
    await db.refresh(share)
    audit(
        action="dashboard.team_share_add",
        actor=current_user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
        team_id=team.id,
        team_name=team.name,
        permission=share.permission,
    )
    return DashboardTeamShareResponse(
        id=share.id,
        team_id=team.id,
        team_name=team.name,
        permission=share.permission,
        shared_at=share.created_at,
    )


@router.delete("/{dashboard_id}/team-shares/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard_team_share(
    dashboard_id: uuid.UUID,
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    dashboard = await _get_owned_dashboard(db, dashboard_id, current_user)
    share = (
        await db.execute(
            select(DashboardTeamShare).where(
                DashboardTeamShare.dashboard_id == dashboard.id,
                DashboardTeamShare.team_id == team_id,
            )
        )
    ).scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    audit(
        action="dashboard.team_share_remove",
        actor=current_user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
        team_id=team_id,
    )
    await db.delete(share)
    await db.flush()
    await _revoke_widget_tokens_without_access(db, dashboard.id)
    await db.commit()
