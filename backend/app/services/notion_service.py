"""Notion API client used by workflow nodes and credential discovery."""

import json
from typing import Any
from urllib.parse import urlencode

import httpx


class NotionService:
    """Synchronous Notion API client for workflow execution."""

    API_BASE_URL = "https://api.notion.com/v1"
    API_VERSION = "2026-03-11"
    _REQUEST_TIMEOUT_SECONDS = 30.0
    _MAX_PAGE_SIZE = 100
    _MAX_PAGINATED_RESULTS = 10_000

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the client with a decrypted Notion credential."""
        self._token = str(config.get("api_token", "")).strip()
        if not self._token:
            raise ValueError("Notion credential requires api_token")

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
        try:
            response = httpx.request(
                method,
                f"{self.API_BASE_URL}{path}",
                headers=self._headers,
                json=payload,
                timeout=self._REQUEST_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise ValueError(f"Notion {operation} failed: {exc}") from exc

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
            payload["filter"] = filter_object
        if sort:
            payload["sort"] = sort
        if start_cursor:
            payload["start_cursor"] = start_cursor
        return self._paginated_post("/search", "search", payload, fetch_all=fetch_all)

    def list_data_sources(self, query: str = "") -> dict[str, Any]:
        """List data sources visible to the integration for editor discovery."""
        result = self.search(
            query=query,
            filter_object={"property": "object", "value": "data_source"},
            fetch_all=True,
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
        return {"data_sources": data_sources, "success": True}

    @staticmethod
    def _extract_title(title: Any) -> str:
        if not isinstance(title, list):
            return ""
        return "".join(
            str(part.get("plain_text", "")) for part in title if isinstance(part, dict)
        ).strip()

    def retrieve_page(self, page_id: str) -> dict[str, Any]:
        """Retrieve a Notion page."""
        normalized_id = self._required_id(page_id, "page")
        page = self._request("GET", f"/pages/{normalized_id}", operation="retrieve page")
        return {"page": page, "success": True}

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
                "data_source_id": data_source_id.strip(),
            }
        elif parent_page_id.strip():
            parent = {"type": "page_id", "page_id": parent_page_id.strip()}
        else:
            raise ValueError("Notion createPage requires data_source_id or parent_page_id")

        payload: dict[str, Any] = {"parent": parent, "properties": properties}
        if children:
            payload["children"] = children
        if icon:
            payload["icon"] = icon
        if cover:
            payload["cover"] = cover
        page = self._request("POST", "/pages", operation="create page", payload=payload)
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

    def append_block_children(
        self,
        block_id: str,
        children: list[Any],
        *,
        after: str | None = None,
    ) -> dict[str, Any]:
        """Append child blocks to a page or block."""
        normalized_id = self._required_id(block_id, "block")
        if not children:
            raise ValueError("Notion appendBlocks requires at least one child block")
        payload: dict[str, Any] = {"children": children}
        if after:
            payload["after"] = after
        result = self._request(
            "PATCH",
            f"/blocks/{normalized_id}/children",
            operation="append blocks",
            payload=payload,
        )
        results = result.get("results", [])
        return {
            **result,
            "count": len(results) if isinstance(results, list) else 0,
            "success": True,
        }

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
        return normalized
