"""What the page planner and the widget builder are told about the data tables a page uses.

The planner gets each table's columns, how its values spread and a few rows, so it proposes
widgets over real columns (a `vendor_source` breakdown, not sample data) and can sketch each
widget's preview from them. The builder gets the ids and columns, so it reads the table with a
dataTable node.
"""

import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataTableRow
from app.services.data_table_access import get_data_table_with_permission

MAX_TABLES = 8
PROFILE_ROWS = 300
EXAMPLE_ROWS = 5
TOP_VALUES = 8
TEXT_LIMIT = 80


@dataclass(frozen=True)
class ColumnProfile:
    """One column, with its most common values (text) or its range (numbers)."""

    name: str
    type: str
    top_values: list[tuple[str, int]] = field(default_factory=list)
    distinct: int = 0
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class TableContext:
    id: uuid.UUID
    name: str
    profiled_rows: int
    columns: list[ColumnProfile]
    examples: list[dict[str, Any]]


class TableUnavailableError(Exception):
    """A table the user cannot read, or that no longer exists."""

    def __init__(self, table_id: uuid.UUID) -> None:
        super().__init__(str(table_id))
        self.table_id = table_id


def _short(value: Any) -> Any:
    if isinstance(value, str) and len(value) > TEXT_LIMIT:
        return value[:TEXT_LIMIT] + "…"
    return value


def profile_columns(
    columns: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> list[ColumnProfile]:
    """Each column's spread over `rows`: top values for text, min and max for numbers."""
    profiles: list[ColumnProfile] = []
    for column in sorted(columns, key=lambda c: c.get("order", 0)):
        name = str(column.get("name") or "")
        kind = str(column.get("type") or "string")
        values = [row.get(name) for row in rows if row.get(name) not in (None, "")]
        if kind == "number":
            numbers = [float(v) for v in values if isinstance(v, (int, float))]
            profiles.append(
                ColumnProfile(
                    name,
                    kind,
                    minimum=min(numbers) if numbers else None,
                    maximum=max(numbers) if numbers else None,
                )
            )
            continue
        counts = Counter(str(_short(v)) for v in values if not isinstance(v, (dict, list)))
        profiles.append(
            ColumnProfile(
                name, kind, top_values=counts.most_common(TOP_VALUES), distinct=len(counts)
            )
        )
    return profiles


async def load_table_contexts(
    db: AsyncSession, table_ids: list[uuid.UUID], user_id: uuid.UUID
) -> list[TableContext]:
    """The tables `user_id` can read, profiled; raises TableUnavailableError otherwise."""
    contexts: list[TableContext] = []
    for table_id in list(dict.fromkeys(table_ids))[:MAX_TABLES]:
        found = await get_data_table_with_permission(db, table_id, user_id)
        if found is None:
            raise TableUnavailableError(table_id)
        table, _ = found
        rows = (
            (
                await db.execute(
                    select(DataTableRow.data)
                    .where(DataTableRow.table_id == table_id)
                    .order_by(DataTableRow.created_at.desc())
                    .limit(PROFILE_ROWS)
                )
            )
            .scalars()
            .all()
        )
        data = [row for row in rows if isinstance(row, dict)]
        contexts.append(
            TableContext(
                id=table.id,
                name=table.name,
                profiled_rows=len(data),
                columns=profile_columns(list(table.columns or []), data),
                examples=[{k: _short(v) for k, v in row.items()} for row in data[:EXAMPLE_ROWS]],
            )
        )
    return contexts


def _column_line(column: ColumnProfile) -> str:
    line = f"  - {column.name} ({column.type})"
    if column.minimum is not None:
        return f"{line}: from {column.minimum:g} to {column.maximum:g}"
    if column.top_values:
        shown = ", ".join(f"{value} ({count})" for value, count in column.top_values)
        more = (
            f", {column.distinct - len(column.top_values)} more"
            if column.distinct > TOP_VALUES
            else ""
        )
        return f"{line}: {shown}{more}"
    return line


def describe_tables(tables: list[TableContext], *, with_data: bool) -> str:
    """The tables as prompt text; `with_data` adds value spreads and example rows."""
    if not tables:
        return ""
    parts = ["Data tables this page uses (read them with a dataTable node and its dataTableId):"]
    for table in tables:
        count = f", its {table.profiled_rows} latest rows profiled" if with_data else ""
        parts.append(f'- "{table.name}" (dataTableId: {table.id}{count}). Columns:')
        parts.extend(
            _column_line(c) if with_data else f"  - {c.name} ({c.type})" for c in table.columns
        )
        if with_data and table.examples:
            parts.append("  Example rows:")
            parts.extend(f"  {row}" for row in table.examples)
    return "\n".join(parts)
