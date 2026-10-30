"""DataTable actions shared by Chat, MCP and A2A, through the DataTable routes."""

import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import data_tables
from app.db.models import User
from app.models.schemas import (
    DataTableColumnDef,
    DataTableRowCreate,
    DataTableRowUpdate,
    DataTableUpdate,
)


class TableArgs(BaseModel):
    table_id: uuid.UUID = Field(description="Table UUID or Heym URL with ?tab=datatable/<uuid>.")

    @field_validator("table_id", mode="before")
    @classmethod
    def parse_table_link(cls, value: Any) -> Any:
        """Extract a table id from a Heym deep link without fetching the URL."""
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            tab = parse_qs(urlparse(value).query).get("tab", [""])[0]
            if tab.startswith("datatable/"):
                return tab.removeprefix("datatable/")
        return value


class ListRowsArgs(TableArgs):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class AddColumnsArgs(TableArgs):
    columns: list[DataTableColumnDef] = Field(min_length=1, max_length=50)


class RemoveColumnsArgs(TableArgs):
    column_names: list[str] = Field(min_length=1, max_length=50)
    confirmed: bool = Field(
        default=False,
        description="True only after the user confirms the tool's deletion warning.",
    )


class InsertRowsArgs(TableArgs):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=100)


class RowArgs(TableArgs):
    row_id: uuid.UUID


class UpdateRowArgs(RowArgs):
    data: dict[str, Any]


class ClearRowsArgs(TableArgs):
    confirmed: bool = Field(
        default=False,
        description="True only after the user confirms the tool's deletion warning.",
    )


_TOOLS: dict[str, tuple[type[TableArgs], str, str]] = {
    "get_data_table": (
        TableArgs,
        "Inspect a table's exact column definitions and row count. Accepts a table UUID or "
        "Heym DataTable link. Requires read access; does not fetch the link.",
        "Inspecting data table...",
    ),
    "list_data_table_rows": (
        ListRowsArgs,
        "Read a page of rows with their UUIDs and values. Requires read access. Use actual "
        "row UUIDs from results for updates and deletions; continue with offset if needed.",
        "Reading data table rows...",
    ),
    "add_data_table_columns": (
        AddColumnsArgs,
        "Add columns to an existing table, preserving all existing columns and rows. Needs "
        "owner or write access, including direct and team shares. Column types: string, "
        "number, boolean, date, json. Names must be distinct. String is the default type.",
        "Adding data table columns...",
    ),
    "remove_data_table_columns": (
        RemoveColumnsArgs,
        "Remove named columns and their values from every row, like the DataTable tab. "
        "Needs owner or write access. First call without confirmed to inspect the impact; "
        "show the warning and ask the user. Call with confirmed=true only after they confirm.",
        "Removing data table columns...",
    ),
    "insert_data_table_rows": (
        InsertRowsArgs,
        "Insert 1 to 100 rows (each an object keyed by column name). Needs owner or write "
        "access. Uses the DataTable tab's types, defaults, required and unique checks. "
        "Returns imported and rejected counts and per-row errors; report partial results.",
        "Adding data table rows...",
    ),
    "update_data_table_row": (
        UpdateRowArgs,
        "Update fields on one row, preserving other fields. Needs owner or write access. "
        "Uses the DataTable tab's type, required and unique validation.",
        "Updating data table row...",
    ),
    "delete_data_table_row": (
        RowArgs,
        "Delete one row by its UUID on the user's request, like the DataTable tab. "
        "Needs owner or write access. Read rows first when the UUID is unknown.",
        "Deleting data table row...",
    ),
    "clear_data_table_rows": (
        ClearRowsArgs,
        "Delete every row while keeping the table's columns. Needs owner or write access. "
        "First call without confirmed to inspect the impact; show the irreversible deletion "
        "warning and ask the user. Set confirmed=true only after they confirm.",
        "Clearing data table rows...",
    ),
}

DATA_TABLE_TOOL_NAMES = frozenset(_TOOLS)


def _tool_schema(name: str, model: type[TableArgs], description: str) -> dict[str, Any]:
    schema = model.model_json_schema()
    # Function tools expect a string, while the model normalizes it to a UUID internally.
    schema["properties"]["table_id"].pop("format", None)
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": schema},
    }


DATA_TABLE_TOOL_SCHEMAS = [
    _tool_schema(name, model, description) for name, (model, description, _label) in _TOOLS.items()
]


def data_table_tool_label(name: str) -> str:
    """Human-readable progress for a DataTable action."""
    return _TOOLS[name][2]


async def _change_columns(
    db: AsyncSession, user: User, args: AddColumnsArgs | RemoveColumnsArgs
) -> dict[str, Any]:
    table = await data_tables._get_data_table_with_access(
        args.table_id, user.id, db, require_write=True
    )
    existing = [DataTableColumnDef.model_validate(column) for column in table.columns or []]
    names = {column.name.casefold() for column in existing}
    if isinstance(args, AddColumnsArgs):
        for column in args.columns:
            column.name = column.name.strip()
            if not column.name:
                return {"error": "Each column needs a name"}
            if column.name.casefold() in names:
                return {"error": f"Duplicate column name: {column.name}"}
            names.add(column.name.casefold())
            column.order = len(existing)
            existing.append(column)
    else:
        removed = set(args.column_names)
        missing = removed - {column.name for column in existing}
        if missing:
            return {"error": f"Unknown columns: {', '.join(sorted(missing))}"}
        if not args.confirmed:
            count = await data_tables._row_count(table.id, db)
            return {
                "status": "pending",
                "requires_confirmation": True,
                "table_id": str(table.id),
                "column_names": sorted(removed),
                "row_count": count,
                "warning": f"Remove {', '.join(sorted(removed))} from {table.name}? "
                f"Their values will be removed from all {count} rows. This cannot be undone.",
            }
        existing = [column for column in existing if column.name not in removed]
    result = await data_tables.update_data_table(
        args.table_id, DataTableUpdate(columns=existing), current_user=user, db=db
    )
    return {"updated": True, "table": result.model_dump(mode="json")}


async def call_data_table_tool(
    db: AsyncSession, user: User, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Validate a chat action and apply the same access and data checks as the UI."""
    try:
        args = _TOOLS[name][0].model_validate(arguments)
        kwargs = {"current_user": user, "db": db}
        if isinstance(args, (AddColumnsArgs, RemoveColumnsArgs)):
            return await _change_columns(db, user, args)
        if isinstance(args, ListRowsArgs):
            rows = await data_tables.list_rows(
                args.table_id,
                limit=args.limit + 1,
                offset=args.offset,
                sort_by="created_at",
                sort_direction="desc",
                **kwargs,
            )
            return {
                "rows": [row.model_dump(mode="json") for row in rows[: args.limit]],
                "has_more": len(rows) > args.limit,
                "next_offset": args.offset + min(len(rows), args.limit),
            }
        if isinstance(args, InsertRowsArgs):
            result = await data_tables.bulk_create_rows(
                args.table_id, [DataTableRowCreate(data=row) for row in args.rows], **kwargs
            )
            return result.model_dump(mode="json")
        if isinstance(args, UpdateRowArgs):
            row = await data_tables.update_row(
                args.table_id, args.row_id, DataTableRowUpdate(data=args.data), **kwargs
            )
            return {"updated": True, "row": row.model_dump(mode="json")}
        if isinstance(args, RowArgs):
            await data_tables.delete_row(args.table_id, args.row_id, **kwargs)
            return {"deleted": True, "row_id": str(args.row_id)}
        if isinstance(args, ClearRowsArgs):
            table = await data_tables._get_data_table_with_access(
                args.table_id, user.id, db, require_write=True
            )
            count = await data_tables._row_count(table.id, db)
            if not args.confirmed:
                return {
                    "status": "pending",
                    "requires_confirmation": True,
                    "table_id": str(table.id),
                    "row_count": count,
                    "warning": f"Delete all {count} rows from {table.name}? This cannot be undone.",
                }
            await data_tables.clear_rows(args.table_id, **kwargs)
            return {"cleared": True, "deleted_count": count}
        table = await data_tables.get_data_table(args.table_id, **kwargs)
        return {"table": table.model_dump(mode="json")}
    except ValidationError as exc:
        return {"error": str(exc)}
    except HTTPException as exc:
        return {"error": str(exc.detail)}


def summarize_data_table_tool(name: str, result: dict[str, Any]) -> str:
    """Summarize outcomes without copying row values into the progress label."""
    if result.get("error"):
        return f"Error: {str(result['error'])[:150]}"
    if result.get("requires_confirmation"):
        return "Waiting for deletion confirmation"
    if "imported" in result:
        return f"Imported {result['imported']} row(s); {len(result['errors'])} rejected"
    if "rows" in result:
        return f"Read {len(result['rows'])} row(s)"
    if result.get("deleted"):
        return "Deleted data table row"
    if result.get("cleared"):
        return f"Deleted {result['deleted_count']} row(s)"
    return "Data table inspected" if name == "get_data_table" else "Data table updated"
