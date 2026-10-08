"""Plan a dashboard page's widgets from a description of the page.

The plan is a short list of proposals; each one's prompt is what the per-widget AI generate
endpoint builds a widget from, so a client can let the user pick and then build them in
parallel. One proposal is always a table whose rows open a detail page: it carries the detail
page's widgets, which read the clicked row's record as ``$page.record``.
"""

import json
import re
import uuid
from dataclasses import dataclass, replace
from typing import Any

from app.db.models import User
from app.services.encryption import decrypt_config
from app.services.llm_provider import is_reasoning_model
from app.services.llm_service import execute_llm
from app.services.llm_trace import LLMTraceContext
from app.services.model_router import build_router_for_credential

MAX_PROPOSALS = 6
MAX_DETAIL_WIDGETS = 4
MAX_EXAMPLE_POINTS = 8
MAX_TITLE_LENGTH = 80
MAX_PROMPT_LENGTH = 2000
MAX_FIELD_LENGTH = 255
PLAN_TEMPERATURE = 0.4
WIDGET_CHART_TYPES = (
    "pie",
    "bar",
    "line",
    "area",
    "table",
    "numeric",
    "gauge",
    "scatter",
    "proportion",
    "barGauge",
    "text",
    "hitl",
)

PLAN_SYSTEM_PROMPT = f"""You plan a dashboard page in Heym. A page is a grid of widgets. Each
widget is built later, on its own, by a workflow builder that reads one instruction and ends
the workflow in a single chart.

Propose between 3 and {MAX_PROPOSALS} widgets that together answer the page description. Do not
propose two widgets that show the same thing.

Answer with JSON only, no prose:
{{"widgets": [{{"title": "...", "chartType": "...", "prompt": "...", "example": {{...}}}},
  {{"title": "...", "chartType": "table", "prompt": "...", "detail": {{"title": "...",
    "recordField": "...", "labelField": "...", "widgets": [{{"title": "...",
    "chartType": "...", "prompt": "...", "example": {{...}}}}]}}}}]}}

- title: at most six words, sentence case.
- chartType: one of {", ".join(WIDGET_CHART_TYPES)}. Use numeric for one headline number,
  table for a list of records, text for notes or checklists, hitl for pending human reviews.
- prompt: one or two sentences for the builder: what the widget shows, which data it uses,
  how it is grouped or filtered, and the chart type. When the description names no data
  source, say the widget uses sample data.
- example: a preview of what the widget will show, {{"labels": [...], "values": [...]}} with
  at most {MAX_EXAMPLE_POINTS} labels and one number per label (one label and one value for
  numeric). Omit it for table, text and hitl.

Always propose exactly one table whose rows a viewer clicks to open a detail page about that
row's record, with "detail" set. Choose the records that matter most for the description (an
invoice, a case, a customer, an order).
- detail.title: the detail page's name, at most four words, such as "Invoice details".
- detail.recordField: the column whose value identifies a record: an id, a number or a code
  made of letters, digits, "-", "_" or "." (never an email address or free text). The table
  shows this column.
- detail.labelField: the column that names a record for people, such as a name or a title, or
  null when the record field says enough.
- detail.widgets: 2 to {MAX_DETAIL_WIDGETS} widgets for the detail page, shaped like the page's
  widgets but without detail. Each one shows the one record the page is about: its prompt says
  the widget reads the record's value from $page.record and keeps only the data whose
  recordField equals it.
- With sample data, list the same sample records (for example ids INV-001 to INV-005) in the
  table's prompt and in every detail widget's prompt, so a clicked row finds its record.

When data tables are given, every widget reads one or more of them, and together the widgets
cover the tables that matter for the description: work from their real columns and values
(group by a column such as a source or a status, count rows, sum a number column, compare or
join tables on a shared column), name each table a widget reads with its dataTableId in its
prompt so the builder reads it with a dataTable node, never propose sample data, and draw each
example from the values and counts you were shown.

Write the titles and prompts in the language of the description."""

_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass(frozen=True)
class WidgetExample:
    """A widget's preview: one value per label."""

    labels: list[str]
    values: list[float]


@dataclass(frozen=True)
class DetailPagePlan:
    """The detail page a table's rows open: the record column, its label and the page's widgets."""

    title: str
    record_field: str
    label_field: str | None
    widgets: list["WidgetProposal"]


@dataclass(frozen=True)
class WidgetProposal:
    """One widget the page could have, with a preview when the model sketched one.

    ``detail`` is set on the one table whose rows open a detail page.
    """

    title: str
    chart_type: str
    prompt: str
    example: WidgetExample | None = None
    detail: DetailPagePlan | None = None


def _json_object(text: str) -> dict[str, Any] | None:
    fenced = _FENCED.search(text)
    candidate = fenced.group(1) if fenced else text[text.find("{") : text.rfind("}") + 1]
    try:
        value = json.loads(candidate)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def parse_widget_example(value: Any) -> WidgetExample | None:
    """A preview with as many numbers as labels, at most eight, or None."""
    if not isinstance(value, dict):
        return None
    labels, values = value.get("labels"), value.get("values")
    if not isinstance(labels, list) or not isinstance(values, list) or not labels:
        return None
    if len(labels) != len(values) or len(labels) > MAX_EXAMPLE_POINTS:
        return None
    numbers = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(numbers) != len(values):
        return None
    return WidgetExample(
        labels=[str(label)[:40] for label in labels], values=[float(n) for n in numbers]
    )


def _with_sentence(prompt: str, sentence: str) -> str:
    """``prompt`` with ``sentence`` after it, cut so the whole fits what ai-generate takes."""
    room = MAX_PROMPT_LENGTH - len(sentence) - 1
    return f"{prompt[:room].rstrip()} {sentence}"


def _parse_proposal(item: Any) -> WidgetProposal | None:
    """One proposal without its detail page, or None when it has no title or prompt."""
    if not isinstance(item, dict):
        return None
    title = str(item.get("title") or "").strip()[:MAX_TITLE_LENGTH]
    prompt = str(item.get("prompt") or "").strip()[:MAX_PROMPT_LENGTH]
    if not title or not prompt:
        return None
    chart_type = str(item.get("chartType") or item.get("chart_type") or "")
    return WidgetProposal(
        title=title,
        chart_type=chart_type if chart_type in WIDGET_CHART_TYPES else "bar",
        prompt=prompt,
        example=parse_widget_example(item.get("example")),
    )


def _field(value: Any) -> str:
    return str(value or "").strip()[:MAX_FIELD_LENGTH]


def parse_detail_page(value: Any, table_title: str) -> DetailPagePlan | None:
    """The detail page a table's rows open, or None without a record field or a widget.

    Each detail widget's prompt is made to name ``$page.record``, so its workflow reads the
    clicked row's record even when the model forgot to say so.
    """
    if not isinstance(value, dict):
        return None
    record_field = _field(value.get("recordField") or value.get("record_field"))
    if not record_field:
        return None
    label_field = _field(value.get("labelField") or value.get("label_field")) or None
    items = value.get("widgets")
    widgets: list[WidgetProposal] = []
    for item in items if isinstance(items, list) else []:
        proposal = _parse_proposal(item)
        if proposal is None:
            continue
        if "$page.record" not in proposal.prompt:
            sentence = (
                f"On this detail page, read the record's {record_field} from $page.record and "
                "show only that record's data."
            )
            proposal = replace(proposal, prompt=_with_sentence(proposal.prompt, sentence))
        widgets.append(proposal)
    if not widgets:
        return None
    title = str(value.get("title") or "").strip()[:MAX_TITLE_LENGTH]
    return DetailPagePlan(
        title=title or f"{table_title} details"[:MAX_TITLE_LENGTH],
        record_field=record_field,
        label_field=label_field,
        widgets=widgets[:MAX_DETAIL_WIDGETS],
    )


def _row_link_sentence(detail: DetailPagePlan) -> str:
    label = f" and the {detail.label_field} column" if detail.label_field else ""
    return (
        f"Show the {detail.record_field} column{label}: clicking a row opens the record's "
        f"detail page with its {detail.record_field} value."
    )


def parse_widget_plan(text: str) -> list[WidgetProposal]:
    """The proposals in a model's answer; malformed items are dropped, at most six are kept.

    The first valid detail page is kept, on a table whose prompt names the record column, and
    it stays among the six; any other detail page is dropped.
    """
    data = _json_object(text) or {}
    items = data.get("widgets")
    proposals: list[WidgetProposal] = []
    linked: WidgetProposal | None = None
    for item in items if isinstance(items, list) else []:
        proposal = _parse_proposal(item)
        if proposal is None:
            continue
        detail = parse_detail_page(item.get("detail"), proposal.title) if linked is None else None
        if detail is not None:
            proposal = replace(
                proposal,
                chart_type="table",
                example=None,
                prompt=_with_sentence(proposal.prompt, _row_link_sentence(detail)),
                detail=detail,
            )
            linked = proposal
        proposals.append(proposal)
    kept = proposals[:MAX_PROPOSALS]
    if linked is not None and all(proposal is not linked for proposal in kept):
        kept = [*kept[: MAX_PROPOSALS - 1], linked]
    return kept


async def plan_dashboard_widgets(
    description: str,
    *,
    credential: Any,
    model: str,
    user: User,
    session_id: uuid.UUID | None = None,
    data_context: str = "",
) -> list[WidgetProposal]:
    """Ask the model for the widgets a page described as `description` should have.

    `session_id` keeps the plan and the widgets built from it in one OpenCode session.
    `data_context` describes the data tables the page uses (`describe_tables`).
    """
    config = decrypt_config(credential.encrypted_config)
    router = build_router_for_credential(
        credential_id=str(credential.id),
        credential_name=credential.name,
        credential_type=credential.type.value,
        config=config,
    )
    raw_base_url = config.get("base_url")
    result = await execute_llm(
        credential_type=credential.type.value,
        api_key=str(config.get("api_key") or ""),
        base_url=str(raw_base_url) if raw_base_url else None,
        model=model,
        system_instruction=PLAN_SYSTEM_PROMPT,
        user_message=f"Page description:\n{description}"
        + (f"\n\n{data_context}" if data_context else ""),
        temperature=None if is_reasoning_model(model) else PLAN_TEMPERATURE,
        trace_context=LLMTraceContext(
            user_id=user.id,
            credential_id=credential.id,
            source="dashboard_widget_plan",
            node_label="AI Page Plan",
            session_id=str(session_id) if session_id else None,
        ),
        router=router,
    )
    return parse_widget_plan(str(result.get("text") or ""))
