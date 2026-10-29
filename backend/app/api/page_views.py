"""Page views reported by the web app, recorded in the audit trail."""

from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.db.models import User
from app.services.audit_log import audit

router = APIRouter()

# Dashboard tabs live in the query (`/?tab=traces`), and a few views are addressed the same
# way, so these keys are the part of the URL that says which page the user is on. Everything
# else (OAuth `code`, `redirect`, error text) stays out of the log.
_KEPT_QUERY_KEYS = ("tab", "dashboard", "board", "suite", "workflowId", "traceId")
_MAX_QUERY_VALUE_LEN = 128

# The last path segment of these pages is a capability secret (see AGENTS.md, secret handling).
_TOKEN_PATH_PREFIXES = ("/review/", "/codex/followup/")
_TOKEN_PLACEHOLDER = ":token"


class PageViewRequest(BaseModel):
    """The route the user navigated to, as vue-router's ``fullPath`` (base path excluded)."""

    path: str = Field(min_length=1, max_length=2048)


def normalize_page_path(raw: str) -> str:
    """Reduce a client-reported URL to its audit-safe path.

    Keeps the path and the allowlisted query keys, drops the fragment and every other query
    parameter, and replaces capability tokens in the path. Raises ``ValueError`` when the
    value is not an in-app path.
    """
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw):
        raise ValueError("path contains control characters")
    if not raw.startswith("/") or raw.startswith("//"):
        raise ValueError("path must be an absolute in-app path")

    parts = urlsplit(raw)
    if parts.scheme or parts.netloc:
        raise ValueError("path must not carry a scheme or host")

    path = parts.path
    for prefix in _TOKEN_PATH_PREFIXES:
        if path.startswith(prefix):
            path = prefix + _TOKEN_PLACEHOLDER
            break

    query = dict(parse_qsl(parts.query, keep_blank_values=False))
    kept = [(key, query[key][:_MAX_QUERY_VALUE_LEN]) for key in _KEPT_QUERY_KEYS if query.get(key)]
    return f"{path}?{urlencode(kept, safe='/')}" if kept else path


@router.post("/page-view", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def record_page_view(
    body: PageViewRequest,
    current_user: User = Depends(get_current_user),
) -> Response:
    """Record that the signed-in user opened a page.

    The path is reported by the browser, so the line shows where a user says they went,
    not proof of what the server returned.
    """
    try:
        path = normalize_page_path(body.path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))

    audit(action="page.view", actor=current_user, path=path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
