"""Dashboards: several per user, shared with users and teams like boards.

Every widget renders from a hidden ``dashboard_widget`` workflow owned by the
dashboard owner, and always runs as that owner, whoever is looking.
"""

import copy
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.ai_assistant import (
    WORKFLOW_BUILDER_TEMPERATURE,
    _extract_generated_workflow_config,
    _record_chat_workflow_edit_version,
    get_credential_for_user,
)
from app.api.deps import get_client_ip, get_current_user
from app.api.workflows import get_workflow_for_user
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
    AiPlanRequest,
    AiPlanResponse,
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
    DetailPageProposalResponse,
    FileRunSlotRequest,
    FileRunSlotResponse,
    MarkdownTaskToggleRequest,
    MarkdownTaskUpdateRequest,
    WidgetCreateRequest,
    WidgetDataResponse,
    WidgetExampleResponse,
    WidgetProposalResponse,
    WidgetRunRequest,
    WidgetRunResponse,
    WidgetUpdateRequest,
)
from app.services import file_intake_service
from app.services.audit_log import audit
from app.services.dashboard_access import (
    PERMISSION_OWNER,
    PERMISSION_READ,
    PERMISSION_WRITE,
    dashboard_permission,
    reachable_dashboard_ids,
    shared_dashboard_permissions,
)
from app.services.dashboard_data import compute_widget_data, run_widget_workflow
from app.services.dashboard_data_context import (
    TableContext,
    TableUnavailableError,
    describe_tables,
    load_table_contexts,
)
from app.services.dashboard_widget_plan import WidgetProposal, plan_dashboard_widgets
from app.services.dashboard_widget_policy import dashboard_widget_blocked_nodes_error
from app.services.data_table_access import get_data_table_with_permission
from app.services.encryption import decrypt_config
from app.services.file_run_widget import FILE_RUN_WIDGET_TYPE, run_widget_payload
from app.services.hitl_service import build_public_base_url
from app.services.llm_provider import is_reasoning_model
from app.services.llm_service import execute_llm
from app.services.llm_trace import LLMTraceContext
from app.services.markdown_task_list import (
    has_task_items,
    toggle_task_item,
    update_or_remove_task_item,
)
from app.services.model_router import build_router_for_credential
from app.services.page_params import (
    DEFAULT_RECORD_FORMAT,
    MAX_RECORD_LENGTH,
    is_valid_record,
)
from app.services.workflow_access import revoke_execution_tokens_without_access
from app.services.workflow_dsl_prompt import build_assistant_prompt
from app.services.workflow_inputs import start_input_fields

router = APIRouter()

DEFAULT_DASHBOARD_NAME = "Dashboard"
TABLE_WIDGET_ROW_LIMIT = 500

_AI_WIDGET_SUFFIX = (
    " The workflow MUST end with a single chartOutput node that produces the chart. "
    "Choose an appropriate chartType (pie, bar, line, area, table, numeric, gauge, scatter, "
    "proportion, barGauge, text, or hitl) and set "
    "labelField/valueField (or series for multi-series line/area, or xField/yField for scatter, "
    "or min/max for gauge, or text for a markdown message) on the "
    "chartOutput node so it renders the requested metric. When the user only describes example or "
    "sample data, produce the upstream rows with a set node using "
    "$array(dict(key=value, ...), ...) — never use ${...} or bare {...} object literals. "
    "For markdown checklists / task lists, use chartType text and put GFM task list lines "
    "(- [ ] / - [x]) directly in chartOutput text (not only in upstream rows). "
    "For numbered markdown lines (especially descending lists), prefix each line with the "
    "explicit number to display (e.g. 9. Title\\n8. Title); use a loop with total - index "
    "to count down and join lines before chartOutput valueField. "
    "When the user wants pending human reviews on the dashboard, use chartType hitl and no "
    "upstream data nodes. Do not include trigger, "
    "input, error-handler, or RabbitMQ nodes in dashboard widget workflows. "
    "On a detail dashboard, read the record the page is about from $page.record. "
    "A dataTable node returns {rows, count}; each row is {id, data, created_at} with the "
    "columns under data, so in a set node group and sum row.data values, not the row itself. "
    "A chartOutput reading those rows directly sees each row's columns at the top level next "
    "to its id: for a table of the rows, connect the dataTable node to a table chartOutput "
    "with dataPath rows and columns set to the table's column names. "
    "Answer with the workflow JSON object only, from its opening { to its closing }: no "
    "explanation, no plan, no questions and no markdown fences before or after it."
)
_JSON_ONLY_RETRY = (
    "\n\nYour previous answer had no workflow JSON object in it. Answer again with the "
    "workflow JSON object only: nothing before or after it."
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
    session_id: uuid.UUID | None = None,
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
        session_id=str(session_id) if session_id else None,
    )
    user_message = prompt + _AI_WIDGET_SUFFIX
    # Some models explain around the JSON or answer with prose only; one retry asks for JSON alone.
    for attempt in range(2):
        result = await execute_llm(
            credential_type=credential.type.value,
            api_key=api_key,
            base_url=base_url,
            model=model,
            system_instruction=system_prompt,
            user_message=user_message + (_JSON_ONLY_RETRY if attempt else ""),
            temperature=None if is_reasoning_model(model) else WORKFLOW_BUILDER_TEMPERATURE,
            trace_context=trace_context,
            router=router,
        )
        try:
            return _extract_generated_workflow_config(str(result.get("text") or ""), prompt)
        except ValueError:
            continue
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="The model did not answer with a widget workflow. Try again or pick another model.",
    )


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
        # A dashboard created in this request has no server default loaded yet.
        record_format=dashboard.record_format or DEFAULT_RECORD_FORMAT,
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
    # A HITL widget is an inbox. It does not read upstream rows.
    if chart_type == "hitl":
        chart_id = str(uuid.uuid4())
        return (
            [
                {
                    "id": chart_id,
                    "type": "chartOutput",
                    "position": {"x": 0, "y": 0},
                    "data": {"label": "reviews", "chartType": "hitl"},
                }
            ],
            [],
        )

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


def _data_table_widget_nodes(table_id: uuid.UUID, columns: list[str]) -> tuple[list, list]:
    """A table widget's graph: a data table's rows, oldest first, shown in ``columns``."""
    src_id = str(uuid.uuid4())
    chart_id = str(uuid.uuid4())
    nodes = [
        {
            "id": src_id,
            "type": "dataTable",
            "position": {"x": 0, "y": 0},
            "data": {
                "label": "tableRows",
                "dataTableId": str(table_id),
                "dataTableOperation": "getAll",
                "dataTableSort": "created_at",
                "dataTableLimit": TABLE_WIDGET_ROW_LIMIT,
            },
        },
        {
            "id": chart_id,
            "type": "chartOutput",
            "position": {"x": 320, "y": 0},
            "data": {
                "label": "chart",
                "chartType": "table",
                "dataPath": "rows",
                "columns": columns,
            },
        },
    ]
    edges = [{"id": str(uuid.uuid4()), "source": src_id, "target": chart_id}]
    return nodes, edges


async def _table_widget_graph(
    db: AsyncSession,
    table_id: uuid.UUID,
    body: WidgetCreateRequest,
    dashboard: Dashboard,
    user: User,
) -> tuple[list, list]:
    """The graph of a table on a data table's rows, once the table and its columns check out."""
    if body.chart_type != "table":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only a table widget can show a data table's rows directly",
        )
    found = await get_data_table_with_permission(db, table_id, user.id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data table not found")
    # The widget's workflow runs as the dashboard's owner, so they must be able to read it too.
    if dashboard.owner_id != user.id and (
        await get_data_table_with_permission(db, table_id, dashboard.owner_id) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The dashboard's owner cannot read this data table. Share it with them first.",
        )
    table, _ = found
    known = {"id"} | {
        str(column.get("name")) for column in table.columns or [] if isinstance(column, dict)
    }
    columns = list(dict.fromkeys(name for name in body.columns if name))
    if not columns:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Choose at least one column for the table",
        )
    unknown = [name for name in columns if name not in known]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"The data table has no column named {', '.join(unknown)}",
        )
    return _data_table_widget_nodes(table.id, columns)


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


def _widget_to_response(
    widget: DashboardWidget, reachable_links: set[uuid.UUID] | None = None
) -> DashboardWidgetResponse:
    return DashboardWidgetResponse(
        id=widget.id,
        workflow_id=widget.workflow_id,
        title=widget.title,
        description=widget.description,
        chart_type=widget.chart_type,
        layout=widget.layout,
        cache_ttl_seconds=widget.cache_ttl_seconds,
        position=widget.position,
        link_dashboard_id=widget.link_dashboard_id,
        link_record_field=widget.link_record_field,
        link_label_field=widget.link_label_field,
        link_accessible=widget.link_dashboard_id is not None
        and widget.link_dashboard_id in (reachable_links or set()),
        updated_at=widget.updated_at,
    )


async def _reachable_links(
    db: AsyncSession, widgets: list[DashboardWidget], user: User
) -> set[uuid.UUID]:
    """The row-link targets among ``widgets`` the caller can open."""
    targets = {w.link_dashboard_id for w in widgets if w.link_dashboard_id is not None}
    return await reachable_dashboard_ids(db, targets, user.id)


async def _apply_row_link(
    db: AsyncSession, widget: DashboardWidget, body: WidgetUpdateRequest, user: User
) -> None:
    """Set or clear a widget's row link; the editor must be able to open the target."""
    if "link_dashboard_id" not in body.model_fields_set:
        return
    if body.link_dashboard_id is None:
        widget.link_dashboard_id = None
        widget.link_record_field = None
        widget.link_label_field = None
        return
    record_field = (body.link_record_field or "").strip()
    if not record_field:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A row link needs the column that holds the record",
        )
    target = (
        await db.execute(select(Dashboard).where(Dashboard.id == body.link_dashboard_id))
    ).scalar_one_or_none()
    if target is None or await dashboard_permission(db, target, user.id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Linked dashboard not found"
        )
    widget.link_dashboard_id = target.id
    widget.link_record_field = record_field
    widget.link_label_field = (body.link_label_field or "").strip() or None


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


async def _file_run_workflow(
    db: AsyncSession, workflow_id: uuid.UUID | None, dashboard: Dashboard, user: User
) -> Workflow:
    """The workflow a new run widget runs: one the creator and the owner can both run."""
    if workflow_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A run widget needs a workflow",
        )
    workflow = await get_workflow_for_user(db, workflow_id, user.id)
    if workflow is None or workflow.kind != "workflow":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    # Runs and drops happen with the dashboard owner's access, so the owner must reach it too.
    if dashboard.owner_id != user.id and (
        await get_workflow_for_user(db, workflow_id, dashboard.owner_id) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The dashboard owner cannot run this workflow",
        )
    return workflow


async def _file_run_widget_data(
    db: AsyncSession, widget: DashboardWidget, dashboard: Dashboard
) -> WidgetDataResponse:
    """A run widget never runs on load: it describes what the workflow takes."""
    workflow = await get_workflow_for_user(db, widget.workflow_id, dashboard.owner_id)
    payload = run_widget_payload(workflow.nodes, workflow.edges) if workflow is not None else None
    return WidgetDataResponse(
        widget_id=widget.id,
        payload=payload,
        cached=False,
        computed_at=None,
        error=None if payload is not None else "This workflow is no longer available",
    )


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
    widgets = list(result.scalars().all())
    summary = _dashboard_summary(dashboard, owner, permission)
    reachable = await _reachable_links(db, widgets, current_user)
    return DashboardResponse(
        **summary.model_dump(),
        widgets=[_widget_to_response(w, reachable) for w in widgets],
    )


@router.patch("/{dashboard_id}", response_model=DashboardSummaryResponse)
async def update_dashboard(
    dashboard_id: uuid.UUID,
    body: DashboardUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    dashboard = await _get_owned_dashboard(db, dashboard_id, current_user)
    if body.name is not None:
        dashboard.name = body.name
    if body.record_format is not None:
        dashboard.record_format = body.record_format
    await db.commit()
    await db.refresh(dashboard)
    audit(
        action="dashboard.update",
        actor=current_user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
        record_format=dashboard.record_format,
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
    if body.chart_type == FILE_RUN_WIDGET_TYPE:
        workflow = await _file_run_workflow(db, body.workflow_id, dashboard, current_user)
    else:
        if body.data_table_id is not None:
            nodes, edges = await _table_widget_graph(
                db, body.data_table_id, body, dashboard, current_user
            )
        else:
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
    clone_title = f"{widget.title[:248]} (Copy)"
    if widget.chart_type == FILE_RUN_WIDGET_TYPE:
        # The copy runs the same workflow; there is no widget graph to copy.
        cloned_workflow = workflow
    else:
        cloned_nodes, cloned_edges = _clone_workflow_graph(
            list(workflow.nodes or []), list(workflow.edges or [])
        )
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
        link_dashboard_id=widget.link_dashboard_id,
        link_record_field=widget.link_record_field,
        link_label_field=widget.link_label_field,
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
    return _widget_to_response(
        cloned_widget, await _reachable_links(db, [cloned_widget], current_user)
    )


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
    await _apply_row_link(db, widget, body, current_user)

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
    return _widget_to_response(widget, await _reachable_links(db, [widget], current_user))


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
    record: str | None = Query(default=None, max_length=MAX_RECORD_LENGTH),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetDataResponse:
    """The widget's chart; ``record`` is the detail page's ``?record=`` value."""
    widget, dashboard, permission = await _load_widget_for_user(
        db, widget_id, current_user, write=False
    )
    if widget.chart_type == FILE_RUN_WIDGET_TYPE:
        return await _file_run_widget_data(db, widget, dashboard)
    # The record comes from a URL: check it before any workflow sees it.
    if record is not None and not is_valid_record(record, dashboard.record_format):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="This page does not accept that record",
        )
    response = await compute_widget_data(db, widget, dashboard.owner_id, force=force, record=record)
    return _widget_data_for(response, permission)


@router.post("/widgets/{widget_id}/run", response_model=WidgetRunResponse)
async def run_widget(
    widget_id: uuid.UUID,
    body: WidgetRunRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetRunResponse:
    """Run a run widget's workflow with the values of its start fields, or with none.

    Anyone who can open the dashboard may run it, as anyone may drop a file on a file
    widget: access to the workflow is the dashboard owner's, and the run is the owner's.
    Values for fields the workflow does not have are dropped.
    """
    widget, dashboard, _ = await _load_widget_for_user(db, widget_id, current_user, write=False)
    if widget.chart_type != FILE_RUN_WIDGET_TYPE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This widget does not run a workflow"
        )
    workflow = await get_workflow_for_user(db, widget.workflow_id, dashboard.owner_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="This workflow is no longer available"
        )
    if file_intake_service.find_file_upload_trigger(workflow.nodes or []) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This widget takes a file"
        )
    fields = {field["key"] for field in start_input_fields(workflow.nodes, workflow.edges)}
    values = {key: value for key, value in body.inputs.items() if key in fields}
    result, history_entry = await run_widget_workflow(
        db, workflow, dashboard.owner_id, {"headers": {}, "query": {}, "body": values}
    )
    return WidgetRunResponse(
        run_id=history_entry.id if history_entry is not None else None,
        status=str(result.status),
        output=result.outputs if isinstance(result.outputs, dict) else {"result": result.outputs},
    )


@router.post("/widgets/{widget_id}/file-slot", response_model=FileRunSlotResponse)
async def create_file_run_slot(
    widget_id: uuid.UUID,
    request: Request,
    body: Annotated[FileRunSlotRequest | None, Body()] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileRunSlotResponse:
    """Mint a single-use upload link for one drop on a file-run widget.

    Anyone who can open the dashboard may drop a file, as anyone may refresh a chart:
    access to the workflow is the dashboard owner's. The upload itself goes to the
    file intake path in the link, which runs the workflow on the main instance. Values for
    the workflow's text input fields travel on the slot, so the public upload cannot set them.
    """
    widget, dashboard, _ = await _load_widget_for_user(db, widget_id, current_user, write=False)
    if widget.chart_type != FILE_RUN_WIDGET_TYPE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This widget does not take files"
        )
    workflow = await get_workflow_for_user(db, widget.workflow_id, dashboard.owner_id)
    node = (
        file_intake_service.find_file_upload_trigger(workflow.nodes or [])
        if workflow is not None
        else None
    )
    if workflow is None or node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="This workflow no longer takes a file"
        )
    fields = {field["key"] for field in start_input_fields(workflow.nodes, workflow.edges)}
    values = {key: value for key, value in (body.inputs if body else {}).items() if key in fields}
    slot, token = await file_intake_service.mint_slot(
        db,
        workflow_id=workflow.id,
        node=node,
        created_by_user_id=current_user.id,
        mint_source="dashboard",
        initial_inputs=values,
    )
    await file_intake_service.write_audit(
        db,
        event="minted",
        slot_id=slot.id,
        workflow_id=workflow.id,
        client_ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    payload = file_intake_service.build_mint_payload(
        base_url=build_public_base_url(request),
        token=token,
        expires_at_iso=slot.expires_at.isoformat(),
        max_size_bytes=slot.max_size_bytes,
        allowed_mime=slot.allowed_mime,
        slot_id=str(slot.id),
    )
    return FileRunSlotResponse(
        upload_url=payload["upload_url"],
        expires_at=payload["expires_at"],
        max_size_mb=payload["max_size_mb"],
        allowed_types=payload["allowed_types"],
        slot_id=payload["slot_id"],
    )


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


async def _table_contexts(
    db: AsyncSession, table_ids: list[uuid.UUID], user_id: uuid.UUID, *, for_owner: bool = False
) -> list[TableContext]:
    """The data tables an AI widget request names, as `user_id` reads them."""
    if not table_ids:
        return []
    try:
        return await load_table_contexts(db, table_ids, user_id)
    except TableUnavailableError as exc:
        if for_owner:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The dashboard's owner cannot read this data table. Share it with them first.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Data table not found"
        ) from exc


@router.post("/ai-plan", response_model=AiPlanResponse)
async def ai_plan_widgets(
    body: AiPlanRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AiPlanResponse:
    """Propose the widgets for a page described in a sentence or two.

    Nothing is saved: the client shows the proposals, and builds the chosen ones with
    ``ai-generate``, passing the same ``session_id``.
    """
    credential = await get_credential_for_user(body.credential_id, current_user, db)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    if credential.type not in LLM_CREDENTIAL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )
    tables = await _table_contexts(db, body.data_table_ids, current_user.id)
    proposals = await plan_dashboard_widgets(
        body.description,
        credential=credential,
        model=body.model,
        user=current_user,
        session_id=body.session_id,
        data_context=describe_tables(tables, with_data=True),
    )
    if not proposals:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The model proposed no widgets. Describe the page in other words.",
        )
    return AiPlanResponse(widgets=[_proposal_response(p) for p in proposals])


def _proposal_response(proposal: WidgetProposal) -> WidgetProposalResponse:
    """A planned widget as the API returns it, with its detail page's widgets."""
    example = proposal.example
    detail = proposal.detail
    return WidgetProposalResponse(
        title=proposal.title,
        chart_type=proposal.chart_type,
        prompt=proposal.prompt,
        example=(
            WidgetExampleResponse(labels=example.labels, values=example.values) if example else None
        ),
        detail=(
            DetailPageProposalResponse(
                title=detail.title,
                record_field=detail.record_field,
                label_field=detail.label_field,
                widgets=[_proposal_response(widget) for widget in detail.widgets],
            )
            if detail
            else None
        ),
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

    # The widget's workflow runs as the dashboard's owner, so they must be able to read it too.
    tables = await _table_contexts(db, body.data_table_ids, current_user.id)
    if dashboard.owner_id != current_user.id:
        await _table_contexts(db, body.data_table_ids, dashboard.owner_id, for_owner=True)
    context = describe_tables(tables, with_data=False)
    dsl = await generate_widget_dsl(
        f"{body.prompt}\n\n{context}" if context else body.prompt,
        credential=credential,
        model=body.model,
        user=current_user,
        node_label="AI Widget Create",
        session_id=body.session_id,
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
    widget, dashboard, _ = await _load_widget_for_user(db, widget_id, current_user, write=True)
    if widget.chart_type == FILE_RUN_WIDGET_TYPE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A file-run widget runs an existing workflow; change it in the editor",
        )
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
    tables = await _table_contexts(db, body.data_table_ids, current_user.id)
    if dashboard.owner_id != current_user.id:
        await _table_contexts(db, body.data_table_ids, dashboard.owner_id, for_owner=True)
    context = describe_tables(tables, with_data=True)
    dsl = await generate_widget_dsl(
        f"{body.prompt}\n\n{context}" if context else body.prompt,
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
