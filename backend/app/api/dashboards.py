import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.ai_assistant import (
    WORKFLOW_BUILDER_TEMPERATURE,
    _extract_generated_workflow_config,
    _record_chat_workflow_edit_version,
    get_credential_for_user,
)
from app.api.deps import get_current_user
from app.db.models import CredentialType, Dashboard, DashboardWidget, User, Workflow
from app.db.session import get_db
from app.models.dashboard_schemas import (
    AiRefineRequest,
    AiWidgetRequest,
    DashboardResponse,
    DashboardWidgetResponse,
    MarkdownTaskToggleRequest,
    MarkdownTaskUpdateRequest,
    WidgetCreateRequest,
    WidgetDataResponse,
    WidgetUpdateRequest,
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
from app.services.workflow_dsl_prompt import build_assistant_prompt

router = APIRouter()

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
    )
    content = str(result.get("text") or "")
    return _extract_generated_workflow_config(content, prompt)


async def _get_or_create_dashboard(db: AsyncSession, user: User) -> Dashboard:
    result = await db.execute(
        select(Dashboard).where(Dashboard.owner_id == user.id).order_by(Dashboard.created_at)
    )
    dashboard = result.scalars().first()
    if dashboard is None:
        dashboard = Dashboard(owner_id=user.id, name="Dashboard")
        db.add(dashboard)
        await db.commit()
        await db.refresh(dashboard)
    return dashboard


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


async def _load_widget(db: AsyncSession, widget_id: uuid.UUID, user: User) -> DashboardWidget:
    result = await db.execute(
        select(DashboardWidget)
        .join(Dashboard, DashboardWidget.dashboard_id == Dashboard.id)
        .where(DashboardWidget.id == widget_id, Dashboard.owner_id == user.id)
    )
    widget = result.scalar_one_or_none()
    if widget is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget not found")
    return widget


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
    current_user: User,
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
    return await compute_widget_data(db, widget, current_user, force=True)


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    dashboard = await _get_or_create_dashboard(db, current_user)
    result = await db.execute(
        select(DashboardWidget)
        .where(DashboardWidget.dashboard_id == dashboard.id)
        .order_by(DashboardWidget.position)
    )
    widgets = result.scalars().all()
    return DashboardResponse(
        id=dashboard.id,
        name=dashboard.name,
        widgets=[_widget_to_response(w) for w in widgets],
    )


@router.post(
    "/widgets", response_model=DashboardWidgetResponse, status_code=status.HTTP_201_CREATED
)
async def create_widget(
    body: WidgetCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardWidgetResponse:
    dashboard = await _get_or_create_dashboard(db, current_user)
    nodes, edges = _seed_widget_nodes(body.chart_type)
    workflow = Workflow(
        name=body.title,
        description=body.description,
        owner_id=current_user.id,
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
    return _widget_to_response(widget)


@router.patch("/widgets/{widget_id}", response_model=DashboardWidgetResponse)
async def update_widget(
    widget_id: uuid.UUID,
    body: WidgetUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardWidgetResponse:
    widget = await _load_widget(db, widget_id, current_user)
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
    widget = await _load_widget(db, widget_id, current_user)
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
    widget = await _load_widget(db, widget_id, current_user)
    return await compute_widget_data(db, widget, current_user, force=force)


@router.patch("/widgets/{widget_id}/markdown-task-toggle", response_model=WidgetDataResponse)
async def toggle_markdown_task(
    widget_id: uuid.UUID,
    body: MarkdownTaskToggleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetDataResponse:
    widget = await _load_widget(db, widget_id, current_user)
    workflow = await _load_widget_workflow(db, widget)

    current = await compute_widget_data(db, widget, current_user, force=False)
    payload = current.payload or {}
    displayed_text = _validate_text_task_widget(workflow, payload)

    try:
        updated_text = toggle_task_item(displayed_text, body.line_index)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return await _apply_markdown_text_to_widget(db, widget, workflow, current_user, updated_text)


@router.patch("/widgets/{widget_id}/markdown-task-update", response_model=WidgetDataResponse)
async def update_markdown_task(
    widget_id: uuid.UUID,
    body: MarkdownTaskUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetDataResponse:
    widget = await _load_widget(db, widget_id, current_user)
    workflow = await _load_widget_workflow(db, widget)

    current = await compute_widget_data(db, widget, current_user, force=False)
    payload = current.payload or {}
    displayed_text = _validate_text_task_widget(workflow, payload)

    try:
        updated_text = update_or_remove_task_item(displayed_text, body.line_index, body.text)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return await _apply_markdown_text_to_widget(db, widget, workflow, current_user, updated_text)


@router.post(
    "/widgets/ai-generate",
    response_model=DashboardWidgetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ai_generate_widget(
    body: AiWidgetRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardWidgetResponse:
    credential = await get_credential_for_user(body.credential_id, current_user, db)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    if credential.type not in (
        CredentialType.openai,
        CredentialType.google,
        CredentialType.custom,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    dashboard = await _get_or_create_dashboard(db, current_user)
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
        owner_id=current_user.id,
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
    return _widget_to_response(widget)


@router.post("/widgets/{widget_id}/ai-refine", response_model=DashboardWidgetResponse)
async def ai_refine_widget(
    widget_id: uuid.UUID,
    body: AiRefineRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardWidgetResponse:
    widget = await _load_widget(db, widget_id, current_user)
    credential = await get_credential_for_user(body.credential_id, current_user, db)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    if credential.type not in (
        CredentialType.openai,
        CredentialType.google,
        CredentialType.custom,
    ):
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
