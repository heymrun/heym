"""SSRF egress guard for the HTTP workflow node (GHSA-8wj7-v2w6-wfcx).

The HTTP node sends requests to URLs chosen by the workflow author. On a
multi-tenant or hosted deployment those authors are not necessarily trusted, so
without a guard the node can be pointed at loopback, private, link-local, or
cloud-metadata endpoints (SSRF, CWE-918). This mirrors the protection already
applied to the MCP http(s)/SSE transports.

Two layers, matching the MCP guard:

* ``guard_http_url`` is a fast pre-connection check: only ``http``/``https`` are
  allowed, and the host must resolve exclusively to globally routable addresses.
* ``get_guarded_http_client`` returns a client whose network backend re-checks
  and pins the resolved IP at dial time, so a DNS-rebinding answer or a redirect
  to an internal host cannot bounce the real connection onto a private address
  after the pre-connection check passed. The client is built with
  ``trust_env=False`` so environment proxies cannot add unpinned proxy
  transports that would dial the target (and thus an internal redirect hop)
  outside the pinned backend.

Self-hosted operators who intentionally call internal hosts can opt out with
``HEYM_HTTP_ALLOW_PRIVATE_URLS=true``. The scheme check still applies even then;
only the non-public-address block is relaxed. The pin is installed fail-closed:
if httpx internals ever change shape the guarded client refuses to build rather
than silently sending unprotected requests.
"""

from __future__ import annotations

import ipaddress
import socket
from threading import Lock
from typing import Any
from urllib.parse import urlparse

import httpcore
import httpx

from app.config import settings
from app.http_identity import HEYM_USER_AGENT

_ALLOWED_URL_SCHEMES = ("http", "https")

_GUARDED_CLIENT: httpx.Client | None = None
_GUARDED_CLIENT_LOCK = Lock()


class SsrfBlockedError(ValueError):
    """Raised when a target URL is refused by the SSRF egress guard."""


def _resolve_host_addresses(
    hostname: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a URL host to every IP address it maps to.

    An IP literal resolves to itself; a DNS name is resolved via ``getaddrinfo``
    so all A/AAAA records are inspected (one safe-looking record is not enough to
    trust the host).
    """
    host = hostname.strip("[]")
    if "%" in host:
        host = host.split("%", 1)[0]

    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    try:
        resolved = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SsrfBlockedError("HTTP node URL host could not be resolved") from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for family, _, _, _, sockaddr in resolved:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        address = ipaddress.ip_address(sockaddr[0].split("%", 1)[0])
        key = address.compressed
        if key in seen:
            continue
        seen.add(key)
        addresses.append(address)

    if not addresses:
        raise SsrfBlockedError("HTTP node URL host could not be resolved")
    return addresses


def _is_public_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Whether an address is globally routable (IPv4-mapped IPv6 unwrapped first).

    ``is_global`` alone treats multicast (e.g. ``224.0.0.1``, ``239.255.255.250``)
    as public, so multicast is rejected explicitly.
    """
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def guard_http_url(url: str) -> None:
    """Reject HTTP node URLs that could reach internal networks (SSRF guard).

    Only ``http``/``https`` schemes are allowed. Unless
    ``HEYM_HTTP_ALLOW_PRIVATE_URLS=true``, the host must resolve exclusively to
    globally routable addresses; loopback, private, link-local (including the
    ``169.254.169.254`` cloud-metadata endpoint), multicast, and other non-public
    destinations are refused.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
        raise SsrfBlockedError("HTTP node URL must use http or https")

    if settings.http_allow_private_urls:
        return

    hostname = parsed.hostname
    if not hostname:
        raise SsrfBlockedError("HTTP node URL must include a host")

    try:
        _ = parsed.port
    except ValueError as exc:
        raise SsrfBlockedError("HTTP node URL includes an invalid port") from exc

    addresses = _resolve_host_addresses(hostname)
    if not all(_is_public_address(address) for address in addresses):
        raise SsrfBlockedError("HTTP node URL is not allowed (resolves to a non-public address)")


def _resolve_pinned_ip(host: str) -> str:
    """Resolve ``host`` and return a public IP to connect to, or raise.

    Every resolved address must be public; the returned literal is used as the
    actual TCP target so the connection cannot be rebound to an internal IP after
    validation (TLS SNI still uses the original hostname, so certs stay valid).
    """
    addresses = _resolve_host_addresses(host)
    if not all(_is_public_address(address) for address in addresses):
        raise SsrfBlockedError("HTTP node URL is not allowed (resolves to a non-public address)")
    return addresses[0].compressed


class _HttpEgressPinBackend(httpcore.NetworkBackend):
    """Sync network backend that validates and pins the target IP at dial time.

    Wrapping the pool's backend means the anti-SSRF check runs against the IP the
    socket actually connects to (closing DNS rebinding), and re-runs for any
    redirect hop or new origin the client dials. Unix sockets are refused.
    """

    def __init__(self, inner: httpcore.NetworkBackend) -> None:
        self._inner = inner

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.NetworkStream:
        try:
            pinned = _resolve_pinned_ip(host)
        except SsrfBlockedError as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        return self._inner.connect_tcp(
            pinned,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.NetworkStream:
        raise httpcore.ConnectError("HTTP node does not allow unix-socket connections")


class _AsyncHttpEgressPinBackend(httpcore.AsyncNetworkBackend):
    """Async counterpart used by integrations with operator-configured base URLs."""

    def __init__(self, inner: httpcore.AsyncNetworkBackend) -> None:
        self._inner = inner

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            pinned = _resolve_pinned_ip(host)
        except SsrfBlockedError as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        return await self._inner.connect_tcp(
            pinned,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("HTTP URL must not use a unix socket")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _install_egress_pin(client: httpx.Client) -> None:
    """Wrap a client's connection pool with the pinning egress backend.

    Fail-closed: if the private-URL opt-out is off and the httpx/httpcore pool
    internals are not the expected shape, raise instead of returning a client
    that would send unprotected requests. A client carrying proxy/mount
    transports is also refused, since a proxy dials the target itself and would
    route around the pinned backend (the client must be built with
    ``trust_env=False`` and no proxy).
    """
    if settings.http_allow_private_urls:
        return
    if getattr(client, "_mounts", None):
        raise RuntimeError(
            "HTTP node SSRF egress pin refuses a client with proxy/mount transports "
            "(a proxy would bypass the pinned backend); build it with trust_env=False"
        )
    transport = getattr(client, "_transport", None)
    pool = getattr(transport, "_pool", None)
    backend = getattr(pool, "_network_backend", None)
    if pool is None or backend is None:
        raise RuntimeError(
            "HTTP node SSRF egress pin could not be installed (httpx internals unavailable)"
        )
    if isinstance(backend, _HttpEgressPinBackend):
        return
    pool._network_backend = _HttpEgressPinBackend(backend)


def install_async_egress_pin(client: httpx.AsyncClient) -> None:
    """Install the same fail-closed dial-time SSRF guard on an async client."""
    if settings.http_allow_private_urls:
        return
    if getattr(client, "_mounts", None):
        raise RuntimeError(
            "HTTP SSRF egress pin refuses a client with proxy/mount transports "
            "(a proxy would bypass the pinned backend); build it with trust_env=False"
        )
    transport = getattr(client, "_transport", None)
    pool = getattr(transport, "_pool", None)
    backend = getattr(pool, "_network_backend", None)
    if pool is None or backend is None:
        raise RuntimeError(
            "HTTP SSRF egress pin could not be installed (httpx internals unavailable)"
        )
    if isinstance(backend, _AsyncHttpEgressPinBackend):
        return
    pool._network_backend = _AsyncHttpEgressPinBackend(backend)


def get_guarded_http_client() -> httpx.Client:
    """Return the shared HTTP-node client with the SSRF egress pin installed.

    Kept separate from ``workflow_executor.get_http_client`` so the guard applies
    only to the user-URL HTTP node, not to integration nodes (crawler, Telegram,
    Slack, Discord) that legitimately reach operator-configured internal hosts.
    """
    from app.services import workflow_executor as _wf

    global _GUARDED_CLIENT
    with _GUARDED_CLIENT_LOCK:
        if _GUARDED_CLIENT is None or _GUARDED_CLIENT.is_closed:
            limits = httpx.Limits(
                max_connections=_wf.HTTP_POOL_SIZE,
                max_keepalive_connections=_wf.HTTP_KEEPALIVE_CONNECTIONS,
            )
            # trust_env=False keeps the dial direct: env proxies (HTTP_PROXY /
            # HTTPS_PROXY) would otherwise add unpinned proxy transports that dial
            # the target themselves, so a public URL could be redirected onto an
            # internal host through the proxy. Direct connections keep the pinned
            # egress backend authoritative (matches the MCP guard).
            client = httpx.Client(
                limits=limits,
                timeout=_wf.HTTP_TIMEOUT,
                follow_redirects=False,
                headers={"User-Agent": HEYM_USER_AGENT},
                trust_env=False,
            )
            try:
                _install_egress_pin(client)
            except Exception:
                client.close()
                raise
            _GUARDED_CLIENT = client
        return _GUARDED_CLIENT


def close_guarded_http_client() -> None:
    """Close and drop the guarded HTTP-node client (test/shutdown helper)."""
    global _GUARDED_CLIENT
    with _GUARDED_CLIENT_LOCK:
        if _GUARDED_CLIENT is not None and not _GUARDED_CLIENT.is_closed:
            _GUARDED_CLIENT.close()
        _GUARDED_CLIENT = None
