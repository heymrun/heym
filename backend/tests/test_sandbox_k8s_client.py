import json
import unittest

import httpx

from app.services.sandbox.kubernetes.client import KubeApiError, KubeClient
from app.services.sandbox.kubernetes.config import KubeConfig

CONFIG = KubeConfig(
    server="https://k8s:443", namespace="sb", own_namespace="heym", in_cluster=True, token="t"
)


def _client(handler) -> tuple[KubeClient, list[httpx.Request]]:  # noqa: ANN001
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return KubeClient(CONFIG, transport=httpx.MockTransport(record)), seen


class ClientTest(unittest.TestCase):
    def test_create_pod_posts_with_bearer_token(self) -> None:
        client, seen = _client(lambda r: httpx.Response(201, json={"metadata": {"name": "p"}}))
        client.create_pod({"metadata": {"name": "p"}})
        self.assertEqual(seen[0].method, "POST")
        self.assertEqual(seen[0].url.path, "/api/v1/namespaces/sb/pods")
        self.assertEqual(seen[0].headers["Authorization"], "Bearer t")

    def test_get_missing_pod_is_none_and_own_namespace_is_explicit(self) -> None:
        client, seen = _client(lambda r: httpx.Response(404, json={"message": "nope"}))
        self.assertIsNone(client.get_pod("p", namespace="heym"))
        self.assertEqual(seen[0].url.path, "/api/v1/namespaces/heym/pods/p")

    def test_delete_is_immediate_and_tolerates_404(self) -> None:
        client, seen = _client(lambda r: httpx.Response(404))
        client.delete_pod("p")
        self.assertEqual(seen[0].url.params["gracePeriodSeconds"], "0")

    def test_errors_carry_the_api_message(self) -> None:
        client, _ = _client(lambda r: httpx.Response(403, json={"message": "forbidden: pods"}))
        with self.assertRaisesRegex(KubeApiError, "403.*forbidden: pods"):
            client.create_pod({})

    def test_can_i(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            allowed = body["spec"]["resourceAttributes"]["subresource"] == "attach"
            return httpx.Response(201, json={"status": {"allowed": allowed}})

        client, _ = _client(handler)
        self.assertTrue(client.can_i("create", "pods", "attach"))
        self.assertFalse(client.can_i("create", "pods"))

    def test_server_version_strips_plus(self) -> None:
        client, _ = _client(lambda r: httpx.Response(200, json={"major": "1", "minor": "30+"}))
        self.assertEqual(client.server_version(), (1, 30))

    def test_attach_url(self) -> None:
        client, _ = _client(lambda r: httpx.Response(200))
        self.assertEqual(
            client.attach_url("p"),
            "wss://k8s:443/api/v1/namespaces/sb/pods/p/attach"
            "?container=sandbox&stdin=true&stdout=true&stderr=true",
        )
