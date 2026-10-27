"""Dashboards in chat: which dashboards a user can open, the widgets on each, placing a workflow
on one as a widget, renaming and deleting widgets, and tidying a dashboard's layout.

Heym Work shows these dashboards as its pages, so ``list_dashboards`` is also the page to widget
map there. The tools follow the Dashboards routes' access rules: a dashboard is reached by
owning it or through a share, a filtered HITL widget stays hidden from a viewer who cannot open
its workflow, and changing a dashboard needs write access. Tidying arranges the dashboard in
Heym, as the Dashboard tab's Tidy up button does; Heym Work keeps its own arrangement of a page.

A new chart widget starts empty, on the placeholder graph the Dashboard tab starts one with, and
the chat then writes its graph with build mode's save_workflow, so no stray workflow is left
behind. An existing workflow can be placed too: a chart widget gets its own hidden
``dashboard_widget`` copy of its graph, as cloning a widget does, so changing or deleting the
widget never touches the workflow it came from, and a workflow without a chartOutput node
becomes a run widget, which points at the workflow itself. Every widget's workflow runs as the
dashboard's owner.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.workflows import get_workflow_for_user
from app.db.models import Dashboard, DashboardWidget, User, Workflow
from app.models.dashboard_schemas import WidgetLayout
from app.services.audit_log import audit
from app.services.dashboard_access import (
    PERMISSION_OWNER,
    PERMISSION_READ,
    shared_dashboard_permissions,
)
from app.services.dashboard_tidy import MAX_PER_ROW, tidy_layouts
from app.services.dashboard_widget_plan import WIDGET_CHART_TYPES
from app.services.dashboard_widget_policy import dashboard_widget_blocked_nodes_error
from app.services.file_run_widget import FILE_RUN_WIDGET_TYPE
from app.services.hitl_widget_service import (
    HITL_WIDGET_TYPE,
    ensure_saved_filter_allowed,
    hidden_hitl_widgets,
    hitl_filters_for_widgets,
)
from app.services.widget_title import DEFAULT_WIDGET_TITLE
from app.services.workflow_dsl_prompt import DASHBOARD_WIDGET_PROMPT_HINT

LIST_DASHBOARDS_TOOL = "list_dashboards"
ADD_DASHBOARD_WIDGET_TOOL = "add_dashboard_widget"
RENAME_DASHBOARD_WIDGET_TOOL = "rename_dashboard_widget"
DELETE_DASHBOARD_WIDGET_TOOL = "delete_dashboard_widget"
TIDY_DASHBOARD_TOOL = "tidy_dashboard"
DASHBOARD_TOOL_NAMES = frozenset(
    {
        LIST_DASHBOARDS_TOOL,
        ADD_DASHBOARD_WIDGET_TOOL,
        RENAME_DASHBOARD_WIDGET_TOOL,
        DELETE_DASHBOARD_WIDGET_TOOL,
        TIDY_DASHBOARD_TOOL,
    }
)

WIDGET_KIND_CHART = "chart"
WIDGET_KIND_RUN = "run"
MAX_WIDGET_TITLE_LENGTH = 255
DEFAULT_EMPTY_CHART_TYPE = "bar"
EMPTY_WIDGET_NEEDS_BUILD_ERROR = (
    "This chat cannot build a widget's workflow. Put an existing workflow on the dashboard "
    "with workflow_id, or build the widget in the Dashboard tab."
)

DASHBOARD_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": LIST_DASHBOARDS_TOOL,
            "description": "List the dashboards the user can open, their own and the ones shared with them, with the widgets on each. Heym Work shows these dashboards as its pages. Each widget has its id, title, chart_type, kind and workflow_id: a chart widget's workflow belongs to that widget alone, a run widget runs an ordinary workflow. Use it when the user asks which dashboards or pages exist, what is on a dashboard, or which dashboard a widget or workflow is on. Pass dashboard_id to read one dashboard, or workflow_id to find the dashboards with a widget that runs that workflow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dashboard_id": {
                        "type": "string",
                        "description": "Optional UUID of one dashboard to read.",
                    },
                    "workflow_id": {
                        "type": "string",
                        "description": "Optional UUID of a workflow: list only the widgets that run it, and the dashboards they are on.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": ADD_DASHBOARD_WIDGET_TOOL,
            "description": "Put a widget on a dashboard, below the widgets already there. To make a new chart widget, omit workflow_id: the dashboard gets an empty widget, and the result gives the widget's workflow_id to write its graph into with save_workflow, then test and finish. Never build a separate workflow to copy onto a dashboard. With workflow_id, an existing workflow is placed instead: one with a chartOutput node becomes a chart widget with its own copy of the workflow, any other a run widget that runs the workflow from the dashboard. Changes to a chart widget always go to the widget's workflow_id from the result. Needs write access to the dashboard; the widget runs as the dashboard's owner. Resolve dashboard_id with list_dashboards and workflow_id with list_workflows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dashboard_id": {
                        "type": "string",
                        "description": "UUID of the dashboard to put the widget on.",
                    },
                    "workflow_id": {
                        "type": "string",
                        "description": "Optional UUID of an existing workflow the widget shows or runs. Omit it for a new, empty chart widget.",
                    },
                    "chart_type": {
                        "type": "string",
                        "enum": list(WIDGET_CHART_TYPES),
                        "description": "For an empty widget: the chart it will draw. hitl lists pending reviews and needs no graph. Default bar.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Widget title: one or two words that say what it shows. Defaults to the workflow's name.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional widget description; defaults to the workflow's.",
                    },
                },
                "required": ["dashboard_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": RENAME_DASHBOARD_WIDGET_TOOL,
            "description": "Rename a widget on a dashboard, and change its description when description is given. A chart widget's workflow takes the new name too; a run widget's workflow keeps its own. Needs write access to the dashboard. Resolve widget_id with list_dashboards.",
            "parameters": {
                "type": "object",
                "properties": {
                    "widget_id": {
                        "type": "string",
                        "description": "UUID of the widget, from list_dashboards.",
                    },
                    "title": {
                        "type": "string",
                        "description": "The widget's new title: one or two words that say what it shows.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional new description.",
                    },
                },
                "required": ["widget_id", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": DELETE_DASHBOARD_WIDGET_TOOL,
            "description": "Delete a widget from its dashboard, for everyone who opens it. A chart widget's workflow and its edit history go with it; a run widget's workflow stays. Call it only when the user asked to delete or remove that widget. Needs write access to the dashboard. Resolve widget_id with list_dashboards.",
            "parameters": {
                "type": "object",
                "properties": {
                    "widget_id": {
                        "type": "string",
                        "description": "UUID of the widget, from list_dashboards.",
                    },
                },
                "required": ["widget_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TIDY_DASHBOARD_TOOL,
            "description": "Rearrange a dashboard's widgets into a tidy grid in their current order, as the Dashboard tab's Tidy up button does: rows of two or three widgets at random, the widgets in a row sharing its width, so calling it again gives another arrangement. Pass per_row for rows of that many widgets. It arranges the dashboard in Heym; Heym Work keeps its own arrangement of a page. Needs write access to the dashboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dashboard_id": {
                        "type": "string",
                        "description": "UUID of the dashboard to tidy.",
                    },
                    "per_row": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_PER_ROW,
                        "description": "Optional number of widgets in every row. Omit it for the random rows of two or three.",
                    },
                },
                "required": ["dashboard_id"],
            },
        },
    },
]

_STEP_LABELS = {
    LIST_DASHBOARDS_TOOL: "Reading dashboards...",
    ADD_DASHBOARD_WIDGET_TOOL: "Adding widget to dashboard...",
    RENAME_DASHBOARD_WIDGET_TOOL: "Renaming widget...",
    DELETE_DASHBOARD_WIDGET_TOOL: "Deleting widget...",
    TIDY_DASHBOARD_TOOL: "Tidying dashboard...",
}
WIDGET_ID_ERROR = "widget_id must be a widget id from list_dashboards"
DASHBOARD_ID_ERROR = "dashboard_id must be a dashboard id from list_dashboards"


def dashboard_tool_label(name: str) -> str:
    """The progress label the chat shows while a dashboard tool runs."""
    return _STEP_LABELS[name]


def dashboard_url(public_base_url: str, dashboard_id: object) -> str:
    """The dashboard's page in the Dashboard tab."""
    return f"{public_base_url.rstrip('/')}/?tab=dashboard&dashboard={dashboard_id}"


def _uuid_arg(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _widget_kind(widget: DashboardWidget) -> str:
    return WIDGET_KIND_RUN if widget.chart_type == FILE_RUN_WIDGET_TYPE else WIDGET_KIND_CHART


def _widget_entry(widget: DashboardWidget) -> dict[str, Any]:
    return {
        "id": str(widget.id),
        "title": widget.title,
        "description": widget.description,
        "chart_type": widget.chart_type,
        "kind": _widget_kind(widget),
        "workflow_id": str(widget.workflow_id),
    }


def _reading_order(widget: DashboardWidget) -> tuple[int, int, int]:
    layout = widget.layout or {}
    return (widget.position or 0, int(layout.get("y", 0)), int(layout.get("x", 0)))


async def list_dashboards_for_chat(
    db: AsyncSession, user: User, args: dict[str, Any], public_base_url: str
) -> dict[str, Any]:
    """The user's dashboards, owned first, each with the widgets the user may see."""
    dashboard_id = _uuid_arg(args.get("dashboard_id"))
    workflow_id = _uuid_arg(args.get("workflow_id"))
    if args.get("dashboard_id") and dashboard_id is None:
        return {"error": "Invalid dashboard_id"}
    if args.get("workflow_id") and workflow_id is None:
        return {"error": "Invalid workflow_id"}

    shared = await shared_dashboard_permissions(db, user.id)
    reachable = Dashboard.owner_id == user.id
    if shared:
        reachable = or_(reachable, Dashboard.id.in_(list(shared)))
    query = select(Dashboard, User.email).join(User, Dashboard.owner_id == User.id).where(reachable)
    if dashboard_id is not None:
        query = query.where(Dashboard.id == dashboard_id)
    rows = (await db.execute(query.order_by(Dashboard.created_at, Dashboard.id))).all()
    if dashboard_id is not None and not rows:
        return {"error": "Dashboard not found"}

    widgets_query = select(DashboardWidget).where(
        DashboardWidget.dashboard_id.in_([dashboard.id for dashboard, _ in rows])
    )
    if workflow_id is not None:
        widgets_query = widgets_query.where(DashboardWidget.workflow_id == workflow_id)
    widgets = list((await db.execute(widgets_query)).scalars().all()) if rows else []
    hitl_filters = await hitl_filters_for_widgets(db, widgets)
    by_dashboard: dict[uuid.UUID, list[DashboardWidget]] = {}
    for widget in widgets:
        by_dashboard.setdefault(widget.dashboard_id, []).append(widget)

    dashboards: list[dict[str, Any]] = []
    for dashboard, owner_email in rows:
        placed = by_dashboard.get(dashboard.id, [])
        own_filters = {w.id: hitl_filters[w.id] for w in placed if w.id in hitl_filters}
        hidden = await hidden_hitl_widgets(db, own_filters, user.id, dashboard.owner_id)
        visible = sorted((w for w in placed if w.id not in hidden), key=_reading_order)
        if workflow_id is not None and not visible:
            continue
        owned = dashboard.owner_id == user.id
        permission = PERMISSION_OWNER if owned else shared.get(dashboard.id, PERMISSION_READ)
        dashboards.append(
            {
                "id": str(dashboard.id),
                "name": dashboard.name,
                "permission": permission,
                "shared_by": None if owned else owner_email,
                "url": dashboard_url(public_base_url, dashboard.id),
                "widget_count": len(visible),
                "widgets": [_widget_entry(widget) for widget in visible],
            }
        )
    dashboards.sort(key=lambda entry: entry["permission"] != PERMISSION_OWNER)
    return {"count": len(dashboards), "dashboards": dashboards}


def _chart_output_node(nodes: list[Any]) -> dict[str, Any] | None:
    charts = [
        node for node in nodes if isinstance(node, dict) and node.get("type") == "chartOutput"
    ]
    return charts[-1] if charts else None


def _text_arg(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


@dataclass(frozen=True)
class _NewWidget:
    """What a new widget runs, and what it is called."""

    workflow: Workflow
    chart_type: str
    title: str
    description: str | None
    source_id: uuid.UUID | None = None


async def _empty_widget(
    db: AsyncSession, dashboard: Dashboard, args: dict[str, Any], chart_type: str
) -> _NewWidget:
    """A chart widget on the placeholder graph the Dashboard tab starts a widget with."""
    from app.api.dashboards import _seed_widget_nodes

    title = _text_arg(args.get("title"))[:MAX_WIDGET_TITLE_LENGTH] or DEFAULT_WIDGET_TITLE
    description = _text_arg(args.get("description")) or None
    nodes, edges = _seed_widget_nodes(chart_type)
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
    return _NewWidget(workflow, chart_type, title, description)


async def _placed_workflow(
    db: AsyncSession, dashboard: Dashboard, user: User, source: Workflow, args: dict[str, Any]
) -> _NewWidget:
    """A chart widget on a copy of ``source``, or a run widget on ``source`` itself.

    Raises HTTPException when ``source`` cannot be either.
    """
    from app.api.dashboards import _clone_workflow_graph, _file_run_workflow

    title = (
        _text_arg(args.get("title"))[:MAX_WIDGET_TITLE_LENGTH]
        or (source.name or DEFAULT_WIDGET_TITLE)[:MAX_WIDGET_TITLE_LENGTH]
    )
    description = _text_arg(args.get("description")) or source.description or None
    nodes = list(source.nodes or [])
    chart_node = _chart_output_node(nodes)
    if chart_node is None:
        workflow = await _file_run_workflow(db, source.id, dashboard, user)
        return _NewWidget(workflow, FILE_RUN_WIDGET_TYPE, title, description, source.id)
    blocked = dashboard_widget_blocked_nodes_error(nodes)
    if blocked is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=blocked)
    await ensure_saved_filter_allowed(db, user.id, [], nodes)
    cloned_nodes, cloned_edges = _clone_workflow_graph(nodes, list(source.edges or []))
    workflow = Workflow(
        name=title,
        description=description,
        owner_id=dashboard.owner_id,
        kind="dashboard_widget",
        nodes=cloned_nodes,
        edges=cloned_edges,
    )
    db.add(workflow)
    await db.flush()
    chart_type = str((chart_node.get("data") or {}).get("chartType") or "bar")
    return _NewWidget(workflow, chart_type, title, description, source.id)


def _next_step(new: _NewWidget) -> str:
    """What the chat does after putting an empty widget on a dashboard."""
    if new.chart_type == HITL_WIDGET_TYPE:
        return "The widget already lists pending reviews: do not save a graph for it."
    return (
        f"The widget is empty. Write its graph with save_workflow and workflow_id "
        f"{new.workflow.id}, keeping the name {new.title!r}, then test it with "
        "run_workflow_test and finish. Follow widget_rules."
    )


async def add_dashboard_widget_for_chat(
    db: AsyncSession,
    user: User,
    args: dict[str, Any],
    public_base_url: str,
    *,
    can_build: bool,
) -> dict[str, Any]:
    """Put a widget on a dashboard: empty for the chat to fill, or on an existing workflow."""
    # app.api.dashboards imports app.api.ai_assistant, which imports this module.
    from app.api.dashboards import _get_dashboard_for_user

    dashboard_id = _uuid_arg(args.get("dashboard_id"))
    workflow_id = _uuid_arg(args.get("workflow_id"))
    chart_type = str(args.get("chart_type") or DEFAULT_EMPTY_CHART_TYPE)
    if dashboard_id is None:
        return {"error": DASHBOARD_ID_ERROR}
    if args.get("workflow_id") and workflow_id is None:
        return {"error": "workflow_id must be a workflow id from list_workflows"}
    if workflow_id is None and not can_build:
        return {"error": EMPTY_WIDGET_NEEDS_BUILD_ERROR}
    if workflow_id is None and chart_type not in WIDGET_CHART_TYPES:
        return {"error": f"chart_type must be one of {', '.join(WIDGET_CHART_TYPES)}"}

    try:
        dashboard, _ = await _get_dashboard_for_user(db, dashboard_id, user, write=True)
        placed = (
            await db.execute(
                select(DashboardWidget.layout, DashboardWidget.position).where(
                    DashboardWidget.dashboard_id == dashboard.id
                )
            )
        ).all()
        if workflow_id is None:
            new = await _empty_widget(db, dashboard, args, chart_type)
        else:
            source = await get_workflow_for_user(db, workflow_id, user.id)
            if source is None:
                return {"error": "Workflow not found"}
            new = await _placed_workflow(db, dashboard, user, source, args)
    except HTTPException as exc:
        return {"error": str(exc.detail)}

    bottom = max(
        (int((layout or {}).get("y", 0)) + int((layout or {}).get("h", 0)) for layout, _ in placed),
        default=0,
    )
    widget = DashboardWidget(
        dashboard_id=dashboard.id,
        workflow_id=new.workflow.id,
        title=new.title,
        description=new.description,
        chart_type=new.chart_type,
        layout=WidgetLayout(y=bottom).model_dump(),
        position=max((position or 0 for _, position in placed), default=-1) + 1,
    )
    db.add(widget)
    await db.commit()
    await db.refresh(widget)
    audit(
        action="dashboard.widget_create",
        actor=user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
        widget_id=widget.id,
        widget_title=widget.title,
        source_workflow_id=new.source_id,
    )
    result: dict[str, Any] = {
        "created": True,
        "widget": _widget_entry(widget),
        "dashboard": _dashboard_ref(dashboard, public_base_url),
    }
    if workflow_id is None:
        result["next_step"] = _next_step(new)
        result["widget_rules"] = DASHBOARD_WIDGET_PROMPT_HINT.strip()
    return result


def _dashboard_ref(dashboard: Dashboard, public_base_url: str) -> dict[str, str]:
    return {
        "id": str(dashboard.id),
        "name": dashboard.name,
        "url": dashboard_url(public_base_url, dashboard.id),
    }


async def rename_dashboard_widget_for_chat(
    db: AsyncSession, user: User, args: dict[str, Any], public_base_url: str
) -> dict[str, Any]:
    """Rename a widget, as the widget settings do, without renaming a run widget's workflow."""
    from app.api.dashboards import _load_widget_for_user

    widget_id = _uuid_arg(args.get("widget_id"))
    title = _text_arg(args.get("title"))[:MAX_WIDGET_TITLE_LENGTH]
    description = args.get("description")
    if widget_id is None:
        return {"error": WIDGET_ID_ERROR}
    if not title:
        return {"error": "title must not be empty"}
    try:
        widget, dashboard, _ = await _load_widget_for_user(db, widget_id, user, write=True)
    except HTTPException as exc:
        return {"error": str(exc.detail)}

    widget.title = title
    if isinstance(description, str):
        widget.description = description.strip() or None
    workflow = (
        await db.execute(select(Workflow).where(Workflow.id == widget.workflow_id))
    ).scalar_one_or_none()
    # The canvas shows a chart widget's own workflow under the widget's name. A run widget's
    # workflow is an ordinary one the dashboard only runs, so it keeps its name.
    if workflow is not None and workflow.kind == "dashboard_widget":
        workflow.name = widget.title
        if isinstance(description, str):
            workflow.description = widget.description
    await db.commit()
    return {
        "renamed": True,
        "widget": _widget_entry(widget),
        "dashboard": _dashboard_ref(dashboard, public_base_url),
    }


async def delete_dashboard_widget_for_chat(
    db: AsyncSession, user: User, args: dict[str, Any], public_base_url: str
) -> dict[str, Any]:
    """Delete a widget, and a chart widget's workflow with it, as the Dashboard tab does."""
    from app.api.dashboards import _delete_widget, _load_widget_for_user

    widget_id = _uuid_arg(args.get("widget_id"))
    if widget_id is None:
        return {"error": WIDGET_ID_ERROR}
    try:
        widget, dashboard, _ = await _load_widget_for_user(db, widget_id, user, write=True)
    except HTTPException as exc:
        return {"error": str(exc.detail)}

    entry = _widget_entry(widget)
    workflow_deleted = await _delete_widget(db, widget)
    await db.commit()
    audit(
        action="dashboard.widget_delete",
        actor=user,
        target_type="dashboard",
        target_id=dashboard.id,
        target_name=dashboard.name,
        widget_id=widget_id,
        widget_title=entry["title"],
    )
    return {
        "deleted": True,
        "widget": entry,
        "workflow_deleted": workflow_deleted,
        "dashboard": _dashboard_ref(dashboard, public_base_url),
    }


def _per_row_arg(value: object) -> int | None:
    """``per_row`` as a whole number, or None when it was not given. Raises ValueError."""
    if value is None or value == "":
        return None
    per_row = int(str(value))
    if not 1 <= per_row <= MAX_PER_ROW:
        raise ValueError(per_row)
    return per_row


def _grid_layout(widget: DashboardWidget) -> dict[str, Any]:
    saved = widget.layout or {}
    return {key: saved.get(key, default) for key, default in WidgetLayout().model_dump().items()}


async def tidy_dashboard_for_chat(
    db: AsyncSession, user: User, args: dict[str, Any], public_base_url: str
) -> dict[str, Any]:
    """Arrange the widgets the user sees, in their order, as the Tidy up button does."""
    from app.api.dashboards import _get_dashboard_for_user

    dashboard_id = _uuid_arg(args.get("dashboard_id"))
    if dashboard_id is None:
        return {"error": DASHBOARD_ID_ERROR}
    try:
        per_row = _per_row_arg(args.get("per_row"))
    except ValueError:
        return {"error": f"per_row must be a whole number from 1 to {MAX_PER_ROW}"}
    try:
        dashboard, _ = await _get_dashboard_for_user(db, dashboard_id, user, write=True)
    except HTTPException as exc:
        return {"error": str(exc.detail)}

    widgets = list(
        (
            await db.execute(
                select(DashboardWidget).where(DashboardWidget.dashboard_id == dashboard.id)
            )
        )
        .scalars()
        .all()
    )
    hitl_filters = await hitl_filters_for_widgets(db, widgets)
    hidden = await hidden_hitl_widgets(db, hitl_filters, user.id, dashboard.owner_id)
    ordered = sorted((w for w in widgets if w.id not in hidden), key=_reading_order)
    if not ordered:
        return {"error": "This dashboard has no widgets to tidy"}

    tidy = tidy_layouts([_grid_layout(widget) for widget in ordered], per_row)
    for widget, layout in zip(ordered, tidy.layouts, strict=True):
        widget.layout = layout
    await db.commit()
    return {
        "tidied": True,
        "widget_count": len(ordered),
        "rows": tidy.rows,
        "dashboard": _dashboard_ref(dashboard, public_base_url),
    }


async def call_dashboard_tool(
    db: AsyncSession,
    user: User,
    name: str,
    args: dict[str, Any],
    public_base_url: str,
    *,
    can_build: bool,
) -> dict[str, Any]:
    """Run one dashboard tool and return its result.

    ``can_build`` says whether the turn can save workflows, which filling an empty widget needs.
    """
    if name == LIST_DASHBOARDS_TOOL:
        return await list_dashboards_for_chat(db, user, args, public_base_url)
    if name == RENAME_DASHBOARD_WIDGET_TOOL:
        return await rename_dashboard_widget_for_chat(db, user, args, public_base_url)
    if name == DELETE_DASHBOARD_WIDGET_TOOL:
        return await delete_dashboard_widget_for_chat(db, user, args, public_base_url)
    if name == TIDY_DASHBOARD_TOOL:
        return await tidy_dashboard_for_chat(db, user, args, public_base_url)
    return await add_dashboard_widget_for_chat(db, user, args, public_base_url, can_build=can_build)


def summarize_dashboard_tool(name: str, data: object) -> str:
    """A short line for the run history step of a dashboard tool."""
    if not isinstance(data, dict):
        return str(data)[:200]
    if data.get("error"):
        return f"Error: {str(data['error'])[:150]}"
    if name == LIST_DASHBOARDS_TOOL:
        widgets = sum(len(entry.get("widgets") or []) for entry in data.get("dashboards") or [])
        return f"{int(data.get('count') or 0)} dashboard(s), {widgets} widget(s) listed"
    widget = data.get("widget") or {}
    dashboard = data.get("dashboard") or {}
    if name == RENAME_DASHBOARD_WIDGET_TOOL:
        return f"Renamed widget to {widget.get('title')!r} on dashboard {dashboard.get('name')!r}"
    if name == DELETE_DASHBOARD_WIDGET_TOOL:
        return f"Deleted widget {widget.get('title')!r} from dashboard {dashboard.get('name')!r}"
    if name == TIDY_DASHBOARD_TOOL:
        rows = ", ".join(str(size) for size in data.get("rows") or [])
        return (
            f"Tidied {int(data.get('widget_count') or 0)} widget(s) on dashboard "
            f"{dashboard.get('name')!r} into rows of {rows}"
        )
    return (
        f"Added {widget.get('kind')} widget {widget.get('title')!r} "
        f"to dashboard {dashboard.get('name')!r}"
    )
