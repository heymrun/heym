"""Page parameters: the record a dashboard detail page passes to its widget workflows.

A dashboard opened with ``?record=<value>`` runs every widget workflow with the value
under ``PAGE_INPUT_KEY`` in the run's inputs, so it travels with the run through the
cluster run queue and HITL resume snapshots, and expressions read it as
``$page.record``. Widget workflows have no trigger node, so ordinary inputs would
reach no node.
"""

import re
from typing import Any, Literal

PAGE_INPUT_KEY = "__heym_page"
PAGE_CONTEXT_NAME = "page"

# The record comes from a URL anyone can type, so the detail dashboard declares which
# values it accepts and the dashboards API rejects the rest before a workflow runs. The
# formats are fixed patterns: a dashboard owner cannot supply a regular expression,
# which could make the server backtrack for seconds on a crafted value.
RecordFormat = Literal["id", "number", "uuid", "email"]
DEFAULT_RECORD_FORMAT: RecordFormat = "id"
MAX_RECORD_LENGTH = 128
RECORD_FORMATS: dict[str, re.Pattern[str]] = {
    "id": re.compile(r"[A-Za-z0-9._-]{1,128}"),
    "number": re.compile(r"[0-9]{1,32}"),
    "uuid": re.compile(
        r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
    ),
    "email": re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})+"),
}


def is_valid_record(value: str, record_format: str | None) -> bool:
    """Whether ``value`` is a record the dashboard's format accepts."""
    pattern = RECORD_FORMATS.get(record_format or DEFAULT_RECORD_FORMAT)
    if pattern is None or len(value) > MAX_RECORD_LENGTH:
        return False
    return pattern.fullmatch(value) is not None


def page_inputs(record: str | None) -> dict[str, Any]:
    """Run inputs for a widget run on a page opened with ``record`` (None: no record)."""
    return {PAGE_INPUT_KEY: {"record": record}}


def page_params_from_inputs(inputs: Any) -> dict[str, Any] | None:
    """The page parameters a run was started with, or None for a run outside a page."""
    if not isinstance(inputs, dict):
        return None
    params = inputs.get(PAGE_INPUT_KEY)
    return dict(params) if isinstance(params, dict) else None


def preview_page_params(workflow_kind: str | None) -> dict[str, Any] | None:
    """Page parameters for the expression dialog: a widget workflow sees ``$page``.

    The dialog has no page open, so ``$page.record`` previews as null, which is what
    a widget run on a dashboard opened without ``?record=`` produces.
    """
    if workflow_kind == "dashboard_widget":
        return {"record": None}
    return None
