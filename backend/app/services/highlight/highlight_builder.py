"""Pure builder for Canvas execution highlights.

Turns a run's ``node_results`` + workflow graph + run inputs into an
execution-ordered, output-only, per-node highlight payload. This is the single
source of truth used by live runs, history reads, and dashboard widgets.
"""

from __future__ import annotations

import json
from typing import Any

MESSAGE_CHAR_CAP = 100_000
INPUT_NODE_TYPES = {"textInput", "cron"}
OUTPUT_NODE_TYPES = {"output", "jsonOutputMapper", "chartOutput"}


def _is_input_type(node_type: str) -> bool:
    return node_type in INPUT_NODE_TYPES or node_type.endswith("Trigger")


def _extract_message(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        text = output
    elif isinstance(output, dict):
        text = ""
        for key in ("text", "message", "content", "output"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                text = value
                break
        if not text:
            try:
                text = json.dumps(output, ensure_ascii=False)
            except (TypeError, ValueError):
                text = str(output)
    else:
        try:
            text = json.dumps(output, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(output)
    if len(text) > MESSAGE_CHAR_CAP:
        text = text[:MESSAGE_CHAR_CAP]
    return text


def _is_retry_attempt(row: dict) -> bool:
    metadata = row.get("metadata") or {}
    return metadata.get("retry_stage") == "attempt_failed"


def _is_empty_output(output: Any) -> bool:
    """A loop body emits one extra empty iteration past the item count; skip it so
    the per-node run count matches the number of real items."""
    if output is None:
        return True
    if isinstance(output, (dict, list, str)) and len(output) == 0:
        return True
    return False


def _extract_input_message(inputs: dict) -> str:
    """Show the meaningful run input, not the raw request envelope.

    Run inputs are webhook-shaped: ``{"body": {...}, "query": {...}, "headers":
    {...}}``. Prefer ``body`` (the user's payload) and drop query/headers noise.
    """
    source: Any = inputs
    if isinstance(inputs, dict):
        body = inputs.get("body")
        if body not in (None, {}, ""):
            source = body
    return _extract_message(source)


def _order_group(record: dict) -> int:
    """Sort key group so records read in execution order: input, middle, output."""
    kind = record["kind"]
    if kind == "input":
        return 0
    if kind == "final" or (kind == "output" and record["node_type"] in OUTPUT_NODE_TYPES):
        return 2
    return 1


def build_highlight_payload(
    node_results: list[dict],
    nodes: list[dict],
    inputs: dict | None = None,
) -> dict:
    """Return ``{"records": [...]}`` -- output-only, execution-ordered records.

    Rules (each node contributes at most one record):
      * input node (trigger / textInput) -> kind "input", message = run inputs
      * output-type node -> kind "output"
      * if no output-type node ran, the last executed node -> kind "final"
      * agent / llm -> kind "agent" / "llm" (auto, no toggle)
      * any node with ``data.highlight is True`` -> kind "output"
    Nodes that ran multiple times get one entry per run in ``runs`` (failed
    retry attempts excluded).
    """
    node_by_id: dict[str, dict] = {n.get("id"): n for n in nodes if n.get("id")}

    ordered_rows = [r for r in node_results if not _is_retry_attempt(r)]
    has_output_node = any(r.get("node_type") in OUTPUT_NODE_TYPES for r in ordered_rows)

    order: list[str] = []
    seen: set[str] = set()
    runs_by_node: dict[str, list[str]] = {}
    first_row_by_node: dict[str, dict] = {}
    for row in ordered_rows:
        nid = row.get("node_id")
        if not nid:
            continue
        if nid not in seen:
            seen.add(nid)
            order.append(nid)
            first_row_by_node[nid] = row
        output = row.get("output")
        if _is_empty_output(output):
            continue
        runs_by_node.setdefault(nid, []).append(_extract_message(output))

    last_executed_nid = order[-1] if order else None

    def kind_for(nid: str, ntype: str, flagged: bool) -> str | None:
        if _is_input_type(ntype):
            return "input"
        if ntype in OUTPUT_NODE_TYPES:
            return "output"
        if ntype == "agent":
            return "agent"
        if ntype == "llm":
            return "llm"
        if not has_output_node and nid == last_executed_nid:
            return "final"
        if flagged:
            return "output"
        return None

    records: list[dict] = []
    for nid in order:
        node = node_by_id.get(nid, {})
        first_row = first_row_by_node.get(nid, {})
        ntype = node.get("type") or first_row.get("node_type") or ""
        flagged = bool((node.get("data") or {}).get("highlight"))
        kind = kind_for(nid, ntype, flagged)
        if kind is None:
            continue
        label = (node.get("data") or {}).get("label") or first_row.get("node_label") or nid
        if kind == "input" and inputs:
            runs = [_extract_input_message(inputs)]
        else:
            runs = runs_by_node.get(nid) or [""]
        records.append(
            {
                "node_id": nid,
                "node_label": label,
                "node_type": ntype,
                "kind": kind,
                "runs": runs,
            }
        )

    # Respect execution order: input first, terminal output/final last, the rest
    # (agent / llm / flagged middle nodes) in between by first-appearance. This
    # corrects the loop case where the executor batches body-node results after
    # the terminal output node in ``node_results``.
    first_index = {nid: i for i, nid in enumerate(order)}
    records.sort(key=lambda r: (_order_group(r), first_index.get(r["node_id"], 0)))

    return {"records": records}
