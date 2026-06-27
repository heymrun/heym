"""ClickHouse client for CRUD, count, and raw SQL node operations.

Uses the official synchronous clickhouse-connect HTTP client, matching the
executor's sync-service-in-threadpool integration pattern (cf. SupabaseService).
"""

import re
from typing import Any

import clickhouse_connect

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_READ_PREFIXES = ("SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "EXISTS")


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
    _QUERY_LIMIT_MAX = 10_000

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
                int(raw_port)
                if raw_port not in (None, "")
                else (8443 if self._secure else 8123)
            )
        except (TypeError, ValueError):
            self._port = 8443 if self._secure else 8123

    def _client(self):
        return clickhouse_connect.get_client(
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
        return [dict(zip(columns, row)) for row in result.result_rows]

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
        return {"result": str(summary), "success": True}

    def _clamp_limit(self, limit: int) -> int:
        if limit <= 0:
            return self._QUERY_LIMIT_MAX
        return min(limit, self._QUERY_LIMIT_MAX)

    def _sanitize_sort(self, sort: str) -> str:
        """Allow 'col' or 'col ASC|DESC'; validate the column identifier."""
        parts = sort.split()
        col = _validate_identifier(parts[0], "sort column")
        direction = ""
        if len(parts) > 1 and parts[1].upper() in {"ASC", "DESC"}:
            direction = " " + parts[1].upper()
        return f"{col}{direction}"

    def find(
        self, table: str, *, filters: dict[str, Any], limit: int, sort: str
    ) -> dict[str, Any]:
        tbl = _validate_identifier(table, "table")
        where, params = self._build_where(filters or {})
        sql = f"SELECT * FROM {tbl}{where}"
        sort = str(sort or "").strip()
        if sort:
            sql += f" ORDER BY {self._sanitize_sort(sort)}"
        sql += f" LIMIT {self._clamp_limit(int(limit))}"
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
