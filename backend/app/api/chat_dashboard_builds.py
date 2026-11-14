"""Dashboard widgets the chat builds or changes several at a time, with Heym's widget generator.

``build_dashboard_widgets`` builds a dashboard's widgets in parallel with the generator behind the
Dashboard tab's AI widget and Heym Work's page wizard, so one call fills a new dashboard. Each
widget is saved as soon as its graph is ready, and its first data is checked: a widget that shows
nothing goes back to the generator once with the reason, as the page wizard does.

``refine_dashboard_widgets`` applies change requests to several widgets at once, as each widget's
AI fine-tune does: the generator edits the widget's graph, and Edit History keeps the one before.
A change and the fixes after it are one edit with one snapshot, and its ``widget_updated`` events
carry that snapshot as ``previous_version``, so a client can offer to revert the whole change.
Heym Work sends the notes a user left on a page's widgets this way.

The turn streams a ``dashboard`` event for every saved widget, so a client shows the dashboard
filling up while the rest still build. Only the model calls run in parallel: reading the
dashboard's context, saving and checking data use the turn's database session, one at a time.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chat_dashboards import (
    DASHBOARD_ID_ERROR,
    MAX_WIDGET_TITLE_LENGTH,
    WIDGET_ADDED,
    WIDGET_ID_ERROR,
    WIDGET_UPDATED,
    _dashboard_ref,
    _text_arg,
    _uuid_arg,
    _widget_entry,
    dashboard_event,
)
from app.db.models import LLM_CREDENTIAL_TYPES, Dashboard, DashboardWidget, User, Workflow
from app.models.dashboard_schemas import WidgetDataResponse
from app.services.chat_progress import ToolProgress
from app.services.dashboard_data import compute_widget_data
from app.services.dashboard_tidy import tidy_layouts
from app.services.dashboard_widget_plan import WIDGET_CHART_TYPES

logger = logging.getLogger(__name__)

BUILD_DASHBOARD_WIDGETS_TOOL = "build_dashboard_widgets"
REFINE_DASHBOARD_WIDGETS_TOOL = "refine_dashboard_widgets"
DASHBOARD_BUILD_TOOL_NAMES = frozenset(
    {BUILD_DASHBOARD_WIDGETS_TOOL, REFINE_DASHBOARD_WIDGETS_TOOL}
)

MAX_WIDGETS_PER_BUILD = 8
MAX_CHANGES_PER_REFINE = 10
# Model calls at once; the rest wait their turn.
MAX_PARALLEL_GENERATIONS = 4
# How many times a widget that shows nothing goes back to the generator, as in the page wizard.
MAX_DATA_FIXES = 2
# The Dashboard tab's AI widget request takes prompts this long.
MAX_WIDGET_PROMPT_LENGTH = 2000
SHOWN_DATA_CHARS = 600

NEEDS_BUILD_ERROR = (
    "This chat cannot build widgets. Put an existing workflow on the dashboard with "
    "add_dashboard_widget and workflow_id, or build widgets in the Dashboard tab."
)
NEEDS_LLM_CREDENTIAL_ERROR = (
    "Building widgets needs the chat's model to run on an OpenAI, Google or Custom credential. "
    "Add each widget with add_dashboard_widget and write its graph with save_workflow instead."
)
TABLE_IDS_ERROR = "data_table_ids must be data table ids from list_data_tables"

DASHBOARD_BUILD_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": BUILD_DASHBOARD_WIDGETS_TOOL,
            "description": f"Build up to {MAX_WIDGETS_PER_BUILD} new chart widgets on a dashboard at once, in parallel, with Heym's widget generator: the one behind the Dashboard tab's AI widget and Heym Work's page wizard. Each widget is saved when it is ready, below the widgets already there and in the order given; its data is checked and a widget that shows nothing is fixed once. Use it to fill a new dashboard or to add several widgets; for one widget it works too. Describe each widget in prompt: what it shows, from which data, grouped or filtered how. Pass the data_table_ids it reads (from list_data_tables) so the generator sees the columns. Needs write access to the dashboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dashboard_id": {
                        "type": "string",
                        "description": "UUID of the dashboard, from create_dashboard or list_dashboards.",
                    },
                    "widgets": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_WIDGETS_PER_BUILD,
                        "description": "The widgets, in the order they appear on the dashboard.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "One or two words that say what the widget shows.",
                                },
                                "prompt": {
                                    "type": "string",
                                    "description": "What the widget shows and from which data, in a sentence or two.",
                                },
                                "chart_type": {
                                    "type": "string",
                                    "enum": list(WIDGET_CHART_TYPES),
                                    "description": "Optional chart to draw; the generator picks one when omitted.",
                                },
                                "data_table_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Optional UUIDs of the data tables the widget reads.",
                                },
                            },
                            "required": ["title", "prompt"],
                        },
                    },
                },
                "required": ["dashboard_id", "widgets"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": REFINE_DASHBOARD_WIDGETS_TOOL,
            "description": f"Change up to {MAX_CHANGES_PER_REFINE} chart widgets at once, in parallel, as each widget's AI fine-tune does: the generator edits the widget's graph to follow the instruction, and Edit History keeps the graph before, so the change can be reverted. Use it for every requested change to what a widget shows or how it draws it, also when the user lists notes on several widgets in one message: pass them all in one call. Rename with rename_dashboard_widget and delete with delete_dashboard_widget instead. A run widget runs an ordinary workflow and cannot be changed here. Needs write access to the widgets' dashboards. Resolve widget_id with list_dashboards.",
            "parameters": {
                "type": "object",
                "properties": {
                    "changes": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_CHANGES_PER_REFINE,
                        "items": {
                            "type": "object",
                            "properties": {
                                "widget_id": {
                                    "type": "string",
                                    "description": "UUID of the widget, from list_dashboards or the user's message.",
                                },
                                "instruction": {
                                    "type": "string",
                                    "description": "What to change, in the user's words with anything they made clear.",
                                },
                                "data_table_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Optional UUIDs of data tables the changed widget reads.",
                                },
                            },
                            "required": ["widget_id", "instruction"],
                        },
                    },
                },
                "required": ["changes"],
            },
        },
    },
]

_STEP_LABELS = {
    BUILD_DASHBOARD_WIDGETS_TOOL: "Building widgets...",
    REFINE_DASHBOARD_WIDGETS_TOOL: "Changing widgets...",
}


def dashboard_build_tool_label(name: str) -> str:
    """The progress label the chat shows while a widget build tool runs."""
    return _STEP_LABELS[name]


@dataclass(frozen=True)
class WidgetModel:
    """The chat turn's model and credential, which build the widgets too.

    ``session_id`` is the conversation's OpenCode session, so the widget calls share it.
    """

    credential: Any | None
    model: str
    session_id: str | None = None


@dataclass
class _WidgetSpec:
    """One widget to build, as the chat asked for it."""

    index: int
    title: str
    request: str
    data_table_ids: list[uuid.UUID]


@dataclass(eq=False)
class _Slot:
    """One widget of a build or one change of a refine, and what happened to it; compared by
    identity."""

    label: str
    # What the widget should show, in the chat's words; a fix keeps to it.
    goal: str = ""
    data_table_ids: list[uuid.UUID] = field(default_factory=list)
    prompt: str = ""
    dashboard: Dashboard | None = None
    widget: DashboardWidget | None = None
    workflow: Workflow | None = None
    # A detail page's widgets read the record a row opens it with; there is none to check with.
    check: bool = True
    error: str | None = None
    # Why the widget's data still shows nothing, after the fixes it had; None when it shows data.
    problem: str | None = None
    fixes: int = 0
    # The Edit History snapshot from before this call's first change to the widget.
    version: int | None = None
    # A widget that existed before the call, so reverting to ``version`` undoes the change.
    revertible: bool = False
    # Where a new widget goes: its grid layout and position on the dashboard.
    layout: dict[str, int] | None = None
    position: int | None = None
    title: str = ""


def _table_ids_arg(value: object) -> list[uuid.UUID] | None:
    """Data table ids from the arguments, or None when one is not an id."""
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    ids = [_uuid_arg(item) for item in value]
    return None if any(item is None for item in ids) else [item for item in ids if item]


def _widget_specs(raw: object) -> list[_WidgetSpec] | str:
    """The widgets to build, or what is wrong with the arguments."""
    if not isinstance(raw, list) or not raw:
        return f"widgets must list 1 to {MAX_WIDGETS_PER_BUILD} widgets"
    if len(raw) > MAX_WIDGETS_PER_BUILD:
        return (
            f"widgets lists {len(raw)} widgets; build at most {MAX_WIDGETS_PER_BUILD} per call "
            "and call again for the rest"
        )
    specs: list[_WidgetSpec] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            return f"widgets[{index}] must be an object with a title and a prompt"
        prompt = _text_arg(item.get("prompt"))[:MAX_WIDGET_PROMPT_LENGTH]
        if not prompt:
            return f"widgets[{index}].prompt must say what the widget shows"
        chart_type = _text_arg(item.get("chart_type"))
        if chart_type and chart_type not in WIDGET_CHART_TYPES:
            return f"widgets[{index}].chart_type must be one of {', '.join(WIDGET_CHART_TYPES)}"
        table_ids = _table_ids_arg(item.get("data_table_ids"))
        if table_ids is None:
            return f"widgets[{index}].{TABLE_IDS_ERROR}"
        title = _text_arg(item.get("title"))[:MAX_WIDGET_TITLE_LENGTH]
        request = f"{prompt}\n\nDraw it as a {chart_type} chart." if chart_type else prompt
        if title:
            request = f"Widget title: {title}.\n\n{request}"
        specs.append(_WidgetSpec(index, title, request, table_ids))
    return specs


def _credential_error(llm: WidgetModel) -> str | None:
    credential = llm.credential
    if credential is None or getattr(credential, "type", None) not in LLM_CREDENTIAL_TYPES:
        return NEEDS_LLM_CREDENTIAL_ERROR
    return None


def _has_value(value: object) -> bool:
    return value is not None and value != ""


def _flat(values: list[Any]) -> list[Any]:
    flat: list[Any] = []
    for value in values:
        flat.extend(value if isinstance(value, list) else [value])
    return flat


def _all_zero(values: list[Any]) -> bool:
    try:
        return all(float(value) == 0 for value in values)
    except (TypeError, ValueError):
        return False


def empty_reason(data: WidgetDataResponse) -> str | None:
    """Why a widget's first data shows nothing, said to the model that fixes it; None when it
    shows data. Mirrors Heym Work's page wizard (``widgetBuild.ts``)."""
    if data.error:
        return f"The widget's workflow failed: {data.error}"
    payload = data.payload
    if not payload:
        return "The widget returned no data."
    chart_type = payload.get("type")
    if chart_type in ("fileRun", "hitl"):
        return None
    if chart_type == "text":
        return None if str(payload.get("text") or "").strip() else "The widget's text is empty."
    if chart_type in ("numeric", "gauge"):
        return None if _has_value(payload.get("value")) else "The widget's value is empty."
    if chart_type == "table":
        return None if payload.get("rows") else "The widget's table has no rows."
    values = [
        value
        for series in payload.get("series") or []
        if isinstance(series, dict)
        for value in _flat(list(series.get("data") or []))
        if _has_value(value)
    ]
    if not values:
        return "The widget's chart has no values."
    # Every value 0 almost always means the wrong column, or a filter that drops every row.
    return "Every value in the widget's chart is 0." if _all_zero(values) else None


def fix_prompt(reason: str, data: WidgetDataResponse, goal: str = "") -> str:
    """What the generator is asked to fix when a widget shows nothing, with what it returned."""
    shown = json.dumps(data.payload, default=str)
    if len(shown) > SHOWN_DATA_CHARS:
        shown = shown[:SHOWN_DATA_CHARS] + "..."
    prompt = (
        f"{reason} It returned: {shown}. Find why and fix the workflow so the chart shows the "
        "real data: a dataTable node's columns are under each row's data, the chartOutput "
        "fields (labelField, valueField, series, value or text) must match the names in the "
        "rows it receives, filters must match values that exist, and every dataTableId and "
        "column must exist. If a node cannot run here at all, for example because the Code "
        "node's sandbox is unavailable, build that step with other nodes, such as a set node "
        "with expressions, instead of the same node again. If the data source itself has no "
        "rows yet, change nothing. Keep the chart type and what the widget shows."
    )
    return f"The widget should show: {goal}\n\n{prompt}" if goal else prompt


class _Generator:
    """The turn's model, building widget graphs a few at a time."""

    def __init__(self, llm: WidgetModel, user: User) -> None:
        self._llm = llm
        self._user = user
        self._gate = asyncio.Semaphore(MAX_PARALLEL_GENERATIONS)

    async def graph(
        self,
        prompt: str,
        *,
        current: dict[str, Any] | None = None,
        workflow_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        from app.api.dashboards import generate_widget_dsl

        async with self._gate:
            return await generate_widget_dsl(
                prompt,
                credential=self._llm.credential,
                model=self._llm.model,
                user=self._user,
                current_workflow=current,
                workflow_id=workflow_id,
                node_label="AI Widget Fine-tune" if current else "AI Widget Create",
                session_id=self._llm.session_id,
            )


def _failure(exc: BaseException) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    logger.warning("Chat widget generation failed: %s", exc)
    return "The model could not build this widget. Try again, or describe it in other words."


class _Tasks:
    """Model calls in flight, each with the slot and step it belongs to."""

    def __init__(self) -> None:
        self.pending: dict[asyncio.Future[Any], tuple[str, _Slot]] = {}

    def start(self, step: str, slot: _Slot, call: Awaitable[dict[str, Any]]) -> None:
        self.pending[asyncio.ensure_future(call)] = (step, slot)

    async def next_done(self) -> list[tuple[str, _Slot, dict[str, Any] | None, str | None]]:
        """The calls that finished, each with its graph or why it failed."""
        done, _ = await asyncio.wait(self.pending, return_when=asyncio.FIRST_COMPLETED)
        finished: list[tuple[str, _Slot, dict[str, Any] | None, str | None]] = []
        for task in done:
            step, slot = self.pending.pop(task)
            exc = task.exception()
            finished.append(
                (step, slot, None, _failure(exc)) if exc else (step, slot, task.result(), None)
            )
        return finished

    def cancel(self) -> None:
        for task in self.pending:
            task.cancel()
        self.pending.clear()


def _new_layouts(count: int, top: int) -> list[dict[str, int]]:
    """Tidy rows for ``count`` new widgets, below the ones already on the dashboard."""
    rows = tidy_layouts([{"x": 0, "y": 0, "w": 4, "h": 4}] * count).layouts
    return [{**layout, "y": layout["y"] + top} for layout in rows]


async def _placement(db: AsyncSession, dashboard: Dashboard) -> tuple[int, int]:
    """The first free grid row below the dashboard's widgets, and the next position."""
    placed = (
        await db.execute(
            select(DashboardWidget.layout, DashboardWidget.position).where(
                DashboardWidget.dashboard_id == dashboard.id
            )
        )
    ).all()
    bottom = max(
        (int((layout or {}).get("y", 0)) + int((layout or {}).get("h", 0)) for layout, _ in placed),
        default=0,
    )
    position = max((position or 0 for _, position in placed), default=-1) + 1
    return bottom, position


def _api() -> Any:
    """``app.api.dashboards``, imported when used: it imports the chat, which imports this."""
    from app.api import dashboards

    return dashboards


async def _data_problem(
    db: AsyncSession, widget: DashboardWidget, dashboard: Dashboard
) -> tuple[str, WidgetDataResponse] | None:
    """Why a widget's data shows nothing, with what it returned; None when it shows data or the
    check itself failed (the widget card then shows its own error)."""
    try:
        data = await compute_widget_data(db, widget, dashboard.owner_id, force=True)
    except Exception as exc:  # noqa: BLE001 - a failed check leaves the widget as it is
        logger.warning("Checking a chat-built widget's data failed: %s", exc)
        return None
    reason = empty_reason(data)
    return (reason, data) if reason else None


class _Batch:
    """Widgets saved one at a time while their graphs are generated in parallel.

    Every saved widget's data is checked; while it shows nothing it goes back to the generator
    with the reason, at most ``MAX_DATA_FIXES`` times, and is checked again after each fix.
    """

    def __init__(
        self, db: AsyncSession, user: User, llm: WidgetModel, progress: ToolProgress
    ) -> None:
        self.db = db
        self.user = user
        self.progress = progress
        self.generator = _Generator(llm, user)
        self.tasks = _Tasks()

    def emit(self, action: str, slot: _Slot) -> None:
        widget = slot.widget
        if widget is not None:
            self.progress.emit(
                dashboard_event(
                    action,
                    widget.dashboard_id,
                    widget_id=widget.id,
                    title=widget.title,
                    previous_version=slot.version if slot.revertible else None,
                )
            )

    async def verify(self, slot: _Slot) -> None:
        """Check a saved widget's data, and send it back to be fixed while it shows nothing."""
        if not slot.check or slot.widget is None or slot.dashboard is None:
            return
        found = await _data_problem(self.db, slot.widget, slot.dashboard)
        if found is None:
            slot.problem = None
            return
        reason, data = found
        slot.problem = reason
        if slot.fixes >= MAX_DATA_FIXES:
            return
        dashboards = _api()
        try:
            slot.workflow = await dashboards._load_widget_workflow(self.db, slot.widget)
            prompt = await dashboards.widget_refine_prompt(
                self.db,
                slot.widget,
                slot.dashboard,
                self.user,
                fix_prompt(reason, data, slot.goal),
                slot.data_table_ids,
                None,
            )
        except HTTPException:
            return
        slot.fixes += 1
        self.refine(slot, prompt, step="fix")

    def refine(self, slot: _Slot, prompt: str, *, step: str) -> None:
        """Generate a new graph for a saved widget from its current one."""
        dashboards = _api()
        workflow = slot.workflow
        if workflow is None:
            return
        self.tasks.start(
            step,
            slot,
            self.generator.graph(
                prompt,
                current=dashboards.widget_workflow_snapshot(workflow),
                workflow_id=workflow.id,
            ),
        )

    async def _save_new(self, slot: _Slot, dsl: dict[str, Any]) -> bool:
        try:
            slot.widget = await _api().save_generated_widget(
                self.db,
                slot.dashboard,
                self.user,
                dsl,
                prompt=slot.goal,
                title=slot.title or None,
                layout=slot.layout,
                position=slot.position,
            )
        except HTTPException as exc:
            slot.error = str(exc.detail)
            return False
        self.emit(WIDGET_ADDED, slot)
        return True

    async def _apply(self, slot: _Slot, dsl: dict[str, Any], *, record_error: bool) -> bool:
        try:
            # One snapshot per widget per call: a fix belongs to the change it fixes, so the
            # newest snapshot stays the graph from before the change and reverts all of it.
            version = await _api().apply_refined_widget(
                self.db, slot.widget, slot.workflow, self.user, dsl, snapshot=slot.version is None
            )
        except HTTPException as exc:
            if record_error:
                slot.error = str(exc.detail)
            return False
        if slot.version is None:
            slot.version = version
        self.emit(WIDGET_UPDATED, slot)
        return True

    async def run(self, report: Any) -> None:
        """Take each finished model call until none is left; ``report()`` updates progress."""
        try:
            while self.tasks.pending:
                for step, slot, dsl, error in await self.tasks.next_done():
                    if dsl is None:
                        # A failed fix leaves the widget, and its problem, as it is.
                        if step != "fix":
                            slot.error = error
                        continue
                    if step == "create":
                        saved = await self._save_new(slot, dsl)
                    else:
                        saved = await self._apply(slot, dsl, record_error=step == "refine")
                    if saved:
                        await self.verify(slot)
                report()
        finally:
            self.tasks.cancel()


def _still_failing(slots: list[_Slot]) -> list[dict[str, str]]:
    return [
        {"widget_id": str(slot.widget.id), "title": slot.widget.title, "error": slot.problem}
        for slot in slots
        if slot.widget is not None and slot.problem and not slot.error
    ]


def _slot_failures(slots: list[_Slot]) -> list[dict[str, str]]:
    return [{"title": slot.label, "error": slot.error} for slot in slots if slot.error]


def _with_still_failing(result: dict[str, Any], slots: list[_Slot]) -> dict[str, Any]:
    failing = _still_failing(slots)
    if failing:
        result["still_failing"] = failing
        result["still_failing_next_step"] = (
            f"These widgets are saved but still show an error or no data after "
            f"{MAX_DATA_FIXES} automatic fixes. Call refine_dashboard_widgets once for them, "
            "each with an instruction that builds it a different way and avoids what the error "
            "names (for example a node that cannot run here). If one still fails after that, "
            "tell the user which widget and why."
        )
    return result


def _plural(count: int) -> str:
    return "s" if count != 1 else ""


async def build_dashboard_widgets_for_chat(
    db: AsyncSession,
    user: User,
    args: dict[str, Any],
    public_base_url: str,
    *,
    can_build: bool,
    llm: WidgetModel,
    progress: ToolProgress,
) -> dict[str, Any]:
    """Build several widgets on a dashboard at once; see the module docstring."""
    dashboards = _api()
    if not can_build:
        return {"error": NEEDS_BUILD_ERROR}
    dashboard_id = _uuid_arg(args.get("dashboard_id"))
    if dashboard_id is None:
        return {"error": DASHBOARD_ID_ERROR}
    specs = _widget_specs(args.get("widgets"))
    if isinstance(specs, str):
        return {"error": specs}
    credential_error = _credential_error(llm)
    if credential_error:
        return {"error": credential_error}
    try:
        dashboard, _ = await dashboards._get_dashboard_for_user(db, dashboard_id, user, write=True)
    except HTTPException as exc:
        return {"error": str(exc.detail)}

    top, first_position = await _placement(db, dashboard)
    layouts = _new_layouts(len(specs), top)
    check = not await dashboards._detail_page_context(db, dashboard, user)
    batch = _Batch(db, user, llm, progress)
    slots: list[_Slot] = []
    for spec in specs:
        slot = _Slot(
            label=spec.title or spec.request[:60],
            goal=spec.request,
            data_table_ids=spec.data_table_ids,
            dashboard=dashboard,
            check=check,
            layout=layouts[spec.index],
            position=first_position + spec.index,
            title=spec.title,
        )
        slots.append(slot)
        try:
            slot.prompt = await dashboards.widget_create_prompt(
                db, dashboard, user, spec.request, spec.data_table_ids
            )
        except HTTPException as exc:
            slot.error = str(exc.detail)
            continue
        batch.tasks.start("create", slot, batch.generator.graph(slot.prompt))

    total = len(specs)
    progress.message = f"Building {total} widget{_plural(total)}"

    def report() -> None:
        built = sum(1 for slot in slots if slot.widget is not None)
        fixing = sum(1 for step, _ in batch.tasks.pending.values() if step == "fix")
        note = f", fixing {fixing}" if fixing else ""
        progress.message = f"Built {built} of {total} widget{_plural(total)}{note}"

    await batch.run(report)

    built_entries = [
        {**_widget_entry(slot.widget), "data_fixes": slot.fixes, "data_problem": slot.problem}
        for slot in slots
        if slot.widget is not None
    ]
    result: dict[str, Any] = {
        "built": built_entries,
        "failed": _slot_failures(slots),
        "dashboard": _dashboard_ref(dashboard, public_base_url),
    }
    if not built_entries:
        result["error"] = "None of the widgets could be built; see failed for why."
        return result
    result["next_step"] = (
        "Tell the user which widgets are on the dashboard and link its url. Try a failed widget "
        "again with build_dashboard_widgets in other words, and change a built one with "
        "refine_dashboard_widgets."
    )
    return _with_still_failing(result, slots)


@dataclass(frozen=True)
class _Change:
    widget_id: uuid.UUID
    instruction: str
    data_table_ids: list[uuid.UUID]


def _change_specs(raw: object) -> list[_Change] | str:
    """The changes, one per widget (several notes on one widget become one instruction), or
    what is wrong with the arguments."""
    if not isinstance(raw, list) or not raw:
        return f"changes must list 1 to {MAX_CHANGES_PER_REFINE} changes"
    by_widget: dict[uuid.UUID, _Change] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            return f"changes[{index}] must be an object with a widget_id and an instruction"
        widget_id = _uuid_arg(item.get("widget_id"))
        if widget_id is None:
            return f"changes[{index}].{WIDGET_ID_ERROR}"
        instruction = _text_arg(item.get("instruction"))
        if not instruction:
            return f"changes[{index}].instruction must say what to change"
        table_ids = _table_ids_arg(item.get("data_table_ids"))
        if table_ids is None:
            return f"changes[{index}].{TABLE_IDS_ERROR}"
        earlier = by_widget.get(widget_id)
        if earlier is not None:
            instruction = f"{earlier.instruction}\n{instruction}"
            table_ids = list(dict.fromkeys([*earlier.data_table_ids, *table_ids]))
        by_widget[widget_id] = _Change(widget_id, instruction[:MAX_WIDGET_PROMPT_LENGTH], table_ids)
    if len(by_widget) > MAX_CHANGES_PER_REFINE:
        return (
            f"changes names {len(by_widget)} widgets; change at most {MAX_CHANGES_PER_REFINE} per "
            "call and call again for the rest"
        )
    return list(by_widget.values())


async def refine_dashboard_widgets_for_chat(
    db: AsyncSession,
    user: User,
    args: dict[str, Any],
    public_base_url: str,
    *,
    can_build: bool,
    llm: WidgetModel,
    progress: ToolProgress,
) -> dict[str, Any]:
    """Change several widgets at once; see the module docstring."""
    dashboards = _api()
    if not can_build:
        return {"error": NEEDS_BUILD_ERROR}
    changes = _change_specs(args.get("changes"))
    if isinstance(changes, str):
        return {"error": changes}
    credential_error = _credential_error(llm)
    if credential_error:
        return {"error": credential_error}

    batch = _Batch(db, user, llm, progress)
    slots: list[_Slot] = []
    reached: dict[uuid.UUID, Dashboard] = {}
    # Whether a dashboard's widgets can be checked: a detail page's need a record.
    checks: dict[uuid.UUID, bool] = {}
    for change in changes:
        slot = _Slot(
            label=str(change.widget_id),
            goal=change.instruction,
            data_table_ids=change.data_table_ids,
            revertible=True,
        )
        slots.append(slot)
        try:
            widget, dashboard, _ = await dashboards._load_widget_for_user(
                db, change.widget_id, user, write=True
            )
            slot.label = widget.title
            dashboards.ensure_refinable(widget)
            slot.workflow = await dashboards._load_widget_workflow(db, widget)
            slot.prompt = await dashboards.widget_refine_prompt(
                db, widget, dashboard, user, change.instruction, change.data_table_ids, None
            )
            if dashboard.id not in checks:
                checks[dashboard.id] = not await dashboards._detail_page_context(
                    db, dashboard, user
                )
            slot.check = checks[dashboard.id]
        except HTTPException as exc:
            slot.error = str(exc.detail)
            continue
        slot.widget, slot.dashboard = widget, dashboard
        reached[dashboard.id] = dashboard
        batch.refine(slot, slot.prompt, step="refine")

    total = len(changes)
    progress.message = f"Changing {total} widget{_plural(total)}"

    def report() -> None:
        changed = sum(1 for slot in slots if slot.version is not None or slot.fixes)
        fixing = sum(1 for step, _ in batch.tasks.pending.values() if step == "fix")
        note = f", fixing {fixing}" if fixing else ""
        progress.message = f"Changed {changed} of {total} widget{_plural(total)}{note}"

    await batch.run(report)

    changed = [slot for slot in slots if slot.widget is not None and not slot.error]
    result: dict[str, Any] = {
        "changed": [
            {
                **_widget_entry(slot.widget),
                "previous_version": slot.version,
                "data_fixes": slot.fixes,
                "data_problem": slot.problem,
            }
            for slot in changed
        ],
        "failed": _slot_failures(slots),
        "dashboards": [_dashboard_ref(item, public_base_url) for item in reached.values()],
    }
    if not changed:
        result["error"] = "None of the widgets could be changed; see failed for why."
        return result
    return _with_still_failing(result, slots)


async def call_dashboard_build_tool(
    db: AsyncSession,
    user: User,
    name: str,
    args: dict[str, Any],
    public_base_url: str,
    *,
    can_build: bool,
    llm: WidgetModel,
    progress: ToolProgress,
) -> dict[str, Any]:
    """Run one widget build tool and return its result."""
    run = (
        build_dashboard_widgets_for_chat
        if name == BUILD_DASHBOARD_WIDGETS_TOOL
        else refine_dashboard_widgets_for_chat
    )
    return await run(
        db, user, args, public_base_url, can_build=can_build, llm=llm, progress=progress
    )


def summarize_dashboard_build_tool(name: str, data: object) -> str:
    """A short line for the run history step of a widget build tool."""
    if not isinstance(data, dict):
        return str(data)[:200]
    failed = len(data.get("failed") or [])
    if data.get("error") and not failed:
        return f"Error: {str(data['error'])[:150]}"
    note = f", {failed} failed" if failed else ""
    if name == BUILD_DASHBOARD_WIDGETS_TOOL:
        dashboard = data.get("dashboard") or {}
        built = data.get("built") or []
        return f"Built {len(built)} widget(s) on dashboard {dashboard.get('name')!r}{note}"
    return f"Changed {len(data.get('changed') or [])} widget(s){note}"
