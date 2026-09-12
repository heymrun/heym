"""Egress-guard tests for credential-supplied node URLs (GHSA-39j3-6x3x-8rcr).

The Slack, Discord, and Crawler nodes dialled ``workflow_executor.get_http_client``
directly, so a credential URL pointing at an internal service was never checked.
These tests assert the guard now runs, that no connection is attempted for a
refused target, and that the Crawler node keeps reaching a FlareSolverr instance
on loopback, which is how the docs tell operators to deploy it.
"""

import contextlib
import http.server
import ipaddress
import socket
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch

import httpcore

from app.services import ssrf_guard
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import crawler_node, discord_node, slack_node
from app.services.ssrf_guard import (
    SsrfBlockedError,
    _HttpEgressPinBackend,
    _is_non_metadata_address,
    _is_public_address,
    _resolve_pinned_addresses,
    guard_carrier_url,
)

LOOPBACK = "http://127.0.0.1:10105/api/auth/login"
METADATA = "http://169.254.169.254/latest/meta-data/"
FLARESOLVERR = "http://localhost:8191"
PUBLIC = "https://hooks.slack.com/services/T000/B000/xxx"


class _FakeExecutor:
    def evaluate_message_template(self, template, inputs, node_id):  # noqa: ANN001
        return template

    def _get_accessible_credential(self, db, credential_id):  # noqa: ANN001
        return types.SimpleNamespace(encrypted_config=b"ciphertext")


def _ctx(node_type: str, node_data: dict) -> NodeExecutionContext:
    return NodeExecutionContext(
        executor=_FakeExecutor(),
        node_id="n1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={},
        node_type=node_type,
        node_data=node_data,
        node_label=node_type,
    )


class _NodeGuardTestCase(unittest.TestCase):
    """Stubs the DB and decryption seams so only the egress path is exercised."""

    def setUp(self) -> None:
        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)

        @contextlib.contextmanager
        def _session():
            yield object()

        session_patcher = patch("app.db.session.SessionLocal", _session)
        session_patcher.start()
        self.addCleanup(session_patcher.stop)

    def _with_credential(self, config: dict) -> MagicMock:
        """Point decrypt_config at ``config`` and return a client spy."""
        patcher = patch("app.services.encryption.decrypt_config", return_value=config)
        patcher.start()
        self.addCleanup(patcher.stop)

        client = MagicMock()
        client.post.return_value = MagicMock(status_code=200, text="{}")
        client.post.return_value.json.return_value = {"solution": {"response": "<html></html>"}}
        return client


class SlackCredentialUrlTests(_NodeGuardTestCase):
    def test_loopback_webhook_is_refused_before_any_request(self) -> None:
        client = self._with_credential({"webhook_url": LOOPBACK})
        with patch.object(ssrf_guard, "get_guarded_http_client", return_value=client):
            with self.assertRaises(SsrfBlockedError):
                slack_node.execute(_ctx("slack", {"credentialId": "c", "message": "hi"}))
        client.post.assert_not_called()

    def test_metadata_webhook_is_refused(self) -> None:
        client = self._with_credential({"webhook_url": METADATA})
        with patch.object(ssrf_guard, "get_guarded_http_client", return_value=client):
            with self.assertRaises(SsrfBlockedError):
                slack_node.execute(_ctx("slack", {"credentialId": "c", "message": "hi"}))
        client.post.assert_not_called()

    def test_public_webhook_uses_the_guarded_client(self) -> None:
        client = self._with_credential({"webhook_url": PUBLIC})
        with patch.object(ssrf_guard, "get_guarded_http_client", return_value=client):
            slack_node.execute(_ctx("slack", {"credentialId": "c", "message": "hi"}))
        client.post.assert_called_once()
        self.assertEqual(client.post.call_args[0][0], PUBLIC)

    def test_opt_out_allows_an_internal_receiver(self) -> None:
        client = self._with_credential({"webhook_url": LOOPBACK})
        with patch.object(ssrf_guard.settings, "http_allow_private_urls", True):
            with patch.object(ssrf_guard, "get_guarded_http_client", return_value=client):
                slack_node.execute(_ctx("slack", {"credentialId": "c", "message": "hi"}))
        client.post.assert_called_once()


class DiscordCredentialUrlTests(_NodeGuardTestCase):
    def test_loopback_webhook_is_refused_before_any_request(self) -> None:
        client = self._with_credential({"webhook_url": LOOPBACK})
        with patch.object(ssrf_guard, "get_guarded_http_client", return_value=client):
            with self.assertRaises(SsrfBlockedError):
                discord_node.execute(_ctx("discord", {"credentialId": "c", "message": "hi"}))
        client.post.assert_not_called()

    def test_guard_runs_on_the_rewritten_url_that_is_dialled(self) -> None:
        """The node appends ``wait=true``; the guarded URL must be that one."""
        client = self._with_credential({"webhook_url": PUBLIC})
        seen: list[str] = []
        with patch.object(
            ssrf_guard, "guard_http_url", side_effect=lambda u, s=None: seen.append(u)
        ):
            with patch.object(ssrf_guard, "get_guarded_http_client", return_value=client):
                discord_node.execute(_ctx("discord", {"credentialId": "c", "message": "hi"}))
        self.assertEqual(seen, [client.post.call_args[0][0]])
        self.assertIn("wait=true", seen[0])


class CrawlerCarrierUrlTests(_NodeGuardTestCase):
    """FlareSolverr is documented on localhost, so private addresses must pass."""

    def _run(self, url: str):
        client = self._with_credential({"flaresolverr_url": url})
        with patch.object(ssrf_guard, "get_guarded_carrier_http_client", return_value=client):
            crawler_node.execute(
                _ctx("crawler", {"credentialId": "c", "crawlerUrl": "http://example.com"})
            )
        return client

    def test_loopback_flaresolverr_still_works(self) -> None:
        client = self._run(FLARESOLVERR)
        client.post.assert_called_once()

    def test_private_compose_service_address_still_works(self) -> None:
        with patch.object(
            ssrf_guard, "guard_carrier_url", side_effect=ssrf_guard.guard_carrier_url
        ):
            client = self._run("http://10.0.1.7:8191")
        client.post.assert_called_once()

    def test_metadata_flaresolverr_url_is_refused(self) -> None:
        client = self._with_credential({"flaresolverr_url": METADATA})
        with patch.object(ssrf_guard, "get_guarded_carrier_http_client", return_value=client):
            with self.assertRaises(SsrfBlockedError):
                crawler_node.execute(
                    _ctx("crawler", {"credentialId": "c", "crawlerUrl": "http://example.com"})
                )
        client.post.assert_not_called()

    def test_crawler_does_not_use_the_strict_public_only_client(self) -> None:
        """Guarding the carrier with the strict policy would break the docs setup."""
        with self.assertRaises(SsrfBlockedError):
            ssrf_guard.guard_http_url(FLARESOLVERR, "FlareSolverr credential URL")
        guard_carrier_url(FLARESOLVERR, "FlareSolverr credential URL")


class CarrierAddressPolicyTests(unittest.TestCase):
    """The carrier policy is narrower, not weaker, than the public-only policy."""

    def setUp(self) -> None:
        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_metadata_reaching_forms_are_refused(self) -> None:
        for literal in (
            "169.254.169.254",  # AWS/GCP/Azure IMDS
            "169.254.170.2",  # ECS task metadata
            "fd00:ec2::254",  # AWS IPv6 IMDS
            "fe80::1",  # IPv6 link-local
            "::ffff:169.254.169.254",  # IPv4-mapped
            "64:ff9b::a9fe:a9fe",  # NAT64-wrapped IMDS
            "::169.254.169.254",  # deprecated IPv4-compatible
            "2002:a9fe:a9fe::",  # 6to4-wrapped IMDS
            "100.100.100.200",  # Alibaba Cloud IMDS, outside 169.254.0.0/16
            "64:ff9b:1::a9fe:a9fe",  # NAT64 local-use prefix (RFC 8215)
        ):
            with self.subTest(literal=literal):
                self.assertFalse(_is_non_metadata_address(ipaddress.ip_address(literal)))

    def test_carrier_deployable_addresses_are_allowed(self) -> None:
        for literal in ("127.0.0.1", "10.0.1.7", "172.17.0.5", "192.168.1.10", "::1", "8.8.8.8"):
            with self.subTest(literal=literal):
                self.assertTrue(_is_non_metadata_address(ipaddress.ip_address(literal)))

    def test_every_address_the_strict_policy_allows_is_also_allowed_here(self) -> None:
        """Narrower means a superset of destinations, never a different set."""
        for literal in ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"):
            address = ipaddress.ip_address(literal)
            with self.subTest(literal=literal):
                if _is_public_address(address):
                    self.assertTrue(_is_non_metadata_address(address))


class GuardedClientSeparationTests(unittest.TestCase):
    """The two shared clients must not share a pool, or one policy would win."""

    def setUp(self) -> None:
        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)
        ssrf_guard.close_guarded_http_client()
        ssrf_guard.close_guarded_carrier_http_client()
        self.addCleanup(ssrf_guard.close_guarded_carrier_http_client)
        self.addCleanup(ssrf_guard.close_guarded_http_client)

    def test_clients_and_pin_policies_are_distinct(self) -> None:
        strict = ssrf_guard.get_guarded_http_client()
        carrier = ssrf_guard.get_guarded_carrier_http_client()
        self.assertIsNot(strict, carrier)

        strict_backend = strict._transport._pool._network_backend
        carrier_backend = carrier._transport._pool._network_backend
        self.assertIs(strict_backend._policy, _is_public_address)
        self.assertIs(carrier_backend._policy, _is_non_metadata_address)

    def test_both_clients_refuse_environment_proxies(self) -> None:
        for client in (
            ssrf_guard.get_guarded_http_client(),
            ssrf_guard.get_guarded_carrier_http_client(),
        ):
            self.assertFalse(getattr(client, "_mounts", None))


class _Ipv4OnlyServer:
    """An IPv4-only HTTP server, the shape a published container port has."""

    def __enter__(self) -> tuple[str, int]:
        body = b'{"solution":{"response":"ok"}}'

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        self._srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        port = self._srv.server_address[1]
        return f"http://carrier.test:{port}/v1", port

    def __exit__(self, *exc: object) -> None:
        self._srv.shutdown()


class PinnedDialFallbackTests(unittest.TestCase):
    """A pinned dial keeps the IPv6-then-IPv4 fallback the resolver would give.

    Regression: the backend dialled only the first validated address, so a host
    resolving to ``::1`` before ``127.0.0.1`` could not reach an IPv4-only
    service. That is the documented FlareSolverr deployment.
    """

    DUAL = [
        (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 0, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0)),
    ]

    def setUp(self) -> None:
        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)
        ssrf_guard.close_guarded_carrier_http_client()
        self.addCleanup(ssrf_guard.close_guarded_carrier_http_client)

    def _dial(self, first_failure: Exception, budget: float = 0.25) -> tuple:
        """Dial a host whose first validated address fails, and report attempts."""
        attempts: list[tuple[str, float | None]] = []

        class Inner:
            def connect_tcp(self, host, port, timeout=None, **kwargs):  # noqa: ANN001
                attempts.append((host, timeout))
                if host == "::1":
                    if isinstance(first_failure, httpcore.ConnectTimeout):
                        time.sleep(timeout or 0)
                    raise first_failure
                return f"stream-to-{host}"

        backend = _HttpEgressPinBackend(Inner(), _is_non_metadata_address)
        with patch.object(ssrf_guard.socket, "getaddrinfo", return_value=self.DUAL):
            result = backend.connect_tcp("carrier.test", 8191, timeout=budget)
        return result, attempts

    def test_falls_back_when_the_first_address_is_refused(self) -> None:
        result, attempts = self._dial(httpcore.ConnectError("refused"))
        self.assertEqual(result, "stream-to-127.0.0.1")
        self.assertEqual([host for host, _t in attempts], ["::1", "127.0.0.1"])

    def test_falls_back_when_the_first_address_times_out(self) -> None:
        """An unresponsive first address must not spend the whole budget."""
        result, attempts = self._dial(httpcore.ConnectTimeout("timed out"))
        self.assertEqual(result, "stream-to-127.0.0.1")
        self.assertEqual([host for host, _t in attempts], ["::1", "127.0.0.1"])

    def test_first_attempt_does_not_consume_the_whole_budget(self) -> None:
        _result, attempts = self._dial(httpcore.ConnectError("refused"), budget=0.25)
        first_timeout = attempts[0][1]
        self.assertIsNotNone(first_timeout)
        self.assertLess(first_timeout, 0.25)

    def test_budget_stays_bounded_across_attempts(self) -> None:
        """Splitting the deadline must not multiply the caller's timeout."""
        started = time.monotonic()
        with self.assertRaises(httpcore.ConnectTimeout):
            self._dial_all_timeout(budget=0.2)
        self.assertLess(time.monotonic() - started, 0.5)

    def _dial_all_timeout(self, budget: float) -> None:
        class Inner:
            def connect_tcp(self, host, port, timeout=None, **kwargs):  # noqa: ANN001
                time.sleep(timeout or 0)
                raise httpcore.ConnectTimeout("timed out")

        backend = _HttpEgressPinBackend(Inner(), _is_non_metadata_address)
        with patch.object(ssrf_guard.socket, "getaddrinfo", return_value=self.DUAL):
            backend.connect_tcp("carrier.test", 8191, timeout=budget)

    def test_fallback_does_not_relax_the_policy(self) -> None:
        """Every resolved address must pass, so a mixed answer is still refused."""
        mixed = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0)),
        ]
        with patch.object(ssrf_guard.socket, "getaddrinfo", return_value=mixed):
            with self.assertRaises(SsrfBlockedError):
                _resolve_pinned_addresses("rebind.example.com", _is_public_address)

    def test_only_validated_addresses_are_offered_to_the_dialer(self) -> None:
        dual = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2606:4700::1111", 0, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0)),
        ]
        with patch.object(ssrf_guard.socket, "getaddrinfo", return_value=dual):
            resolved = _resolve_pinned_addresses("dual.example.com", _is_public_address)
        self.assertEqual([addr for _f, addr in resolved], ["2606:4700::1111", "93.184.216.34"])

    def test_reaches_an_ipv4_only_service_through_a_real_socket(self) -> None:
        """End-to-end, with the address order forced only for the carrier host."""
        real_getaddrinfo = socket.getaddrinfo

        def only_for_carrier(host, *args, **kwargs):  # noqa: ANN001
            if host == "carrier.test":
                return self.DUAL
            return real_getaddrinfo(host, *args, **kwargs)

        with _Ipv4OnlyServer() as (url, _port):
            with patch.object(ssrf_guard.socket, "getaddrinfo", side_effect=only_for_carrier):
                response = ssrf_guard.get_guarded_carrier_http_client().post(
                    url, json={"cmd": "request.get"}, timeout=5
                )
        self.assertEqual(response.status_code, 200)


class OptOutRestoresProxyTests(unittest.TestCase):
    """The documented escape hatch has to restore proxy use, not just the pin.

    Regression: both shared clients hardcoded ``trust_env=False``, so an operator
    whose integrations only reach the internet through ``HTTP_PROXY`` had no
    working configuration once these nodes moved onto the guarded clients.
    """

    def _clients(self) -> list:
        ssrf_guard.close_guarded_http_client()
        ssrf_guard.close_guarded_carrier_http_client()
        self.addCleanup(ssrf_guard.close_guarded_http_client)
        self.addCleanup(ssrf_guard.close_guarded_carrier_http_client)
        return [
            ssrf_guard.get_guarded_http_client(),
            ssrf_guard.get_guarded_carrier_http_client(),
        ]

    def test_guard_on_keeps_environment_proxies_disabled(self) -> None:
        with patch.object(ssrf_guard.settings, "http_allow_private_urls", False):
            for client in self._clients():
                self.assertFalse(client.trust_env)
                self.assertFalse(getattr(client, "_mounts", None))

    def test_opt_out_restores_environment_proxies(self) -> None:
        with patch.object(ssrf_guard.settings, "http_allow_private_urls", True):
            for client in self._clients():
                self.assertTrue(client.trust_env)


if __name__ == "__main__":
    unittest.main()
