from __future__ import annotations

import json
import uuid
from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext


def _build_data_table_sort_clauses(sort_str: str, columns: list) -> list:
    """Build SQLAlchemy order_by clauses for a DataTable sort string.

    Supports optional '-' prefix for descending order.
    Row metadata ('id', 'table_id', 'created_at', 'updated_at', 'created_by', 'updated_by')
    maps to real table columns unless overridden by a schema column of the same name.
    User schema columns live in the JSONB 'data' blob. When column type is 'number',
    numeric sort is performed via regex validation + cast to NUMERIC, falling back to NULL
    for invalid/empty values so queries never fail.
    NULLS LAST is explicitly applied.
    'DataTableRow.created_at.asc()' is added as the primary tie-breaker unless
    already sorting by 'created_at' or 'id'.
    'DataTableRow.id.asc()' is added as the final ordering key for deterministic LIMIT
    unless already sorting by 'id'.
    """
    from sqlalchemy import Numeric, case, cast, null

    from app.db.models import DataTableRow

    if not isinstance(sort_str, str) or not sort_str:
        return []

    stripped = sort_str.strip()
    if not stripped:
        return []

    descending = stripped.startswith("-")
    col_name = stripped[1:].strip() if descending else stripped

    schema_cols = {c["name"]: c for c in (columns or []) if isinstance(c, dict) and "name" in c}
    meta_columns = {
        "id": DataTableRow.id,
        "table_id": DataTableRow.table_id,
        "created_at": DataTableRow.created_at,
        "updated_at": DataTableRow.updated_at,
        "created_by": DataTableRow.created_by,
        "updated_by": DataTableRow.updated_by,
    }

    if not col_name:
        field = DataTableRow.created_at
    elif col_name not in schema_cols and col_name in meta_columns:
        field = meta_columns[col_name]
    else:
        raw_val = DataTableRow.data.op("->>")(col_name)
        if schema_cols.get(col_name, {}).get("type") == "number":
            num_regex = r"^[ \t]*[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?[ \t]*$"
            field = case(
                (raw_val.op("~")(num_regex), cast(raw_val, Numeric)),
                else_=null(),
            )
        else:
            field = raw_val

    order_expr = field.desc().nulls_last() if descending else field.asc().nulls_last()
    clauses = [order_expr]
    if col_name not in ("id", "created_at", ""):
        clauses.append(DataTableRow.created_at.asc())
    if col_name != "id":
        clauses.append(DataTableRow.id.asc())
    return clauses


def _check_unique_sync(
    table_id: str | uuid.UUID,
    data: dict,
    columns: list,
    db: object,
    exclude_row_id: str | None = None,
) -> None:
    """Check unique constraints using sync session. Raises ValueError on conflict."""
    from app.api.data_tables import _check_unique_constraints_sync

    errors = _check_unique_constraints_sync(
        table_id=table_id,
        data=data,
        columns=columns,
        db=db,
        exclude_row_id=exclude_row_id,
    )
    if errors:
        raise ValueError(errors[0])


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the dataTable node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    _build_data_table_filter_clauses = _workflow_executor._build_data_table_filter_clauses
    _coerce_row_data = _workflow_executor._coerce_row_data
    _check_unique_constraints_sync = _workflow_executor._check_unique_constraints_sync
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    from app.db.models import DataTableRow
    from app.db.session import SessionLocal

    data_table_id = node_data.get("dataTableId")
    if not data_table_id:
        raise ValueError("DataTable node requires a table selection")

    operation = node_data.get("dataTableOperation", "")
    if not operation:
        raise ValueError("DataTable node requires an operation")

    with SessionLocal() as db:
        table = self._get_accessible_data_table(db, data_table_id, operation)
        if not table:
            raise ValueError(f"DataTable not found or not accessible: {data_table_id}")

        owner_id = self.actor_user_id
        columns = table.columns or []

        def _coerce_output(data: dict, cols: list) -> dict:
            """Coerce stored row data to proper types on read."""
            col_map = {c["name"]: c for c in cols}
            result = dict(data) if data else {}
            for key, value in list(result.items()):
                col = col_map.get(key)
                if not col or value is None:
                    continue
                col_type = col.get("type", "string")
                try:
                    if col_type == "number" and isinstance(value, str):
                        result[key] = float(value) if "." in value else int(value)
                    elif col_type == "boolean":
                        if isinstance(value, str):
                            result[key] = value.lower() in ("true", "1", "yes")
                        elif isinstance(value, (int, float)):
                            result[key] = bool(value)
                except (ValueError, TypeError):
                    pass
            return result

        columns = table.columns or []

        def _check_unique_sync(data: dict, exclude_row_id: str | None = None) -> None:
            """Check unique constraints using sync session. Raises ValueError on conflict."""
            errors = _check_unique_constraints_sync(
                table_id=data_table_id,
                data=data,
                columns=columns,
                db=db,
                exclude_row_id=exclude_row_id,
            )
            if errors:
                raise ValueError(errors[0])

        if operation == "find":
            filter_template = node_data.get("dataTableFilter", "{}")
            filter_str = self.evaluate_message_template(filter_template, inputs, node_id)
            try:
                filter_dict = json.loads(filter_str) if isinstance(filter_str, str) else filter_str
            except Exception:
                filter_dict = {}

            query = db.query(DataTableRow).filter(DataTableRow.table_id == data_table_id)
            if filter_dict and isinstance(filter_dict, dict):
                clauses = _build_data_table_filter_clauses(filter_dict, columns)
                if clauses:
                    query = query.filter(*clauses)

            sort_template = node_data.get("dataTableSort", "")
            if sort_template:
                sort_str = self.evaluate_message_template(sort_template, inputs, node_id)
                if sort_str:
                    sort_clauses = _build_data_table_sort_clauses(sort_str, columns)
                    if sort_clauses:
                        query = query.order_by(*sort_clauses)

            raw_limit = node_data.get("dataTableLimit")
            if raw_limit is not None and int(raw_limit) > 0:
                query = query.limit(int(raw_limit))
            rows = query.all()
            output = {
                "success": True,
                "operation": "find",
                "rows": [
                    {
                        "id": str(r.id),
                        "data": _coerce_output(r.data, columns),
                        "created_at": str(r.created_at),
                    }
                    for r in rows
                ],
                "count": len(rows),
            }

        elif operation == "getAll":
            query = db.query(DataTableRow).filter(DataTableRow.table_id == data_table_id)

            sort_template = node_data.get("dataTableSort", "")
            if sort_template:
                sort_str = self.evaluate_message_template(sort_template, inputs, node_id)
                if sort_str:
                    sort_clauses = _build_data_table_sort_clauses(sort_str, columns)
                    if sort_clauses:
                        query = query.order_by(*sort_clauses)

            raw_limit = node_data.get("dataTableLimit")
            if raw_limit is not None and int(raw_limit) > 0:
                query = query.limit(int(raw_limit))
            rows = query.all()
            output = {
                "success": True,
                "operation": "getAll",
                "rows": [
                    {
                        "id": str(r.id),
                        "data": _coerce_output(r.data, columns),
                        "created_at": str(r.created_at),
                    }
                    for r in rows
                ],
                "count": len(rows),
            }

        elif operation == "count":
            filter_template = node_data.get("dataTableFilter", "{}")
            filter_str = self.evaluate_message_template(filter_template, inputs, node_id)
            try:
                filter_dict = json.loads(filter_str) if isinstance(filter_str, str) else filter_str
            except Exception:
                filter_dict = {}

            query = db.query(DataTableRow).filter(DataTableRow.table_id == data_table_id)
            if isinstance(filter_dict, dict) and filter_dict:
                clauses = _build_data_table_filter_clauses(filter_dict, columns)
                if clauses:
                    query = query.filter(*clauses)
            total = query.count()
            output = {
                "success": True,
                "operation": "count",
                "count": int(total),
            }

        elif operation == "getById":
            row_id_template = node_data.get("dataTableRowId", "")
            row_id = self.evaluate_message_template(row_id_template, inputs, node_id)
            if not row_id:
                raise ValueError("DataTable getById requires a row ID")
            row = (
                db.query(DataTableRow)
                .filter(
                    DataTableRow.id == row_id,
                    DataTableRow.table_id == data_table_id,
                )
                .first()
            )
            output = {
                "success": True,
                "operation": "getById",
                "row": {
                    "id": str(row.id),
                    "data": _coerce_output(row.data, columns),
                    "created_at": str(row.created_at),
                }
                if row
                else None,
                "found": row is not None,
            }

        elif operation == "insert":
            data_template = node_data.get("dataTableData", "{}")
            data_str = self.evaluate_message_template(data_template, inputs, node_id)
            try:
                row_data = json.loads(data_str) if isinstance(data_str, str) else data_str
            except Exception:
                row_data = {}

            coerced_data = row_data if isinstance(row_data, dict) else {}
            coerced_data, _ = _coerce_row_data(coerced_data, table.columns or [])
            _check_unique_sync(coerced_data)

            new_row = DataTableRow(
                id=str(uuid.uuid4()),
                table_id=data_table_id,
                data=coerced_data,
                created_by=owner_id,
                updated_by=owner_id,
            )
            db.add(new_row)
            db.commit()
            db.refresh(new_row)
            output = {
                "success": True,
                "operation": "insert",
                "row": {
                    "id": str(new_row.id),
                    "data": new_row.data,
                    "created_at": str(new_row.created_at),
                },
                "id": str(new_row.id),
            }

        elif operation == "update":
            row_id_template = node_data.get("dataTableRowId", "")
            row_id = self.evaluate_message_template(row_id_template, inputs, node_id)
            if not row_id:
                raise ValueError("DataTable update requires a row ID")

            data_template = node_data.get("dataTableData", "{}")
            data_str = self.evaluate_message_template(data_template, inputs, node_id)
            try:
                update_data = json.loads(data_str) if isinstance(data_str, str) else data_str
            except Exception:
                update_data = {}

            row = (
                db.query(DataTableRow)
                .filter(
                    DataTableRow.id == row_id,
                    DataTableRow.table_id == data_table_id,
                )
                .first()
            )
            if not row:
                raise ValueError(f"Row not found: {row_id}")

            merged = {
                **(row.data or {}),
                **(update_data if isinstance(update_data, dict) else {}),
            }
            merged, _ = _coerce_row_data(merged, table.columns or [])
            _check_unique_sync(merged, exclude_row_id=str(row.id))
            row.data = merged
            row.updated_by = owner_id
            db.commit()
            db.refresh(row)
            output = {
                "success": True,
                "operation": "update",
                "row": {
                    "id": str(row.id),
                    "data": row.data,
                    "created_at": str(row.created_at),
                },
                "id": str(row.id),
            }

        elif operation == "remove":
            row_id_template = node_data.get("dataTableRowId", "")
            row_id = self.evaluate_message_template(row_id_template, inputs, node_id)
            if not row_id:
                raise ValueError("DataTable remove requires a row ID")

            row = (
                db.query(DataTableRow)
                .filter(
                    DataTableRow.id == row_id,
                    DataTableRow.table_id == data_table_id,
                )
                .first()
            )
            if not row:
                raise ValueError(f"Row not found: {row_id}")

            db.delete(row)
            db.commit()
            output = {
                "success": True,
                "operation": "remove",
                "id": row_id,
            }

        elif operation == "upsert":
            filter_template = node_data.get("dataTableFilter", "{}")
            filter_str = self.evaluate_message_template(filter_template, inputs, node_id)
            try:
                filter_dict = json.loads(filter_str) if isinstance(filter_str, str) else filter_str
            except Exception:
                filter_dict = {}

            data_template = node_data.get("dataTableData", "{}")
            data_str = self.evaluate_message_template(data_template, inputs, node_id)
            try:
                upsert_data = json.loads(data_str) if isinstance(data_str, str) else data_str
            except Exception:
                upsert_data = {}

            # Try to find existing row by filter
            existing_row = None
            if filter_dict and isinstance(filter_dict, dict):
                query = db.query(DataTableRow).filter(DataTableRow.table_id == data_table_id)
                for col_name, col_value in filter_dict.items():
                    query = query.filter(DataTableRow.data.op("->>")(col_name) == str(col_value))
                existing_row = query.first()

            if existing_row:
                merged = {
                    **(existing_row.data or {}),
                    **(upsert_data if isinstance(upsert_data, dict) else {}),
                }
                merged, _ = _coerce_row_data(merged, table.columns or [])
                _check_unique_sync(merged, exclude_row_id=str(existing_row.id))
                existing_row.data = merged
                existing_row.updated_by = owner_id
                db.commit()
                db.refresh(existing_row)
                output = {
                    "success": True,
                    "operation": "update",
                    "row": {
                        "id": str(existing_row.id),
                        "data": existing_row.data,
                        "created_at": str(existing_row.created_at),
                    },
                    "id": str(existing_row.id),
                }
            else:
                upsert_coerced = upsert_data if isinstance(upsert_data, dict) else {}
                upsert_coerced, _ = _coerce_row_data(upsert_coerced, table.columns or [])
                _check_unique_sync(upsert_coerced)
                new_row = DataTableRow(
                    id=str(uuid.uuid4()),
                    table_id=data_table_id,
                    data=upsert_coerced,
                    created_by=owner_id,
                    updated_by=owner_id,
                )
                db.add(new_row)
                db.commit()
                db.refresh(new_row)
                output = {
                    "success": True,
                    "operation": "insert",
                    "row": {
                        "id": str(new_row.id),
                        "data": new_row.data,
                        "created_at": str(new_row.created_at),
                    },
                    "id": str(new_row.id),
                }

        else:
            raise ValueError(f"Unknown DataTable operation: {operation}")
    return output
