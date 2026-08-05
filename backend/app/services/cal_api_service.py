"""Cal.com API v2 client used by managed trigger subscriptions."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CalWebhookSubscription, CredentialType
from app.services.credential_access import get_accessible_credential
from app.services.encryption import decrypt_config

_DEFAULT_BASE_URL = "https://api.cal.com"
_TIMEOUT_SECONDS = 30.0
_WEBHOOK_PAGE_SIZE = 250
_MAX_WEBHOOK_PAGES = 100


class CalApiError(RuntimeError):
    """Raised when Cal.com rejects or cannot complete an API operation."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class CalApiConfig:
    """Authenticated Cal.com API endpoint configuration."""

    api_key: str
    base_url: str = _DEFAULT_BASE_URL

    @property
    def api_v2_url(self) -> str:
        cleaned = self.base_url.rstrip("/")
        return cleaned if cleaned.endswith("/v2") else f"{cleaned}/v2"


class CalApiClient:
    """Small async client for Cal.com webhook CRUD operations."""

    def __init__(self, config: CalApiConfig) -> None:
        self._config = config
        self._client: httpx.AsyncClient | None = None
        self._context_depth = 0

    async def __aenter__(self) -> CalApiClient:
        self._context_depth += 1
        if self._client is not None:
            return self
        from app.services.ssrf_guard import guard_http_url, install_async_egress_pin

        try:
            guard_http_url(self._config.api_v2_url)
            client = httpx.AsyncClient(
                base_url=self._config.api_v2_url,
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Accept": "application/json",
                },
                timeout=_TIMEOUT_SECONDS,
                trust_env=False,
                follow_redirects=False,
            )
            try:
                install_async_egress_pin(client)
            except Exception:
                await client.aclose()
                raise
            self._client = client
        except ValueError as exc:
            self._context_depth -= 1
            raise CalApiError(f"Cal.com API base URL is not allowed: {exc}") from exc
        except RuntimeError as exc:
            self._context_depth -= 1
            raise CalApiError("Unable to initialize the Cal.com API connection") from exc
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self._context_depth -= 1
        if self._context_depth == 0 and self._client is not None:
            client = self._client
            self._client = None
            await client.aclose()

    async def list_webhooks(self) -> list[dict[str, Any]]:
        """Return all webhooks visible to the configured Cal.com credential."""
        webhooks: list[dict[str, Any]] = []
        async with self:
            for page in range(_MAX_WEBHOOK_PAGES):
                payload = await self._request(
                    "GET",
                    "/webhooks",
                    params={"take": _WEBHOOK_PAGE_SIZE, "skip": page * _WEBHOOK_PAGE_SIZE},
                )
                page_items = _webhook_list_data(payload)
                webhooks.extend(page_items)
                if len(page_items) < _WEBHOOK_PAGE_SIZE:
                    return webhooks
        raise CalApiError("Cal.com webhook pagination exceeded the safety limit")

    async def create_webhook(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create one Cal.com webhook and return its representation."""
        return _webhook_data(await self._request("POST", "/webhooks", json=body))

    async def update_webhook(
        self,
        webhook_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Update one managed Cal.com webhook."""
        return _webhook_data(await self._request("PATCH", f"/webhooks/{webhook_id}", json=body))

    async def delete_webhook(self, webhook_id: str) -> None:
        """Delete one managed Cal.com webhook."""
        await self._request("DELETE", f"/webhooks/{webhook_id}")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, int] | None = None,
    ) -> Any:
        if self._client is None:
            async with self:
                return await self._request(method, path, json=json, params=params)
        try:
            response = await self._client.request(method, path, json=json, params=params)
        except httpx.HTTPError as exc:
            raise CalApiError("Unable to reach Cal.com API") from exc
        if response.is_success:
            if response.status_code == 204 or not response.content:
                return {}
            try:
                return response.json()
            except ValueError as exc:
                raise CalApiError("Cal.com API returned invalid JSON") from exc

        detail = _error_detail(response)
        raise CalApiError(detail, status_code=response.status_code)


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


def cal_subscription_lock_id(workflow_id: uuid.UUID, node_id: str) -> int:
    """Return a stable signed PostgreSQL advisory-lock key for one trigger node."""
    digest = hashlib.blake2b(
        f"{workflow_id}:{node_id}".encode("utf-8"),
        digest_size=8,
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


async def lock_cal_subscription(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    node_id: str,
) -> None:
    """Serialize subscription mutations for one workflow trigger until commit or rollback."""
    await db.execute(
        select(func.pg_advisory_xact_lock(cal_subscription_lock_id(workflow_id, node_id)))
    )


async def delete_managed_cal_subscriptions(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    owner_id: uuid.UUID,
    node_ids: set[str] | None = None,
) -> None:
    """Delete remote hooks before removing local registrations, or fail for retry."""
    if node_ids is not None and not node_ids:
        return

    query = select(CalWebhookSubscription).where(CalWebhookSubscription.workflow_id == workflow_id)
    if node_ids is not None:
        query = query.where(CalWebhookSubscription.node_id.in_(node_ids))

    if node_ids is not None:
        lock_node_ids = set(node_ids)
    else:
        existing = await db.execute(query)
        lock_node_ids = {subscription.node_id for subscription in existing.scalars().all()}
    # Lock before re-reading so sync/deactivate cannot race with cleanup.
    for node_id in sorted(lock_node_ids):
        await lock_cal_subscription(db, workflow_id, node_id)

    result = await db.execute(query)
    subscriptions = list(result.scalars().all())
    for subscription in subscriptions:
        if subscription.external_webhook_id:
            if subscription.credential_id is None:
                raise CalApiError(
                    f"Cal.com webhook {subscription.external_webhook_id} has no API credential"
                )
            credential = await get_accessible_credential(
                db,
                subscription.credential_id,
                owner_id,
            )
            if credential is None or credential.type != CredentialType.cal_api:
                raise CalApiError(
                    f"Cal.com webhook {subscription.external_webhook_id} credential is inaccessible"
                )
            config = decrypt_config(credential.encrypted_config)
            api_key = str(config.get("api_key") or "").strip()
            if not api_key:
                raise CalApiError(
                    f"Cal.com webhook {subscription.external_webhook_id} credential has no API key"
                )
            client = CalApiClient(
                CalApiConfig(
                    api_key=api_key,
                    base_url=str(config.get("base_url") or _DEFAULT_BASE_URL),
                )
            )
            try:
                await client.delete_webhook(subscription.external_webhook_id)
            except CalApiError as exc:
                if exc.status_code != 404:
                    raise
        await db.execute(
            delete(CalWebhookSubscription).where(CalWebhookSubscription.id == subscription.id)
        )
