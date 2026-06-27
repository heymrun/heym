"""ClickHouse client for CRUD, count, and raw SQL node operations.

Uses the official synchronous clickhouse-connect HTTP client, matching the
executor's sync-service-in-threadpool integration pattern (cf. SupabaseService).
"""

import datetime as _dt
import re
from decimal import Decimal
from ipaddress import IPv4Address, IPv6Address
from typing import Any
from uuid import UUID

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_READ_PREFIXES = ("SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "EXISTS")


def _json_safe(value: Any) -> Any:
    """Coerce ClickHouse driver values into JSON-serializable types.

    clickhouse-connect returns rich Python objects (datetime, Decimal, UUID,
    IP addresses, bytes, and nested Array/Tuple/Map containers). The workflow
    executor serializes node output with ``json.dumps``, so anything that is not
    natively JSON-serializable must be normalized here at the service boundary.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (UUID, IPv4Address, IPv6Address)):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _command_summary_result(summary: Any) -> Any:
    """Return a JSON-safe command result instead of a driver object repr."""
    raw_summary = getattr(summary, "summary", None)
    if not isinstance(raw_summary, dict):
        return _json_safe(summary)

    result: dict[str, Any] = {"summary": _json_safe(raw_summary)}
    for field_name in ("written_rows", "written_bytes", "query_id"):
        value = getattr(summary, field_name, None)
        if callable(value):
            value = value()
        if value not in (None, ""):
            result[field_name] = _json_safe(value)
    return result


def _validate_identifier(value: str, kind: str) -> str:
    """Validate a table/column identifier; raise ValueError if unsafe."""
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"ClickHouse {kind} is required")
    if not _IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ValueError(f"ClickHouse {kind} must be a simple identifier: {value!r}")
    return normalized


def _ch_param_type(value: Any) -> str:
    """Map a Python value to a ClickHouse bound-parameter type."""
    if isinstance(value, bool):
        return "Bool"
    if isinstance(value, int):
        return "Int64"
    if isinstance(value, float):
        return "Float64"
    return "String"


class ClickHouseService:
    """Synchronous ClickHouse client wrapper."""

    _CONNECT_TIMEOUT_SECONDS = 15
    _QUERY_LIMIT_DEFAULT = 100

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = dict(config)
        self._host = str(self._config.get("host", "")).strip()
        if not self._host:
            raise ValueError("ClickHouse credential requires host")
        self._database = str(self._config.get("database", "") or "default").strip() or "default"
        self._username = str(self._config.get("username", "") or "default").strip() or "default"
        self._password = str(self._config.get("password", "") or "")
        self._secure = bool(self._config.get("secure", False))
        raw_port = self._config.get("port")
        try:
            self._port = (
                int(raw_port) if raw_port not in (None, "") else (8443 if self._secure else 8123)
            )
        except (TypeError, ValueError):
            self._port = 8443 if self._secure else 8123

    def _client(self):
        from app.services.clickhouse_pool import get_clickhouse_client

        return get_clickhouse_client(
            host=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            database=self._database,
            secure=self._secure,
            connect_timeout=self._CONNECT_TIMEOUT_SECONDS,
        )

    def test_connection(self) -> None:
        """Verify connectivity with a trivial query."""
        try:
            client = self._client()
            client.query("SELECT 1")
        except Exception as exc:  # noqa: BLE001 - surfaced as a user-facing error
            raise ValueError(f"ClickHouse connection test failed: {exc}") from exc

    @staticmethod
    def _rows_to_dicts(result) -> list[dict[str, Any]]:
        columns = list(result.column_names)
        return [
            {col: _json_safe(val) for col, val in zip(columns, row)} for row in result.result_rows
        ]

    def _build_where(self, filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Build a parameterized WHERE clause from a {column: value} dict."""
        if not filters:
            return "", {}
        clauses: list[str] = []
        params: dict[str, Any] = {}
        for column, value in filters.items():
            col = _validate_identifier(column, "column")
            param_name = f"v_{col}"
            clauses.append(f"{col} = {{{param_name}:{_ch_param_type(value)}}}")
            params[param_name] = value
        return " WHERE " + " AND ".join(clauses), params

    def _is_read(self, sql: str) -> bool:
        head = sql.strip().lstrip("(").upper()
        return any(head.startswith(prefix) for prefix in _READ_PREFIXES)

    def query(self, sql: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        sql = str(sql or "").strip()
        if not sql:
            raise ValueError("ClickHouse query is required")
        client = self._client()
        if self._is_read(sql):
            result = client.query(sql, parameters=parameters or {})
            rows = self._rows_to_dicts(result)
            return {"rows": rows, "count": len(rows), "success": True}
        summary = client.command(sql, parameters=parameters or {})
        return {"result": _command_summary_result(summary), "success": True}

    def _sanitize_sort(self, sort: str) -> str:
        """Allow 'col' or 'col ASC|DESC'; validate the column identifier."""
        parts = sort.split()
        col = _validate_identifier(parts[0], "sort column")
        direction = ""
        if len(parts) > 1 and parts[1].upper() in {"ASC", "DESC"}:
            direction = " " + parts[1].upper()
        return f"{col}{direction}"

    def find(self, table: str, *, filters: dict[str, Any], limit: int, sort: str) -> dict[str, Any]:
        tbl = _validate_identifier(table, "table")
        where, params = self._build_where(filters or {})
        sql = f"SELECT * FROM {tbl}{where}"
        sort = str(sort or "").strip()
        if sort:
            sql += f" ORDER BY {self._sanitize_sort(sort)}"
        limit_int = int(limit)
        if limit_int > 0:  # 0 (or negative) means unlimited — emit no LIMIT clause
            sql += f" LIMIT {limit_int}"
        result = self._client().query(sql, parameters=params)
        rows = self._rows_to_dicts(result)
        return {"rows": rows, "count": len(rows), "success": True}

    def get_all(self, table: str, *, limit: int) -> dict[str, Any]:
        return self.find(table, filters={}, limit=limit, sort="")

    def count(self, table: str, *, filters: dict[str, Any]) -> dict[str, Any]:
        tbl = _validate_identifier(table, "table")
        where, params = self._build_where(filters or {})
        result = self._client().query(f"SELECT count() FROM {tbl}{where}", parameters=params)
        total = int(result.result_rows[0][0]) if result.result_rows else 0
        return {"count": total, "success": True}

    def get_by_id(self, table: str, row_id: str, *, id_column: str = "id") -> dict[str, Any]:
        tbl = _validate_identifier(table, "table")
        col = _validate_identifier(id_column, "id column")
        result = self._client().query(
            f"SELECT * FROM {tbl} WHERE {col} = {{v_id:String}} LIMIT 1",
            parameters={"v_id": str(row_id)},
        )
        rows = self._rows_to_dicts(result)
        return {"row": rows[0] if rows else None, "success": True}

    def list_columns(self, table: str) -> dict[str, Any]:
        """Discover a table's columns (name + type) via DESCRIBE TABLE."""
        tbl = _validate_identifier(table, "table")
        result = self._client().query(f"DESCRIBE TABLE {tbl}")
        columns = [
            {"name": str(row[0]), "type": str(row[1])}
            for row in result.result_rows
            if row and row[0]
        ]
        return {"columns": columns, "success": True}

    def insert(self, table: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        tbl = _validate_identifier(table, "table")
        if not rows:
            raise ValueError("ClickHouse insert requires at least one row")
        if not all(isinstance(r, dict) for r in rows):
            raise ValueError("ClickHouse insert rows must be JSON objects")
        column_set: list[str] = []
        for row in rows:
            for key in row:
                col = _validate_identifier(key, "column")
                if col not in column_set:
                    column_set.append(col)
        data = [[row.get(col) for col in column_set] for row in rows]
        self._client().insert(tbl, data, column_names=column_set)
        return {"count": len(rows), "success": True}

    def upsert(self, table: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        # ClickHouse upsert relies on a ReplacingMergeTree table; an INSERT is the upsert.
        return self.insert(table, rows)

    def update(
        self, table: str, *, data: dict[str, Any], filters: dict[str, Any]
    ) -> dict[str, Any]:
        tbl = _validate_identifier(table, "table")
        if not data:
            raise ValueError("ClickHouse update requires data")
        if not filters:
            raise ValueError("ClickHouse update requires a filter to avoid a full-table mutation")
        set_parts: list[str] = []
        params: dict[str, Any] = {}
        for column, value in data.items():
            col = _validate_identifier(column, "column")
            name = f"set_{col}"
            set_parts.append(f"{col} = {{{name}:{_ch_param_type(value)}}}")
            params[name] = value
        where, where_params = self._build_where(filters)
        params.update(where_params)
        sql = f"ALTER TABLE {tbl} UPDATE " + ", ".join(set_parts) + where
        self._client().command(sql, parameters=params)
        return {"success": True}

    def remove(self, table: str, *, filters: dict[str, Any]) -> dict[str, Any]:
        tbl = _validate_identifier(table, "table")
        if not filters:
            raise ValueError("ClickHouse remove requires a filter to avoid deleting all rows")
        where, params = self._build_where(filters)
        self._client().command(f"DELETE FROM {tbl}{where}", parameters=params)
        return {"success": True}
