"""SSRF egress guard for outbound fetches the backend performs on a user URL.

Used by the HTTP workflow node (GHSA-8wj7-v2w6-wfcx) and the LLM image-edit
input loader (GHSA-6rph-qqcv-jqh4). Both send requests to URLs chosen by the
workflow author, or by the caller when the field is templated from input. On a
multi-tenant or hosted deployment those authors are not necessarily trusted, so
without a guard they can be pointed at loopback, private, link-local, or
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

# Prefixes the rejection messages so the operator sees the field they configured.
# The dial-time pin is shared by every caller of the guarded client, so it cannot
# attribute a hop to one node and uses the neutral subject instead.
_DEFAULT_URL_SUBJECT = "HTTP node URL"
_PINNED_DIAL_SUBJECT = "Guarded request URL"

# IPv6 forms that carry an IPv4 destination but that ``is_global`` still reports
# as globally routable, so the embedded address has to be checked instead.
_NAT64_WELL_KNOWN_PREFIX = ipaddress.ip_network("64:ff9b::/96")  # RFC 6052
_NAT64_LOCAL_USE_PREFIX = ipaddress.ip_network("64:ff9b:1::/48")  # RFC 8215
_IPV4_COMPATIBLE_PREFIX = ipaddress.ip_network("::/96")  # deprecated ::x.x.x.x

_GUARDED_CLIENT: httpx.Client | None = None
_GUARDED_CLIENT_LOCK = Lock()


class SsrfBlockedError(ValueError):
    """Raised when a target URL is refused by the SSRF egress guard."""


def _resolve_host_addresses(
    hostname: str,
    subject: str = _DEFAULT_URL_SUBJECT,
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
        raise SsrfBlockedError(f"{subject} host could not be resolved") from exc

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
        raise SsrfBlockedError(f"{subject} host could not be resolved")
    return addresses


def _embedded_ipv4(
    address: ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | None:
    """Return the IPv4 address carried inside an IPv6 transition address, if any.

    Only the forms ``is_global`` misjudges are unwrapped. It already refuses 6to4
    (``2002::/16``) and Teredo (``2001::/32``) wholesale, so those are left alone
    rather than re-admitted through their embedded IPv4. The NAT64 well-known
    prefix and the deprecated IPv4-compatible form are the gap: both are reported
    globally routable even when they carry loopback, private, or cloud-metadata
    IPv4 (GHSA-79qr-f49h-6g8c).
    """
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address in _NAT64_WELL_KNOWN_PREFIX or address in _IPV4_COMPATIBLE_PREFIX:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None


def _is_public_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Whether an address is globally routable (embedded IPv4 unwrapped first).

    ``is_global`` alone treats multicast (e.g. ``224.0.0.1``, ``239.255.255.250``)
    as public, so multicast is rejected explicitly, and it misjudges two IPv6
    transition forms, so those are decided by the IPv4 they carry.
    """
    if isinstance(address, ipaddress.IPv6Address):
        if address in _NAT64_LOCAL_USE_PREFIX:
            # Already private per RFC 8215, asserted here so a future change in
            # the stdlib classification cannot silently open a local-use range
            # whose embedded IPv4 offset depends on the deployed prefix length.
            return False
        embedded = _embedded_ipv4(address)
        if embedded is not None:
            address = embedded
    return address.is_global and not address.is_multicast


def guard_http_url(url: str, subject: str = _DEFAULT_URL_SUBJECT) -> None:
    """Reject user-supplied URLs that could reach internal networks (SSRF guard).

    Only ``http``/``https`` schemes are allowed. Unless
    ``HEYM_HTTP_ALLOW_PRIVATE_URLS=true``, the host must resolve exclusively to
    globally routable addresses; loopback, private, link-local (including the
    ``169.254.169.254`` cloud-metadata endpoint), multicast, and other non-public
    destinations are refused.

    ``subject`` names the field being guarded so the rejection message points at
    the node the operator actually configured.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
        raise SsrfBlockedError(f"{subject} must use http or https")

    if settings.http_allow_private_urls:
        return

    hostname = parsed.hostname
    if not hostname:
        raise SsrfBlockedError(f"{subject} must include a host")

    try:
        _ = parsed.port
    except ValueError as exc:
        raise SsrfBlockedError(f"{subject} includes an invalid port") from exc

    addresses = _resolve_host_addresses(hostname, subject)
    if not all(_is_public_address(address) for address in addresses):
        raise SsrfBlockedError(f"{subject} is not allowed (resolves to a non-public address)")


def _resolve_pinned_ip(host: str) -> str:
    """Resolve ``host`` and return a public IP to connect to, or raise.

    Every resolved address must be public; the returned literal is used as the
    actual TCP target so the connection cannot be rebound to an internal IP after
    validation (TLS SNI still uses the original hostname, so certs stay valid).
    """
    addresses = _resolve_host_addresses(host, _PINNED_DIAL_SUBJECT)
    if not all(_is_public_address(address) for address in addresses):
        raise SsrfBlockedError(
            f"{_PINNED_DIAL_SUBJECT} is not allowed (resolves to a non-public address)"
        )
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
        raise httpcore.ConnectError(
            "The guarded HTTP client does not allow unix-socket connections"
        )


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
            "SSRF egress pin refuses a client with proxy/mount transports "
            "(a proxy would bypass the pinned backend); build it with trust_env=False"
        )
    transport = getattr(client, "_transport", None)
    pool = getattr(transport, "_pool", None)
    backend = getattr(pool, "_network_backend", None)
    if pool is None or backend is None:
        raise RuntimeError("SSRF egress pin could not be installed (httpx internals unavailable)")
    if isinstance(backend, _HttpEgressPinBackend):
        return
    pool._network_backend = _HttpEgressPinBackend(backend)


def get_guarded_http_client() -> httpx.Client:
    """Return the shared guarded client with the SSRF egress pin installed.

    Kept separate from ``workflow_executor.get_http_client`` so the guard applies
    only where the backend dials a user-supplied URL (the HTTP node and the LLM
    image-edit input loader), not to integration nodes (crawler, Telegram, Slack,
    Discord) that legitimately reach operator-configured internal hosts. Carriers
    that fetch on our behalf, such as FlareSolverr and the Playwright runner, are
    deliberately out of scope: they resolve the target themselves, so their egress
    belongs to the deployment's network policy rather than to this guard.
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
