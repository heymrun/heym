"""Translate a Data Table node's Mongo-style filter into SQLAlchemy clauses."""

from decimal import Decimal

# Text PostgreSQL can cast to NUMERIC; a blank or non-numeric cell compares as NULL instead.
_NUMBER_PATTERN = r"^\s*[-+]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][-+]?[0-9]+)?\s*$"


def _as_number(value: object) -> Decimal | None:
    """Return a filter value as a number, or None when it is not one (booleans are not)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = Decimal(str(value).strip())
    except ArithmeticError:
        return None
    return number if number.is_finite() else None


def build_data_table_filter_clauses(filter_dict: dict, columns: list) -> list:
    """Build SQLAlchemy filter clauses for a DataTable Mongo-style filter.

    A plain value means equality. An object value applies comparison operators:
    ``$eq``, ``$ne``, ``$gt``, ``$gte``, ``$lt``, ``$lte``, ``$contains`` (ILIKE
    substring) and ``$in`` (list membership).

    User-defined schema columns live in the JSON ``data`` blob and are matched as text
    (booleans use ``"true"``/``"false"``). A ``number`` column compares as ``NUMERIC``, so
    ``10`` matches a cell written ``10.00``; a blank or non-numeric cell never matches a
    number, and ``$ne`` keeps it.
    Row metadata (``id``, ``created_at``, ``updated_at``, ``created_by``, ``updated_by``,
    ``table_id``) are real table columns matched directly; ``$contains`` casts them to text.
    A schema column sharing a metadata name still resolves against the JSON blob.
    Unknown operators are ignored.
    """
    from sqlalchemy import Numeric, String, and_, case, cast, or_

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

        # Cast only text that is a number: one blank cell would otherwise fail the whole query.
        number_field = case((field.op("~")(_NUMBER_PATTERN), cast(field, Numeric)))

        def _equals(value: object) -> object:
            number = _as_number(value) if is_number else None
            return field == _coerce(value) if number is None else number_field == number

        if isinstance(condition, dict):
            for op, raw_value in condition.items():
                if op == "$eq":
                    clauses.append(_equals(raw_value))
                elif op == "$ne":
                    number = _as_number(raw_value) if is_number else None
                    if number is None:
                        clauses.append(field != _coerce(raw_value))
                    else:
                        not_a_number = and_(field.is_not(None), number_field.is_(None))
                        clauses.append(or_(number_field != number, not_a_number))
                elif op in ("$gt", "$gte", "$lt", "$lte"):
                    if is_number:
                        number = _as_number(raw_value)
                        left, right = number_field, raw_value if number is None else number
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
                    if is_number and raw_value:
                        clauses.append(or_(*(_equals(v) for v in raw_value)))
                    else:
                        clauses.append(field.in_([_coerce(v) for v in raw_value]))
                # Unknown operators are ignored.
        else:
            clauses.append(_equals(condition))

    return clauses
