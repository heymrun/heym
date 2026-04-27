# BigQuery Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a BigQuery integration node to Heym with OAuth2 authentication, supporting `query` (SQL → rows) and `insertRows` (raw JSON array or selective key-value mappings) operations.

**Architecture:** New `CredentialType.bigquery` added to the DB enum with a dedicated OAuth2 route (`/api/credentials/bigquery/oauth/`) that mirrors the Google Sheets OAuth flow. A `BigQueryService` class wraps the BigQuery REST API v2 with auto-refreshing token logic. The workflow executor gets a new `elif node_type == "bigquery"` branch. The frontend PropertiesPanel gets a BigQuery UI block alongside the Google Sheets block. The heymweb landing page gets BigQuery added to the logo carousel, nodes section, and feature copy.

**Tech Stack:** Python 3.11 + FastAPI + httpx (sync) + SQLAlchemy sync session (executor pattern) · Vue 3 + TypeScript (strict) · BigQuery REST API v2 · Google OAuth2 · Alembic (Postgres enum migration) · Next.js 14 (heymweb)

---

## File Map

### New files (heymrun)
- `backend/app/services/bigquery_service.py` — `BigQueryService` class: token refresh + `run_query()` + `insert_rows()`
- `backend/app/api/bigquery_oauth.py` — OAuth2 authorize & callback routes for BigQuery
- `backend/alembic/versions/057_add_bigquery_credential_type.py` — Alembic migration
- `backend/tests/test_bigquery_node.py` — unit tests for the BigQuery executor branch and service

### Modified files (heymrun)
- `backend/app/db/models.py:26-41` — add `bigquery = "bigquery"` to `CredentialType`
- `backend/app/api/credentials.py:35-62, 649-744` — add `bigquery` to `get_masked_value()` and `validate_credential_config()`
- `backend/app/main.py:13-40` — import and register `bigquery_oauth` router
- `backend/app/services/workflow_executor.py` — add `elif node_type == "bigquery"` branch after the `googleSheets` block (~line 6586)
- `backend/app/services/workflow_dsl_prompt.py` — add BigQuery node DSL documentation
- `frontend/src/types/workflow.ts:115-147` — add `"bigquery"` to `NodeType` union
- `frontend/src/types/node.ts:18-550` — add `bigquery` entry to `NODE_DEFINITIONS`
- `frontend/src/components/Panels/PropertiesPanel.vue` — add BigQuery template section, credential ref, computed options, watcher

### Modified files (heymweb)
- `src/components/sections/LogoCarousel.tsx` — add BigQuery entry to `integrations` array + update `sr-only` text
- `src/components/sections/NodesSection.tsx` — add BigQuery to integrations list
- `src/app/page.tsx` — update `sr-only` SEO paragraph to mention BigQuery

---

## Task 1: DB model + Alembic migration

**Files:**
- Modify: `backend/app/db/models.py:41`
- Create: `backend/alembic/versions/057_add_bigquery_credential_type.py`

- [ ] **Step 1: Add `bigquery` to `CredentialType` enum in models.py**

In `backend/app/db/models.py`, find the `CredentialType` class and add the new value after `google_sheets`:

```python
class CredentialType(str, PyEnum):
    openai = "openai"
    google = "google"
    custom = "custom"
    bearer = "bearer"
    header = "header"
    slack = "slack"
    slack_trigger = "slack_trigger"
    smtp = "smtp"
    redis = "redis"
    qdrant = "qdrant"
    grist = "grist"
    rabbitmq = "rabbitmq"
    cohere = "cohere"
    flaresolverr = "flaresolverr"
    google_sheets = "google_sheets"
    bigquery = "bigquery"
```

- [ ] **Step 2: Create Alembic migration**

Create `backend/alembic/versions/057_add_bigquery_credential_type.py`:

```python
"""add bigquery credential type

Revision ID: 057
Revises: 056
Create Date: 2026-04-16
"""

from alembic import op

revision: str = "057"
down_revision: str = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'bigquery'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
```

- [ ] **Step 3: Run migration**

```bash
cd backend && uv run alembic upgrade head
```

Expected: `Running upgrade 056 -> 057, add bigquery credential type`

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/057_add_bigquery_credential_type.py
git commit -m "feat: add bigquery credential type to DB enum"
```

---

## Task 2: BigQueryService

**Files:**
- Create: `backend/app/services/bigquery_service.py`

- [ ] **Step 1: Write the failing test for token refresh**

Create `backend/tests/test_bigquery_node.py`:

```python
"""Unit tests for BigQueryService and the BigQuery executor branch."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _make_config(expired: bool = False) -> dict:
    """Return a minimal BigQuery OAuth2 config dict."""
    if expired:
        expiry = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    else:
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    return {
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "access_token": "ya29.valid-token",
        "refresh_token": "1//refresh-token",
        "token_expiry": expiry,
        "scope": "https://www.googleapis.com/auth/bigquery",
    }


class TestTokenRefresh(unittest.TestCase):
    def _make_service(self, expired: bool = False):
        from app.services.bigquery_service import BigQueryService

        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = MagicMock()
        return BigQueryService("cred-id-1", _make_config(expired=expired), fake_db)

    def test_valid_token_no_refresh_called(self) -> None:
        svc = self._make_service(expired=False)
        with patch("httpx.post") as mock_post:
            token = svc._get_valid_token()
        mock_post.assert_not_called()
        self.assertEqual(token, "ya29.valid-token")

    def test_expired_token_triggers_refresh(self) -> None:
        svc = self._make_service(expired=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "ya29.new-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response) as mock_post:
            token = svc._get_valid_token()
        mock_post.assert_called_once()
        call_data = mock_post.call_args[1]["data"]
        self.assertEqual(call_data["grant_type"], "refresh_token")
        self.assertEqual(call_data["refresh_token"], "1//refresh-token")
        self.assertEqual(token, "ya29.new-token")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_bigquery_node.py::TestTokenRefresh -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.bigquery_service'`

- [ ] **Step 3: Implement BigQueryService**

Create `backend/app/services/bigquery_service.py`:

```python
"""Google BigQuery REST API client with OAuth2 token management."""

from datetime import datetime, timedelta, timezone

import httpx

from app.services.encryption import encrypt_config

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_BQ_BASE = "https://bigquery.googleapis.com/bigquery/v2"
_BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"


class BigQueryService:
    """Sync BigQuery REST API v2 client.

    Manages token refresh and query / insertAll operations.
    Uses sync httpx + sync DB session to match the existing executor pattern.
    """

    def __init__(self, credential_id: str, config: dict, db) -> None:
        """Initialise with decrypted credential config and an open sync DB session."""
        self._credential_id = credential_id
        self._config = dict(config)
        self._db = db

    def _is_token_expired(self) -> bool:
        """Return True if the access token expires within 60 seconds."""
        expiry_str = self._config.get("token_expiry", "")
        if not expiry_str:
            return True
        try:
            expiry = datetime.fromisoformat(expiry_str)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) >= expiry - timedelta(seconds=60)
        except ValueError:
            return True

    def _refresh_token(self) -> None:
        """Exchange the refresh token for a new access token and persist to DB."""
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._config["refresh_token"],
                "client_id": self._config["client_id"],
                "client_secret": self._config["client_secret"],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._config["access_token"] = data["access_token"]
        self._config["token_expiry"] = (
            datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])
        ).isoformat()

        from app.db.models import Credential

        cred = self._db.query(Credential).filter(Credential.id == self._credential_id).first()
        if cred:
            cred.encrypted_config = encrypt_config(self._config)
            self._db.commit()

    def _get_valid_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        if self._is_token_expired():
            self._refresh_token()
        return self._config["access_token"]

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_valid_token()}"}

    def run_query(self, project_id: str, query: str, max_results: int = 1000) -> dict:
        """Run a synchronous BigQuery SQL query and return rows.

        Uses the jobs.query endpoint which blocks until complete (up to 10s timeout).
        Returns {rows, totalRows, schema, success}.
        """
        url = f"{_BQ_BASE}/projects/{project_id}/queries"
        body = {
            "query": query,
            "maxResults": max_results,
            "useLegacySql": False,
            "timeoutMs": 10000,
        }
        resp = httpx.post(url, headers=self._auth_headers(), json=body)
        resp.raise_for_status()
        data = resp.json()

        schema_fields = data.get("schema", {}).get("fields", [])
        schema = [{"name": f["name"], "type": f["type"]} for f in schema_fields]
        field_names = [f["name"] for f in schema_fields]

        raw_rows = data.get("rows", [])
        rows = []
        for raw_row in raw_rows:
            cells = raw_row.get("f", [])
            row = {field_names[i]: (cells[i]["v"] if i < len(cells) else None) for i in range(len(field_names))}
            rows.append(row)

        return {
            "rows": rows,
            "totalRows": int(data.get("totalRows", len(rows))),
            "schema": schema,
            "success": True,
        }

    def insert_rows(self, project_id: str, dataset_id: str, table_id: str, rows: list[dict]) -> dict:
        """Stream-insert rows into a BigQuery table using the tabledata.insertAll API.

        rows: list of dicts mapping column names to values.
        Returns {insertedCount, success}.
        """
        url = f"{_BQ_BASE}/projects/{project_id}/datasets/{dataset_id}/tables/{table_id}/insertAll"
        insert_rows = [{"insertId": str(i), "json": row} for i, row in enumerate(rows)]
        body = {"rows": insert_rows, "skipInvalidRows": False, "ignoreUnknownValues": False}
        resp = httpx.post(url, headers=self._auth_headers(), json=body)
        resp.raise_for_status()
        data = resp.json()

        insert_errors = data.get("insertErrors", [])
        if insert_errors:
            raise ValueError(f"BigQuery insertAll errors: {insert_errors}")

        return {"insertedCount": len(rows), "success": True}
```

- [ ] **Step 4: Run token refresh tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_bigquery_node.py::TestTokenRefresh -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/bigquery_service.py backend/tests/test_bigquery_node.py
git commit -m "feat: add BigQueryService with OAuth2 token refresh"
```

---

## Task 3: Test and validate BigQueryService operations

**Files:**
- Modify: `backend/tests/test_bigquery_node.py`

- [ ] **Step 1: Add query and insert tests to test_bigquery_node.py**

Append these test classes after `TestTokenRefresh`:

```python
class TestRunQuery(unittest.TestCase):
    def _make_service(self):
        from app.services.bigquery_service import BigQueryService

        fake_db = MagicMock()
        return BigQueryService("cred-id-1", _make_config(), fake_db)

    def test_run_query_returns_rows(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "schema": {"fields": [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "STRING"}]},
            "rows": [{"f": [{"v": "1"}, {"v": "Alice"}]}, {"f": [{"v": "2"}, {"v": "Bob"}]}],
            "totalRows": "2",
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response):
            result = svc.run_query("my-project", "SELECT id, name FROM dataset.users LIMIT 2")
        self.assertTrue(result["success"])
        self.assertEqual(result["totalRows"], 2)
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["rows"][0], {"id": "1", "name": "Alice"})
        self.assertEqual(result["schema"], [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "STRING"}])

    def test_run_query_empty_result(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "schema": {"fields": [{"name": "id", "type": "INTEGER"}]},
            "rows": [],
            "totalRows": "0",
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response):
            result = svc.run_query("my-project", "SELECT id FROM dataset.empty_table")
        self.assertTrue(result["success"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["totalRows"], 0)


class TestInsertRows(unittest.TestCase):
    def _make_service(self):
        from app.services.bigquery_service import BigQueryService

        fake_db = MagicMock()
        return BigQueryService("cred-id-1", _make_config(), fake_db)

    def test_insert_rows_success(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {}  # no insertErrors key = success
        mock_response.raise_for_status = MagicMock()
        rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = svc.insert_rows("my-project", "my-dataset", "users", rows)
        self.assertTrue(result["success"])
        self.assertEqual(result["insertedCount"], 2)
        call_body = mock_post.call_args[1]["json"]
        self.assertEqual(len(call_body["rows"]), 2)
        self.assertEqual(call_body["rows"][0]["json"], {"id": 1, "name": "Alice"})

    def test_insert_rows_api_error_raises(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "insertErrors": [{"index": 0, "errors": [{"reason": "invalid", "message": "bad value"}]}]
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response):
            with self.assertRaises(ValueError) as ctx:
                svc.insert_rows("my-project", "my-dataset", "users", [{"id": "bad"}])
        self.assertIn("insertAll errors", str(ctx.exception))
```

- [ ] **Step 2: Run all BigQueryService tests**

```bash
cd backend && uv run pytest tests/test_bigquery_node.py -v
```

Expected: PASS (6 tests)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_bigquery_node.py
git commit -m "test: add BigQueryService query and insert row tests"
```

---

## Task 4: OAuth2 route

**Files:**
- Create: `backend/app/api/bigquery_oauth.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create bigquery_oauth.py**

Create `backend/app/api/bigquery_oauth.py`:

```python
"""Google BigQuery OAuth2 authorization and callback endpoints."""

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db.models import Credential, CredentialType, User
from app.db.session import get_db
from app.services.encryption import decrypt_config, encrypt_config
from app.services.public_url import resolve_public_origin

router = APIRouter()

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"
_STATE_TYPE = "bq_oauth_state"
_STATE_TTL_MINUTES = 10


class AuthorizeRequest(BaseModel):
    credential_id: str


def create_oauth_state(
    user_id: str,
    credential_id: str | None,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> str:
    """Encode OAuth2 state as a signed JWT."""
    payload = {
        "user_id": user_id,
        "credential_id": credential_id,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "type": _STATE_TYPE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def handle_callback_state(state: str) -> dict | None:
    """Decode and validate the OAuth2 state JWT. Returns payload dict or None on failure."""
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != _STATE_TYPE:
            return None
        return payload
    except JWTError:
        return None


def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Build the Google OAuth2 authorization URL for BigQuery scope."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _BIGQUERY_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"


def _popup_html(success: bool, credential_id: str = "", message: str = "") -> str:
    """Return an HTML page that posts a message to the opener and closes."""
    if success:
        script = f"""
            if (window.opener) {{
                window.opener.postMessage(
                    {{type: 'google-oauth-success', credentialId: '{credential_id}'}},
                    '*'
                );
            }}
            window.close();
        """
    else:
        safe_msg = message.replace("'", "\\'").replace("\n", " ")
        script = f"""
            if (window.opener) {{
                window.opener.postMessage(
                    {{type: 'google-oauth-error', message: '{safe_msg}'}},
                    '*'
                );
            }}
            window.close();
        """
    return f"<html><body><script>{script}</script></body></html>"


@router.post("/authorize")
async def authorize(
    body: AuthorizeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the Google OAuth2 authorization URL for the BigQuery popup flow."""
    cred_uuid = uuid.UUID(body.credential_id)
    result = await db.execute(
        select(Credential).where(
            Credential.id == cred_uuid,
            Credential.owner_id == current_user.id,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    config = decrypt_config(credential.encrypted_config)
    client_id = config.get("client_id", "").strip()
    client_secret = config.get("client_secret", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential is missing client_id or client_secret",
        )

    redirect_uri = (
        resolve_public_origin(request).rstrip("/") + "/api/credentials/bigquery/oauth/callback"
    )
    state = create_oauth_state(
        user_id=str(current_user.id),
        credential_id=str(cred_uuid),
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    auth_url = build_auth_url(client_id, redirect_uri, state)
    return {"auth_url": auth_url, "state": state}


@router.get("/callback", response_class=HTMLResponse)
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Handle the Google OAuth2 callback, exchange code for tokens, persist credential."""
    if error or not code or not state:
        return HTMLResponse(_popup_html(False, message=error or "Authorization cancelled"))

    payload = handle_callback_state(state)
    if not payload:
        return HTMLResponse(_popup_html(False, message="Invalid or expired state"))

    redirect_uri = payload["redirect_uri"]
    client_id = payload["client_id"]
    client_secret = payload["client_secret"]
    user_id = uuid.UUID(payload["user_id"])
    credential_id = payload.get("credential_id")

    try:
        resp = httpx.post(
            _GOOGLE_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        token_data = resp.json()
    except Exception as exc:
        return HTMLResponse(_popup_html(False, message=f"Token exchange failed: {exc}"))

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)
    token_expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    config = {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expiry": token_expiry,
        "scope": _BIGQUERY_SCOPE,
    }
    encrypted = encrypt_config(config)

    if credential_id:
        cred_uuid = uuid.UUID(credential_id)
        result = await db.execute(select(Credential).where(Credential.id == cred_uuid))
        cred = result.scalar_one_or_none()
        if cred:
            cred.encrypted_config = encrypted
            await db.commit()
            return HTMLResponse(_popup_html(True, credential_id=str(cred.id)))

    new_cred = Credential(
        name="BigQuery",
        type=CredentialType.bigquery,
        owner_id=user_id,
        encrypted_config=encrypted,
    )
    db.add(new_cred)
    await db.commit()
    await db.refresh(new_cred)
    return HTMLResponse(_popup_html(True, credential_id=str(new_cred.id)))
```

- [ ] **Step 2: Register the router in main.py**

In `backend/app/main.py`, add the import alongside the other OAuth imports:

```python
from app.api import (
    agent_memory,
    ai_assistant,
    analytics,
    auth,
    bigquery_oauth,        # ← add this line
    config,
    credentials,
    data_tables,
    evals,
    expressions,
    files,
    folders,
    global_variables,
    google_sheets_oauth,
    hitl,
    logs,
    mcp,
    oauth,
    playwright,
    portal,
    skill_builder,
    slack,
    teams,
    templates,
    traces,
    vector_stores,
    workflows,
)
```

Then find where `google_sheets_oauth` router is registered and add the BigQuery router directly after it. Search for `google_sheets_oauth` in `main.py` to find the `include_router` call, then add:

```python
app.include_router(
    bigquery_oauth.router,
    prefix="/api/credentials/bigquery/oauth",
    tags=["bigquery-oauth"],
)
```

- [ ] **Step 3: Run ruff and verify no lint errors**

```bash
cd backend && uv run ruff check app/api/bigquery_oauth.py app/main.py && uv run ruff format app/api/bigquery_oauth.py app/main.py
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/bigquery_oauth.py backend/app/main.py
git commit -m "feat: add BigQuery OAuth2 route (authorize + callback)"
```

---

## Task 5: Credential API support

**Files:**
- Modify: `backend/app/api/credentials.py:35-62` (get_masked_value)
- Modify: `backend/app/api/credentials.py:649-744` (validate_credential_config)

- [ ] **Step 1: Add bigquery to get_masked_value()**

In `backend/app/api/credentials.py`, find `get_masked_value()` and add after the `google_sheets` block:

```python
    elif credential_type == CredentialType.bigquery:
        if config.get("refresh_token", "").strip():
            return "connected"
        client_id = config.get("client_id", "")
        return mask_api_key(client_id) if client_id else None
```

- [ ] **Step 2: Add bigquery to validate_credential_config()**

In `backend/app/api/credentials.py`, find `validate_credential_config()` and add after the `google_sheets` block:

```python
    elif credential_type == CredentialType.bigquery:
        if "client_id" not in config or not config["client_id"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="BigQuery credential requires client_id",
            )
        if "client_secret" not in config or not config["client_secret"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="BigQuery credential requires client_secret",
            )
```

- [ ] **Step 3: Run ruff**

```bash
cd backend && uv run ruff check app/api/credentials.py && uv run ruff format app/api/credentials.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/credentials.py
git commit -m "feat: add bigquery credential support to credentials API"
```

---

## Task 6: Workflow executor branch + executor unit tests

**Files:**
- Modify: `backend/app/services/workflow_executor.py` (after the `googleSheets` elif block, ~line 6586)
- Modify: `backend/tests/test_bigquery_node.py`

The executor tests use the same full-workflow pattern as `test_workflow_executor_branching.py`: build a minimal node/edge list, run `WorkflowExecutor(...).execute(...)`, inspect `result.status` and `result.node_results`.

- [ ] **Step 1: Write failing executor tests**

Append these classes to `backend/tests/test_bigquery_node.py` (add `import uuid` to the imports at the top if not already present):

```python
def _make_bq_workflow(bq_data: dict) -> tuple:
    """Build a minimal workflow: textInput → bigquery → output."""
    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "value": "hello", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "bq",
            "type": "bigquery",
            "position": {"x": 200, "y": 0},
            "data": {"label": "bqNode", **bq_data},
        },
        {
            "id": "out",
            "type": "output",
            "position": {"x": 400, "y": 0},
            "data": {"label": "out", "message": "$bqNode", "allowDownstream": False},
        },
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "bq"},
        {"id": "e2", "source": "bq", "target": "out"},
    ]
    return nodes, edges, {"text": "hello"}


class TestBigQueryExecutorBranch(unittest.TestCase):
    """Test the workflow executor BigQuery branch via full WorkflowExecutor.execute()."""

    def test_missing_credential_results_in_error(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_bq_workflow({"credentialId": "", "bqOperation": "query"})
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        self.assertEqual(result.status, "error")
        # The node result for "bqNode" should be in error state
        bq_result = next((r for r in result.node_results if r["node_label"] == "bqNode"), None)
        self.assertIsNotNone(bq_result)
        self.assertEqual(bq_result["status"], "error")
        self.assertIn("credential", bq_result.get("error", "").lower())

    def test_missing_operation_results_in_error(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_bq_workflow({"credentialId": "some-id", "bqOperation": ""})
        with patch("app.services.workflow_executor.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch(
                "app.services.workflow_executor.decrypt_config",
                return_value={"client_id": "x", "client_secret": "y"},
            ):
                executor = WorkflowExecutor(nodes=nodes, edges=edges)
                result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        self.assertEqual(result.status, "error")
        bq_result = next((r for r in result.node_results if r["node_label"] == "bqNode"), None)
        self.assertIsNotNone(bq_result)
        self.assertEqual(bq_result["status"], "error")
        self.assertIn("operation", bq_result.get("error", "").lower())

    def test_query_operation_calls_service(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_bq_workflow(
            {
                "credentialId": "cred-1",
                "bqOperation": "query",
                "bqProjectId": "my-project",
                "bqQuery": "SELECT 1",
                "bqMaxResults": "100",
            }
        )
        expected_output = {"rows": [{"val": "1"}], "totalRows": 1, "schema": [], "success": True}
        with patch("app.services.workflow_executor.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.workflow_executor.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.bigquery_service.BigQueryService.run_query",
                    return_value=expected_output,
                ) as mock_query:
                    executor = WorkflowExecutor(nodes=nodes, edges=edges)
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        mock_query.assert_called_once_with("my-project", "SELECT 1", 100)
        self.assertEqual(result.status, "success")

    def test_insert_rows_raw_mode(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_bq_workflow(
            {
                "credentialId": "cred-1",
                "bqOperation": "insertRows",
                "bqProjectId": "my-project",
                "bqDatasetId": "my-dataset",
                "bqTableId": "users",
                "bqRowsInputMode": "raw",
                "bqRows": '[{"id": 1, "name": "Alice"}]',
            }
        )
        expected_output = {"insertedCount": 1, "success": True}
        with patch("app.services.workflow_executor.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.workflow_executor.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.bigquery_service.BigQueryService.insert_rows",
                    return_value=expected_output,
                ) as mock_insert:
                    executor = WorkflowExecutor(nodes=nodes, edges=edges)
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        mock_insert.assert_called_once_with(
            "my-project", "my-dataset", "users", [{"id": 1, "name": "Alice"}]
        )
        self.assertEqual(result.status, "success")

    def test_insert_rows_selective_mode(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_bq_workflow(
            {
                "credentialId": "cred-1",
                "bqOperation": "insertRows",
                "bqProjectId": "my-project",
                "bqDatasetId": "my-dataset",
                "bqTableId": "users",
                "bqRowsInputMode": "selective",
                "bqMappings": [{"key": "name", "value": "Alice"}, {"key": "age", "value": "30"}],
            }
        )
        expected_output = {"insertedCount": 1, "success": True}
        with patch("app.services.workflow_executor.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.workflow_executor.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.bigquery_service.BigQueryService.insert_rows",
                    return_value=expected_output,
                ) as mock_insert:
                    executor = WorkflowExecutor(nodes=nodes, edges=edges)
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        mock_insert.assert_called_once_with(
            "my-project", "my-dataset", "users", [{"name": "Alice", "age": "30"}]
        )
        self.assertEqual(result.status, "success")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_bigquery_node.py::TestBigQueryExecutorBranch -v
```

Expected: FAIL — executor branch not yet implemented

- [ ] **Step 3: Add the BigQuery executor branch to workflow_executor.py**

In `backend/app/services/workflow_executor.py`, find the line:

```python
            elif node_type == "rabbitmq":
```

and insert this block immediately before it:

```python
            elif node_type == "bigquery":
                import json as _json

                from app.db.models import Credential
                from app.db.session import SessionLocal
                from app.services.bigquery_service import BigQueryService
                from app.services.encryption import decrypt_config

                credential_id = node_data.get("credentialId")
                if not credential_id:
                    raise ValueError("BigQuery node requires a credential")

                bq_config: dict = {}
                with SessionLocal() as db:
                    cred = db.query(Credential).filter(Credential.id == credential_id).first()
                    if cred:
                        bq_config = decrypt_config(cred.encrypted_config)

                if not bq_config:
                    raise ValueError("BigQuery credential not found or invalid")

                operation = node_data.get("bqOperation", "")
                if not operation:
                    raise ValueError("BigQuery node requires an operation")

                project_id = self.evaluate_message_template(
                    node_data.get("bqProjectId", ""), inputs, node_id
                ).strip()

                with SessionLocal() as db:
                    service = BigQueryService(credential_id, bq_config, db)

                    if operation == "query":
                        query = self.evaluate_message_template(
                            node_data.get("bqQuery", ""), inputs, node_id
                        )
                        _mr_raw = str(node_data.get("bqMaxResults", "1000") or "1000")
                        _mr_ev = self.evaluate_message_template(_mr_raw, inputs, node_id).strip()
                        try:
                            max_results = max(1, int(float(_mr_ev or "1000")))
                        except (ValueError, TypeError):
                            max_results = 1000
                        output = service.run_query(project_id, query, max_results)

                    elif operation == "insertRows":
                        dataset_id = self.evaluate_message_template(
                            node_data.get("bqDatasetId", ""), inputs, node_id
                        ).strip()
                        table_id = self.evaluate_message_template(
                            node_data.get("bqTableId", ""), inputs, node_id
                        ).strip()
                        input_mode = node_data.get("bqRowsInputMode", "raw")

                        if input_mode == "selective":
                            mappings = node_data.get("bqMappings", [])
                            row: dict = {}
                            for mapping in mappings:
                                key = mapping.get("key", "")
                                val = self.evaluate_message_template(
                                    str(mapping.get("value", "")), inputs, node_id
                                )
                                if key:
                                    row[key] = val
                            rows = [row]
                        else:
                            raw_rows = self.evaluate_message_template(
                                node_data.get("bqRows", "[]"), inputs, node_id
                            )
                            rows = _json.loads(raw_rows)

                        output = service.insert_rows(project_id, dataset_id, table_id, rows)

                    else:
                        raise ValueError(f"Unknown BigQuery operation: {operation}")
```

- [ ] **Step 4: Run all BigQuery tests**

```bash
cd backend && uv run pytest tests/test_bigquery_node.py -v
```

Expected: PASS (all 11 tests)

- [ ] **Step 5: Run full test suite**

```bash
cd backend && ./run_tests.sh
```

Expected: all tests pass

- [ ] **Step 6: Run ruff**

```bash
cd backend && uv run ruff check app/services/workflow_executor.py && uv run ruff format app/services/workflow_executor.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/workflow_executor.py backend/tests/test_bigquery_node.py
git commit -m "feat: add BigQuery executor branch (query + insertRows raw/selective)"
```

---

## Task 7: Workflow DSL update

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py`

- [ ] **Step 1: Add BigQuery node documentation to the DSL prompt**

In `backend/app/services/workflow_dsl_prompt.py`, find the section that documents the `googleSheets` node (search for `googleSheets` or `Google Sheets` in the file). Add the BigQuery node documentation in the same format, directly after the Google Sheets entry:

```
### bigquery
Run SQL queries or insert rows into Google BigQuery tables.
Requires a `bigquery` credential type configured with OAuth2 (client_id + client_secret, then OAuth connect).

**Operations:**
- `query` — run a SQL SELECT and get rows back
- `insertRows` — stream-insert rows into a table

**Fields (query):**
- `credentialId`: string — BigQuery credential ID
- `bqOperation`: "query"
- `bqProjectId`: string — GCP project ID (e.g. "my-gcp-project")
- `bqQuery`: string — Standard SQL query (e.g. `"SELECT id, name FROM \`project.dataset.table\` WHERE active = true LIMIT $input.limit"`)
- `bqMaxResults`: number — max rows to return (default 1000)

**Fields (insertRows — raw mode):**
- `credentialId`: string
- `bqOperation`: "insertRows"
- `bqProjectId`: string
- `bqDatasetId`: string — dataset ID (e.g. "analytics")
- `bqTableId`: string — table ID (e.g. "events")
- `bqRowsInputMode`: "raw"
- `bqRows`: string — JSON array of row objects (e.g. `"[$input]"`)

**Fields (insertRows — selective mode):**
- `credentialId`: string
- `bqOperation`: "insertRows"
- `bqProjectId`: string
- `bqDatasetId`: string
- `bqTableId`: string
- `bqRowsInputMode`: "selective"
- `bqMappings`: array of `{key, value}` — field-by-field mapping (e.g. `[{key: "user_id", value: "$input.userId"}, {key: "event", value: "page_view"}]`)

**Output (query):** `{rows: [...], totalRows: number, schema: [{name, type}], success: true}`
**Output (insertRows):** `{insertedCount: number, success: true}`
```

- [ ] **Step 2: Run ruff**

```bash
cd backend && uv run ruff check app/services/workflow_dsl_prompt.py && uv run ruff format app/services/workflow_dsl_prompt.py
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py
git commit -m "docs: add BigQuery node to workflow DSL prompt"
```

---

## Task 8: Frontend type definitions

**Files:**
- Modify: `frontend/src/types/workflow.ts:115-147`
- Modify: `frontend/src/types/node.ts`

- [ ] **Step 1: Add "bigquery" to NodeType union in workflow.ts**

In `frontend/src/types/workflow.ts`, find the `NodeType` union (starts around line 115) and add `"bigquery"` after `"googleSheets"`:

```typescript
export type NodeType =
  | "textInput"
  | "cron"
  | "llm"
  | "agent"
  | "condition"
  | "switch"
  | "execute"
  | "output"
  | "wait"
  | "http"
  | "sticky"
  | "merge"
  | "set"
  | "jsonOutputMapper"
  | "slack"
  | "sendEmail"
  | "errorHandler"
  | "variable"
  | "loop"
  | "disableNode"
  | "redis"
  | "rag"
  | "grist"
  | "googleSheets"
  | "bigquery"
  | "throwError"
  | "rabbitmq"
  | "crawler"
  | "consoleLog"
  | "playwright"
  | "dataTable"
  | "drive"
  | "slackTrigger";
```

- [ ] **Step 2: Add bigquery to NODE_DEFINITIONS in node.ts**

In `frontend/src/types/node.ts`, find the closing `};` of `NODE_DEFINITIONS` (after the `drive` entry) and add the `bigquery` entry before it:

```typescript
  bigquery: {
    type: "bigquery",
    label: "BigQuery",
    description: "Run SQL queries and insert rows into Google BigQuery",
    color: "node-google-sheets",
    icon: "Database",
    inputs: 1,
    outputs: 1,
    defaultData: {
      label: "bigquery",
      credentialId: "",
      bqOperation: undefined as string | undefined,
      bqProjectId: "",
      bqQuery: "",
      bqMaxResults: "1000",
      bqDatasetId: "",
      bqTableId: "",
      bqRowsInputMode: "raw",
      bqRows: "[]",
      bqMappings: [{ key: "field", value: "$input.text" }],
    },
  },
```

- [ ] **Step 3: Run typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/types/node.ts
git commit -m "feat: add bigquery NodeType and NODE_DEFINITIONS entry"
```

---

## Task 9: Frontend PropertiesPanel UI

**Files:**
- Modify: `frontend/src/components/Panels/PropertiesPanel.vue`

- [ ] **Step 1: Add bigquery credential ref and computed options in the script section**

In `PropertiesPanel.vue`, find where `googleSheetsCredentials` is declared (around line 312):

```typescript
const googleSheetsCredentials = ref<CredentialListItem[]>([]);
```

Add directly after it:

```typescript
const bigQueryCredentials = ref<CredentialListItem[]>([]);
```

Find `googleSheetsCredentialOptions` computed and add after it:

```typescript
const bigQueryCredentialOptions = computed(() =>
  bigQueryCredentials.value.map((c) => ({ label: c.name, value: c.id }))
);

const bigQueryOperationOptions = [
  { label: "Query", value: "query" },
  { label: "Insert Rows", value: "insertRows" },
];
```

- [ ] **Step 2: Add bigquery credential loading in the node type watcher**

Find the watcher that loads `googleSheetsCredentials` (around line 555):

```typescript
    if (type === "googleSheets") {
      try {
        googleSheetsCredentials.value = await credentialsApi.listByType("google_sheets");
      } catch {
        googleSheetsCredentials.value = [];
      }
    }
```

Add the BigQuery case directly after it:

```typescript
    if (type === "bigquery") {
      try {
        bigQueryCredentials.value = await credentialsApi.listByType("bigquery");
      } catch {
        bigQueryCredentials.value = [];
      }
    }
```

- [ ] **Step 3: Add BigQuery template section in the template**

In `PropertiesPanel.vue`, find the closing `</template>` of the `googleSheets` section (after line ~7750) and add the BigQuery section directly after it:

```html
          <template v-if="selectedNode.type === 'bigquery'">
            <div class="space-y-2">
              <Label>BigQuery Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="bigQueryCredentialOptions"
                :disabled="!isWorkflowOwner"
                @update:model-value="updateNodeData('credentialId', $event)"
              />
              <div v-if="!selectedNode.data.credentialId">
                <p class="text-xs text-amber-500 flex items-center gap-1">
                  <AlertTriangle class="h-3 w-3" />
                  Credential is required.
                </p>
                <p class="text-xs text-muted-foreground mt-1">
                  <a
                    href="/?tab=credentials"
                    class="text-primary hover:underline"
                    @click.prevent="$router.push('/?tab=credentials')"
                  >Add credentials</a> in Dashboard
                </p>
              </div>
            </div>

            <div class="space-y-2">
              <Label>Operation</Label>
              <Select
                :model-value="selectedNode.data.bqOperation || ''"
                :options="bigQueryOperationOptions"
                @update:model-value="updateNodeData('bqOperation', $event)"
              />
            </div>

            <template v-if="selectedNode.data.bqOperation">
              <div class="space-y-2">
                <Label>Project ID</Label>
                <ExpressionInput
                  :model-value="selectedNode.data.bqProjectId || ''"
                  placeholder="my-gcp-project"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Project ID"
                  @update:model-value="updateNodeData('bqProjectId', $event)"
                />
              </div>

              <!-- Query operation -->
              <template v-if="selectedNode.data.bqOperation === 'query'">
                <div class="space-y-2">
                  <Label>SQL Query</Label>
                  <ExpressionInput
                    :model-value="selectedNode.data.bqQuery || ''"
                    placeholder="SELECT * FROM `project.dataset.table` LIMIT 100"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    dialog-key-label="SQL Query"
                    @update:model-value="updateNodeData('bqQuery', $event)"
                  />
                </div>
                <div class="space-y-2">
                  <Label>Max Results</Label>
                  <input
                    type="number"
                    min="1"
                    :value="selectedNode.data.bqMaxResults ?? '1000'"
                    placeholder="1000"
                    class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    @input="updateNodeData('bqMaxResults', String(($event.target as HTMLInputElement).value))"
                  >
                </div>
              </template>

              <!-- InsertRows operation -->
              <template v-if="selectedNode.data.bqOperation === 'insertRows'">
                <div class="space-y-2">
                  <Label>Dataset ID</Label>
                  <ExpressionInput
                    :model-value="selectedNode.data.bqDatasetId || ''"
                    placeholder="my-dataset"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    dialog-key-label="Dataset ID"
                    @update:model-value="updateNodeData('bqDatasetId', $event)"
                  />
                </div>
                <div class="space-y-2">
                  <Label>Table ID</Label>
                  <ExpressionInput
                    :model-value="selectedNode.data.bqTableId || ''"
                    placeholder="my-table"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    dialog-key-label="Table ID"
                    @update:model-value="updateNodeData('bqTableId', $event)"
                  />
                </div>

                <div class="space-y-2">
                  <Label>Input Mode</Label>
                  <Select
                    :model-value="selectedNode.data.bqRowsInputMode || 'raw'"
                    :options="[{ label: 'Raw JSON', value: 'raw' }, { label: 'Selective (field mapping)', value: 'selective' }]"
                    @update:model-value="updateNodeData('bqRowsInputMode', $event)"
                  />
                </div>

                <!-- Raw mode: JSON array textarea -->
                <div
                  v-if="(selectedNode.data.bqRowsInputMode || 'raw') === 'raw'"
                  class="space-y-2"
                >
                  <Label>Rows (JSON array)</Label>
                  <ExpressionInput
                    :model-value="selectedNode.data.bqRows || '[]'"
                    placeholder='[{"column": "value"}]'
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    dialog-key-label="Rows JSON"
                    @update:model-value="updateNodeData('bqRows', $event)"
                  />
                </div>

                <!-- Selective mode: key-value mapping rows -->
                <template v-if="selectedNode.data.bqRowsInputMode === 'selective'">
                  <div class="space-y-2">
                    <Label>Field Mappings</Label>
                    <div
                      v-for="(mapping, index) in (selectedNode.data.bqMappings || [])"
                      :key="index"
                      class="flex gap-2 items-start"
                    >
                      <input
                        type="text"
                        :value="mapping.key"
                        placeholder="field"
                        class="flex h-9 w-1/3 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        @input="updateBqMapping(index, 'key', ($event.target as HTMLInputElement).value)"
                      >
                      <ExpressionInput
                        :model-value="mapping.value || ''"
                        placeholder="$input.field"
                        :nodes="workflowStore.nodes"
                        :node-results="workflowStore.nodeResults"
                        :edges="workflowStore.edges"
                        :current-node-id="selectedNode.id"
                        class="flex-1"
                        @update:model-value="updateBqMapping(index, 'value', $event)"
                      />
                      <button
                        class="h-9 px-2 text-muted-foreground hover:text-destructive transition-colors"
                        @click="removeBqMapping(index)"
                      >
                        <X class="h-4 w-4" />
                      </button>
                    </div>
                    <button
                      class="text-xs text-primary hover:underline"
                      @click="addBqMapping"
                    >
                      + Add field
                    </button>
                  </div>
                </template>
              </template>
            </template>
          </template>
```

- [ ] **Step 4: Add mapping helper functions in the script section**

In `PropertiesPanel.vue` script section, add these functions near the other helper functions (e.g. after the Google Sheets helper functions):

```typescript
function addBqMapping(): void {
  const mappings = [...(selectedNode.value?.data.bqMappings || [])];
  mappings.push({ key: "", value: "" });
  updateNodeData("bqMappings", mappings);
}

function removeBqMapping(index: number): void {
  const mappings = [...(selectedNode.value?.data.bqMappings || [])];
  mappings.splice(index, 1);
  updateNodeData("bqMappings", mappings);
}

function updateBqMapping(index: number, field: "key" | "value", value: string): void {
  const mappings = [...(selectedNode.value?.data.bqMappings || [])];
  mappings[index] = { ...mappings[index], [field]: value };
  updateNodeData("bqMappings", mappings);
}
```

- [ ] **Step 5: Run typecheck and lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Panels/PropertiesPanel.vue
git commit -m "feat: add BigQuery node UI panel in PropertiesPanel"
```

---

## Task 10: heymweb landing page updates

**Files (heymweb repo):**
- Modify: `src/components/sections/LogoCarousel.tsx`
- Modify: `src/components/sections/NodesSection.tsx`
- Modify: `src/app/page.tsx`

- [ ] **Step 1: Add BigQuery to LogoCarousel integrations array**

In `/Users/mbakgun/Projects/heym/heymweb/src/components/sections/LogoCarousel.tsx`, add the BigQuery entry to the `integrations` array after the `Google Sheets` entry:

```tsx
  {
    name: 'Google BigQuery',
    logo: (
      <svg viewBox="0 0 24 24" fill="currentColor" className="w-6 h-6">
        <path d="M11.39 0L0 6.573v10.855L11.39 24l11.39-6.572V6.573L11.39 0zm6.308 17.013l-1.842-1.851c.44-.736.697-1.595.697-2.513 0-2.7-2.184-4.888-4.878-4.888-2.694 0-4.878 2.188-4.878 4.888s2.184 4.888 4.878 4.888c.918 0 1.776-.257 2.51-.697l1.84 1.851-3.184 1.838-9.148-5.278V7.749l9.148-5.278 9.149 5.278v8.486l-4.292 2.778zm-6.023-1.851c-1.519 0-2.75-1.234-2.75-2.756s1.231-2.757 2.75-2.757 2.75 1.235 2.75 2.757-1.231 2.756-2.75 2.756z" />
      </svg>
    ),
  },
```

Also update the `sr-only` text at the bottom of `LogoCarousel.tsx` to include BigQuery:

```tsx
      <p className="sr-only">
        Heym integrates with OpenAI for GPT models, Ollama for local LLM inference, Slack for team notifications, Redis for caching and rate limiting, PostgreSQL for data storage, RabbitMQ for message queues, Qdrant for vector search and RAG, Docker for containerized deployment, Python and TypeScript for backend and frontend development, Grist for spreadsheet automation, Google Gemini for multimodal AI capabilities, Google Sheets for spreadsheet read and write automation, and Google BigQuery for cloud data warehouse SQL queries and row insertion.
      </p>
```

- [ ] **Step 2: Add BigQuery to NodesSection**

In `/Users/mbakgun/Projects/heym/heymweb/src/components/sections/NodesSection.tsx`, find the integrations array and add BigQuery after the Google Sheets entry:

```tsx
      { icon: Database, name: 'BigQuery', description: 'Run SQL queries against Google BigQuery data warehouses and stream-insert rows using OAuth2 credentials.' },
```

Make sure `Database` is imported from `lucide-react` at the top of the file (check existing imports and add if missing).

- [ ] **Step 3: Update page.tsx sr-only SEO text**

In `/Users/mbakgun/Projects/heym/heymweb/src/app/page.tsx`, find the `sr-only` paragraphs and add a mention of BigQuery alongside the existing integrations list. Find the paragraph that lists integration nodes and update it to include:

```
Google BigQuery for cloud data warehouse querying and row insertion via OAuth2,
```

- [ ] **Step 4: Build heymweb to verify no errors**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && bun run build
```

Expected: build succeeds

- [ ] **Step 5: Commit heymweb changes**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/components/sections/LogoCarousel.tsx src/components/sections/NodesSection.tsx src/app/page.tsx
git commit -m "feat: add Google BigQuery to landing page integrations, nodes section, and SEO copy"
```

---

## Task 11: Documentation (heym-documentation skill)

- [ ] **Step 1: Invoke heym-documentation skill**

Use the `heym-documentation` skill to create a BigQuery node reference page and update the integrations overview to list BigQuery. Pass the spec at `docs/superpowers/specs/2026-04-16-bigquery-node-design.md` as context.

---

## Task 12: Final verification

- [ ] **Step 1: Run full backend check**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && ./check.sh
```

Expected: ruff format (no changes), ruff lint (no errors), all tests pass

- [ ] **Step 2: Commit any ruff formatting diffs**

```bash
git add -u && git diff --staged --quiet || git commit -m "style: ruff format fixes"
```

- [ ] **Step 3: Run typecheck and lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors
