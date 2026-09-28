"""What the workflow assistant may know about the user's Heym DataTables.

The assistant sees each table's name, id, description, access and column definitions,
never its rows. This module loads that catalog, formats the prompt section the canvas
builder and the chat's workflow builder get, and shapes what the chat's
`list_data_tables` tool returns.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataTable, DataTableShare, DataTableTeamShare, Team, TeamMember, User


class DataTablePromptMode(str, Enum):
    """How much of the data table flow an assistant surface may run."""

    ASK = "ask"
    APPLY_CHOICES = "apply_choices"


# Operations the executor refuses on a read-only share (`_get_accessible_data_table`).
WRITE_OPERATIONS = frozenset({"insert", "update", "remove", "upsert"})
# Row columns outside the JSON data blob that `find` and `count` filters accept.
ROW_METADATA_KEYS = frozenset(
    {"id", "table_id", "created_at", "updated_at", "created_by", "updated_by"}
)
COLUMN_TYPES = frozenset({"string", "number", "boolean", "date", "json"})

PROMPT_TABLE_LIMIT = 50
PROMPT_COLUMN_LIMIT = 40
PROMPT_DESCRIPTION_LIMIT = 200
TOOL_TABLE_LIMIT = 100

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class CatalogColumn:
    """A column as the assistant sees it."""

    name: str
    type: str
    required: bool = False
    unique: bool = False


@dataclass(frozen=True)
class CatalogDataTable:
    """A table the user can use: its identity, access and columns, never its rows."""

    id: uuid.UUID
    name: str
    description: str | None
    access: str
    shared_by: str | None
    columns: tuple[CatalogColumn, ...]

    @property
    def writable(self) -> bool:
        """Whether insert, update, remove and upsert may run against this table."""
        return self.access in ("owner", "write")

    def fits(self, operation: str) -> bool:
        """Whether a `dataTable` node running `operation` may use this table."""
        return self.writable or operation not in WRITE_OPERATIONS


def _column_order(column: dict[str, Any]) -> int:
    order = column.get("order")
    return order if isinstance(order, int) else 0


def catalog_columns(raw: object) -> tuple[CatalogColumn, ...]:
    """Read stored column definitions into catalog columns, in column order."""
    if not isinstance(raw, list):
        return ()
    stored = [
        column
        for column in raw
        if isinstance(column, dict) and str(column.get("name") or "").strip()
    ]
    stored.sort(key=_column_order)
    return tuple(
        CatalogColumn(
            name=str(column["name"]).strip(),
            type=str(column.get("type") or "string"),
            required=bool(column.get("required", False)),
            unique=bool(column.get("unique", False)),
        )
        for column in stored
    )


_TABLE_FIELDS = (
    DataTable.id,
    DataTable.name,
    DataTable.description,
    DataTable.columns,
    DataTable.updated_at,
)


async def load_data_table_catalog(db: AsyncSession, user_id: uuid.UUID) -> list[CatalogDataTable]:
    """Return the user's own tables, then the tables shared with them, each newest first.

    A table shared several ways keeps its highest permission; on a tie the direct share
    wins, as in the DataTable list endpoint. Rows are never read.
    """
    owned = await db.execute(
        select(*_TABLE_FIELDS)
        .where(DataTable.owner_id == user_id)
        .order_by(DataTable.updated_at.desc())
    )
    direct = await db.execute(
        select(*_TABLE_FIELDS, DataTableShare.permission, User.email)
        .join(DataTableShare, DataTableShare.table_id == DataTable.id)
        .join(User, User.id == DataTable.owner_id)
        .where(DataTableShare.user_id == user_id)
    )
    team = await db.execute(
        select(*_TABLE_FIELDS, DataTableTeamShare.permission, Team.name)
        .join(DataTableTeamShare, DataTableTeamShare.table_id == DataTable.id)
        .join(TeamMember, TeamMember.team_id == DataTableTeamShare.team_id)
        .join(Team, Team.id == DataTableTeamShare.team_id)
        .where(TeamMember.user_id == user_id)
    )
    tables = [
        CatalogDataTable(table_id, name, description, "owner", None, catalog_columns(columns))
        for table_id, name, description, columns, _updated_at in owned.all()
    ]
    owned_ids = {table.id for table in tables}
    shared: dict[uuid.UUID, tuple[CatalogDataTable, datetime]] = {}
    for table_id, name, description, columns, updated_at, permission, shared_by in [
        *direct.all(),
        *team.all(),
    ]:
        if table_id in owned_ids:
            continue
        access = "write" if permission == "write" else "read"
        current = shared.get(table_id)
        if current is not None and (current[0].access == "write" or access == "read"):
            continue
        table = CatalogDataTable(
            table_id, name, description, access, shared_by, catalog_columns(columns)
        )
        shared[table_id] = (table, updated_at or _EPOCH)
    ordered = sorted(shared.values(), key=lambda item: item[1], reverse=True)
    return [*tables, *(table for table, _updated_at in ordered)]


_INTRO = (
    "You never see table rows. Below are the Heym DataTables the user can use, with their "
    "id, access and columns. This section overrides the `datatable-uuid` placeholder: put a "
    "listed table's id in `dataTableId`."
)

_USE_RULE = (
    "When a workflow saves, stores, logs or looks up records and the user names no other "
    "store (Google Sheets, Grist, Supabase, Redis, ...), use a `dataTable` node."
)

_FIT_RULE = (
    "A table fits a node when it has a column for every field the node writes or filters "
    "on, and, for insert, update, remove and upsert, its access is owner or write."
)

_COLUMN_RULE = (
    "Use the table's exact column names as the keys of `dataTableData` and "
    "`dataTableFilter`. Never write a column the table does not have."
)

_NO_INVENT_RULE = "Never invent a table id, and never write a table name that is not listed here."

_ASK_RULES = (
    _USE_RULE,
    _FIT_RULE,
    "When the user names a listed table that fits, use it without asking.",
    "Otherwise emit one `single` `heym-clarify` question and stop. Offer up to five fitting "
    "tables as table options, then one createTable option (see the Clarification "
    'Protocol), and set `"allowOther": true`.',
    "When the user asks to create a table, emit the same question with only the "
    "createTable option. The card creates the table when the user submits.",
    'Answers come back as `Data table "<name>" (id <id>)` or '
    '`Created data table "<name>" (id <id>)`. Use that id. A created table appears in '
    "this list on the next turn.",
    _COLUMN_RULE,
    "Never change an existing table's columns. When a table lacks a column the workflow "
    "needs, name the column and offer a new table or using the table with its existing "
    "columns. Columns are added in the DataTable tab.",
    "Do not ask again about a table already chosen in this conversation, or about a "
    "`dataTable` node you are editing that already has a table.",
    _NO_INVENT_RULE,
)

_APPLY_RULES = (
    _USE_RULE,
    _FIT_RULE,
    "You cannot ask questions in this step. The request lists the data tables the user "
    "chose. Put a chosen table's id in each new `dataTable` node it fits. When a choice "
    "says to leave the table empty, or no choice fits a node, leave its `dataTableId` empty.",
    _COLUMN_RULE,
    _NO_INVENT_RULE,
)


def describe_columns(columns: tuple[CatalogColumn, ...], limit: int | None = None) -> str:
    """One-line column list, such as `email string unique, name string`."""
    shown = columns if limit is None else columns[:limit]
    parts: list[str] = []
    for column in shown:
        words = [column.name, column.type]
        if column.unique:
            words.append("unique")
        if column.required:
            words.append("required")
        parts.append(" ".join(words))
    text = ", ".join(parts) or "none"
    if len(columns) > len(shown):
        text += f", and {len(columns) - len(shown)} more"
    return text


def _access_text(table: CatalogDataTable) -> str:
    if table.access == "owner":
        return "owner"
    access = "write" if table.access == "write" else "read only"
    return f"{access}, shared by {table.shared_by}" if table.shared_by else access


def _describe(table: CatalogDataTable) -> str:
    line = f"- `{table.name}` (id `{table.id}`, {_access_text(table)})"
    description = " ".join((table.description or "").split())
    if len(description) > PROMPT_DESCRIPTION_LIMIT:
        description = description[:PROMPT_DESCRIPTION_LIMIT].rstrip() + "…"
    if description:
        line += f": {description}"
    return f"{line}. Columns: {describe_columns(table.columns, PROMPT_COLUMN_LIMIT)}"


def format_data_tables_prompt(tables: list[CatalogDataTable], mode: DataTablePromptMode) -> str:
    """Return the assistant prompt section for `mode`."""
    rules = _ASK_RULES if mode is DataTablePromptMode.ASK else _APPLY_RULES
    shown = tables[:PROMPT_TABLE_LIMIT]
    listing = [_describe(table) for table in shown] or ["- The user has no data tables yet."]
    if len(tables) > len(shown):
        listing.append(
            f"- {len(tables) - len(shown)} more tables are not shown; ask the user for the "
            "table's exact name."
        )
    lines = [
        "## Data tables",
        "",
        _INTRO,
        "",
        *(f"{index}. {rule}" for index, rule in enumerate(rules, start=1)),
        "",
        "The user's data tables:",
        *listing,
    ]
    return "\n\n" + "\n".join(lines) + "\n"


async def build_data_tables_prompt(
    db: AsyncSession, user_id: uuid.UUID, mode: DataTablePromptMode
) -> str:
    """Load the user's tables and format the prompt section for `mode`."""
    return format_data_tables_prompt(await load_data_table_catalog(db, user_id), mode)


def table_summary(table: CatalogDataTable) -> dict[str, Any]:
    """A table as the chat's data table tools return it."""
    return {
        "id": str(table.id),
        "name": table.name,
        "description": table.description,
        "access": table.access,
        "shared_by": table.shared_by,
        "columns": [
            {
                "name": column.name,
                "type": column.type,
                "required": column.required,
                "unique": column.unique,
            }
            for column in table.columns
        ],
    }


def list_data_tables_payload(tables: list[CatalogDataTable]) -> dict[str, Any]:
    """What `list_data_tables` returns: up to `TOOL_TABLE_LIMIT` tables, never rows."""
    shown = tables[:TOOL_TABLE_LIMIT]
    return {
        "count": len(tables),
        "tables": [table_summary(table) for table in shown],
        "truncated": len(tables) > len(shown),
    }
