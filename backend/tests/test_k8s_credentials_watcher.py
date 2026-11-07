"""The Secret watcher against a fake API server: list, watch events, errors."""

from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import AsyncMock

import httpx

from app.services.k8s_credentials.store import CredentialUnavailableError, SecretCredentialStore
from app.services.k8s_credentials.watcher import SecretsForbiddenError, SecretWatcher
from app.services.sandbox.kubernetes.config import KubeConfig

CONFIG = KubeConfig(
    server="https://k8s.test", namespace="heym", own_namespace="heym", in_cluster=False, token="t"
)


def _secret(name: str, api_key: str) -> dict:
    return {
        "metadata": {
            "name": name,
            "namespace": "heym",
            "annotations": {
                "heym.run/name": name,
                "heym.run/type": "openai",
                "heym.run/owner": "admin@example.com",
            },
        },
        "data": {"api_key": base64.b64encode(api_key.encode()).decode()},
    }


def _watcher(handler, store: SecretCredentialStore, on_change=None) -> SecretWatcher:
    return SecretWatcher(
        CONFIG, "heym", store=store, transport=httpx.MockTransport(handler), on_change=on_change
    )


def _store() -> SecretCredentialStore:
    store = SecretCredentialStore()
    store.enabled = True
    return store


class ListTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_fills_the_store_and_marks_it_synced(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200, json={"metadata": {"resourceVersion": "41"}, "items": [_secret("a", "sk-a")]}
            )

        store = _store()
        on_change = AsyncMock()
        resource_version = await _watcher(handler, store, on_change).list_once()

        self.assertEqual(resource_version, "41")
        self.assertTrue(store.ready())
        self.assertEqual(store.config_for("k8s:heym/a"), {"api_key": "sk-a"})
        self.assertEqual(requests[0].url.params["labelSelector"], "heym.run/credential=true")
        self.assertEqual(requests[0].headers["authorization"], "Bearer t")
        on_change.assert_awaited_once()

    async def test_forbidden_list_is_a_configuration_error(self) -> None:
        store = _store()
        watcher = _watcher(lambda _r: httpx.Response(403, json={"message": "no"}), store)

        with self.assertRaises(SecretsForbiddenError):
            await watcher.list_once()
        self.assertFalse(store.ready())


class WatchTests(unittest.IsolatedAsyncioTestCase):
    async def _watch(self, events: list[dict], store: SecretCredentialStore) -> None:
        body = "\n".join(json.dumps(e) for e in events) + "\n"

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["watch"] == "1"
            assert request.url.params["resourceVersion"] == "41"
            return httpx.Response(200, content=body.encode())

        await _watcher(handler, store).watch_once("41")

    async def test_events_add_rotate_and_remove(self) -> None:
        store = _store()
        store.replace_all([])

        await self._watch(
            [
                {"type": "ADDED", "object": _secret("a", "sk-1")},
                {"type": "MODIFIED", "object": _secret("a", "sk-2")},
                {"type": "ADDED", "object": _secret("b", "sk-b")},
                {"type": "DELETED", "object": _secret("b", "sk-b")},
                {"type": "BOOKMARK", "object": {"metadata": {"resourceVersion": "50"}}},
            ],
            store,
        )

        self.assertEqual(store.config_for("k8s:heym/a"), {"api_key": "sk-2"})
        with self.assertRaisesRegex(CredentialUnavailableError, "heym/b not found"):
            store.config_for("k8s:heym/b")

    async def test_an_expired_watch_stops_so_the_caller_relists(self) -> None:
        store = _store()
        store.replace_all([])

        await self._watch(
            [
                {"type": "ERROR", "object": {"code": 410, "message": "too old resource version"}},
                {"type": "ADDED", "object": _secret("late", "sk")},
            ],
            store,
        )

        self.assertIsNone(store.get("k8s:heym/late"))


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_failed_relist_keeps_the_last_known_values(self) -> None:
        """An API-server blip must not drop credentials that were working."""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(
                    200,
                    json={"metadata": {"resourceVersion": "1"}, "items": [_secret("a", "sk-a")]},
                )
            raise httpx.ConnectError("api server down")

        store = _store()
        watcher = _watcher(handler, store)
        await watcher.list_once()
        with self.assertRaises(httpx.ConnectError):
            await watcher.list_once()

        self.assertEqual(store.config_for("k8s:heym/a"), {"api_key": "sk-a"})


class PermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_denied_verbs_are_named(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            verb = json.loads(request.content)["spec"]["resourceAttributes"]["verb"]
            return httpx.Response(201, json={"status": {"allowed": verb == "list"}})

        with self.assertRaisesRegex(
            SecretsForbiddenError, "may not watch secrets in namespace 'heym'"
        ):
            await _watcher(handler, _store()).check_permissions()

    async def test_allowed_passes(self) -> None:
        handler = lambda _r: httpx.Response(201, json={"status": {"allowed": True}})  # noqa: E731

        await _watcher(handler, _store()).check_permissions()


if __name__ == "__main__":
    unittest.main()
