"""Settings-free URL redaction shared by Heym and Heym Work.

Redacts secrets from URLs in log records (outgoing httpx requests, uvicorn access lines,
and application request logs) without altering non-sensitive parameters or paths.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from app.services.agent_tool_observability import _is_sensitive_key

_REDACTED = "[REDACTED]"
_URL_SENSITIVE_EXACT_KEYS = frozenset({"auth", "key", "session", "sig", "signature"})


def _is_sensitive_query_param(name: str) -> bool:
    norm = name.strip().lower().replace("-", "_")
    if norm in _URL_SENSITIVE_EXACT_KEYS:
        return True
    if norm.endswith("signature") or norm.endswith("_sig"):
        return True
    return _is_sensitive_key(name)


def _redact_query(query: str) -> str:
    if not query:
        return query
    pairs = query.split("&")
    new_pairs: list[str] = []
    for pair in pairs:
        if not pair:
            new_pairs.append(pair)
            continue
        if "=" in pair:
            k, v = pair.split("=", 1)
            if _is_sensitive_query_param(unquote(k)):
                new_pairs.append(f"{k}={_REDACTED}")
            else:
                new_pairs.append(pair)
        else:
            if _is_sensitive_query_param(unquote(pair)):
                new_pairs.append(f"{pair}={_REDACTED}")
            else:
                new_pairs.append(pair)
    return "&".join(new_pairs)


def _redact_path(hostname: str, path: str) -> str:
    if not path:
        return path

    # Slack: hooks.slack.com/services/...
    if ("slack.com" in hostname or "hooks.slack.com" in hostname) and path.startswith("/services/"):
        return f"/services/{_REDACTED}"

    # Telegram: /bot<token>/... or /bot<token>
    if "telegram" in hostname or re.search(r"/bot(?:\d+:[^/]+|[^/]*:[^/]+|\[REDACTED\])", path):
        path = re.sub(r"/bot[^/]+(?=/|$)", f"/bot{_REDACTED}", path)

    # Discord: /webhooks/<id>/<token>[/...]
    path = re.sub(r"(.*?/webhooks/[^/]+)/[^/]+(.*)", rf"\1/{_REDACTED}\2", path)

    # Heym capability routes:
    # /api/files/dl/{access_token}
    path = re.sub(r"^(/?(?:api/)?files/dl/)[^/]+(/.*)?$", rf"\1{_REDACTED}\2", path)
    # /api/codex/followups/{token}
    path = re.sub(r"^(/?(?:api/)?codex/followups/)[^/]+(/.*)?$", rf"\1{_REDACTED}\2", path)
    # /api/file-intake/u/{token}
    path = re.sub(r"^(/?(?:api/)?file-intake/u/)[^/]+(/.*)?$", rf"\1{_REDACTED}\2", path)
    # /review/{token} (backend alias for HITL review links)
    path = re.sub(r"^(/?(?:api/)?review/)[^/]+(/.*)?$", rf"\1{_REDACTED}\2", path)
    # /api/hitl/{token}
    m = re.match(r"^(/?(?:api/)?hitl/)([^/]+)(/.*)?$", path)
    if m:
        first_seg = m.group(2)
        if first_seg not in {"inbox", "sources"}:
            tail = m.group(3) or ""
            path = f"{m.group(1)}{_REDACTED}{tail}"

    return path


def redact_url(url: str) -> str:
    """Return the URL with secrets replaced by [REDACTED].

    Replaces:
    - Values of sensitive query parameters (key, session, sig, signature, api_key, token, auth, etc.)
    - User info (e.g. https://user:pass@host -> https://[REDACTED]@host)
    - Known secret path segments:
      - Telegram: /bot<token>/...
      - Slack: hooks.slack.com/services/...
      - Discord: /webhooks/<id>/<token>[/...]
      - Heym capability links: /api/files/dl/<token>, /api/hitl/<token>, /review/<token>,
        /api/codex/followups/<token>, /api/file-intake/u/<token>
    """
    if not url or not isinstance(url, str):
        return "" if url is None else str(url)
    try:
        parsed = urlsplit(url)
        netloc = parsed.netloc
        if "@" in netloc:
            _userinfo, host = netloc.rsplit("@", 1)
            netloc = f"{_REDACTED}@{host}"
        else:
            host = netloc

        hostname = (parsed.hostname or "").lower()
        path = _redact_path(hostname, parsed.path)
        query = _redact_query(parsed.query)

        return urlunsplit((parsed.scheme, netloc, path, query, parsed.fragment))
    except Exception:
        return url


class URLRedactionFilter(logging.Filter):
    """Logging filter that redacts secrets from URL arguments in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(self._redact_arg(arg) for arg in record.args)
            elif isinstance(record.args, list):
                record.args = [self._redact_arg(arg) for arg in record.args]
            elif isinstance(record.args, dict):
                record.args = {k: self._redact_arg(v) for k, v in record.args.items()}
            elif isinstance(record.args, str):
                record.args = redact_url(record.args)
        return True

    @staticmethod
    def _redact_arg(arg: Any) -> Any:
        if isinstance(arg, str):
            return redact_url(arg)
        if type(arg).__name__ == "URL" or (hasattr(arg, "scheme") and hasattr(arg, "netloc")):
            return redact_url(str(arg))
        return arg


def install_url_redaction_filters() -> None:
    """Attach the URL redaction filter to the httpx and uvicorn.access loggers."""
    filter_instance = URLRedactionFilter()
    for name in ("httpx", "uvicorn.access"):
        log = logging.getLogger(name)
        if not any(isinstance(f, URLRedactionFilter) for f in log.filters):
            log.addFilter(filter_instance)
