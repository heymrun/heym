"""SSRF egress-guard tests for the HTTP workflow node (GHSA-8wj7-v2w6-wfcx)."""

import os
import socket
import unittest
from unittest.mock import MagicMock, patch

import httpcore
import httpx

from app.services import ssrf_guard
from app.services.ssrf_guard import (
    SsrfBlockedError,
    _HttpEgressPinBackend,
    _install_egress_pin,
    _is_public_address,
    _resolve_pinned_ip,
    get_guarded_http_client,
    guard_http_url,
)


def _addrinfo(*ips: str) -> list:
    """Build a getaddrinfo-style result for the given IPv4/IPv6 literals."""
    out = []
    for ip in ips:
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        sockaddr = (ip, 0, 0, 0) if family == socket.AF_INET6 else (ip, 0)
        out.append((family, socket.SOCK_STREAM, 0, "", sockaddr))
    return out


class GuardIpLiteralTests(unittest.TestCase):
    """IP-literal hosts are validated without a DNS lookup."""

    def setUp(self) -> None:
        # Pin the opt-out so these assertions do not depend on the ambient
        # HEYM_HTTP_ALLOW_PRIVATE_URLS value on the machine running the suite.
        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_cloud_metadata_ip_blocked(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            guard_http_url("http://169.254.169.254/latest/meta-data/")

    def test_ipv4_loopback_blocked(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            guard_http_url("http://127.0.0.1:8080/")

    def test_ipv4_private_blocked(self) -> None:
        for url in (
            "http://10.0.0.5/",
            "http://192.168.1.10/",
            "http://172.16.5.5/",
        ):
            with self.subTest(url=url), self.assertRaises(SsrfBlockedError):
                guard_http_url(url)

    def test_ipv6_loopback_blocked(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            guard_http_url("http://[::1]:9000/")

    def test_ipv4_mapped_ipv6_metadata_blocked(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            guard_http_url("http://[::ffff:169.254.169.254]/")

    def test_multicast_blocked(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            guard_http_url("http://239.255.255.250/")

    def test_public_ip_allowed(self) -> None:
        # Should not raise for a public literal.
        guard_http_url("http://1.1.1.1/")

    def test_non_http_scheme_blocked(self) -> None:
        for url in ("file:///etc/passwd", "gopher://1.1.1.1/", "ftp://1.1.1.1/"):
            with self.subTest(url=url), self.assertRaises(SsrfBlockedError):
                guard_http_url(url)


class GuardDnsTests(unittest.TestCase):
    """DNS names are resolved and every returned address must be public."""

    def setUp(self) -> None:
        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dns_resolving_to_private_blocked(self) -> None:
        with patch.object(ssrf_guard.socket, "getaddrinfo", return_value=_addrinfo("10.0.0.9")):
            with self.assertRaises(SsrfBlockedError):
                guard_http_url("http://internal.example.com/")

    def test_dns_with_any_private_record_blocked(self) -> None:
        # A public + private split answer must be refused (DNS rebinding defense).
        with patch.object(
            ssrf_guard.socket,
            "getaddrinfo",
            return_value=_addrinfo("93.184.216.34", "127.0.0.1"),
        ):
            with self.assertRaises(SsrfBlockedError):
                guard_http_url("http://mixed.example.com/")

    def test_dns_resolving_to_public_allowed(self) -> None:
        with patch.object(
            ssrf_guard.socket, "getaddrinfo", return_value=_addrinfo("93.184.216.34")
        ):
            guard_http_url("http://example.com/")

    def test_unresolvable_host_blocked(self) -> None:
        with patch.object(ssrf_guard.socket, "getaddrinfo", side_effect=socket.gaierror("nope")):
            with self.assertRaises(SsrfBlockedError):
                guard_http_url("http://does-not-resolve.example/")


class GuardOptOutTests(unittest.TestCase):
    """HEYM_HTTP_ALLOW_PRIVATE_URLS relaxes the IP block but not the scheme."""

    def test_private_allowed_when_opted_out(self) -> None:
        with patch.object(ssrf_guard.settings, "http_allow_private_urls", True):
            guard_http_url("http://127.0.0.1:8080/")
            guard_http_url("http://169.254.169.254/latest/meta-data/")

    def test_scheme_still_enforced_when_opted_out(self) -> None:
        with patch.object(ssrf_guard.settings, "http_allow_private_urls", True):
            with self.assertRaises(SsrfBlockedError):
                guard_http_url("file:///etc/passwd")


class PublicAddressTests(unittest.TestCase):
    def test_multicast_is_not_public(self) -> None:
        import ipaddress

        self.assertFalse(_is_public_address(ipaddress.ip_address("224.0.0.1")))

    def test_global_unicast_is_public(self) -> None:
        import ipaddress

        self.assertTrue(_is_public_address(ipaddress.ip_address("8.8.8.8")))


class Ipv6TransitionAddressTests(unittest.TestCase):
    """IPv6 transition forms are judged by the IPv4 they carry, not by is_global.

    NAT64 (64:ff9b::/96) and the deprecated IPv4-compatible form (::x.x.x.x) are
    reported globally routable by ipaddress even when the embedded IPv4 is
    loopback, private, or the cloud-metadata endpoint (GHSA-79qr-f49h-6g8c).
    """

    def setUp(self) -> None:
        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_transition_forms_wrapping_internal_ipv4_blocked(self) -> None:
        import ipaddress

        for label, literal in (
            ("nat64-metadata", "64:ff9b::169.254.169.254"),
            ("nat64-loopback", "64:ff9b::127.0.0.1"),
            ("nat64-private", "64:ff9b::10.0.0.1"),
            ("nat64-local-use-prefix", "64:ff9b:1::a9fe:a9fe"),
            ("ipv4-compatible-metadata", "::169.254.169.254"),
            ("ipv4-compatible-private", "::10.0.0.1"),
            ("sixtofour-metadata", "2002:a9fe:a9fe::"),
            ("sixtofour-private", "2002:0a00:0001::"),
        ):
            with self.subTest(label):
                self.assertFalse(_is_public_address(ipaddress.ip_address(literal)))

    def test_sixtofour_and_teredo_stay_blocked_even_when_public(self) -> None:
        import ipaddress

        # ipaddress refuses 2002::/16 and 2001::/32 wholesale. Unwrapping them to
        # their embedded IPv4 would re-admit addresses that are blocked today, so
        # the fix deliberately leaves both to is_global.
        for label, literal in (
            ("sixtofour-public-embedded", "2002:5db8:d822::"),
            ("sixtofour-public-embedded-dns", "2002:0808:0808::"),
            ("teredo-public-server-and-client", "2001:0:0808:0808:0000:0000:f5ff:fffe"),
            ("teredo-sample", "2001:0:4136:e378:8000:63bf:3fff:fdd2"),
        ):
            with self.subTest(label):
                self.assertFalse(_is_public_address(ipaddress.ip_address(literal)))

    def test_transition_forms_wrapping_public_ipv4_allowed(self) -> None:
        import ipaddress

        # IPv6-only deployments legitimately reach public IPv4 through NAT64, and
        # these were already allowed before the fix, so nothing narrows here.
        for label, literal in (
            ("nat64-public", "64:ff9b::1.1.1.1"),
            ("ipv4-compatible-public", "::8.8.8.8"),
            ("native-public-v6", "2606:4700:4700::1111"),
        ):
            with self.subTest(label):
                self.assertTrue(_is_public_address(ipaddress.ip_address(literal)))

    def test_guard_rejects_nat64_metadata_url(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            guard_http_url("http://[64:ff9b::169.254.169.254]/latest/meta-data/")

    def test_guard_rejects_ipv4_compatible_metadata_url(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            guard_http_url("http://[::169.254.169.254]/latest/meta-data/")

    def test_pinned_dial_rejects_nat64_metadata(self) -> None:
        with patch.object(
            ssrf_guard.socket,
            "getaddrinfo",
            return_value=_addrinfo("64:ff9b::169.254.169.254"),
        ):
            with self.assertRaises(SsrfBlockedError):
                _resolve_pinned_ip("rebind.example.com")

    def test_pinned_dial_rejects_ipv4_compatible_metadata(self) -> None:
        with patch.object(
            ssrf_guard.socket,
            "getaddrinfo",
            return_value=_addrinfo("::169.254.169.254"),
        ):
            with self.assertRaises(SsrfBlockedError):
                _resolve_pinned_ip("rebind.example.com")


class PinBackendTests(unittest.TestCase):
    """The dial-time pin re-validates and rewrites the target to a public IP."""

    def test_connect_tcp_pins_public_ip(self) -> None:
        inner = MagicMock()
        backend = _HttpEgressPinBackend(inner)
        with patch.object(
            ssrf_guard.socket, "getaddrinfo", return_value=_addrinfo("93.184.216.34")
        ):
            backend.connect_tcp("example.com", 443, timeout=5.0)
        inner.connect_tcp.assert_called_once()
        pinned_host = inner.connect_tcp.call_args.args[0]
        self.assertEqual(pinned_host, "93.184.216.34")

    def test_connect_tcp_private_raises_connect_error(self) -> None:
        inner = MagicMock()
        backend = _HttpEgressPinBackend(inner)
        with patch.object(ssrf_guard.socket, "getaddrinfo", return_value=_addrinfo("10.1.2.3")):
            with self.assertRaises(httpcore.ConnectError):
                backend.connect_tcp("rebind.example.com", 80)
        inner.connect_tcp.assert_not_called()

    def test_unix_socket_refused(self) -> None:
        backend = _HttpEgressPinBackend(MagicMock())
        with self.assertRaises(httpcore.ConnectError):
            backend.connect_unix_socket("/var/run/x.sock")

    def test_resolve_pinned_ip_rejects_private(self) -> None:
        with patch.object(ssrf_guard.socket, "getaddrinfo", return_value=_addrinfo("192.168.0.2")):
            with self.assertRaises(SsrfBlockedError):
                _resolve_pinned_ip("internal.example.com")


class GuardedClientTests(unittest.TestCase):
    def setUp(self) -> None:
        ssrf_guard.close_guarded_http_client()

    def tearDown(self) -> None:
        ssrf_guard.close_guarded_http_client()

    def test_client_has_pin_backend_installed(self) -> None:
        with patch.object(ssrf_guard.settings, "http_allow_private_urls", False):
            client = get_guarded_http_client()
            backend = client._transport._pool._network_backend
            self.assertIsInstance(backend, _HttpEgressPinBackend)

    def test_client_skips_pin_when_opted_out(self) -> None:
        with patch.object(ssrf_guard.settings, "http_allow_private_urls", True):
            client = get_guarded_http_client()
            backend = client._transport._pool._network_backend
            self.assertNotIsInstance(backend, _HttpEgressPinBackend)

    def test_install_fails_closed_on_unexpected_internals(self) -> None:
        with patch.object(ssrf_guard.settings, "http_allow_private_urls", False):
            broken = MagicMock()
            broken._transport = None
            broken._mounts = {}
            with self.assertRaises(RuntimeError):
                _install_egress_pin(broken)

    def test_env_proxy_is_ignored(self) -> None:
        # HTTP_PROXY/HTTPS_PROXY must not add unpinned proxy transports; a proxy
        # would dial the target itself and let a public URL be redirected onto an
        # internal host outside the pinned backend (GHSA-8wj7-v2w6-wfcx follow-up).
        with (
            patch.object(ssrf_guard.settings, "http_allow_private_urls", False),
            patch.dict(
                os.environ,
                {"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9"},
            ),
        ):
            client = get_guarded_http_client()
            self.assertFalse(getattr(client, "_mounts", None))
            backend = client._transport._pool._network_backend
            self.assertIsInstance(backend, _HttpEgressPinBackend)

    def test_install_refuses_proxy_mounts(self) -> None:
        # A client that carries proxy/mount transports must be refused fail-closed.
        with patch.object(ssrf_guard.settings, "http_allow_private_urls", False):
            client_with_proxy = httpx.Client(proxy="http://127.0.0.1:9")
            self.addCleanup(client_with_proxy.close)
            with self.assertRaises(RuntimeError):
                _install_egress_pin(client_with_proxy)


class HttpNodeIntegrationTests(unittest.TestCase):
    """The HTTP node handler refuses an internal target before dialing."""

    def setUp(self) -> None:
        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _ctx(self, curl: str):
        executor = MagicMock()
        executor.evaluate_message_template.side_effect = lambda text, *_a, **_k: text
        executor.parse_curl.return_value = ("GET", curl, {}, None, False)
        ctx = MagicMock()
        ctx.executor = executor
        ctx.node_id = "n1"
        ctx.inputs = {}
        ctx.node_data = {"curl": curl}
        return ctx

    def test_node_blocks_metadata_url(self) -> None:
        from app.services.node_execution.nodes import http_node

        with self.assertRaises(SsrfBlockedError):
            http_node.execute(self._ctx("http://169.254.169.254/latest/meta-data/"))


if __name__ == "__main__":
    unittest.main()
