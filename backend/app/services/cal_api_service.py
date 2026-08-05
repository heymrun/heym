"""Synchronous Cal.com API v2 client used by workflow nodes."""

from __future__ import annotations

from typing import Any

import httpx

from app.services.ssrf_guard import get_guarded_http_client, guard_http_url

_DEFAULT_BASE_URL = "https://api.cal.com"
_WEBHOOK_PAGE_SIZE = 250
_MAX_WEBHOOK_PAGES = 100


class CalApiError(RuntimeError):
    """Raised when Cal.com rejects or cannot complete an API operation."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CalApiService:
    """Small synchronous client for Cal.com webhook CRUD operations."""

    def __init__(
        self,
        config: dict[str, Any],
        client: httpx.Client | None = None,
    ) -> None:
        api_key = str(config.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("Cal.com API credential requires api_key")
        base_url = str(config.get("base_url") or _DEFAULT_BASE_URL).strip().rstrip("/")
        api_v2_url = base_url if base_url.endswith("/v2") else f"{base_url}/v2"
        try:
            guard_http_url(api_v2_url)
        except ValueError as exc:
            raise ValueError(f"Cal.com API base URL is not allowed: {exc}") from exc
        self._base_url = api_v2_url
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._client = client or get_guarded_http_client()

    def list_webhooks(self) -> list[dict[str, Any]]:
        """Return all webhooks visible to the configured credential."""
        webhooks: list[dict[str, Any]] = []
        for page in range(_MAX_WEBHOOK_PAGES):
            payload = self._request(
                "GET",
                "/webhooks",
                params={"take": _WEBHOOK_PAGE_SIZE, "skip": page * _WEBHOOK_PAGE_SIZE},
            )
            page_items = _webhook_list_data(payload)
            webhooks.extend(page_items)
            if len(page_items) < _WEBHOOK_PAGE_SIZE:
                return webhooks
        raise CalApiError("Cal.com webhook pagination exceeded the safety limit")

    def create_webhook(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create one Cal.com webhook and return its representation."""
        return _webhook_data(self._request("POST", "/webhooks", json=body))

    def update_webhook(self, webhook_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Update one Cal.com webhook and return its representation."""
        return _webhook_data(self._request("PATCH", f"/webhooks/{webhook_id}", json=body))

    def delete_webhook(self, webhook_id: str) -> None:
        """Delete one Cal.com webhook."""
        self._request("DELETE", f"/webhooks/{webhook_id}")

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, int] | None = None,
    ) -> Any:
        try:
            response = self._client.request(
                method,
                f"{self._base_url}{path}",
                headers=self._headers,
                json=json,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise CalApiError("Unable to reach Cal.com API") from exc
        if response.is_success:
            if response.status_code == 204 or not response.content:
                return {}
            try:
                return response.json()
            except ValueError as exc:
                raise CalApiError("Cal.com API returned invalid JSON") from exc
        raise CalApiError(_error_detail(response), status_code=response.status_code)


def _response_data(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    return payload.get("data", payload)


def _webhook_list_data(payload: Any) -> list[dict[str, Any]]:
    data = _response_data(payload)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("webhooks") or data.get("items") or []
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _webhook_data(payload: Any) -> dict[str, Any]:
    data = _response_data(payload)
    if isinstance(data, dict) and isinstance(data.get("webhook"), dict):
        data = data["webhook"]
    if not isinstance(data, dict):
        raise CalApiError("Cal.com API response is missing webhook data")
    return data


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return f"Cal.com API request failed: {value.strip()}"
    return f"Cal.com API request failed with status {response.status_code}"
