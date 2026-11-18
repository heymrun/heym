"""How an Outlook credential reaches an organization's own Exchange Server.

An Outlook Mail or Outlook Calendar credential signs in to a Microsoft account with OAuth
(Microsoft Graph, the default) or, with ``auth_mode: "ews"``, to an on-premises Exchange
Server with the user's domain sign-in over Exchange Web Services. Microsoft 365 mailboxes
always use Graph: Exchange Online is retiring EWS.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import dns.exception
import dns.resolver
from exchangelib import DELEGATE, Account, Configuration, Credentials, EWSTimeZone
from exchangelib import errors as ews
from exchangelib.protocol import FailFast

from app.services.outlook_service import OutlookApiError
from app.services.ssrf_guard import SsrfBlockedError, guard_http_url

AUTH_MODE_EWS = "ews"
EWS_PATH = "/EWS/Exchange.asmx"
LABEL = "Exchange Server"
_DNS_TIMEOUT_SECONDS = 5
_HOST = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*(?::\d{1,5})?$"
)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Exchange Online answers EWS too until it is switched off; its mailboxes belong on Graph.
_EXCHANGE_ONLINE_HOSTS = ("outlook.office365.com", "outlook.office.com", "outlook.live.com")

# At DEBUG these log NTLM responses (crackable offline) and whole EWS bodies (mail content).
for _library in ("exchangelib", "spnego", "requests_ntlm"):
    logging.getLogger(_library).setLevel(logging.WARNING)


def is_ews(config: dict[str, Any]) -> bool:
    """Whether an Outlook credential signs in to Exchange Server rather than with OAuth."""
    return str(config.get("auth_mode") or "").strip() == AUTH_MODE_EWS


@dataclass(frozen=True)
class EwsSettings:
    """The sign-in an Outlook credential holds in Exchange Server mode."""

    email: str
    username: str
    password: str
    server: str


def ews_settings(config: dict[str, Any]) -> EwsSettings:
    """Read the Exchange Server fields of a credential config.

    A blank user name signs in with the email address, as Outlook on the web allows.
    """
    email = str(config.get("ews_email") or "").strip().lower()
    return EwsSettings(
        email=email,
        username=str(config.get("ews_username") or "").strip() or email,
        password=str(config.get("ews_password") or ""),
        server=str(config.get("ews_server") or "").strip(),
    )


def _server_url(server: str) -> str:
    """``https://host[:port]/EWS/Exchange.asmx`` from a host or an https EWS address."""
    value = server.strip().rstrip("/")
    if "://" in value:
        parsed = urlparse(value)
        if parsed.scheme.lower() != "https":
            raise ValueError("Exchange server must use https")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("Enter the Exchange server as a host name, such as mail.contoso.com")
        if parsed.path and parsed.path.lower() not in ("", EWS_PATH.lower()):
            raise ValueError(f"Exchange server address must end with {EWS_PATH}")
        value = parsed.netloc
    if not _HOST.match(value):
        raise ValueError("Enter the Exchange server as a host name, such as mail.contoso.com")
    host = value.rsplit(":", 1)[0].lower() if value.count(":") == 1 else value.lower()
    if host in _EXCHANGE_ONLINE_HOSTS:
        raise ValueError("Microsoft 365 mailboxes connect with the Microsoft account option")
    return f"https://{value}{EWS_PATH}"


def validation_problem(config: dict[str, Any]) -> str | None:
    """Why an Exchange Server sign-in cannot be saved, or None. No network is used."""
    settings = ews_settings(config)
    if not _EMAIL.match(settings.email):
        return "Exchange Server sign-in requires the mailbox's email address"
    if not settings.password:
        return "Exchange Server sign-in requires a password"
    if settings.server:
        try:
            _server_url(settings.server)
        except ValueError as exc:
            return str(exc)
    return None


def discover_server(email: str) -> str:
    """The Exchange host the domain's Autodiscover SRV record names."""
    domain = email.rpartition("@")[2].strip(".").lower()
    if not domain:
        raise ValueError("Enter the mailbox's email address")
    try:
        answers = dns.resolver.resolve(
            f"_autodiscover._tcp.{domain}", "SRV", lifetime=_DNS_TIMEOUT_SECONDS
        )
    except dns.exception.DNSException:
        answers = []
    records = sorted(answers, key=lambda record: (record.priority, -record.weight))
    for record in records:
        host = str(record.target).rstrip(".")
        if host:
            return host if record.port in (0, 443) else f"{host}:{record.port}"
    raise ValueError(f"No Exchange server found for {domain}; enter the server address")


def service_endpoint(settings: EwsSettings) -> str:
    """The EWS address to use, after the SSRF check every user-supplied address gets."""
    url = _server_url(settings.server or discover_server(settings.email))
    guard_http_url(url, "Exchange server")
    return url


def ews_account(config: dict[str, Any]) -> Account:
    """An exchangelib account for the credential's own mailbox; one request per call, no retry."""
    settings = ews_settings(config)
    problem = validation_problem(config)
    if problem:
        raise ValueError(problem)
    configuration = Configuration(
        credentials=Credentials(settings.username, settings.password),
        service_endpoint=service_endpoint(settings),
        retry_policy=FailFast(),
        max_connections=2,
    )
    return Account(
        primary_smtp_address=settings.email,
        config=configuration,
        autodiscover=False,
        access_type=DELEGATE,
        default_timezone=EWSTimeZone("UTC"),
    )


@contextmanager
def ews_errors(label: str = LABEL) -> Iterator[None]:
    """Turn exchangelib failures into OutlookApiError, keeping server text out of messages."""
    try:
        yield
    except OutlookApiError:
        raise
    except SsrfBlockedError as exc:
        raise OutlookApiError(400, f"{label}: {exc}") from exc
    except ews.UnauthorizedError as exc:
        raise OutlookApiError(
            401,
            f"{label}: sign-in failed; check the password, and enter the user name as on "
            "Outlook on the web (the email address or DOMAIN\\user, for example CONTOSO\\jane)",
        ) from exc
    except (ews.ErrorAccessDenied, ews.ErrorSendAsDenied) as exc:
        raise OutlookApiError(403, f"{label}: access denied for this mailbox") from exc
    except (ews.ErrorItemNotFound, ews.ErrorFolderNotFound, ews.ErrorInvalidIdMalformed) as exc:
        raise OutlookApiError(404, f"{label}: not found") from exc
    except (ews.ErrorNonExistentMailbox, ews.ErrorInvalidSmtpAddress) as exc:
        raise OutlookApiError(400, f"{label}: no mailbox found for this address") from exc
    except (ews.ErrorServerBusy, ews.RateLimitError) as exc:
        raise OutlookApiError(429, f"{label}: the server is busy; retry later") from exc
    except (ews.TransportError, ews.RedirectError) as exc:
        raise OutlookApiError(502, f"{label}: the server could not be reached") from exc
    except ews.EWSError as exc:
        raise OutlookApiError(502, f"{label}: the server refused ({type(exc).__name__})") from exc
    except ValueError as exc:
        raise OutlookApiError(400, f"{label}: {exc}") from exc


def to_utc(value: datetime) -> datetime:
    """An EWS datetime as a stdlib UTC datetime; EWSDateTime.astimezone refuses stdlib zones."""
    return datetime.fromtimestamp(value.timestamp(), tz=timezone.utc)


def raise_failed(result: Any) -> Any:
    """exchangelib hands failed items back as exception objects; raise them instead."""
    if isinstance(result, Exception):
        raise result
    return result


def check_connection(config: dict[str, Any], *, calendar: bool = False) -> str:
    """Sign in and open the inbox (or calendar); return what the test reports on success."""
    with ews_errors():
        account = ews_account(config)
        folder = account.calendar if calendar else account.inbox
        folder.refresh()
        host = urlparse(account.protocol.service_endpoint).hostname or ""
    return f"Connected to {account.primary_smtp_address} on {host}"
