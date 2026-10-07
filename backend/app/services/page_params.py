"""Page parameters: the record a dashboard detail page passes to its widget workflows.

A dashboard opened with ``?record=<value>`` runs every widget workflow with the value
under ``PAGE_INPUT_KEY`` in the run's inputs, so it travels with the run through the
cluster run queue and HITL resume snapshots, and expressions read it as
``$page.record``. Widget workflows have no trigger node, so ordinary inputs would
reach no node.
"""

from typing import Any

PAGE_INPUT_KEY = "__heym_page"
PAGE_CONTEXT_NAME = "page"


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
