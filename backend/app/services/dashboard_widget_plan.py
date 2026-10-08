"""Plan a dashboard page's widgets from a description of the page.

The plan is a short list of proposals; each one's prompt is what the per-widget AI generate
endpoint builds a widget from, so a client can let the user pick and then build them in
parallel.
"""

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.db.models import User
from app.services.encryption import decrypt_config
from app.services.llm_provider import is_reasoning_model
from app.services.llm_service import execute_llm
from app.services.llm_trace import LLMTraceContext
from app.services.model_router import build_router_for_credential

MAX_PROPOSALS = 6
MAX_EXAMPLE_POINTS = 8
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
{{"widgets": [{{"title": "...", "chartType": "...", "prompt": "...", "example": {{...}}}}]}}

- title: at most six words, sentence case.
- chartType: one of {", ".join(WIDGET_CHART_TYPES)}. Use numeric for one headline number,
  table for a list of records, text for notes or checklists, hitl for pending human reviews.
- prompt: one or two sentences for the builder: what the widget shows, which data it uses,
  how it is grouped or filtered, and the chart type. When the description names no data
  source, say the widget uses sample data.
- example: a preview of what the widget will show, {{"labels": [...], "values": [...]}} with
  at most {MAX_EXAMPLE_POINTS} labels and one number per label (one label and one value for
  numeric). Omit it for table, text and hitl.

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
class WidgetProposal:
    """One widget the page could have, with a preview when the model sketched one."""

    title: str
    chart_type: str
    prompt: str
    example: WidgetExample | None = None


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


def parse_widget_plan(text: str) -> list[WidgetProposal]:
    """The proposals in a model's answer; malformed items are dropped, at most six are kept."""
    data = _json_object(text) or {}
    items = data.get("widgets")
    proposals: list[WidgetProposal] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:80]
        prompt = str(item.get("prompt") or "").strip()[:2000]
        if not title or not prompt:
            continue
        chart_type = str(item.get("chartType") or item.get("chart_type") or "")
        proposals.append(
            WidgetProposal(
                title=title,
                chart_type=chart_type if chart_type in WIDGET_CHART_TYPES else "bar",
                prompt=prompt,
                example=parse_widget_example(item.get("example")),
            )
        )
    return proposals[:MAX_PROPOSALS]


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
