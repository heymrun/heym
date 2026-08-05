"""Tests for Cal.com API-managed webhook operations."""

import json
import socket
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.config import settings
from app.db.models import CredentialType
from app.services.cal_api_service import (
    CalApiClient,
    CalApiConfig,
    CalApiError,
    cal_subscription_lock_id,
    delete_managed_cal_subscriptions,
)


class CalApiConfigTests(unittest.TestCase):
    def test_normalizes_cloud_and_self_hosted_v2_urls(self) -> None:
        self.assertEqual(
            CalApiConfig(api_key="key").api_v2_url,
            "https://api.cal.com/v2",
        )
        self.assertEqual(
            CalApiConfig(api_key="key", base_url="https://cal.example.test/v2/").api_v2_url,
            "https://cal.example.test/v2",
        )

    def test_subscription_lock_id_is_stable_signed_int(self) -> None:
        workflow_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        first = cal_subscription_lock_id(workflow_id, "cal-node")
        second = cal_subscription_lock_id(workflow_id, "cal-node")
        other = cal_subscription_lock_id(workflow_id, "other-node")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertGreaterEqual(first, -(2**63))
        self.assertLess(first, 2**63)


class CalApiClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocks_cloud_metadata_base_url(self) -> None:
        client = CalApiClient(
            CalApiConfig(api_key="cal-secret", base_url="http://metadata.internal")
        )
        resolved = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0)),
        ]
        with (
            patch.object(settings, "http_allow_private_urls", False),
            patch("app.services.ssrf_guard.socket.getaddrinfo", return_value=resolved),
            self.assertRaises(CalApiError) as raised,
        ):
            await client.list_webhooks()

        self.assertIn("base URL is not allowed", str(raised.exception))

    async def test_crud_uses_bearer_auth_and_v2_webhook_paths(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "POST":
                return httpx.Response(201, json={"data": {"id": "hook-1"}})
            if request.method == "PATCH":
                return httpx.Response(200, json={"data": {"id": "hook-1"}})
            return httpx.Response(204)

        original_async_client = httpx.AsyncClient

        def client_factory(**kwargs: object) -> httpx.AsyncClient:
            return original_async_client(
                base_url=str(kwargs["base_url"]),
                headers=kwargs["headers"],
                timeout=kwargs["timeout"],
                transport=httpx.MockTransport(handler),
            )

        client = CalApiClient(CalApiConfig(api_key="cal-secret"))
        body = {
            "subscriberUrl": "https://heym.example/api/cal/webhook/workflow/node",
            "triggers": ["BOOKING_CREATED"],
            "secret": "webhook-secret",
            "version": "2021-10-20",
            "active": True,
        }
        with (
            patch("app.services.cal_api_service.httpx.AsyncClient", side_effect=client_factory),
            patch.object(settings, "http_allow_private_urls", True),
        ):
            created = await client.create_webhook(body)
            updated = await client.update_webhook("hook-1", body)
            await client.delete_webhook("hook-1")

        self.assertEqual(created["id"], "hook-1")
        self.assertEqual(updated["id"], "hook-1")
        self.assertEqual([request.method for request in requests], ["POST", "PATCH", "DELETE"])
        self.assertEqual(requests[0].url.path, "/v2/webhooks")
        self.assertEqual(requests[1].url.path, "/v2/webhooks/hook-1")
        self.assertEqual(requests[2].url.path, "/v2/webhooks/hook-1")
        self.assertEqual(requests[0].headers["authorization"], "Bearer cal-secret")
        self.assertEqual(json.loads(requests[0].content), body)

    async def test_list_webhooks_fetches_every_page(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            skip = int(request.url.params.get("skip", "0"))
            count = 250 if skip == 0 else 1
            return httpx.Response(
                200,
                json={"data": [{"id": f"hook-{skip + index}"} for index in range(count)]},
            )

        original_async_client = httpx.AsyncClient

        def client_factory(**kwargs: object) -> httpx.AsyncClient:
            return original_async_client(
                base_url=str(kwargs["base_url"]),
                transport=httpx.MockTransport(handler),
            )

        client = CalApiClient(CalApiConfig(api_key="cal-secret"))
        with (
            patch(
                "app.services.cal_api_service.httpx.AsyncClient", side_effect=client_factory
            ) as async_client,
            patch.object(settings, "http_allow_private_urls", True),
        ):
            webhooks = await client.list_webhooks()

        self.assertEqual(len(webhooks), 251)
        self.assertEqual(async_client.call_count, 1)
        self.assertEqual([request.url.params["skip"] for request in requests], ["0", "250"])
        self.assertTrue(all(request.url.params["take"] == "250" for request in requests))

    async def test_surfaces_safe_api_error_message(self) -> None:
        original_async_client = httpx.AsyncClient

        def client_factory(**kwargs: object) -> httpx.AsyncClient:
            return original_async_client(
                base_url=str(kwargs["base_url"]),
                transport=httpx.MockTransport(
                    lambda _request: httpx.Response(401, json={"message": "Invalid API key"})
                ),
            )

        client = CalApiClient(CalApiConfig(api_key="bad-key"))
        with (
            patch("app.services.cal_api_service.httpx.AsyncClient", side_effect=client_factory),
            patch.object(settings, "http_allow_private_urls", True),
            self.assertRaises(CalApiError) as raised,
        ):
            await client.list_webhooks()

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(str(raised.exception), "Cal.com API request failed: Invalid API key")


class DeleteManagedCalSubscriptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_failure_keeps_local_registration_for_retry(self) -> None:
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        credential_id = uuid.uuid4()
        subscription = SimpleNamespace(
            id=uuid.uuid4(),
            node_id="cal-node",
            credential_id=credential_id,
            external_webhook_id="remote-hook",
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [subscription]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        credential = SimpleNamespace(
            type=CredentialType.cal_api,
            encrypted_config="encrypted",
        )

        with (
            patch("app.services.cal_api_service.lock_cal_subscription", AsyncMock()),
            patch(
                "app.services.cal_api_service.get_accessible_credential",
                AsyncMock(return_value=credential),
            ),
            patch(
                "app.services.cal_api_service.decrypt_config",
                return_value={"api_key": "key", "base_url": "https://api.cal.com"},
            ),
            patch.object(
                CalApiClient,
                "delete_webhook",
                AsyncMock(side_effect=CalApiError("temporary failure", status_code=503)),
            ),
            self.assertRaises(CalApiError),
        ):
            await delete_managed_cal_subscriptions(
                db,
                workflow_id=workflow_id,
                owner_id=owner_id,
                node_ids={"cal-node"},
            )

        # Only the subscription SELECT ran; no local DELETE was issued.
        self.assertEqual(db.execute.await_count, 1)

    async def test_locks_target_nodes_before_deleting_local_rows(self) -> None:
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        subscription = SimpleNamespace(
            id=uuid.uuid4(),
            node_id="cal-node",
            credential_id=None,
            external_webhook_id=None,
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [subscription]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        lock = AsyncMock()

        with patch("app.services.cal_api_service.lock_cal_subscription", lock):
            await delete_managed_cal_subscriptions(
                db,
                workflow_id=workflow_id,
                owner_id=owner_id,
                node_ids={"cal-node", "other-node"},
            )

        self.assertEqual(
            [call.args[1:] for call in lock.await_args_list],
            [(workflow_id, "cal-node"), (workflow_id, "other-node")],
        )
        self.assertGreaterEqual(db.execute.await_count, 2)
