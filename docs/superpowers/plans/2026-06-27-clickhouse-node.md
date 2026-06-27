# ClickHouse Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `clickhouse` workflow node to heymrun (DataTable-style CRUD + count + raw SQL against an external ClickHouse DB), with backend tests, DSL updates, and heymweb docs/intro/template sync.

**Architecture:** A sync `ClickHouseService` wraps the official `clickhouse-connect` HTTP client and runs inside the executor's threadpool, mirroring the existing Supabase integration. A new `clickhouse` credential type stores connection details. The executor gains a `clickhouse` node branch that resolves expressions and dispatches operations. Frontend adds node/credential types, a properties editor, and palette/icon registration. heymweb receives synced docs, a DSL prompt sync, a marketing node entry, and a template.

**Tech Stack:** Python 3.11 / FastAPI / `clickhouse-connect`; Vue 3 + TS (strict); Next.js (heymweb).

**Reference patterns (read before starting):**
- Service: `backend/app/services/supabase_service.py`
- Executor branch: `backend/app/services/workflow_executor.py:10009-10210` (supabase)
- Selective mode: `backend/app/services/workflow_executor.py:8852-8872` (bigquery `bqMappings`)
- Credential wiring: `backend/app/models/schemas.py:444` (CredentialType), `backend/app/api/credentials.py`
- DSL: `backend/app/services/workflow_dsl_prompt.py:2363` (supabase section)
- Tests: `backend/tests/test_supabase_service.py`, `backend/tests/test_credential_supabase.py`
- Frontend types: `frontend/src/types/credential.ts`, `frontend/src/types/node.ts:781`, `frontend/src/types/workflow.ts`
- Frontend editor: `frontend/src/components/Panels/PropertiesPanel.vue` (supabase section)
- heymweb: `scripts/sync-docs.mjs`, `scripts/sync-dsl-prompt.mjs`, `src/components/sections/NodesSection.tsx:372`, `src/lib/node-doc-links.ts:38`, `src/lib/templates.ts`

**clickhouse-connect API cheatsheet:**
- `client = clickhouse_connect.get_client(host=, port=, username=, password=, database=, secure=)`
- `res = client.query(sql, parameters={...})` → `res.result_rows` (list[tuple]), `res.column_names`
- `client.insert(table, data, column_names=[...])` where `data` is `list[list]`
- `client.command(sql, parameters={...})` for DDL/mutations (`ALTER`, `DELETE`, `INSERT`)
- Server-side bound params use `{name:Type}` placeholders, e.g. `WHERE id = {v_id:String}`

---

## Phase 1 — Backend Service

### Task 1: Add `clickhouse-connect` dependency

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add the dependency**

In `backend/pyproject.toml`, add to the `dependencies` array (alphabetical-ish, near other clients):

```toml
    "clickhouse-connect>=0.8.0",
```

- [ ] **Step 2: Sync**

Run: `cd backend && uv sync`
Expected: resolves and installs `clickhouse-connect`.

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "build: add clickhouse-connect dependency"
```

---

### Task 2: ClickHouseService — connection + validation skeleton

**Files:**
- Create: `backend/app/services/clickhouse_service.py`
- Test: `backend/tests/test_clickhouse_service.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_clickhouse_service.py`:

```python
"""Unit tests for ClickHouseService and the clickhouse executor branch."""

import unittest
from unittest.mock import MagicMock, patch


def _make_config() -> dict:
    return {
        "host": "ch.example.com",
        "port": 8443,
        "username": "default",
        "password": "secret",
        "database": "analytics",
        "secure": True,
    }


class TestClickHouseServiceValidation(unittest.TestCase):
    def _make_service(self):
        from app.services.clickhouse_service import ClickHouseService

        return ClickHouseService(_make_config())

    def test_requires_host(self) -> None:
        from app.services.clickhouse_service import ClickHouseService

        with self.assertRaises(ValueError):
            ClickHouseService({"host": "", "database": "db"})

    def test_rejects_bad_table_name(self) -> None:
        svc = self._make_service()
        with self.assertRaises(ValueError):
            svc.find("bad-table; DROP", filters={}, limit=10, sort="")

    def test_rejects_bad_column_in_filter(self) -> None:
        svc = self._make_service()
        with self.assertRaises(ValueError):
            svc.find("events", filters={"bad col": 1}, limit=10, sort="")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clickhouse_service.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.clickhouse_service`.

- [ ] **Step 3: Write the service skeleton**

Create `backend/app/services/clickhouse_service.py`:

```python
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
            self._port = int(raw_port) if raw_port not in (None, "") else (8443 if self._secure else 8123)
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
```

- [ ] **Step 4: Run to verify validation tests pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clickhouse_service.py -v`
Expected: `test_requires_host` PASSES; `test_rejects_bad_table_name` / `test_rejects_bad_column_in_filter` FAIL (methods not defined yet). That is expected — they pass after Task 3.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/clickhouse_service.py backend/tests/test_clickhouse_service.py
git commit -m "feat: add ClickHouseService skeleton with identifier validation"
```

---

### Task 3: ClickHouseService — read operations (query, find, getAll, count, getById)

**Files:**
- Modify: `backend/app/services/clickhouse_service.py`
- Test: `backend/tests/test_clickhouse_service.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_clickhouse_service.py`:

```python
class TestClickHouseReads(unittest.TestCase):
    def _svc_with_client(self, mock_client):
        from app.services.clickhouse_service import ClickHouseService

        svc = ClickHouseService(_make_config())
        svc._client = MagicMock(return_value=mock_client)
        return svc

    def _mock_query_result(self, rows, columns):
        result = MagicMock()
        result.result_rows = rows
        result.column_names = columns
        return result

    def test_query_select_returns_rows(self) -> None:
        client = MagicMock()
        client.query.return_value = self._mock_query_result(
            [(1, "a"), (2, "b")], ["id", "name"]
        )
        svc = self._svc_with_client(client)
        out = svc.query("SELECT id, name FROM events")
        self.assertEqual(out["rows"], [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
        self.assertEqual(out["count"], 2)
        self.assertTrue(out["success"])

    def test_query_non_select_uses_command(self) -> None:
        client = MagicMock()
        client.command.return_value = "OK"
        svc = self._svc_with_client(client)
        out = svc.query("ALTER TABLE events DELETE WHERE id = 1")
        client.command.assert_called_once()
        self.assertTrue(out["success"])

    def test_find_builds_parameterized_where(self) -> None:
        client = MagicMock()
        client.query.return_value = self._mock_query_result([(1,)], ["id"])
        svc = self._svc_with_client(client)
        svc.find("events", filters={"status": "active"}, limit=5, sort="created_at DESC")
        sql, kwargs = client.query.call_args[0][0], client.query.call_args[1]
        self.assertIn("status = {", sql)
        self.assertIn("LIMIT 5", sql)
        self.assertIn("ORDER BY", sql)
        self.assertEqual(kwargs["parameters"]["v_status"], "active")

    def test_count_returns_int(self) -> None:
        client = MagicMock()
        result = MagicMock()
        result.result_rows = [(42,)]
        result.column_names = ["count"]
        client.query.return_value = result
        svc = self._svc_with_client(client)
        out = svc.count("events", filters={})
        self.assertEqual(out["count"], 42)
        self.assertTrue(out["success"])

    def test_get_by_id(self) -> None:
        client = MagicMock()
        client.query.return_value = self._mock_query_result([(7, "x")], ["id", "name"])
        svc = self._svc_with_client(client)
        out = svc.get_by_id("events", "7")
        self.assertEqual(out["row"], {"id": 7, "name": "x"})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clickhouse_service.py::TestClickHouseReads -v`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Implement read methods**

Append to `ClickHouseService` in `backend/app/services/clickhouse_service.py`:

```python
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

    def _sanitize_sort(self, sort: str) -> str:
        """Allow 'col' or 'col ASC|DESC'; validate the column identifier."""
        parts = sort.split()
        col = _validate_identifier(parts[0], "sort column")
        direction = ""
        if len(parts) > 1 and parts[1].upper() in {"ASC", "DESC"}:
            direction = " " + parts[1].upper()
        return f"{col}{direction}"
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clickhouse_service.py -v`
Expected: all read tests + Task 2 validation tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/clickhouse_service.py backend/tests/test_clickhouse_service.py
git commit -m "feat: ClickHouseService read operations (query/find/getAll/count/getById)"
```

---

### Task 4: ClickHouseService — write operations (insert, update, remove, upsert)

**Files:**
- Modify: `backend/app/services/clickhouse_service.py`
- Test: `backend/tests/test_clickhouse_service.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_clickhouse_service.py`:

```python
class TestClickHouseWrites(unittest.TestCase):
    def _svc_with_client(self, mock_client):
        from app.services.clickhouse_service import ClickHouseService

        svc = ClickHouseService(_make_config())
        svc._client = MagicMock(return_value=mock_client)
        return svc

    def test_insert_aligns_columns(self) -> None:
        client = MagicMock()
        svc = self._svc_with_client(client)
        out = svc.insert("events", [{"id": 1, "name": "a"}, {"name": "b"}])
        table, data = client.insert.call_args[0][0], client.insert.call_args[0][1]
        column_names = client.insert.call_args[1]["column_names"]
        self.assertEqual(table, "events")
        self.assertEqual(sorted(column_names), ["id", "name"])
        # missing keys become None, aligned to column order
        self.assertEqual(len(data), 2)
        self.assertEqual(out["count"], 2)
        self.assertTrue(out["success"])

    def test_insert_rejects_empty(self) -> None:
        svc = self._svc_with_client(MagicMock())
        with self.assertRaises(ValueError):
            svc.insert("events", [])

    def test_update_builds_alter(self) -> None:
        client = MagicMock()
        svc = self._svc_with_client(client)
        svc.update("events", data={"name": "z"}, filters={"id": 1})
        sql = client.command.call_args[0][0]
        params = client.command.call_args[1]["parameters"]
        self.assertIn("ALTER TABLE events UPDATE", sql)
        self.assertIn("name = {", sql)
        self.assertIn("WHERE", sql)
        self.assertEqual(params["set_name"], "z")
        self.assertEqual(params["v_id"], 1)

    def test_update_requires_filter(self) -> None:
        svc = self._svc_with_client(MagicMock())
        with self.assertRaises(ValueError):
            svc.update("events", data={"name": "z"}, filters={})

    def test_remove_builds_delete(self) -> None:
        client = MagicMock()
        svc = self._svc_with_client(client)
        svc.remove("events", filters={"id": 1})
        sql = client.command.call_args[0][0]
        self.assertIn("DELETE FROM events WHERE", sql)

    def test_remove_requires_filter(self) -> None:
        svc = self._svc_with_client(MagicMock())
        with self.assertRaises(ValueError):
            svc.remove("events", filters={})

    def test_upsert_delegates_to_insert(self) -> None:
        client = MagicMock()
        svc = self._svc_with_client(client)
        out = svc.upsert("events", [{"id": 1}])
        client.insert.assert_called_once()
        self.assertTrue(out["success"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clickhouse_service.py::TestClickHouseWrites -v`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Implement write methods**

Append to `ClickHouseService`:

```python
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
```

- [ ] **Step 4: Run the full service test module**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clickhouse_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/clickhouse_service.py backend/tests/test_clickhouse_service.py
git commit -m "feat: ClickHouseService write operations (insert/update/remove/upsert)"
```

---

## Phase 2 — Backend Credential + Schemas

### Task 5: Add `clickhouse` credential type and config model

**Files:**
- Modify: `backend/app/models/schemas.py:444` (CredentialType enum), and after `CredentialConfigSupabase`

- [ ] **Step 1: Add enum member**

In `backend/app/models/schemas.py`, in `class CredentialType`, after `elevenlabs = "elevenlabs"`:

```python
    clickhouse = "clickhouse"
```

- [ ] **Step 2: Add config model**

After `class CredentialConfigSupabase` (around line 531), add:

```python
class CredentialConfigClickHouse(BaseModel):
    host: str
    port: int | None = None
    username: str | None = "default"
    password: str | None = ""
    database: str | None = "default"
    secure: bool | None = False
```

- [ ] **Step 3: Verify import compiles**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "from app.models.schemas import CredentialType, CredentialConfigClickHouse; print(CredentialType.clickhouse.value)"`
Expected: prints `clickhouse`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/schemas.py
git commit -m "feat: add clickhouse credential type and config model"
```

---

### Task 6: Wire credential masking, summary, and connection test

**Files:**
- Modify: `backend/app/api/credentials.py`
- Test: `backend/tests/test_credential_clickhouse.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_credential_clickhouse.py`:

```python
"""Tests for the clickhouse credential summary and connection test."""

import unittest
from unittest.mock import MagicMock, patch

from app.models.schemas import CredentialType


class TestClickHouseCredential(unittest.TestCase):
    def test_summary_includes_host_and_database(self) -> None:
        from app.api.credentials import get_masked_value

        summary = get_masked_value(
            CredentialType.clickhouse,
            {"host": "ch.example.com", "database": "analytics"},
        )
        self.assertIn("ch.example.com", summary)
        self.assertIn("analytics", summary)

    def test_test_connection_invoked(self) -> None:
        from app.services.clickhouse_service import ClickHouseService

        svc = ClickHouseService(
            {"host": "ch.example.com", "database": "analytics", "secure": True}
        )
        with patch.object(svc, "_client", return_value=MagicMock()) as mock_client:
            svc.test_connection()
            mock_client.return_value.query.assert_called_once_with("SELECT 1")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_credential_clickhouse.py -v`
Expected: FAIL — `get_masked_value` returns `None` for clickhouse.

- [ ] **Step 3: Add masking/summary**

In `backend/app/api/credentials.py`, inside `get_masked_value`, after the `elif credential_type == CredentialType.s3:` branch (around line 159), add:

```python
    elif credential_type == CredentialType.clickhouse:
        host = str(config.get("host", "")).strip()
        database = str(config.get("database", "default")).strip() or "default"
        if host:
            return f"{host} ({database})"
        return None
```

- [ ] **Step 4: Allow connection testing**

In `backend/app/api/credentials.py`, find the connection-test guard near line 677:

```python
    if test_data.type not in {CredentialType.supabase, CredentialType.notion}:
```

Change it to include clickhouse:

```python
    if test_data.type not in {
        CredentialType.supabase,
        CredentialType.notion,
        CredentialType.clickhouse,
    }:
```

Then in the test-dispatch block (near line 705, where supabase's `test_connection` is called), add a branch:

```python
        elif test_data.type == CredentialType.clickhouse:
            from app.services.clickhouse_service import ClickHouseService

            await run_in_threadpool(ClickHouseService(config).test_connection)
```

(Place it as a sibling to the existing `if test_data.type == CredentialType.supabase:` / notion branches; match the surrounding structure and `await run_in_threadpool(...)` usage already present in that block.)

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_credential_clickhouse.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/credentials.py backend/tests/test_credential_clickhouse.py
git commit -m "feat: clickhouse credential masking, summary, and connection test"
```

---

## Phase 3 — Backend Executor Branch

### Task 7: Add `clickhouse` node branch to the executor

**Files:**
- Modify: `backend/app/services/workflow_executor.py` (add branch after the supabase branch, near line 10208, before `elif node_type == "s3":`)
- Test: `backend/tests/test_clickhouse_service.py` (add executor-branch tests)

- [ ] **Step 1: Write failing executor tests**

Append to `backend/tests/test_clickhouse_service.py`:

```python
class TestClickHouseExecutorBranch(unittest.IsolatedAsyncioTestCase):
    def _executor(self):
        from app.services.workflow_executor import WorkflowExecutor

        return WorkflowExecutor.__new__(WorkflowExecutor)

    async def test_find_dispatch(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        node_data = {
            "credentialId": "cred-1",
            "clickhouseOperation": "find",
            "clickhouseTable": "events",
            "clickhouseFilter": '{"status":"active"}',
            "clickhouseLimit": "5",
            "clickhouseSort": "",
        }
        executor = self._executor()
        executor.evaluate_message_template = lambda tpl, inputs, node_id: tpl
        executor.evaluate_nonempty_message_template = lambda tpl, inputs, node_id: tpl
        fake_service = MagicMock()
        fake_service.find.return_value = {"rows": [], "count": 0, "success": True}
        with patch.object(
            WorkflowExecutor, "_get_accessible_credential", return_value=MagicMock(encrypted_config="x")
        ), patch("app.services.encryption.decrypt_config", return_value={"host": "h", "database": "d"}), patch(
            "app.services.clickhouse_service.ClickHouseService", return_value=fake_service
        ):
            output = await executor._run_clickhouse_node(node_data, {}, "node-1")
        fake_service.find.assert_called_once()
        self.assertTrue(output["success"])
```

> Note: this test calls a small helper `_run_clickhouse_node` you will extract in Step 3 so the branch is unit-testable without running the whole `execute_node`. If you prefer to keep the logic inline in `execute_node`, replace this test with an integration-style test that builds a minimal workflow; the inline approach is also acceptable. The helper approach is recommended for testability.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clickhouse_service.py::TestClickHouseExecutorBranch -v`
Expected: FAIL — `_run_clickhouse_node` not defined.

- [ ] **Step 3: Add the branch + helper**

In `backend/app/services/workflow_executor.py`, add a method on `WorkflowExecutor` (near the other node helpers) that contains the dispatch logic:

```python
    async def _run_clickhouse_node(self, node_data: dict, inputs: dict, node_id: str) -> dict:
        import json as _json

        from app.db.session import SessionLocal
        from app.services.clickhouse_service import ClickHouseService
        from app.services.encryption import decrypt_config

        credential_id = node_data.get("credentialId")
        if not credential_id:
            raise ValueError("ClickHouse node requires a credential")

        ch_config: dict = {}
        with SessionLocal() as db:
            cred = self._get_accessible_credential(db, credential_id)
            if cred:
                ch_config = decrypt_config(cred.encrypted_config)
        if not ch_config:
            raise ValueError("ClickHouse credential not found or invalid")

        operation = str(node_data.get("clickhouseOperation", "") or "").strip()
        if not operation:
            raise ValueError("ClickHouse node requires an operation")

        service = ClickHouseService(ch_config)

        def _resolve(field: str, default: str = "") -> str:
            return self.evaluate_message_template(
                str(node_data.get(field, default) or default), inputs, node_id
            ).strip()

        def _resolve_filters() -> dict:
            raw = self.evaluate_message_template(
                str(node_data.get("clickhouseFilter", "{}") or "{}"), inputs, node_id
            )
            parsed = _json.loads(raw or "{}")
            if not isinstance(parsed, dict):
                raise ValueError("clickhouseFilter must be a JSON object")
            return parsed

        def _resolve_limit(default: int = 100) -> int:
            raw = _resolve("clickhouseLimit", str(default))
            try:
                return int(float(raw or default))
            except (TypeError, ValueError):
                return default

        def _resolve_rows() -> list:
            input_mode = str(node_data.get("clickhouseInputMode", "raw") or "raw").strip()
            if input_mode == "selective":
                mappings = node_data.get("clickhouseMappings", []) or []
                row: dict = {}
                for mapping in mappings:
                    key = str(mapping.get("key", "") or "")
                    if not key:
                        continue
                    row[key] = self.evaluate_message_template(
                        str(mapping.get("value", "")), inputs, node_id
                    )
                return [row]
            raw = self.evaluate_message_template(
                str(node_data.get("clickhouseData", "[]") or "[]"), inputs, node_id
            )
            parsed = _json.loads(raw or "[]")
            if isinstance(parsed, dict):
                return [parsed]
            if not isinstance(parsed, list):
                raise ValueError("clickhouseData must be a JSON array or object")
            return parsed

        if operation == "query":
            sql = self.evaluate_message_template(
                str(node_data.get("clickhouseQuery", "") or ""), inputs, node_id
            ).strip()
            return service.query(sql)
        if operation == "find":
            return service.find(
                _resolve("clickhouseTable"),
                filters=_resolve_filters(),
                limit=_resolve_limit(),
                sort=_resolve("clickhouseSort"),
            )
        if operation == "getAll":
            return service.get_all(_resolve("clickhouseTable"), limit=_resolve_limit())
        if operation == "count":
            return service.count(_resolve("clickhouseTable"), filters=_resolve_filters())
        if operation == "getById":
            return service.get_by_id(
                _resolve("clickhouseTable"), _resolve("clickhouseRowId")
            )
        if operation == "insert":
            return service.insert(_resolve("clickhouseTable"), _resolve_rows())
        if operation == "upsert":
            return service.upsert(_resolve("clickhouseTable"), _resolve_rows())
        if operation == "update":
            raw_data = self.evaluate_message_template(
                str(node_data.get("clickhouseData", "{}") or "{}"), inputs, node_id
            )
            data = _json.loads(raw_data or "{}")
            if not isinstance(data, dict):
                raise ValueError("clickhouseData must be a JSON object for update")
            return service.update(
                _resolve("clickhouseTable"), data=data, filters=_resolve_filters()
            )
        if operation == "remove":
            return service.remove(
                _resolve("clickhouseTable"), filters=_resolve_filters()
            )
        raise ValueError(f"Unknown ClickHouse operation: {operation}")
```

Then add the branch in `execute_node` (after the supabase branch ends, before `elif node_type == "s3":`):

```python
            elif node_type == "clickhouse":
                output = await self._run_clickhouse_node(node_data, inputs, node_id)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clickhouse_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflow_executor.py backend/tests/test_clickhouse_service.py
git commit -m "feat: add clickhouse node branch to workflow executor"
```

---

## Phase 4 — DSL Prompt

### Task 8: Document the clickhouse node in the DSL prompt

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py` (add a section after the supabase section, near line 2420)
- Test: `backend/tests/test_clickhouse_service.py`

- [ ] **Step 1: Write a failing presence test**

Append to `backend/tests/test_clickhouse_service.py`:

```python
class TestClickHouseDslPrompt(unittest.TestCase):
    def test_prompt_mentions_clickhouse(self) -> None:
        from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT

        self.assertIn('"type": "clickhouse"', WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("clickhouseOperation", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("clickhouseQuery", WORKFLOW_DSL_SYSTEM_PROMPT)
```

> Confirm the exported constant name first: `grep -n "WORKFLOW_DSL_SYSTEM_PROMPT" backend/app/services/workflow_dsl_prompt.py`. If the prompt string is assembled under a different symbol, import that instead.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clickhouse_service.py::TestClickHouseDslPrompt -v`
Expected: FAIL.

- [ ] **Step 3: Add the DSL section**

In `backend/app/services/workflow_dsl_prompt.py`, after the supabase section (it ends before the next `### NN.` header following line 2420), insert a new section that mirrors the supabase format:

````python
### 24B. clickhouse (ClickHouse Database Operations)
- **Purpose**: Run CRUD, count, and raw SQL operations against an external ClickHouse database via the official HTTP client.
- **Credential required**: `clickhouse` credential type (`host`, `port`, `username`, `password`, `database`, `secure`).
- **Fields**:
  - `credentialId`: UUID of the ClickHouse credential.
  - `clickhouseOperation`: `"query"` | `"find"` | `"getAll"` | `"count"` | `"getById"` | `"insert"` | `"update"` | `"remove"` | `"upsert"`.
  - `clickhouseTable`: Table name (simple identifier; supports expressions). Required for all ops except `query`.
  - `clickhouseQuery`: Raw SQL for `query` (SELECT returns rows; other statements run as commands). Supports expressions.
  - `clickhouseFilter`: JSON object of equality filters, e.g. `{"status":"active"}`. Used by `find`, `count`, `update`, `remove`. Values are parameterized.
  - `clickhouseLimit`: Max rows for `find` / `getAll` (`"0"` = up to 10000). Default `100`.
  - `clickhouseSort`: Optional `column` or `column ASC|DESC` for `find`.
  - `clickhouseRowId`: Value matched against the `id` column for `getById`.
  - `clickhouseInputMode`: `"raw"` (JSON in `clickhouseData`) | `"selective"` (key/value `clickhouseMappings`) for `insert` / `upsert`.
  - `clickhouseData`: JSON array of row objects for `insert`/`upsert`, or JSON object of column values for `update`. Supports expressions.
  - `clickhouseMappings`: Array of `{key, value}` pairs used when `clickhouseInputMode` is `"selective"`.
- **Operation → required fields → output**:

| Operation | Required | Output |
| --- | --- | --- |
| `query` | `clickhouseQuery` | `{rows, count, success}` (SELECT) or `{result, success}` |
| `find` | `clickhouseTable` | `{rows, count, success}` |
| `getAll` | `clickhouseTable` | `{rows, count, success}` |
| `count` | `clickhouseTable` | `{count, success}` |
| `getById` | `clickhouseTable`, `clickhouseRowId` | `{row, success}` |
| `insert` (raw) | `clickhouseTable`, `clickhouseData` | `{count, success}` |
| `insert` (selective) | `clickhouseTable`, `clickhouseMappings` | `{count, success}` |
| `update` | `clickhouseTable`, `clickhouseData`, `clickhouseFilter` | `{success}` |
| `remove` | `clickhouseTable`, `clickhouseFilter` | `{success}` |
| `upsert` | `clickhouseTable`, `clickhouseData` | `{count, success}` |

- **Notes**:
  - `update` (`ALTER TABLE ... UPDATE`) and `remove` (`DELETE FROM`) are asynchronous ClickHouse mutations — they are eventually applied and are costly; prefer batch writes.
  - `upsert` assumes a `ReplacingMergeTree` table; it performs an `INSERT`.
  - `getById` assumes an `id` column.
  - `update` and `remove` require a non-empty `clickhouseFilter` to avoid full-table mutations.

Example:
```json
{
  "id": "ch_1",
  "type": "clickhouse",
  "data": {
    "credentialId": "<clickhouse-credential-uuid>",
    "clickhouseOperation": "insert",
    "clickhouseTable": "events",
    "clickhouseInputMode": "raw",
    "clickhouseData": "[{\"id\": \"{{$json.id}}\", \"event\": \"signup\"}]"
  }
}
```
````

> Keep this OUT of any clarify-protocol-guarded block; it belongs in the synced `WORKFLOW_DSL_SYSTEM_PROMPT` body so heymweb `/convert` picks it up via the DSL sync.

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_clickhouse_service.py::TestClickHouseDslPrompt -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./run_tests.sh`
Expected: PASS (no regressions). If the DSL sync-diff guard test (heymweb parity) exists and fails, that is expected until Phase 6 Task 14 runs the sync — note it and continue.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py backend/tests/test_clickhouse_service.py
git commit -m "docs: add clickhouse node to workflow DSL prompt"
```

---

## Phase 5 — Frontend (heymrun)

### Task 9: Add node + credential TypeScript types

**Files:**
- Modify: `frontend/src/types/workflow.ts`, `frontend/src/types/credential.ts`

- [ ] **Step 1: Add node type + config fields in `workflow.ts`**

In the node-type union (near line 167, after `"supabase"`), add:

```typescript
  | "clickhouse"
```

Add a `ClickHouseOperation` type near `DataTableOperation` (line 237):

```typescript
export type ClickHouseOperation =
  | "query"
  | "find"
  | "getAll"
  | "count"
  | "getById"
  | "insert"
  | "update"
  | "remove"
  | "upsert";
```

In the node-data interface (after the `supabase*` fields, around line 609), add:

```typescript
  clickhouseOperation?: ClickHouseOperation;
  clickhouseTable?: string;
  clickhouseQuery?: string;
  clickhouseFilter?: string;
  clickhouseLimit?: string;
  clickhouseSort?: string;
  clickhouseRowId?: string;
  clickhouseInputMode?: "raw" | "selective";
  clickhouseData?: string;
  clickhouseMappings?: Array<{ key: string; value: string }>;
```

- [ ] **Step 2: Add credential type in `credential.ts`**

In the credential-type union (after `"elevenlabs"`, line 26):

```typescript
  | "clickhouse"
```

After `CredentialConfigSupabase` (line 200), add:

```typescript
export interface CredentialConfigClickHouse {
  host: string;
  port?: number;
  username?: string;
  password?: string;
  database?: string;
  secure?: boolean;
}
```

In the labels map (line ~318) add:

```typescript
  clickhouse: "ClickHouse",
```

In the descriptions map (line ~348) add:

```typescript
  clickhouse: "Connect to ClickHouse — run SQL and CRUD over OLAP tables via the HTTP interface",
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/types/credential.ts
git commit -m "feat: clickhouse node and credential TypeScript types"
```

---

### Task 10: Register node definition, icon, and palette

**Files:**
- Modify: `frontend/src/types/node.ts:781` (after supabase block), `frontend/src/lib/nodeIcons.ts:81,132`

- [ ] **Step 1: Add node definition in `node.ts`**

After the `supabase: { ... }` definition block (ends ~line 806), add:

```typescript
  clickhouse: {
    type: "clickhouse",
    label: "ClickHouse",
    description: "Run SQL, CRUD, and count operations against ClickHouse",
    color: "node-datatable",
    icon: "Database",
    inputs: 1,
    outputs: 1,
    defaultData: {
      label: "clickhouse",
      credentialId: "",
      clickhouseOperation: undefined as string | undefined,
      clickhouseTable: "",
      clickhouseQuery: "",
      clickhouseFilter: "{}",
      clickhouseLimit: "100",
      clickhouseSort: "",
      clickhouseRowId: "",
      clickhouseInputMode: "raw",
      clickhouseData: "[]",
      clickhouseMappings: [] as Array<{ key: string; value: string }>,
    },
  },
```

- [ ] **Step 2: Add icon mappings in `nodeIcons.ts`**

After `supabase: Database,` (line 81):

```typescript
  clickhouse: Database,
```

After `supabase: "text-node-datatable",` (line 132):

```typescript
  clickhouse: "text-node-datatable",
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Verify the node appears in the palette**

Confirm the node palette is data-driven from `node.ts` (search `NodePanel.vue` for how it lists nodes). If `NodePanel.vue` keys off the node definitions map, no further change is needed. If it has an explicit category/allowlist array, add `"clickhouse"` to the same group that contains `"supabase"`.

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/node.ts frontend/src/lib/nodeIcons.ts frontend/src/components/Panels/NodePanel.vue
git commit -m "feat: register clickhouse node definition, icon, and palette entry"
```

---

### Task 11: Properties editor + credential form

**Files:**
- Modify: `frontend/src/components/Panels/PropertiesPanel.vue`, `frontend/src/components/Credentials/CredentialDialog.vue`

- [ ] **Step 1: Add the ClickHouse properties editor**

In `PropertiesPanel.vue`, locate the supabase editor block (search `supabaseOperation`). Add a sibling `<template v-if="node.type === 'clickhouse'">` section that renders, bound to `node.data`:
- credential selector filtered to `clickhouse` credentials (reuse the existing credential-select component used by the supabase block);
- an operation `<select>` over `query | find | getAll | count | getById | insert | update | remove | upsert`;
- conditional fields by operation:
  - `query`: a `clickhouseQuery` textarea;
  - `find`/`count`/`update`/`remove`: `clickhouseTable` + `clickhouseFilter` (JSON) inputs; `find` also shows `clickhouseSort` + `clickhouseLimit`;
  - `getAll`: `clickhouseTable` + `clickhouseLimit`;
  - `getById`: `clickhouseTable` + `clickhouseRowId`;
  - `insert`/`upsert`: `clickhouseTable` + an input-mode toggle (`raw` shows `clickhouseData` textarea; `selective` shows the key/value `clickhouseMappings` editor — reuse the same mapping-row component the bigquery `bqMappings` editor uses);
  - `update`: also a `clickhouseData` JSON-object textarea.

Mark `clickhouseTable`, `clickhouseQuery`, `clickhouseFilter`, `clickhouseLimit`, `clickhouseSort`, `clickhouseRowId`, `clickhouseData`, and mapping `value` fields as expression-eligible (wire them the same way the supabase fields register with the expression dialog metadata, so double-click `1/n` navigation discovers them).

- [ ] **Step 2: Add the ClickHouse credential form**

In `CredentialDialog.vue`, find the supabase credential form branch and add a `clickhouse` branch with inputs for `host`, `port`, `username`, `password` (password input type), `database`, and a `secure` checkbox, bound to the credential config. Include the "Test connection" button if the dialog wires it generically (clickhouse is already allowed by Task 6).

- [ ] **Step 3: Lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Manual smoke (no UI test harness — see project rule "No frontend UI tests")**

Run the app (`./run.sh`), add a ClickHouse node, confirm: operation switch shows the right fields; credential form saves; expression dialog (double-click node) lists the clickhouse fields. Note results in the commit message.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Panels/PropertiesPanel.vue frontend/src/components/Credentials/CredentialDialog.vue
git commit -m "feat: clickhouse node properties editor and credential form"
```

---

### Task 12: heymrun docs for the node

**Files:**
- Create: `frontend/src/docs/content/nodes/clickhouse-node.md`
- Modify: `frontend/src/docs/content/reference/node-types.md`, `integrations.md`, `credentials.md`, `credentials-sharing.md`
- Modify: `frontend/src/docs/manifest.ts` (register the new doc page if pages are listed there)

- [ ] **Step 1: Write the node doc**

Create `frontend/src/docs/content/nodes/clickhouse-node.md`, modeled on `supabase-node.md`. Cover: purpose, credential setup (host/port/username/password/database/secure), each operation with required fields and output shape (copy the operation table from the DSL section), input modes (raw/selective), and the mutation/`ReplacingMergeTree`/`id`-column caveats.

- [ ] **Step 2: Add reference rows**

Add a ClickHouse row to each reference doc, matching the existing Supabase rows:
- `node-types.md` — node list row.
- `integrations.md` — integration row.
- `credentials.md` — `| ClickHouse | ClickHouse | host + port + username/password + database (+ secure) |`.
- `credentials-sharing.md` — `| [ClickHouse](../nodes/clickhouse-node.md) | credentialId | ClickHouse connection details |` and add ClickHouse to the node-types list line.

- [ ] **Step 3: Register in manifest if needed**

Check `frontend/src/docs/manifest.ts` for how `supabase-node.md` is registered; add an analogous `clickhouse-node` entry.

- [ ] **Step 4: Lint/typecheck**

Run: `cd frontend && bun run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/docs/
git commit -m "docs: add clickhouse node documentation"
```

---

### Task 13: Run heymrun verification gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full check**

Run: `cd /Users/mbakgun/Projects/heym/heymrun && SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
Expected: ruff format clean, backend lint + tests PASS, frontend lint + typecheck PASS.

- [ ] **Step 2: Commit any formatting-only diffs**

```bash
git add -A
git commit -m "style: ruff/lint formatting for clickhouse node" || echo "nothing to format"
```

---

## Phase 6 — heymweb Sync + Intro + Template

> All heymweb work happens in `/Users/mbakgun/Projects/heym/heymweb`. Per project rules: heymweb has no lint/test runner — verify with `bunx tsc --noEmit` + `bun run build`. No automatic git push.

### Task 14: Sync docs and DSL prompt to heymweb

**Files:** generated/synced under `heymweb/src/content/docs` and `heymweb/src/lib/heymDslPrompt.ts`

- [ ] **Step 1: Sync docs**

Run: `cd /Users/mbakgun/Projects/heym/heymweb && bun run sync-docs`
Expected: `clickhouse-node.md` + updated reference docs appear under `src/content/docs`.

- [ ] **Step 2: Sync DSL prompt**

Run: `cd /Users/mbakgun/Projects/heym/heymweb && bun run sync-dsl-prompt`
Expected: `src/lib/heymDslPrompt.ts` now contains the clickhouse section.

- [ ] **Step 3: Verify**

Run: `cd /Users/mbakgun/Projects/heym/heymweb && grep -c clickhouse src/lib/heymDslPrompt.ts src/content/docs/nodes/clickhouse-node.md`
Expected: non-zero counts.

- [ ] **Step 4: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/content/docs src/lib/heymDslPrompt.ts
git commit -m "docs: sync clickhouse node docs and DSL prompt from heymrun"
```

---

### Task 15: Introduce the node on heymweb marketing surfaces

**Files:**
- Modify: `heymweb/src/components/sections/NodesSection.tsx:122` (nodes array), `heymweb/src/lib/node-doc-links.ts:38`
- Modify (if needed): `heymweb/src/components/templates/nodePreviewTokens.ts`, `heymweb/src/components/templates/TemplateCanvasNode.tsx`

- [ ] **Step 1: Add the MarketingNode entry**

In `NodesSection.tsx`, in the `nodes` array, add an entry modeled on the `supabase` one (id `'clickhouse'`, name `'ClickHouse'`, a description covering SQL/CRUD/count over OLAP tables, the same `categories` the supabase node uses — e.g. data/integrations). The displayed node count and "Show All N Nodes" derive from `nodes.length` automatically.

- [ ] **Step 2: Add the doc link**

In `node-doc-links.ts`, after `supabase: 'nodes/supabase-node.md',`:

```typescript
  clickhouse: 'nodes/clickhouse-node.md',
```

- [ ] **Step 3: Add a preview token if the template canvas needs it**

If Task 16's template uses a clickhouse node token, add a `clickhouse` entry to `nodePreviewTokens.ts` (color/icon/label) and ensure `TemplateCanvasNode.tsx` renders it — model on the supabase token.

- [ ] **Step 4: Verify**

Run: `cd /Users/mbakgun/Projects/heym/heymweb && bunx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/components/sections/NodesSection.tsx src/lib/node-doc-links.ts src/components/templates/nodePreviewTokens.ts src/components/templates/TemplateCanvasNode.tsx
git commit -m "feat: introduce clickhouse node on heymweb (listing + doc link + preview token)"
```

---

### Task 16: Add a ClickHouse template

**Files:**
- Modify: `heymweb/src/lib/templates.ts`

- [ ] **Step 1: Add the StaticTemplate**

Add a new `StaticTemplate` entry modeled on an existing data-pipeline template. Suggested template: **"Event Analytics to ClickHouse"** — a webhook/trigger → a transform/set step → a `clickhouse` `insert` node, with a second branch: a `cron` trigger → `clickhouse` `count`/`query` → a notification/Slack node for a daily report. Use the existing `TemplateNode`/`TemplateEdge` shapes, a valid `category` (e.g. the one used by other data templates), node ids/positions consistent with sibling templates, and the `clickhouse` preview token from Task 15.

- [ ] **Step 2: Verify build**

Run: `cd /Users/mbakgun/Projects/heym/heymweb && bunx tsc --noEmit && bun run build`
Expected: PASS; the new template route is generated.

- [ ] **Step 3: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/lib/templates.ts
git commit -m "feat: add ClickHouse event-analytics template"
```

---

## Final Verification

- [ ] **heymrun:** `cd /Users/mbakgun/Projects/heym/heymrun && SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh` → all PASS.
- [ ] **heymweb:** `cd /Users/mbakgun/Projects/heym/heymweb && bunx tsc --noEmit && bun run build` → PASS.
- [ ] **Manual smoke:** create a ClickHouse credential, add a node, run each operation against a test ClickHouse instance (or confirm validation errors for missing fields).
- [ ] **Do NOT push.** Summarize the commits on both repos and ask the user before pushing.

---

## Notes for the Implementer

- Match existing code style exactly (ruff format, TS strict, Composition API `<script setup>`).
- Keep files focused; if `PropertiesPanel.vue` exceeds its size budget, follow the existing pattern rather than restructuring unrelated code.
- `clickhouse-connect` calls are synchronous and run inside the executor threadpool — never `await` them directly.
- Confirm exact line numbers before editing (they drift); the references above were captured on 2026-06-27.
