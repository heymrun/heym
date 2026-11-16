"""Translate a Data Table node's Mongo-style filter into SQLAlchemy clauses."""


def build_data_table_filter_clauses(filter_dict: dict, columns: list) -> list:
    """Build SQLAlchemy filter clauses for a DataTable Mongo-style filter.

    A plain value means equality. An object value applies comparison operators:
    ``$eq``, ``$ne``, ``$gt``, ``$gte``, ``$lt``, ``$lte``, ``$contains`` (ILIKE
    substring) and ``$in`` (list membership).

    User-defined schema columns live in the JSON ``data`` blob and are matched as text
    (numeric comparisons cast to ``NUMERIC`` when ``number``; booleans use ``"true"``/``"false"``).
    Row metadata (``id``, ``created_at``, ``updated_at``, ``created_by``, ``updated_by``,
    ``table_id``) are real table columns matched directly; ``$contains`` casts them to text.
    A schema column sharing a metadata name still resolves against the JSON blob.
    Unknown operators are ignored.
    """
    from sqlalchemy import Numeric, String, cast

    from app.db.models import DataTableRow

    if not isinstance(filter_dict, dict) or not filter_dict:
        return []

    schema_cols = {c["name"]: c for c in (columns or [])}
    meta_cols = {"id", "table_id", "created_at", "updated_at", "created_by", "updated_by"}
    clauses: list = []

    for col_name, condition in filter_dict.items():
        is_meta = col_name not in schema_cols and col_name in meta_cols
        if is_meta:
            field, is_json, is_number = getattr(DataTableRow, col_name), False, False
        else:
            field = DataTableRow.data.op("->>")(col_name)
            is_json, is_number = True, schema_cols.get(col_name, {}).get("type") == "number"

        is_boolean = schema_cols.get(col_name, {}).get("type") == "boolean"

        def _coerce(value: object) -> object:
            if not is_json:
                return value
            if is_boolean and isinstance(value, bool):
                return "true" if value else "false"
            return str(value)

        if isinstance(condition, dict):
            for op, raw_value in condition.items():
                if op == "$eq":
                    clauses.append(field == _coerce(raw_value))
                elif op == "$ne":
                    clauses.append(field != _coerce(raw_value))
                elif op in ("$gt", "$gte", "$lt", "$lte"):
                    if is_number:
                        left, right = cast(field, Numeric), raw_value
                    else:
                        left, right = field, _coerce(raw_value)
                    if op == "$gt":
                        clauses.append(left > right)
                    elif op == "$gte":
                        clauses.append(left >= right)
                    elif op == "$lt":
                        clauses.append(left < right)
                    else:
                        clauses.append(left <= right)
                elif op == "$contains":
                    target = field if is_json else cast(field, String)
                    text = str(raw_value).replace("/", "//").replace("%", "/%").replace("_", "/_")
                    clauses.append(target.ilike(f"%{text}%", escape="/"))
                elif op == "$in" and isinstance(raw_value, list):
                    clauses.append(field.in_([_coerce(v) for v in raw_value]))
                # Unknown operators are ignored.
        else:
            clauses.append(field == _coerce(condition))

    return clauses
