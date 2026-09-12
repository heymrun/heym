"""SSRF egress guard for outbound fetches the backend performs on a user URL.

Used by workflow nodes and services that send requests to URLs chosen by a
workflow author or stored in a credential. On a multi-tenant or hosted deployment
those authors are not necessarily trusted, so without a guard they can be pointed
at loopback, private, link-local, or cloud-metadata endpoints (SSRF, CWE-918).
This mirrors the protection already applied to the MCP http(s)/SSE transports.

Two layers, matching the MCP guard:

* ``guard_http_url`` and ``guard_websocket_url`` are fast pre-connection checks:
  only the matching URL schemes are allowed, and the host must resolve
  exclusively to globally routable addresses.
* Guarded HTTP client factories and ``open_guarded_websocket`` re-check and pin
  the resolved IP at dial time, so a DNS-rebinding answer cannot bounce the real
  connection onto a private address after the pre-connection check passed. The
  guarded transports connect directly rather than trusting environment proxies.

Self-hosted operators who intentionally call internal hosts can opt out with
``HEYM_HTTP_ALLOW_PRIVATE_URLS=true``. The scheme check still applies even then;
only the non-public-address block is relaxed. The pin is installed fail-closed:
if httpx internals ever change shape the guarded client refuses to build rather
than silently sending unprotected requests.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections.abc import Callable
from threading import Lock
from typing import Any
from urllib.parse import urlparse

import httpcore
import httpx
import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import InvalidStatus

from app.config import settings
from app.http_identity import HEYM_USER_AGENT

_ALLOWED_URL_SCHEMES = ("http", "https")
_ALLOWED_WEBSOCKET_SCHEMES = ("ws", "wss")

# Prefixes the rejection messages so the operator sees the field they configured.
# The dial-time pin is shared by every caller of the guarded client, so it cannot
# attribute a hop to one node and uses the neutral subject instead.
_DEFAULT_URL_SUBJECT = "HTTP node URL"
_PINNED_DIAL_SUBJECT = "Guarded request URL"
_DEFAULT_WEBSOCKET_SUBJECT = "WebSocket node URL"
_CARRIER_DIAL_SUBJECT = "Guarded carrier URL"
_PRIVATE_URL_OPT_OUT_HINT = (
    " Set HEYM_HTTP_ALLOW_PRIVATE_URLS=true on a trusted self-hosted instance "
    "to permit internal targets."
)

# IPv6 forms that carry an IPv4 destination but that ``is_global`` still reports
# as globally routable, so the embedded address has to be checked instead.
_NAT64_WELL_KNOWN_PREFIX = ipaddress.ip_network("64:ff9b::/96")  # RFC 6052
_NAT64_LOCAL_USE_PREFIX = ipaddress.ip_network("64:ff9b:1::/48")  # RFC 8215
_IPV4_COMPATIBLE_PREFIX = ipaddress.ip_network("::/96")  # deprecated ::x.x.x.x

# Metadata endpoints refused by the carrier policy. Alibaba (100.100.100.200)
# and AWS IPv6 (fd00:ec2::254) sit outside the link-local ranges, so are listed.
_IPV4_LINK_LOCAL = ipaddress.ip_network("169.254.0.0/16")
_IPV6_LINK_LOCAL = ipaddress.ip_network("fe80::/10")
_IPV4_METADATA_ADDRESSES = frozenset({ipaddress.ip_address("100.100.100.200")})
_IPV6_METADATA_ADDRESSES = frozenset({ipaddress.ip_address("fd00:ec2::254")})

_GUARDED_CLIENT: httpx.Client | None = None
_GUARDED_CLIENT_LOCK = Lock()
_GUARDED_CARRIER_CLIENT: httpx.Client | None = None
_GUARDED_CARRIER_CLIENT_LOCK = Lock()

# Decides whether one resolved address may be dialed.
_AddressPolicy = Callable[[ipaddress.IPv4Address | ipaddress.IPv6Address], bool]


class _Deadline:
    """One connect budget split across the addresses a pinned dial may try."""

    def __init__(self, timeout: float | None) -> None:
        self._timeout = timeout
        self._start = time.monotonic()

    def remaining(self) -> float | None:
        if self._timeout is None:
            return None
        return max(0.0, self._timeout - (time.monotonic() - self._start))

    def share(self, attempts_left: int) -> float | None:
        # An unresponsive first address must not spend the whole budget, or the
        # working second address is never reached.
        remaining = self.remaining()
        if remaining is None:
            return None
        return remaining / max(1, attempts_left)

    def expired(self) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining <= 0.0


class SsrfBlockedError(ValueError):
    """Raised when a target URL is refused by the SSRF egress guard."""


class SsrfResolutionError(SsrfBlockedError):
    """Raised when a guarded target cannot currently be resolved."""


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
        raise SsrfResolutionError(f"{subject} host could not be resolved") from exc

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
        raise SsrfResolutionError(f"{subject} host could not be resolved")
    return addresses


def _embedded_ipv4(
    address: ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | None:
    """Return the IPv4 address carried inside an IPv6 transition address, if any.

    Only the NAT64 well-known prefix and the deprecated IPv4-compatible form are
    unwrapped. Both are reported globally routable even when they carry loopback,
    private, or cloud-metadata IPv4 (GHSA-79qr-f49h-6g8c). 6to4 and Teredo are
    refused outright by the caller instead, so they never reach this function.
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
    as public, so multicast is rejected explicitly, and it misjudges several IPv6
    transition forms, which are refused or decided by the IPv4 they carry.
    """
    if isinstance(address, ipaddress.IPv6Address):
        if address.sixtofour is not None or address.teredo is not None:
            # Refused outright rather than left to is_global. The stdlib only
            # began treating these as private in 3.11.10 (CVE-2024-4032) and the
            # project supports >=3.11, so on an older interpreter a 6to4 address
            # wrapping 169.254.169.254 is reported globally routable. Neither
            # relay is worth reaching, so the check does not depend on the
            # interpreter's classification.
            return False
        if address in _NAT64_LOCAL_USE_PREFIX:
            # Already private per RFC 8215, asserted here so a future change in
            # the stdlib classification cannot silently open a local-use range
            # whose embedded IPv4 offset depends on the deployed prefix length.
            return False
        embedded = _embedded_ipv4(address)
        if embedded is not None:
            address = embedded
    return address.is_global and not address.is_multicast


def _is_non_metadata_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Whether an address is outside the known instance-metadata endpoints.

    Deliberately weaker than :func:`_is_public_address`: loopback and private
    addresses pass, because carriers are normally deployed beside Heym. Refuses
    link-local, the listed metadata addresses, and the IPv6 transition forms
    that can carry one. A known-endpoint list, not a guarantee per provider.
    """
    if isinstance(address, ipaddress.IPv6Address):
        if address.sixtofour is not None or address.teredo is not None:
            return False
        if address in _IPV6_LINK_LOCAL or address in _IPV6_METADATA_ADDRESSES:
            return False
        if address in _NAT64_LOCAL_USE_PREFIX:
            return False
        embedded = _embedded_ipv4(address)
        if embedded is None:
            return True
        address = embedded
    return address not in _IPV4_LINK_LOCAL and address not in _IPV4_METADATA_ADDRESSES


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
    _guard_url(url, subject, _is_public_address, "resolves to a non-public address")


def guard_carrier_url(url: str, subject: str = _CARRIER_DIAL_SUBJECT) -> None:
    """Reject carrier endpoint URLs that would reach instance metadata.

    For endpoints the operator runs alongside Heym, where :func:`guard_http_url`
    would refuse the documented setup. Loopback and private addresses pass on
    purpose, so a workflow author can still reach other internal services this
    way; the deployment's network policy owns that boundary.
    """
    _guard_url(url, subject, _is_non_metadata_address, "resolves to a metadata address")


def _guard_url(
    url: str,
    subject: str,
    policy: _AddressPolicy,
    rejection: str,
) -> None:
    """Scheme, host, and resolved-address checks shared by the URL guards."""
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
    if not all(policy(address) for address in addresses):
        raise SsrfBlockedError(
            f"{subject} is not allowed ({rejection}).{_PRIVATE_URL_OPT_OUT_HINT}"
        )


def _resolve_pinned_addresses(
    host: str,
    policy: _AddressPolicy = _is_public_address,
    subject: str = _PINNED_DIAL_SUBJECT,
    rejection: str = "resolves to a non-public address",
) -> list[tuple[socket.AddressFamily, str]]:
    """Resolve ``host`` and return every address ``policy`` accepts for dialing.

    Every resolved address must pass. Returning all valid answers preserves
    normal IPv4/IPv6 fallback while ensuring every attempted TCP target is one of
    the addresses inspected by the guard.
    """
    addresses = _resolve_host_addresses(host, subject)
    if not all(policy(address) for address in addresses):
        raise SsrfBlockedError(
            f"{subject} is not allowed ({rejection}).{_PRIVATE_URL_OPT_OUT_HINT}"
        )
    return [
        (
            socket.AF_INET6 if isinstance(address, ipaddress.IPv6Address) else socket.AF_INET,
            address.compressed,
        )
        for address in addresses
    ]


class _HttpEgressPinBackend(httpcore.NetworkBackend):
    """Sync network backend that validates and pins the target IP at dial time.

    Wrapping the pool's backend means the anti-SSRF check runs against the IP the
    socket actually connects to (closing DNS rebinding), and re-runs for any
    redirect hop or new origin the client dials. Unix sockets are refused.

    ``policy`` decides which addresses may be dialed, so the carrier client
    pins under the narrower rule without a second backend implementation.
    """

    def __init__(
        self,
        inner: httpcore.NetworkBackend,
        policy: _AddressPolicy = _is_public_address,
        subject: str = _PINNED_DIAL_SUBJECT,
        rejection: str = "resolves to a non-public address",
    ) -> None:
        self._inner = inner
        self._policy = policy
        self._subject = subject
        self._rejection = rejection

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.NetworkStream:
        try:
            pinned = _resolve_pinned_addresses(host, self._policy, self._subject, self._rejection)
        except SsrfBlockedError as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        deadline = _Deadline(timeout)
        last: Exception | None = None
        for index, (_family, address) in enumerate(pinned):
            try:
                return self._inner.connect_tcp(
                    address,
                    port,
                    timeout=deadline.share(len(pinned) - index),
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:  # noqa: PERF203 - try the next validated address
                last = exc
                if deadline.expired():
                    break
        raise (
            last
            if last is not None
            else httpcore.ConnectError(f"{self._subject} could not be resolved to a usable address")
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


class _AsyncHttpEgressPinBackend(httpcore.AsyncNetworkBackend):
    """Async counterpart of :class:`_HttpEgressPinBackend`."""

    def __init__(
        self,
        inner: httpcore.AsyncNetworkBackend,
        policy: _AddressPolicy = _is_public_address,
        subject: str = _PINNED_DIAL_SUBJECT,
        rejection: str = "resolves to a non-public address",
    ) -> None:
        self._inner = inner
        self._policy = policy
        self._subject = subject
        self._rejection = rejection

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            pinned = await asyncio.to_thread(
                _resolve_pinned_addresses, host, self._policy, self._subject, self._rejection
            )
        except SsrfBlockedError as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        deadline = _Deadline(timeout)
        last: Exception | None = None
        for index, (_family, address) in enumerate(pinned):
            try:
                return await self._inner.connect_tcp(
                    address,
                    port,
                    timeout=deadline.share(len(pinned) - index),
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:  # noqa: PERF203 - try the next validated address
                last = exc
                if deadline.expired():
                    break
        raise (
            last
            if last is not None
            else httpcore.ConnectError(f"{self._subject} could not be resolved to a usable address")
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError(
            "The guarded HTTP client does not allow unix-socket connections"
        )


def _install_egress_pin(
    client: httpx.Client,
    policy: _AddressPolicy = _is_public_address,
    subject: str = _PINNED_DIAL_SUBJECT,
    rejection: str = "resolves to a non-public address",
) -> None:
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
    pool._network_backend = _HttpEgressPinBackend(backend, policy, subject, rejection)


def _install_async_egress_pin(
    client: httpx.AsyncClient,
    policy: _AddressPolicy = _is_public_address,
    subject: str = _PINNED_DIAL_SUBJECT,
    rejection: str = "resolves to a non-public address",
) -> None:
    """Install the fail-closed pinning backend on an async HTTP client."""
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
    if isinstance(backend, _AsyncHttpEgressPinBackend):
        return
    pool._network_backend = _AsyncHttpEgressPinBackend(backend, policy, subject, rejection)


def build_guarded_http_client(
    *,
    policy: _AddressPolicy = _is_public_address,
    pin_subject: str = _PINNED_DIAL_SUBJECT,
    pin_rejection: str = "resolves to a non-public address",
    **kwargs: Any,
) -> httpx.Client:
    """Build a sync HTTP client with the dial-time SSRF pin installed."""
    if not settings.http_allow_private_urls:
        kwargs["trust_env"] = False
        # Environment proxies must stay disabled because they can bypass the
        # pinned dial. Restore only the operator's CA bundle, which httpx would
        # otherwise discard together with proxy settings under trust_env=False.
        if "verify" not in kwargs:
            kwargs["verify"] = httpx.create_ssl_context(trust_env=True)
    client = httpx.Client(**kwargs)
    try:
        _install_egress_pin(client, policy, pin_subject, pin_rejection)
    except Exception:
        client.close()
        raise
    return client


async def build_guarded_async_http_client(
    *,
    policy: _AddressPolicy = _is_public_address,
    pin_subject: str = _PINNED_DIAL_SUBJECT,
    pin_rejection: str = "resolves to a non-public address",
    **kwargs: Any,
) -> httpx.AsyncClient:
    """Build an async HTTP client with the dial-time SSRF pin installed."""
    if not settings.http_allow_private_urls:
        kwargs["trust_env"] = False
        if "verify" not in kwargs:
            kwargs["verify"] = httpx.create_ssl_context(trust_env=True)
    client = httpx.AsyncClient(**kwargs)
    try:
        _install_async_egress_pin(client, policy, pin_subject, pin_rejection)
    except Exception:
        await client.aclose()
        raise
    return client


def get_guarded_http_client() -> httpx.Client:
    """Return the shared guarded client with the SSRF egress pin installed.

    Kept separate from ``workflow_executor.get_http_client`` so the guard applies
    only where the backend dials a user-controlled URL.

    For a carrier such as FlareSolverr the boundary runs through the middle: the
    address we dial to reach it is guarded (metadata-only, via
    :func:`get_guarded_carrier_http_client`), while the target it then resolves
    for us belongs to the deployment's network policy.
    """
    from app.services import workflow_executor as _wf

    global _GUARDED_CLIENT
    with _GUARDED_CLIENT_LOCK:
        if _GUARDED_CLIENT is None or _GUARDED_CLIENT.is_closed:
            limits = httpx.Limits(
                max_connections=_wf.HTTP_POOL_SIZE,
                max_keepalive_connections=_wf.HTTP_KEEPALIVE_CONNECTIONS,
            )
            # build_guarded_http_client disables env proxies while the guard is
            # on; an unpinned proxy transport would dial the target itself.
            client = build_guarded_http_client(
                limits=limits,
                timeout=_wf.HTTP_TIMEOUT,
                follow_redirects=False,
                headers={"User-Agent": HEYM_USER_AGENT},
            )
            _GUARDED_CLIENT = client
        return _GUARDED_CLIENT


def get_guarded_carrier_http_client() -> httpx.Client:
    """Return the shared carrier client, pinned under the metadata-only policy.

    Separate from :func:`get_guarded_http_client` because a shared pool would
    apply whichever of the two policies was installed first.
    """
    from app.services import workflow_executor as _wf

    global _GUARDED_CARRIER_CLIENT
    with _GUARDED_CARRIER_CLIENT_LOCK:
        if _GUARDED_CARRIER_CLIENT is None or _GUARDED_CARRIER_CLIENT.is_closed:
            limits = httpx.Limits(
                max_connections=_wf.HTTP_POOL_SIZE,
                max_keepalive_connections=_wf.HTTP_KEEPALIVE_CONNECTIONS,
            )
            _GUARDED_CARRIER_CLIENT = build_guarded_http_client(
                policy=_is_non_metadata_address,
                pin_subject=_CARRIER_DIAL_SUBJECT,
                pin_rejection="resolves to a metadata address",
                limits=limits,
                timeout=_wf.HTTP_TIMEOUT,
                follow_redirects=False,
                headers={"User-Agent": HEYM_USER_AGENT},
            )
        return _GUARDED_CARRIER_CLIENT


def close_guarded_carrier_http_client() -> None:
    """Close and drop the guarded carrier client (test/shutdown helper)."""
    global _GUARDED_CARRIER_CLIENT
    with _GUARDED_CARRIER_CLIENT_LOCK:
        if _GUARDED_CARRIER_CLIENT is not None and not _GUARDED_CARRIER_CLIENT.is_closed:
            _GUARDED_CARRIER_CLIENT.close()
        _GUARDED_CARRIER_CLIENT = None


def close_guarded_http_client() -> None:
    """Close and drop the guarded HTTP-node client (test/shutdown helper)."""
    global _GUARDED_CLIENT
    with _GUARDED_CLIENT_LOCK:
        if _GUARDED_CLIENT is not None and not _GUARDED_CLIENT.is_closed:
            _GUARDED_CLIENT.close()
        _GUARDED_CLIENT = None


# --- WebSocket egress -----------------------------------------------------
#
# ``guard_http_url`` admits http/https only and the pin above lives on an
# ``httpx.Client``, so neither reaches a ``websockets.connect`` dial. The two
# helpers below are the ws/wss counterparts, sharing this module's address
# policy rather than restating it.

# Handshake-steering headers. Unlike ``Authorization`` or ``Origin``, a
# caller-supplied value here rewrites the request target or the upgrade
# negotiation itself, so these are refused rather than forwarded. ``Origin`` is
# passed through the dedicated ``websockets.connect`` parameter by the shared
# WebSocket helpers.
_RESERVED_WEBSOCKET_HEADERS = frozenset({"host", "connection", "upgrade"})
_RESERVED_WEBSOCKET_HEADER_PREFIX = "sec-websocket-"


def guard_websocket_url(url: str, subject: str = _DEFAULT_WEBSOCKET_SUBJECT) -> None:
    """Reject user-supplied WebSocket URLs that could reach internal networks.

    The ``ws``/``wss`` counterpart of :func:`guard_http_url`: same address
    policy, same ``HEYM_HTTP_ALLOW_PRIVATE_URLS`` opt-out, different scheme
    set. A WebSocket handshake is an HTTP request carrying attacker-chosen
    headers, so the egress decision is the same one.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_WEBSOCKET_SCHEMES:
        raise SsrfBlockedError(f"{subject} must use ws or wss")

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
        raise SsrfBlockedError(
            f"{subject} is not allowed (resolves to a non-public address)."
            f"{_PRIVATE_URL_OPT_OUT_HINT}"
        )


def reject_reserved_websocket_headers(
    headers: dict[str, str] | None,
    subject: str = _DEFAULT_WEBSOCKET_SUBJECT,
) -> None:
    """Refuse caller-supplied headers that steer the handshake itself."""
    for name in headers or {}:
        lowered = str(name).strip().lower()
        if lowered in _RESERVED_WEBSOCKET_HEADERS or lowered.startswith(
            _RESERVED_WEBSOCKET_HEADER_PREFIX
        ):
            raise SsrfBlockedError(f"{subject} may not set the {name} header")


async def _open_pinned_websocket_socket(url: str) -> socket.socket:
    """Connect a socket to the validated public IP behind ``url``.

    Dialing the literal is what closes DNS rebinding: the address checked is
    the address connected to. TLS is unaffected because ``websockets`` defaults
    ``server_hostname`` to the URI host, so certificate verification and SNI
    still use the original name.

    Rejections here carry ``_PINNED_DIAL_SUBJECT`` rather than the caller's
    subject, for the reason already stated at the top of this module: the pin
    is shared and cannot attribute a hop to one node.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme.lower() == "wss" else 80)
    pinned_addresses = await asyncio.to_thread(_resolve_pinned_addresses, host)

    last_error: OSError | None = None
    for family, pinned in pinned_addresses:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setblocking(False)
        address: tuple[str, int] | tuple[str, int, int, int]
        address = (pinned, port, 0, 0) if family == socket.AF_INET6 else (pinned, port)
        try:
            await asyncio.get_running_loop().sock_connect(sock, address)
        except OSError as exc:
            sock.close()
            last_error = exc
            continue
        except BaseException:
            sock.close()
            raise
        return sock

    if last_error is not None:
        raise last_error
    raise SsrfResolutionError(f"{_PINNED_DIAL_SUBJECT} host could not be resolved")


def _is_redirect_error(exc: BaseException) -> bool:
    """Return whether ``exc`` represents a WebSocket HTTP redirect response."""
    candidate: BaseException | None = exc
    while candidate is not None:
        if isinstance(candidate, InvalidStatus):
            return candidate.response.status_code in {300, 301, 302, 303, 307, 308}
        candidate = candidate.__cause__
    return False


async def open_guarded_websocket(
    url: str,
    subject: str = _DEFAULT_WEBSOCKET_SUBJECT,
    **connect_kwargs: Any,
) -> ClientConnection:
    """Open an outbound WebSocket connection through the SSRF egress guard.

    Two layers, matching the HTTP side: ``guard_websocket_url`` is the
    pre-connection check, and the dial is pinned to the validated address so a
    rebinding answer cannot bounce the real connection onto a private host.

    ``proxy=None`` is passed while the guard is enabled for the same reason the
    guarded HTTP client is built ``trust_env=False``: ``websockets`` otherwise
    consults environment proxy variables, and a proxy would route around the
    pin. The private-URL opt-out preserves the library's normal proxy behavior.

    ``open_timeout`` covers the complete opening operation, including both DNS
    checks, TCP connect, TLS, and the WebSocket handshake. Redirects are refused
    while the guard is enabled because a caller-provided socket cannot be safely
    reused for a different target.

    The socket is owned here until the handshake succeeds. ``websockets``
    closes a caller-supplied socket on cancellation but *not* when the
    handshake fails or times out, which on the Trigger's reconnect loop would
    leak one descriptor per retry against a host that accepts TCP without
    speaking WebSocket. ``socket.close()`` is idempotent, so closing on every
    failure path is safe even where the library already did.
    """
    open_timeout_value = connect_kwargs.pop("open_timeout", 10)
    open_timeout = None if open_timeout_value is None else float(open_timeout_value)
    try:
        async with asyncio.timeout(open_timeout):
            await asyncio.to_thread(guard_websocket_url, url, subject)

            if settings.http_allow_private_urls:
                return await websockets.connect(url, open_timeout=None, **connect_kwargs)

            connect_kwargs.pop("proxy", None)
            sock = await _open_pinned_websocket_socket(url)
            handed_off = False
            try:
                try:
                    connection = await websockets.connect(
                        url,
                        sock=sock,
                        proxy=None,
                        open_timeout=None,
                        **connect_kwargs,
                    )
                except BaseException as exc:
                    if _is_redirect_error(exc):
                        raise SsrfBlockedError(
                            f"{subject} redirects are not allowed while the SSRF guard is enabled"
                        ) from exc
                    raise
                handed_off = True
                return connection
            finally:
                if not handed_off:
                    sock.close()
    except TimeoutError as exc:
        raise TimeoutError(
            f"{subject} timed out while resolving and opening the connection"
        ) from exc
