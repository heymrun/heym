"""Supabase PostgREST client for table CRUD operations."""

import json
import re
from typing import Any

import httpx

from app.services.ssrf_guard import get_guarded_http_client, guard_http_url


class SupabaseService:
    """Sync Supabase PostgREST client.

    Uses sync httpx to match the existing workflow executor integration pattern.
    """

    _TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    _FILTER_QUOTE_PATTERN = re.compile(r'[\s,.:()"\\\\-]')
    _SELECT_PAGE_SIZE = 1000
    _SELECT_UNBOUNDED_MAX_ROWS = 10_000
    _SUPPORTED_FILTER_OPERATORS = {
        "eq",
        "neq",
        "gt",
        "gte",
        "lt",
        "lte",
        "like",
        "ilike",
        "is",
        "in",
        "cs",
        "cd",
        "ov",
        "sl",
        "sr",
        "nxr",
        "nxl",
        "adj",
        "fts",
        "plfts",
        "phfts",
        "wfts",
    }

    _CONNECTION_TEST_TIMEOUT_SECONDS = 15.0
    _REQUEST_TIMEOUT_SECONDS = 30.0

    def __init__(self, config: dict[str, Any], client: httpx.Client | None = None) -> None:
        """Initialise with decrypted credential config."""
        self._config = dict(config)
        self._base_url = str(self._config.get("supabase_url", "")).strip().rstrip("/")
        self._api_key = str(self._config.get("supabase_key", "")).strip()
        if not self._base_url:
            raise ValueError("Supabase credential requires supabase_url")
        if not self._api_key:
            raise ValueError("Supabase credential requires supabase_key")
        if client is None:
            guard_http_url(self._base_url, "Supabase credential URL")
            client = get_guarded_http_client()
        self._client = client
        schema = str(self._config.get("supabase_schema", "public")).strip()
        self._default_schema = schema or "public"

    def test_connection(self) -> None:
        """Verify the Supabase URL and API key against the PostgREST root."""
        try:
            response = self._client.get(
                f"{self._base_url}/rest/v1/",
                headers={
                    "apikey": self._api_key,
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                },
                timeout=self._CONNECTION_TEST_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise ValueError(f"Supabase connection test failed: {exc}") from exc
        if response.status_code == 401:
            raise ValueError("Supabase API key is invalid or unauthorized")
        if not response.is_success:
            message = response.text
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    message = str(
                        payload.get("message")
                        or payload.get("error_description")
                        or payload.get("hint")
                        or message
                    )
            except ValueError:
                pass
            raise ValueError(f"Supabase connection test failed ({response.status_code}): {message}")

    def _openapi_root(self, schema: str) -> dict[str, Any]:
        """Fetch the PostgREST OpenAPI root for discovery operations."""
        try:
            response = self._client.get(
                f"{self._base_url}/rest/v1/",
                headers=self._headers(schema),
                timeout=self._CONNECTION_TEST_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise ValueError(f"Supabase discovery failed: {exc}") from exc
        self._raise_for_error(response, "discovery")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Supabase discovery returned an invalid response")
        return payload

    def list_tables(self, *, schema: str = "public") -> dict[str, Any]:
        """List tables exposed by the selected Supabase schema."""
        payload = self._openapi_root(schema)
        paths = payload.get("paths", {})
        if not isinstance(paths, dict):
            raise ValueError("Supabase discovery returned invalid path metadata")

        tables = sorted(
            path.replace("/", "")
            for path in paths
            if isinstance(path, str)
            and path not in {"/"}
            and not path.startswith("/rpc/")
            and self._TABLE_NAME_PATTERN.fullmatch(path.replace("/", ""))
        )
        return {"tables": tables, "success": True}

    def list_columns(self, table: str, *, schema: str = "public") -> dict[str, Any]:
        """List column names for a discovered Supabase table."""
        normalized_table = table.strip()
        if not normalized_table:
            raise ValueError("Supabase table is required")
        if not self._TABLE_NAME_PATTERN.fullmatch(normalized_table):
            raise ValueError(
                "Supabase table must be a simple table name; use supabaseSchema for schemas"
            )

        payload = self._openapi_root(schema)
        definitions = payload.get("definitions", {})
        if not isinstance(definitions, dict):
            raise ValueError("Supabase discovery returned invalid definition metadata")

        table_definition = definitions.get(normalized_table)
        if not isinstance(table_definition, dict):
            return {"columns": [], "success": True}

        properties = table_definition.get("properties", {})
        if not isinstance(properties, dict):
            return {"columns": [], "success": True}

        columns = [key for key in properties if isinstance(key, str)]
        return {"columns": columns, "success": True}

    def _headers(self, schema: str, *, write: bool = False, count: bool = False) -> dict[str, str]:
        """Build authenticated PostgREST headers for the selected schema."""
        normalized_schema = schema.strip() or self._default_schema
        headers = {
            "apikey": self._api_key,
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        if write:
            headers["Content-Profile"] = normalized_schema
        else:
            headers["Accept-Profile"] = normalized_schema
        if count:
            headers["Prefer"] = "count=exact"
        return headers

    def _table_url(self, table: str) -> str:
        """Return the PostgREST URL for a table."""
        normalized_table = table.strip()
        if not normalized_table:
            raise ValueError("Supabase table is required")
        if not self._TABLE_NAME_PATTERN.fullmatch(normalized_table):
            raise ValueError(
                "Supabase table must be a simple table name; use supabaseSchema for schemas"
            )
        return f"{self._base_url}/rest/v1/{normalized_table}"

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        operation: str | None = None,
        params: list[tuple[str, str]] | None = None,
        json_body: Any | None = None,
    ) -> httpx.Response:
        """Execute a Supabase request with a consistent timeout and transport errors."""
        request_kwargs: dict[str, Any] = {
            "headers": headers,
            "timeout": self._REQUEST_TIMEOUT_SECONDS,
        }
        if params is not None:
            request_kwargs["params"] = params
        if json_body is not None:
            request_kwargs["json"] = json_body

        try:
            return self._client.request(method, url, **request_kwargs)
        except httpx.HTTPError as exc:
            operation_name = operation or method.lower()
            raise ValueError(f"Supabase {operation_name} failed: {exc}") from exc

    @staticmethod
    def _normalize_count(response: httpx.Response, rows: list[dict[str, Any]]) -> int:
        """Extract an exact row count from the content-range header when present."""
        content_range = response.headers.get("content-range", "")
        if "/" in content_range:
            total = content_range.rsplit("/", 1)[-1].strip()
            if total.isdigit():
                return int(total)
        return len(rows)

    @staticmethod
    def _raise_for_error(response: httpx.Response, operation: str) -> None:
        """Raise a readable ValueError for Supabase API failures."""
        if response.is_success:
            return
        message = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = str(
                    payload.get("message")
                    or payload.get("error_description")
                    or payload.get("hint")
                    or payload.get("details")
                    or message
                )
        except ValueError:
            pass
        raise ValueError(f"Supabase {operation} failed ({response.status_code}): {message}")

    @classmethod
    def _encode_scalar_filter_value(cls, value: Any) -> str:
        """Encode a scalar value for PostgREST filter syntax."""
        if value is None:
            return "null"
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, str):
            if not value:
                return '""'
            if cls._FILTER_QUOTE_PATTERN.search(value):
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                return f'"{escaped}"'
            return value
        return str(value)

    @classmethod
    def _format_operator_filter(cls, operator: str, value: Any, *, top_level: bool = False) -> str:
        """Format a PostgREST operator/value pair."""
        normalized_operator = operator.strip().lower()
        if normalized_operator not in cls._SUPPORTED_FILTER_OPERATORS:
            raise ValueError(f"Unsupported Supabase filter operator: {operator}")

        # Full-text values keep main's encoding: `wfts."report weekly"` reads as a phrase in
        # websearch_to_tsquery, and dropping the quotes would match the words in any order.
        quoted_operators = {"in", "cs", "cd", "ov", "fts", "plfts", "phfts", "wfts"}
        if top_level and isinstance(value, str) and normalized_operator not in quoted_operators:
            # PostgREST reads a top-level value verbatim and removes double quotes only
            # inside `in.(...)` lists and `or`/`and` groups: `eq."a.b@c.com"` matches nothing.
            return f"{normalized_operator}.{value}"

        if normalized_operator == "eq":
            if value is None:
                return "is.null"
            if isinstance(value, str):
                return cls._format_string_filter(value)
            return f"eq.{cls._encode_scalar_filter_value(value)}"

        if normalized_operator == "is":
            if value is None:
                return "is.null"
            encoded = cls._encode_scalar_filter_value(value)
            return f"is.{encoded}"

        if normalized_operator == "in":
            if not isinstance(value, list | tuple):
                raise ValueError("Supabase 'in' filter requires an array value")
            encoded_items = ",".join(cls._encode_scalar_filter_value(item) for item in value)
            return f"in.({encoded_items})"

        if normalized_operator in {"cs", "cd", "ov"}:
            if not isinstance(value, list | tuple):
                raise ValueError(f"Supabase '{normalized_operator}' filter requires an array value")
            encoded_items = ",".join(cls._encode_scalar_filter_value(item) for item in value)
            return f"{normalized_operator}.{{{encoded_items}}}"

        encoded = cls._encode_scalar_filter_value(value)
        return f"{normalized_operator}.{encoded}"

    @classmethod
    def _compile_field_filter_fragments(
        cls, field: str, value: Any, *, top_level: bool = False
    ) -> list[str]:
        """Compile a single field filter into one or more PostgREST fragments."""
        normalized_field = str(field).strip()
        if not normalized_field:
            return []

        if isinstance(value, dict):
            if not value:
                raise ValueError(
                    f"Supabase filter for '{normalized_field}' cannot be an empty object"
                )
            fragments: list[str] = []
            for operator, operator_value in value.items():
                formatted = cls._format_operator_filter(
                    str(operator), operator_value, top_level=top_level
                )
                fragments.append(f"{normalized_field}.{formatted}")
            return fragments

        return [
            f"{normalized_field}.{cls._format_operator_filter('eq', value, top_level=top_level)}"
        ]

    @classmethod
    def _compile_condition_fragment(cls, condition: Any) -> str:
        """Compile a nested logical condition into a PostgREST fragment."""
        if not isinstance(condition, dict):
            raise ValueError("Supabase logical filters must contain JSON objects")

        fragments: list[str] = []
        for key, value in condition.items():
            normalized_key = str(key).strip()
            if not normalized_key:
                continue
            if normalized_key in {"or", "and"}:
                fragments.append(cls._compile_logical_group_fragment(normalized_key, value))
                continue
            fragments.extend(cls._compile_field_filter_fragments(normalized_key, value))

        if not fragments:
            raise ValueError("Supabase logical filters must contain at least one condition")
        if len(fragments) == 1:
            return fragments[0]
        return f"and({','.join(fragments)})"

    @classmethod
    def _compile_logical_group_fragment(cls, operator: str, value: Any) -> str:
        """Compile an `and`/`or` logical group for PostgREST."""
        if not isinstance(value, list) or not value:
            raise ValueError(f"Supabase '{operator}' filter requires a non-empty array")
        fragments = [cls._compile_condition_fragment(item) for item in value]
        return f"{operator}({','.join(fragments)})"

    @classmethod
    def _compile_filter_params(cls, filters: dict[str, Any] | None) -> list[tuple[str, str]]:
        """Compile structured JSON filters into PostgREST query parameters."""
        if not filters:
            return []

        params: list[tuple[str, str]] = []
        for key, value in filters.items():
            normalized_key = str(key).strip()
            if not normalized_key:
                continue
            if normalized_key in {"or", "and"}:
                logical_group = cls._compile_logical_group_fragment(normalized_key, value)
                prefix = f"{normalized_key}("
                if not logical_group.startswith(prefix) or not logical_group.endswith(")"):
                    raise ValueError(f"Failed to compile Supabase '{normalized_key}' filter")
                params.append((normalized_key, logical_group[len(normalized_key) :]))
                continue
            for fragment in cls._compile_field_filter_fragments(
                normalized_key, value, top_level=True
            ):
                field_name, encoded_value = fragment.split(".", 1)
                params.append((field_name, encoded_value))
        return params

    @classmethod
    def _format_string_filter(cls, value: str) -> str:
        """Encode string filter values for PostgREST URL grammar."""
        if not value:
            return 'eq.""'
        if cls._FILTER_QUOTE_PATTERN.search(value):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'eq."{escaped}"'
        return f"eq.{value}"

    @staticmethod
    def _without_ignored_fields(
        item: dict[str, Any], ignored_fields: set[str] | None = None
    ) -> dict[str, Any]:
        """Return a copy of an object without ignored field names."""
        if not ignored_fields:
            return dict(item)
        return {key: value for key, value in item.items() if key not in ignored_fields}

    @classmethod
    def normalize_auto_map_rows(
        cls,
        value: Any,
        *,
        ignored_fields: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Normalize auto-mapped workflow input into Supabase row objects."""
        rows: list[dict[str, Any]]
        if isinstance(value, dict):
            nested_rows = value.get("rows")
            if isinstance(nested_rows, list):
                if not all(isinstance(item, dict) for item in nested_rows):
                    raise ValueError("Supabase auto-mapped rows must contain only JSON objects")
                rows = [dict(item) for item in nested_rows]
            else:
                rows = [dict(value)]
        elif isinstance(value, list):
            if not all(isinstance(item, dict) for item in value):
                raise ValueError("Supabase auto-mapped rows must contain only JSON objects")
            rows = [dict(item) for item in value]
        else:
            raise ValueError(
                "Supabase auto-map expects an object, an array of objects, or an upstream rows array"
            )

        normalized_rows = [cls._without_ignored_fields(row, ignored_fields) for row in rows]
        if not normalized_rows:
            raise ValueError("Supabase auto-map produced no rows")
        return normalized_rows

    @classmethod
    def normalize_auto_map_object(
        cls,
        value: Any,
        *,
        ignored_fields: set[str] | None = None,
    ) -> dict[str, Any]:
        """Normalize auto-mapped workflow input into a single Supabase object."""
        if isinstance(value, dict):
            nested_rows = value.get("rows")
            if isinstance(nested_rows, list):
                if len(nested_rows) != 1 or not isinstance(nested_rows[0], dict):
                    raise ValueError(
                        "Supabase auto-map for update requires exactly one object or one upstream row"
                    )
                source_object = dict(nested_rows[0])
            else:
                source_object = dict(value)
        elif isinstance(value, list):
            if len(value) != 1 or not isinstance(value[0], dict):
                raise ValueError(
                    "Supabase auto-map for update requires exactly one object or one upstream row"
                )
            source_object = dict(value[0])
        else:
            raise ValueError(
                "Supabase auto-map for update expects an object, a single-object array, or an upstream rows array"
            )

        return cls._without_ignored_fields(source_object, ignored_fields)

    def select_rows(
        self,
        table: str,
        *,
        schema: str = "public",
        columns: str = "*",
        filters: dict[str, Any] | None = None,
        limit: int = 100,
        order_by: str = "",
        ascending: bool = True,
    ) -> dict[str, Any]:
        """Select rows from a Supabase table."""
        params: list[tuple[str, str]] = [("select", columns.strip() or "*")]
        if limit < 0:
            limit = 100
        if order_by.strip():
            direction = "asc" if ascending else "desc"
            params.append(("order", f"{order_by.strip()}.{direction}"))
        params.extend(self._compile_filter_params(filters))

        requested_limit = limit
        all_rows: list[dict[str, Any]] = []
        total_count: int | None = None
        offset = 0
        unbounded_max = self._SELECT_UNBOUNDED_MAX_ROWS

        while True:
            if requested_limit == 0 and len(all_rows) >= unbounded_max:
                raise ValueError(
                    f"Supabase select with no row limit exceeds the maximum of "
                    f"{unbounded_max} rows; set supabaseLimit to a positive value"
                )
            page_limit = (
                self._SELECT_PAGE_SIZE
                if requested_limit == 0
                else min(max(requested_limit - len(all_rows), 0), self._SELECT_PAGE_SIZE)
            )
            if requested_limit > 0 and page_limit <= 0:
                break

            page_params = list(params)
            page_params.append(("limit", str(page_limit)))
            if offset > 0:
                page_params.append(("offset", str(offset)))

            response = self._request(
                "GET",
                self._table_url(table),
                headers=self._headers(schema, count=True),
                operation="select",
                params=page_params,
            )
            self._raise_for_error(response, "select")
            rows = response.json()
            if not isinstance(rows, list):
                raise ValueError("Supabase select returned a non-list response")

            if total_count is None:
                total_count = self._normalize_count(response, rows)
                if requested_limit == 0 and total_count > unbounded_max:
                    raise ValueError(
                        f"Supabase select with no row limit would fetch {total_count} rows, "
                        f"which exceeds the maximum of {unbounded_max}; set supabaseLimit to a "
                        f"positive value"
                    )

            all_rows.extend(rows)
            fetched_count = len(rows)
            if fetched_count < page_limit:
                break

            offset += fetched_count

            if requested_limit > 0 and len(all_rows) >= requested_limit:
                break

        return {
            "rows": all_rows,
            "count": total_count if total_count is not None else len(all_rows),
            "success": True,
        }

    def insert_rows(
        self,
        table: str,
        rows: list[dict[str, Any]],
        *,
        schema: str = "public",
        upsert: bool = False,
        on_conflict: str = "",
    ) -> dict[str, Any]:
        """Insert or upsert rows into a Supabase table."""
        if not rows:
            raise ValueError("Supabase insert requires at least one row")
        headers = self._headers(schema, write=True)
        prefer_parts = ["return=representation"]
        params: list[tuple[str, str]] = []
        if upsert:
            prefer_parts.append("resolution=merge-duplicates")
            if on_conflict.strip():
                params.append(("on_conflict", on_conflict.strip()))
        headers["Prefer"] = ",".join(prefer_parts)

        response = self._request(
            "POST",
            self._table_url(table),
            headers=headers,
            operation="upsert" if upsert else "insert",
            params=params,
            json_body=rows,
        )
        self._raise_for_error(response, "upsert" if upsert else "insert")
        result_rows = response.json()
        if not isinstance(result_rows, list):
            raise ValueError("Supabase write returned a non-list response")
        return {
            "rows": result_rows,
            "count": len(result_rows),
            "success": True,
        }

    def update_rows(
        self,
        table: str,
        data: dict[str, Any],
        *,
        schema: str = "public",
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update rows matching exact-match filters."""
        if not data:
            raise ValueError("Supabase update requires at least one data field")
        if not filters:
            raise ValueError("Supabase update requires at least one filter")
        params = self._compile_filter_params(filters)
        headers = self._headers(schema, write=True)
        headers["Prefer"] = "return=representation"
        response = self._request(
            "PATCH",
            self._table_url(table),
            headers=headers,
            operation="update",
            params=params,
            json_body=data,
        )
        self._raise_for_error(response, "update")
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("Supabase update returned a non-list response")
        return {"rows": rows, "count": len(rows), "success": True}

    def delete_rows(
        self,
        table: str,
        *,
        schema: str = "public",
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Delete rows matching exact-match filters."""
        if not filters:
            raise ValueError("Supabase delete requires at least one filter")
        params = self._compile_filter_params(filters)
        headers = self._headers(schema, write=True)
        headers["Prefer"] = "return=representation"
        response = self._request(
            "DELETE",
            self._table_url(table),
            headers=headers,
            operation="delete",
            params=params,
        )
        self._raise_for_error(response, "delete")
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("Supabase delete returned a non-list response")
        return {"rows": rows, "count": len(rows), "success": True}

    @staticmethod
    def parse_json_object(raw: str, field_name: str) -> dict[str, Any]:
        """Parse a JSON object field."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON for {field_name}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{field_name} must be a JSON object")
        return data

    @staticmethod
    def parse_json_rows(raw: str, field_name: str) -> list[dict[str, Any]]:
        """Parse a JSON array of row objects."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON for {field_name}") from exc
        if not isinstance(data, list):
            raise ValueError(f"{field_name} must be a JSON array")
        if not all(isinstance(item, dict) for item in data):
            raise ValueError(f"{field_name} must contain only JSON objects")
        return data
