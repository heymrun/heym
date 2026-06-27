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
