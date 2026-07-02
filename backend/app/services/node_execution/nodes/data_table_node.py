from __future__ import annotations

import json
import uuid
from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the dataTable node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    _build_data_table_filter_clauses = _workflow_executor._build_data_table_filter_clauses
    _coerce_row_data = _workflow_executor._coerce_row_data
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
            from sqlalchemy import text as sa_text

            unique_checks = []
            for col in columns:
                if not col.get("unique"):
                    continue
                name = col["name"]
                if name not in data:
                    continue
                value = data[name]
                if value is None or value == "":
                    continue
                unique_checks.append((name, str(value)))
            if not unique_checks:
                return
            conditions = []
            params: dict = {"table_id": str(data_table_id)}
            for i, (cn, cv) in enumerate(unique_checks):
                conditions.append(f"data ->> :cn{i} = :cv{i}")
                params[f"cn{i}"] = cn
                params[f"cv{i}"] = cv
            sql = f"SELECT data FROM data_table_rows WHERE table_id = :table_id AND ({' OR '.join(conditions)})"
            if exclude_row_id:
                sql += " AND id != :exclude_id"
                params["exclude_id"] = exclude_row_id
            rows = db.execute(sa_text(sql), params).fetchall()
            for cn, cv in unique_checks:
                for r in rows:
                    rd = r[0] if isinstance(r[0], dict) else {}
                    if str(rd.get(cn, "")) == cv:
                        raise ValueError(f"Duplicate value for unique column '{cn}': {cv}")

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
                    if sort_str.startswith("-"):
                        query = query.order_by(DataTableRow.created_at.desc())
                    else:
                        query = query.order_by(DataTableRow.created_at.asc())

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
                if sort_str and sort_str.startswith("-"):
                    query = query.order_by(DataTableRow.created_at.desc())
                else:
                    query = query.order_by(DataTableRow.created_at.asc())

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
