"""Deterministic data table handling for workflows the chat builder generates.

The builder model is told which tables to use; this pass makes the result safe no matter
what it wrote. Names become ids, unknown ids and read-only tables for writing operations
are dropped, the user's choices fill empty fields, and a new node nobody chose a table for
is returned as a need instead of being saved empty. Keys a table lacks come back as
warnings, because the node would store them where the DataTable tab never shows them.
"""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.services.data_table_catalog import (
    ROW_METADATA_KEYS,
    WRITE_OPERATIONS,
    CatalogDataTable,
    describe_columns,
)
from app.services.generated_node_match import node_label, previous_node_version

DATA_TABLE_NODE_TYPE = "dataTable"
DATA_TABLE_FIELD = "dataTableId"
_DATA_OPERATIONS = frozenset({"insert", "update", "upsert"})
_FILTER_OPERATIONS = frozenset({"find", "count", "upsert"})

REQUIRES_DATA_TABLE_INSTRUCTIONS = (
    "The workflow was not saved. Call list_data_tables, ask one heym-clarify question with "
    "the fitting tables and a createTable option, then call this tool again with "
    "data_table_choices."
)
DATA_TABLE_WARNINGS_NOTE = (
    "These keys are not columns of the table. The node stores them where the DataTable tab "
    "does not show them, and the next column change drops them. Tell the user; columns are "
    "added in the DataTable tab."
)


@dataclass(frozen=True)
class DataTableChoice:
    """One answer the user gave in chat: a table by id or exact name, or "" for none."""

    table_id: str


@dataclass(frozen=True)
class DataTableNeed:
    """A new `dataTable` node no choice gave a table."""

    node: str
    operation: str
    writes: bool


@dataclass(frozen=True)
class DataTableWarning:
    """Keys a node writes or filters on that its table has no column for."""

    node: str
    table: str
    unknown_columns: tuple[str, ...]


@dataclass
class DataTablePassResult:
    """Nodes after the pass, the nodes that still need a table, and column warnings."""

    nodes: list[dict[str, Any]]
    needs: list[DataTableNeed] = field(default_factory=list)
    warnings: list[DataTableWarning] = field(default_factory=list)


def parse_data_table_choices(raw: object) -> list[DataTableChoice]:
    """Parse the `data_table_choices` tool argument, skipping malformed entries."""
    if not isinstance(raw, list):
        return []
    choices: list[DataTableChoice] = []
    for item in raw:
        if not isinstance(item, dict) or item.get("table_id") is None:
            continue
        choices.append(DataTableChoice(str(item["table_id"]).strip()))
    return choices


def _canonical_uuid(text: str) -> str:
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return text


def resolve_data_table(value: object, catalog: list[CatalogDataTable]) -> CatalogDataTable | None:
    """The catalog table a generated value names: its id, or an exact name.

    A name several tables share resolves to the user's own table, or else only when
    exactly one listed table has it.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    canonical = _canonical_uuid(text)
    for table in catalog:
        if str(table.id) == canonical:
            return table
    named = [table for table in catalog if table.name == text]
    owned = [table for table in named if table.access == "owner"]
    if owned:
        return owned[0]
    return named[0] if len(named) == 1 else None


def format_data_table_choices(
    choices: list[DataTableChoice], catalog: list[CatalogDataTable]
) -> str:
    """Render choices as builder instructions, or "" when there are none."""
    if not choices:
        return ""
    lines = ["Data tables the user chose:"]
    for choice in choices:
        if not choice.table_id:
            lines.append("- leave the table empty; the user picks it later")
            continue
        table = resolve_data_table(choice.table_id, catalog)
        if table is None:
            lines.append(f"- `{choice.table_id}` is not one of the user's tables; do not use it")
            continue
        lines.append(
            f"- `{table.name}` (id `{table.id}`), columns: {describe_columns(table.columns)}"
        )
    return "\n".join(lines)


def _template_keys(template: object) -> list[str]:
    """Top-level keys of a JSON object template, or [] when it is not one."""
    parsed = template
    if isinstance(template, str):
        try:
            parsed = json.loads(template)
        except json.JSONDecodeError:
            return []
    return [str(key) for key in parsed] if isinstance(parsed, dict) else []


def unknown_columns(data: dict[str, Any], table: CatalogDataTable) -> tuple[str, ...]:
    """Keys the node writes or filters on that `table` has no column for."""
    operation = str(data.get("dataTableOperation") or "")
    columns = {column.name for column in table.columns}
    unknown: list[str] = []
    if operation in _DATA_OPERATIONS:
        unknown += [key for key in _template_keys(data.get("dataTableData")) if key not in columns]
    if operation in _FILTER_OPERATIONS:
        unknown += [
            key
            for key in _template_keys(data.get("dataTableFilter"))
            if key not in columns and key not in ROW_METADATA_KEYS
        ]
    return tuple(dict.fromkeys(unknown))


def _single_fitting_choice(
    chosen: list[CatalogDataTable], operation: str
) -> CatalogDataTable | None:
    fitting = [table for table in chosen if table.fits(operation)]
    return fitting[0] if len(fitting) == 1 else None


def _restore(data: dict[str, Any], value: object) -> None:
    if value is None:
        data.pop(DATA_TABLE_FIELD, None)
    else:
        data[DATA_TABLE_FIELD] = value


def apply_generated_data_tables(
    nodes: list[dict[str, Any]],
    *,
    catalog: list[CatalogDataTable],
    choices: list[DataTableChoice],
    previous_nodes: list[dict[str, Any]] | None,
) -> DataTablePassResult:
    """Make every `dataTable` node of a generated workflow point at a usable table.

    A node that already existed keeps a value the builder left unchanged, since that was
    the user's own choice, and reverts a value the builder broke. Otherwise the value must
    be, or name, a catalog table the operation may use; a single fitting choice fills an
    empty field; and a new node still without a table becomes a need unless the user chose
    to leave it empty.
    """
    previous = [node for node in previous_nodes or [] if isinstance(node, dict)]
    chosen: list[CatalogDataTable] = []
    for choice in choices:
        table = resolve_data_table(choice.table_id, catalog)
        if table is not None and table not in chosen:
            chosen.append(table)
    leave_empty = any(not choice.table_id for choice in choices)
    result = copy.deepcopy(nodes)
    needs: list[DataTableNeed] = []
    warnings: list[DataTableWarning] = []
    for node in result:
        if not isinstance(node, dict) or node.get("type") != DATA_TABLE_NODE_TYPE:
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        operation = str(data.get("dataTableOperation") or "")
        label = node_label(node) or str(node.get("id") or "")
        before = previous_node_version(node, previous)
        old_data = before.get("data") if before is not None else None
        old_value = old_data.get(DATA_TABLE_FIELD) if isinstance(old_data, dict) else None
        value = data.get(DATA_TABLE_FIELD)
        if before is not None and value == old_value:
            table = resolve_data_table(value, catalog)
        else:
            table = resolve_data_table(value, catalog)
            if table is not None and not table.fits(operation):
                table = None
            if table is None and before is None:
                table = _single_fitting_choice(chosen, operation)
            if table is None and before is not None:
                _restore(data, old_value)
                table = resolve_data_table(old_value, catalog)
            else:
                data[DATA_TABLE_FIELD] = str(table.id) if table is not None else ""
                if table is None and not leave_empty:
                    needs.append(DataTableNeed(label, operation, operation in WRITE_OPERATIONS))
        if table is not None:
            unknown = unknown_columns(data, table)
            if unknown:
                warnings.append(DataTableWarning(label, table.name, unknown))
    return DataTablePassResult(nodes=result, needs=needs, warnings=warnings)


def requires_data_table_payload(needs: list[DataTableNeed]) -> dict[str, Any]:
    """Tool result that asks the chat to settle each table before saving."""
    return {
        "status": "requires_data_table",
        "needs": [
            {"node": need.node, "operation": need.operation, "writes": need.writes}
            for need in needs
        ],
        "instructions": REQUIRES_DATA_TABLE_INSTRUCTIONS,
    }


def data_table_warnings_payload(warnings: list[DataTableWarning]) -> dict[str, Any]:
    """Saved-result fields that name keys a table has no column for, or {}."""
    if not warnings:
        return {}
    return {
        "data_table_warnings": [
            {
                "node": warning.node,
                "table": warning.table,
                "unknown_columns": list(warning.unknown_columns),
            }
            for warning in warnings
        ],
        "data_table_warnings_note": DATA_TABLE_WARNINGS_NOTE,
    }
