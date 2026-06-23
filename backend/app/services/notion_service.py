"""Notion API client used by workflow nodes and credential discovery."""

import json
import random
import re
import time
from threading import Lock
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx


class NotionService:
    """Synchronous Notion API client for workflow execution."""

    API_BASE_URL = "https://api.notion.com/v1"
    API_VERSION = "2026-03-11"
    _REQUEST_TIMEOUT_SECONDS = 30.0
    _MAX_PAGE_SIZE = 100
    _MAX_PAGINATED_RESULTS = 10_000
    _MAX_CHILDREN_PER_REQUEST = 100
    _MAX_RATE_LIMIT_RETRIES = 3
    _MAX_RETRY_DELAY_SECONDS = 10.0
    _RETRY_JITTER_RATIO = 0.25
    _shared_client: httpx.Client | None = None
    _shared_client_lock = Lock()
    _NOTION_ID_PATTERN = re.compile(
        r"(?<![0-9a-fA-F])([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
        r"(?![0-9a-fA-F])"
    )

    @staticmethod
    def resolve_bearer_token(config: dict[str, Any]) -> str:
        """Return the Notion bearer token for API and credentials-context use."""
        auth_mode = str(config.get("auth_mode", "")).strip()
        token_value = (
            config.get("access_token")
            if auth_mode == "oauth"
            else config.get("api_token") or config.get("access_token")
        )
        return str(token_value or "").strip()

    def __init__(
        self,
        config: dict[str, Any],
        *,
        client: httpx.Client | None = None,
    ) -> None:
        """Initialize the client with a decrypted Notion credential."""
        self._token = self.resolve_bearer_token(config)
        if not self._token:
            raise ValueError("Notion credential requires api_token or OAuth access_token")
        self._client = client

    def close(self) -> None:
        """Release per-service resources.

        The default HTTP client is process-wide and is closed during application shutdown.
        Injected clients are owned by their caller.
        """

    def __enter__(self) -> "NotionService":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        with self._shared_client_lock:
            if self.__class__._shared_client is None:
                self.__class__._shared_client = httpx.Client(timeout=self._REQUEST_TIMEOUT_SECONDS)
            return self.__class__._shared_client

    @classmethod
    def close_shared_client(cls) -> None:
        """Close the process-wide Notion HTTP connection pool."""
        with cls._shared_client_lock:
            if cls._shared_client is not None:
                cls._shared_client.close()
                cls._shared_client = None

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": self.API_VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def parse_json_object(value: str, field_name: str) -> dict[str, Any]:
        """Parse a JSON object field with a readable validation error."""
        try:
            parsed = json.loads(value or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{field_name} must be a JSON object")
        return parsed

    @staticmethod
    def parse_json_array(value: str, field_name: str) -> list[Any]:
        """Parse a JSON array field with a readable validation error."""
        try:
            parsed = json.loads(value or "[]")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be valid JSON") from exc
        if not isinstance(parsed, list):
            raise ValueError(f"{field_name} must be a JSON array")
        return parsed

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        message = response.text
        try:
            payload = response.json()
        except ValueError:
            return message
        if isinstance(payload, dict):
            return str(payload.get("message") or payload.get("code") or message)
        return message

    def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response: httpx.Response | None = None
        for retry_number in range(self._MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = self._get_client().request(
                    method,
                    f"{self.API_BASE_URL}{path}",
                    headers=self._headers,
                    json=payload,
                )
            except httpx.HTTPError as exc:
                raise ValueError(f"Notion {operation} failed: {exc}") from exc
            if (
                response.status_code not in {429, 529}
                or retry_number >= self._MAX_RATE_LIMIT_RETRIES
            ):
                break
            retry_after = response.headers.get("Retry-After", "")
            try:
                base_delay_seconds = max(float(retry_after), 0.0)
            except (TypeError, ValueError):
                base_delay_seconds = float(2**retry_number)
            capped_delay_seconds = min(
                base_delay_seconds,
                self._MAX_RETRY_DELAY_SECONDS,
            )
            jitter_seconds = random.uniform(
                0.0,
                capped_delay_seconds * self._RETRY_JITTER_RATIO,
            )
            delay_seconds = min(
                capped_delay_seconds + jitter_seconds,
                self._MAX_RETRY_DELAY_SECONDS,
            )
            time.sleep(delay_seconds)

        assert response is not None
        if not response.is_success:
            raise ValueError(
                f"Notion {operation} failed ({response.status_code}): "
                f"{self._error_message(response)}"
            )
        try:
            result = response.json()
        except ValueError as exc:
            raise ValueError(f"Notion {operation} returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ValueError(f"Notion {operation} returned an invalid response")
        return result

    def test_connection(self) -> dict[str, Any]:
        """Verify the integration token by retrieving the current bot user."""
        return self._request("GET", "/users/me", operation="connection test")

    def search(
        self,
        *,
        query: str = "",
        filter_object: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
        page_size: int = 100,
        start_cursor: str | None = None,
        fetch_all: bool = False,
    ) -> dict[str, Any]:
        """Search pages and data sources available to the integration."""
        payload: dict[str, Any] = {"page_size": self._normalize_page_size(page_size)}
        if query.strip():
            payload["query"] = query.strip()
        if filter_object:
            payload["filter"] = self._normalize_search_filter(filter_object)
        if sort:
            payload["sort"] = sort
        if start_cursor:
            payload["start_cursor"] = start_cursor
        return self._paginated_post("/search", "search", payload, fetch_all=fetch_all)

    def list_data_sources(
        self,
        query: str = "",
        *,
        start_cursor: str | None = None,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """List data sources visible to the integration for editor discovery."""
        result = self.search(
            query=query,
            filter_object={"property": "object", "value": "data_source"},
            page_size=page_size,
            start_cursor=start_cursor,
            fetch_all=False,
        )
        data_sources = []
        for item in result["results"]:
            if item.get("object") != "data_source":
                continue
            data_sources.append(
                {
                    "id": str(item.get("id", "")),
                    "title": self._extract_title(item.get("title")),
                    "url": item.get("url"),
                }
            )
        return {
            "data_sources": data_sources,
            "next_cursor": result.get("next_cursor"),
            "has_more": bool(result.get("has_more")),
            "success": True,
        }

    def list_pages(
        self,
        query: str = "",
        *,
        start_cursor: str | None = None,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """List ordinary pages visible to the integration for parent-page discovery."""
        result = self.search(
            query=query,
            filter_object={"property": "object", "value": "page"},
            page_size=page_size,
            start_cursor=start_cursor,
            fetch_all=False,
        )
        pages = []
        for item in result["results"]:
            if item.get("object") != "page":
                continue
            pages.append(
                {
                    "id": str(item.get("id", "")),
                    "title": self._extract_page_title(item.get("properties")),
                    "url": item.get("url"),
                }
            )
        return {
            "pages": pages,
            "next_cursor": result.get("next_cursor"),
            "has_more": bool(result.get("has_more")),
            "success": True,
        }

    @staticmethod
    def _extract_title(title: Any) -> str:
        if not isinstance(title, list):
            return ""
        return "".join(
            str(part.get("plain_text", "")) for part in title if isinstance(part, dict)
        ).strip()

    @staticmethod
    def _extract_page_title(properties: Any) -> str:
        if not isinstance(properties, dict):
            return ""
        for property_value in properties.values():
            if not isinstance(property_value, dict) or property_value.get("type") != "title":
                continue
            return NotionService._extract_title(property_value.get("title"))
        return ""

    def retrieve_page(self, page_id: str) -> dict[str, Any]:
        """Retrieve a Notion page."""
        normalized_id = self._required_id(page_id, "page")
        page = self._request("GET", f"/pages/{normalized_id}", operation="retrieve page")
        return {"page": page, "success": True}

    def create_database(self, database: dict[str, Any]) -> dict[str, Any]:
        """Create a Notion database container."""
        if not isinstance(database.get("parent"), dict):
            raise ValueError("Notion createDatabase requires a parent object")
        created_database = self._request(
            "POST",
            "/databases",
            operation="create database",
            payload=database,
        )
        return {
            "database": created_database,
            "id": created_database.get("id"),
            "url": created_database.get("url"),
            "success": True,
        }

    def retrieve_database(self, database_id: str) -> dict[str, Any]:
        """Retrieve a Notion database container and its data sources."""
        normalized_id = self._required_id(database_id, "database")
        database = self._request(
            "GET",
            f"/databases/{normalized_id}",
            operation="retrieve database",
        )
        return {"database": database, "success": True}

    def update_database(
        self,
        database_id: str,
        database: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a Notion database container."""
        normalized_id = self._required_id(database_id, "database")
        if not database:
            raise ValueError("Notion updateDatabase requires at least one field")
        updated_database = self._request(
            "PATCH",
            f"/databases/{normalized_id}",
            operation="update database",
            payload=database,
        )
        return {
            "database": updated_database,
            "id": updated_database.get("id"),
            "url": updated_database.get("url"),
            "success": True,
        }

    def retrieve_data_source(self, data_source_id: str) -> dict[str, Any]:
        """Retrieve a Notion data source, including its property schema."""
        normalized_id = self._required_id(data_source_id, "data source")
        data_source = self._request(
            "GET",
            f"/data_sources/{normalized_id}",
            operation="retrieve data source",
        )
        return {"data_source": data_source, "success": True}

    def create_data_source(self, data_source: dict[str, Any]) -> dict[str, Any]:
        """Create a data source using the current Notion Data Source API."""
        if not isinstance(data_source.get("parent"), dict):
            raise ValueError("Notion createDataSource requires a parent object")
        properties = data_source.get("properties")
        if not isinstance(properties, dict) or not properties:
            raise ValueError("Notion createDataSource requires a properties object")
        created_data_source = self._request(
            "POST",
            "/data_sources",
            operation="create data source",
            payload=data_source,
        )
        return {
            "data_source": created_data_source,
            "id": created_data_source.get("id"),
            "url": created_data_source.get("url"),
            "success": True,
        }

    def update_data_source(
        self,
        data_source_id: str,
        data_source: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a data source schema or metadata."""
        normalized_id = self._required_id(data_source_id, "data source")
        if not data_source:
            raise ValueError("Notion updateDataSource requires at least one field")
        updated_data_source = self._request(
            "PATCH",
            f"/data_sources/{normalized_id}",
            operation="update data source",
            payload=data_source,
        )
        return {
            "data_source": updated_data_source,
            "id": updated_data_source.get("id"),
            "url": updated_data_source.get("url"),
            "success": True,
        }

    def create_page(
        self,
        *,
        properties: dict[str, Any],
        data_source_id: str = "",
        parent_page_id: str = "",
        children: list[Any] | None = None,
        icon: dict[str, Any] | None = None,
        cover: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a page under a data source or another page."""
        if data_source_id.strip():
            parent = {
                "type": "data_source_id",
                "data_source_id": self._required_id(data_source_id, "data source"),
            }
        elif parent_page_id.strip():
            parent = {
                "type": "page_id",
                "page_id": self._required_id(parent_page_id, "page"),
            }
        else:
            raise ValueError("Notion createPage requires data_source_id or parent_page_id")

        payload: dict[str, Any] = {"parent": parent, "properties": properties}
        initial_children = list(children or [])[: self._MAX_CHILDREN_PER_REQUEST]
        if initial_children:
            payload["children"] = initial_children
        if icon:
            payload["icon"] = icon
        if cover:
            payload["cover"] = cover
        page = self._request("POST", "/pages", operation="create page", payload=payload)
        remaining_children = list(children or [])[self._MAX_CHILDREN_PER_REQUEST :]
        if remaining_children:
            page_id = str(page.get("id", "") or "")
            if not page_id:
                raise ValueError("Notion create page response is missing page ID")
            self.append_block_children(page_id, remaining_children, position="end")
        return {"page": page, "id": page.get("id"), "url": page.get("url"), "success": True}

    def update_page(
        self,
        page_id: str,
        *,
        properties: dict[str, Any] | None = None,
        icon: dict[str, Any] | None = None,
        cover: dict[str, Any] | None = None,
        in_trash: bool | None = None,
    ) -> dict[str, Any]:
        """Update page properties or trash state."""
        normalized_id = self._required_id(page_id, "page")
        payload: dict[str, Any] = {}
        if properties:
            payload["properties"] = properties
        if icon is not None:
            payload["icon"] = icon
        if cover is not None:
            payload["cover"] = cover
        if in_trash is not None:
            payload["in_trash"] = in_trash
        if not payload:
            raise ValueError("Notion updatePage requires at least one field")
        page = self._request(
            "PATCH",
            f"/pages/{normalized_id}",
            operation="update page",
            payload=payload,
        )
        return {"page": page, "id": page.get("id"), "url": page.get("url"), "success": True}

    def query_data_source(
        self,
        data_source_id: str,
        *,
        filter_object: dict[str, Any] | None = None,
        sorts: list[Any] | None = None,
        page_size: int = 100,
        start_cursor: str | None = None,
        fetch_all: bool = False,
    ) -> dict[str, Any]:
        """Query pages from a Notion data source."""
        normalized_id = self._required_id(data_source_id, "data source")
        payload: dict[str, Any] = {"page_size": self._normalize_page_size(page_size)}
        if filter_object:
            payload["filter"] = filter_object
        if sorts:
            payload["sorts"] = sorts
        if start_cursor:
            payload["start_cursor"] = start_cursor
        return self._paginated_post(
            f"/data_sources/{normalized_id}/query",
            "query data source",
            payload,
            fetch_all=fetch_all,
        )

    def retrieve_block_children(
        self,
        block_id: str,
        *,
        page_size: int = 100,
        start_cursor: str | None = None,
        fetch_all: bool = False,
    ) -> dict[str, Any]:
        """Retrieve child blocks, optionally following all cursors."""
        normalized_id = self._required_id(block_id, "block")
        results: list[Any] = []
        cursor = start_cursor
        while True:
            params = {"page_size": str(self._normalize_page_size(page_size))}
            if cursor:
                params["start_cursor"] = cursor
            path = f"/blocks/{normalized_id}/children?{urlencode(params)}"
            response = self._request("GET", path, operation="retrieve block children")
            response_results = response.get("results", [])
            if not isinstance(response_results, list):
                raise ValueError("Notion retrieve block children returned invalid results")
            results.extend(response_results)
            cursor = response.get("next_cursor")
            if not fetch_all or not response.get("has_more") or not cursor:
                return {
                    **response,
                    "results": results,
                    "count": len(results),
                    "success": True,
                }
            if len(results) >= self._MAX_PAGINATED_RESULTS:
                raise ValueError("Notion pagination exceeded 10000 results")

    def update_block(
        self,
        block_id: str,
        block: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a block using its type-specific Notion payload."""
        normalized_id = self._required_id(block_id, "block")
        if not block:
            raise ValueError("Notion updateBlock requires a block payload")
        updated_block = self._request(
            "PATCH",
            f"/blocks/{normalized_id}",
            operation="update block",
            payload=block,
        )
        return {"block": updated_block, "id": updated_block.get("id"), "success": True}

    def delete_block(self, block_id: str) -> dict[str, Any]:
        """Archive a block through Notion's delete block endpoint."""
        normalized_id = self._required_id(block_id, "block")
        block = self._request("DELETE", f"/blocks/{normalized_id}", operation="delete block")
        return {"block": block, "id": block.get("id"), "success": True}

    def append_block_children(
        self,
        block_id: str,
        children: list[Any],
        *,
        position: str = "end",
        after: str | None = None,
    ) -> dict[str, Any]:
        """Append child blocks to a page or block."""
        normalized_id = self._required_id(block_id, "block")
        if not children:
            raise ValueError("Notion appendBlocks requires at least one child block")
        normalized_position = position.strip() or "end"
        if after and normalized_position == "end":
            normalized_position = "after_block"
        if normalized_position not in {"start", "end", "after_block"}:
            raise ValueError("Notion appendBlocks position must be start, end, or after_block")
        if normalized_position == "after_block" and not after:
            raise ValueError("Notion appendBlocks after_block position requires an after block ID")

        all_results: list[Any] = []
        last_response: dict[str, Any] = {}
        next_position = normalized_position
        next_after = after
        for offset in range(0, len(children), self._MAX_CHILDREN_PER_REQUEST):
            chunk = children[offset : offset + self._MAX_CHILDREN_PER_REQUEST]
            payload: dict[str, Any] = {
                "children": chunk,
                "position": self._build_append_position(next_position, next_after),
            }
            last_response = self._request(
                "PATCH",
                f"/blocks/{normalized_id}/children",
                operation="append blocks",
                payload=payload,
            )
            chunk_results = last_response.get("results", [])
            if not isinstance(chunk_results, list):
                raise ValueError("Notion append blocks returned invalid results")
            all_results.extend(chunk_results)
            if offset + self._MAX_CHILDREN_PER_REQUEST >= len(children):
                continue
            if normalized_position == "end":
                next_position = "end"
                next_after = None
                continue
            last_id = (
                str(chunk_results[-1].get("id", "") or "")
                if chunk_results and isinstance(chunk_results[-1], dict)
                else ""
            )
            if not last_id:
                raise ValueError("Notion append blocks response is missing the last block ID")
            next_position = "after_block"
            next_after = last_id

        return {
            **last_response,
            "results": all_results,
            "count": len(all_results),
            "success": True,
        }

    def _build_append_position(
        self,
        position: str,
        after: str | None,
    ) -> dict[str, Any]:
        if position == "after_block":
            return {
                "type": "after_block",
                "after_block": {"id": self._required_id(after or "", "after block")},
            }
        return {"type": position}

    @classmethod
    def _normalize_search_filter(cls, value: Any) -> Any:
        """Translate pre-2025 search object filters to current data source terminology."""
        if isinstance(value, dict):
            normalized = {key: cls._normalize_search_filter(item) for key, item in value.items()}
            if normalized.get("property") == "object" and normalized.get("value") == "database":
                normalized["value"] = "data_source"
            return normalized
        if isinstance(value, list):
            return [cls._normalize_search_filter(item) for item in value]
        return value

    def _paginated_post(
        self,
        path: str,
        operation: str,
        payload: dict[str, Any],
        *,
        fetch_all: bool,
    ) -> dict[str, Any]:
        results: list[Any] = []
        request_payload = dict(payload)
        while True:
            response = self._request(
                "POST",
                path,
                operation=operation,
                payload=request_payload,
            )
            response_results = response.get("results", [])
            if not isinstance(response_results, list):
                raise ValueError(f"Notion {operation} returned invalid results")
            results.extend(response_results)
            next_cursor = response.get("next_cursor")
            if not fetch_all or not response.get("has_more") or not next_cursor:
                return {
                    **response,
                    "results": results,
                    "count": len(results),
                    "success": True,
                }
            if len(results) >= self._MAX_PAGINATED_RESULTS:
                raise ValueError("Notion pagination exceeded 10000 results")
            request_payload["start_cursor"] = next_cursor

    @classmethod
    def _normalize_page_size(cls, page_size: int) -> int:
        return min(max(page_size, 1), cls._MAX_PAGE_SIZE)

    @staticmethod
    def _required_id(value: str, resource_name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"Notion {resource_name} ID is required")
        if normalized.startswith(("http://", "https://")):
            path = urlparse(normalized).path
            matches = list(NotionService._NOTION_ID_PATTERN.finditer(path))
            if not matches:
                raise ValueError(f"Notion {resource_name} URL does not contain a valid ID")
            raw_id = matches[-1].group(1).replace("-", "")
            return f"{raw_id[:8]}-{raw_id[8:12]}-{raw_id[12:16]}-{raw_id[16:20]}-{raw_id[20:]}"
        return normalized
