# Google Drive Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `googleDrive` node to Heym with interactive popup OAuth2 and six operations — `listFolderFiles`, `downloadFile`, `syncToHeymDrive`, `updateFile`, `removeFile`, `removeFolder` — wired through the DSL, docs, and the heymweb marketing site.

**Architecture:** Mirrors the existing Google Sheets integration. A `GoogleDriveService` owns all Drive v3 HTTP calls and OAuth token refresh; a thin node handler resolves templated fields and dispatches to it; a dedicated OAuth router runs the popup consent flow. `syncToHeymDrive` reuses the Heym Drive storage helpers that `drive_node.py` already uses.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 + Alembic + httpx + pytest (backend); Vue 3 + TypeScript strict + Pinia (frontend); Next.js + Bun (heymweb).

**Spec:** `docs/superpowers/specs/2026-07-27-google-drive-node-design.md`

**Branch:** `impl/gdrive-node`. Do not push. Commit after every task.

---

## Background an implementer needs

**There are two unrelated "drive" concepts.** The existing `drive` node type is **Heym Drive** — internal file storage backed by the `GeneratedFile` table (`backend/app/services/node_execution/nodes/drive_node.py`). The node this plan adds is **`googleDrive`**. They only meet in `syncToHeymDrive`, which downloads from Google and stores into Heym Drive.

**Google-native files have no bytes.** Google Docs/Sheets/Slides are database records on Google's servers, not files. `GET /drive/v3/files/<id>?alt=media` returns `403 Only files with binary content can be downloaded`. To retrieve them you must call `GET /drive/v3/files/<id>/export?mimeType=<target>`, which makes Google render the document into a real format on the fly. This is why every download path in this plan branches on the MIME type.

**A folder is a file.** In Drive, a folder is a file whose `mimeType` is `application/vnd.google-apps.folder`. Nothing in the API stops you from deleting a folder through a "file" call. That is why `removeFile` and `removeFolder` both verify the target type first.

**The executor calls handlers synchronously.** Node handlers use sync `httpx` and sync `SessionLocal()`, not async. Follow that; do not introduce `async def` into the service or handler.

**Field values are templated.** Every user-facing field goes through `self.evaluate_message_template(value, inputs, node_id)` so `$input.foo` expressions work.

---

## File structure

**Created:**

| Path | Responsibility |
| --- | --- |
| `backend/alembic/versions/103_add_google_drive_cred_type.py` | Add `google_drive` to the `credential_type` PG enum |
| `backend/app/api/google_drive_oauth.py` | OAuth authorize + callback endpoints |
| `backend/app/services/google_drive_service.py` | Drive v3 client, token refresh, all six operations |
| `backend/app/services/node_execution/nodes/google_drive_node.py` | Thin handler: resolve fields → dispatch → return |
| `backend/tests/test_google_drive_service.py` | Service unit tests (mocked httpx) |
| `backend/tests/test_google_drive_node.py` | Handler unit tests (mocked service) |
| `backend/tests/test_google_drive_oauth.py` | OAuth state/callback tests |
| `frontend/src/components/Panels/propertiesPanel/nodes/GoogleDriveNodeProperties.vue` | All node config UI |
| `frontend/src/docs/content/nodes/google-drive-node.md` | Node documentation page |

**Modified:** `backend/app/db/models.py`, `backend/app/models/schemas.py`, `backend/app/api/credentials.py`, `backend/app/main.py`, `backend/app/services/node_execution/registry.py`, `backend/app/services/workflow_dsl_prompt.py`, `backend/app/api/ai_assistant.py`, plus the frontend/docs/heymweb files listed in their phases.

---

## Phase 1 — Credential type and OAuth

### Task 1: Add the `google_drive` credential type

**Files:**
- Modify: `backend/app/db/models.py:60`
- Modify: `backend/app/models/schemas.py:540`
- Create: `backend/alembic/versions/103_add_google_drive_cred_type.py`

- [ ] **Step 1: Add the enum member to the ORM model**

In `backend/app/db/models.py`, the `CredentialType` enum ends with `opencode = "opencode"` (line 60). Add one line after it:

```python
    opencode = "opencode"
    google_drive = "google_drive"
```

- [ ] **Step 2: Add the matching Pydantic enum member**

In `backend/app/models/schemas.py`, the credential type enum ends with `opencode = "opencode"` (line 540). Add the same line after it:

```python
    opencode = "opencode"
    google_drive = "google_drive"
```

- [ ] **Step 3: Create the migration**

The current sole Alembic head is `102_merge_user_ai_live_heads` (verified with `uv run alembic heads`). The Postgres enum type is named `credential_type`.

Create `backend/alembic/versions/103_add_google_drive_cred_type.py`:

```python
"""add google drive credential type

Revision ID: 103_add_google_drive_cred_type
Revises: 102_merge_user_ai_live_heads
Create Date: 2026-07-27 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "103_add_google_drive_cred_type"
down_revision: Union[str, None] = "102_merge_user_ai_live_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'google_drive'")


def downgrade() -> None:
    # Postgres cannot drop an enum value; downgrade is a no-op.
    pass
```

- [ ] **Step 4: Verify there is still a single head**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run alembic heads`
Expected: `103_add_google_drive_cred_type (head)` — exactly one line.

- [ ] **Step 5: Apply the migration**

Run: `docker-compose up -d postgres && cd backend && uv run alembic upgrade head`
Expected: no error; the enum value is added.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/app/models/schemas.py backend/alembic/versions/103_add_google_drive_cred_type.py
git commit -m "feat(credentials): add google_drive credential type"
```

---

### Task 2: Credential validation and summary

**Files:**
- Modify: `backend/app/api/credentials.py:210-213` (summary) and `:1586-1596` (validation)

- [ ] **Step 1: Add the summary branch**

`credentials.py` around line 210 has the `google_sheets` summary branch. Add an identical branch for `google_drive` directly after the `bigquery` branch (which ends near line 219):

```python
    elif credential_type == CredentialType.google_drive:
        if config.get("refresh_token", "").strip():
            return "connected"
        client_id = config.get("client_id", "")
        return mask_api_key(client_id) if client_id else None
```

This is what makes the dashboard show `connected` once OAuth completes rather than a masked client id.

- [ ] **Step 2: Add the validation branch**

Around line 1586 is the `google_sheets` validation branch. Add after the `bigquery` branch that follows it:

```python
    elif credential_type == CredentialType.google_drive:
        if "client_id" not in config or not config["client_id"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google Drive credential requires client_id",
            )
        if "client_secret" not in config or not config["client_secret"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google Drive credential requires client_secret",
            )
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "import app.api.credentials"`
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/credentials.py
git commit -m "feat(credentials): validate google_drive client_id and client_secret"
```

---

### Task 3: OAuth authorize and callback endpoints

**Files:**
- Create: `backend/app/api/google_drive_oauth.py`
- Modify: `backend/app/main.py:35` (import) and `:292` (router registration)
- Test: `backend/tests/test_google_drive_oauth.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_google_drive_oauth.py`:

```python
"""Tests for the Google Drive OAuth2 state helpers and URL builder."""

import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt

from app.api.google_drive_oauth import (
    _DRIVE_SCOPE,
    build_auth_url,
    create_oauth_state,
    handle_callback_state,
)
from app.config import settings


class TestGoogleDriveOAuthState(unittest.TestCase):
    def test_round_trip_state_preserves_payload(self) -> None:
        state = create_oauth_state(
            user_id="11111111-1111-1111-1111-111111111111",
            credential_id="22222222-2222-2222-2222-222222222222",
            client_id="client-abc",
            client_secret="secret-xyz",
            redirect_uri="https://app.example.com/api/credentials/google-drive/oauth/callback",
        )
        payload = handle_callback_state(state)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["user_id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(payload["credential_id"], "22222222-2222-2222-2222-222222222222")
        self.assertEqual(payload["client_id"], "client-abc")
        self.assertEqual(payload["client_secret"], "secret-xyz")
        self.assertEqual(payload["type"], "gd_oauth_state")

    def test_rejects_state_from_a_different_flow(self) -> None:
        """A Google Sheets state token must not authorize a Drive credential."""
        foreign = jwt.encode(
            {
                "user_id": "11111111-1111-1111-1111-111111111111",
                "type": "gs_oauth_state",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            },
            settings.secret_key,
            algorithm=settings.jwt_algorithm,
        )
        self.assertIsNone(handle_callback_state(foreign))

    def test_rejects_expired_state(self) -> None:
        expired = jwt.encode(
            {
                "user_id": "11111111-1111-1111-1111-111111111111",
                "type": "gd_oauth_state",
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            settings.secret_key,
            algorithm=settings.jwt_algorithm,
        )
        self.assertIsNone(handle_callback_state(expired))

    def test_rejects_tampered_state(self) -> None:
        forged = jwt.encode(
            {
                "user_id": "11111111-1111-1111-1111-111111111111",
                "type": "gd_oauth_state",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            },
            "not-the-real-secret-key-at-all-32b",
            algorithm=settings.jwt_algorithm,
        )
        self.assertIsNone(handle_callback_state(forged))


class TestGoogleDriveAuthUrl(unittest.TestCase):
    def test_requests_full_drive_scope_offline(self) -> None:
        url = build_auth_url(
            "client-abc",
            "https://app.example.com/api/credentials/google-drive/oauth/callback",
            "state-token",
        )
        query = parse_qs(urlparse(url).query)

        self.assertEqual(query["scope"], [_DRIVE_SCOPE])
        self.assertEqual(_DRIVE_SCOPE, "https://www.googleapis.com/auth/drive")
        # offline + consent guarantee a refresh_token is issued every time.
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["state"], ["state-token"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_oauth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.google_drive_oauth'`

- [ ] **Step 3: Create the OAuth router**

Create `backend/app/api/google_drive_oauth.py`. This is the Google Sheets router with the scope, state type, callback path, and credential type changed:

```python
"""Google Drive OAuth2 authorization and callback endpoints."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from jwt import InvalidTokenError
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
# Full Drive scope: the node lists, updates, and deletes files the user already
# owns, which the narrower drive.file scope cannot see.
_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
_STATE_TYPE = "gd_oauth_state"
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
    except InvalidTokenError:
        return None


def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Build the Google OAuth2 authorization URL."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _DRIVE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"


def _json_for_inline_script(payload: dict) -> str:
    """Serialize JSON for direct embedding in an inline script element."""
    return (
        json.dumps(payload)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def _popup_html(success: bool, credential_id: str = "", message: str = "") -> str:
    """Return an HTML page that posts a message to the opener and closes."""
    if success:
        payload = {"type": "google-oauth-success", "credentialId": credential_id}
    else:
        payload = {"type": "google-oauth-error", "message": message.replace("\n", " ")}

    script = f"""
        const message = {_json_for_inline_script(payload)};
        const targetOrigin = window.location.origin;
        if (window.opener) {{
            window.opener.postMessage(message, targetOrigin);
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
    """Return the Google OAuth2 authorization URL for the popup flow.

    Looks up the stored Google Drive credential to retrieve the client_id and
    client_secret, so the frontend only needs to pass the credential_id.
    """
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
        resolve_public_origin(request).rstrip("/") + "/api/credentials/google-drive/oauth/callback"
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
        "scope": _DRIVE_SCOPE,
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
        name="Google Drive",
        type=CredentialType.google_drive,
        owner_id=user_id,
        encrypted_config=encrypted,
    )
    db.add(new_cred)
    await db.commit()
    await db.refresh(new_cred)
    return HTMLResponse(_popup_html(True, credential_id=str(new_cred.id)))
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, the import block around line 35 lists `google_sheets_oauth,`. Add `google_drive_oauth,` immediately before it (imports are alphabetical: `google_drive` sorts before `google_sheets`).

Then, next to the `google_sheets_oauth` registration at line 291-295, add:

```python
app.include_router(
    google_drive_oauth.router,
    prefix="/api/credentials/google-drive/oauth",
    tags=["Google Drive OAuth"],
)
```

The prefix must be exactly `/api/credentials/google-drive/oauth` — it is what `resolve_public_origin(...) + "/api/credentials/google-drive/oauth/callback"` builds in `authorize`, and what the user registers in Google Cloud Console.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_oauth.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Verify the app still boots**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "from app.main import app; print(len(app.routes))"`
Expected: prints a route count, no exception.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/google_drive_oauth.py backend/app/main.py backend/tests/test_google_drive_oauth.py
git commit -m "feat(oauth): add Google Drive OAuth2 authorize and callback endpoints"
```

---

## Phase 2 — GoogleDriveService

### Task 4: Service skeleton — ID parsing and token refresh

**Files:**
- Create: `backend/app/services/google_drive_service.py`
- Test: `backend/tests/test_google_drive_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_google_drive_service.py`:

```python
"""Tests for GoogleDriveService."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services.google_drive_service import GoogleDriveService, parse_drive_id


class TestParseDriveId(unittest.TestCase):
    def test_extracts_id_from_file_url(self) -> None:
        self.assertEqual(
            parse_drive_id("https://drive.google.com/file/d/1AbC-dEf_2/view?usp=sharing"),
            "1AbC-dEf_2",
        )

    def test_extracts_id_from_folder_url(self) -> None:
        self.assertEqual(
            parse_drive_id("https://drive.google.com/drive/folders/1FolderXyz_9"),
            "1FolderXyz_9",
        )

    def test_extracts_id_from_docs_url(self) -> None:
        self.assertEqual(
            parse_drive_id("https://docs.google.com/document/d/1DocId_77/edit"),
            "1DocId_77",
        )

    def test_extracts_id_from_open_query_url(self) -> None:
        self.assertEqual(
            parse_drive_id("https://drive.google.com/open?id=1OpenId_5"),
            "1OpenId_5",
        )

    def test_passes_through_bare_id(self) -> None:
        self.assertEqual(parse_drive_id("  1BareId_3  "), "1BareId_3")


def _config(expiry: datetime | None) -> dict:
    return {
        "client_id": "cid",
        "client_secret": "csecret",
        "access_token": "old-token",
        "refresh_token": "rtoken",
        "token_expiry": expiry.isoformat() if expiry else "",
    }


class TestTokenRefresh(unittest.TestCase):
    def test_uses_existing_token_when_not_expired(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        service = GoogleDriveService("cred-1", _config(future), MagicMock())

        with patch("app.services.google_drive_service.httpx.post") as post:
            self.assertEqual(service._get_valid_token(), "old-token")
            post.assert_not_called()

    def test_refreshes_and_persists_when_expired(self) -> None:
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        db = MagicMock()
        cred_row = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = cred_row
        service = GoogleDriveService("cred-1", _config(past), db)

        response = MagicMock()
        response.json.return_value = {"access_token": "fresh-token", "expires_in": 3600}
        with patch("app.services.google_drive_service.httpx.post", return_value=response):
            self.assertEqual(service._get_valid_token(), "fresh-token")

        # The refreshed token must be written back, or every run re-refreshes.
        self.assertIsNotNone(cred_row.encrypted_config)
        db.commit.assert_called_once()

    def test_refreshes_when_expiry_missing(self) -> None:
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock()
        service = GoogleDriveService("cred-1", _config(None), db)

        response = MagicMock()
        response.json.return_value = {"access_token": "fresh-token", "expires_in": 3600}
        with patch("app.services.google_drive_service.httpx.post", return_value=response):
            self.assertEqual(service._get_valid_token(), "fresh-token")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.google_drive_service'`

- [ ] **Step 3: Create the service skeleton**

Create `backend/app/services/google_drive_service.py`:

```python
"""Google Drive API client with OAuth2 token management."""

import base64
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.services.encryption import encrypt_config

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DRIVE_BASE = "https://www.googleapis.com/drive/v3"
_DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"

FOLDER_MIME = "application/vnd.google-apps.folder"
_NATIVE_MIME_PREFIX = "application/vnd.google-apps."

# Drive caps pageSize at 1000.
_MAX_PAGE_SIZE = 1000

_ID_PATTERNS = (
    re.compile(r"/(?:file|document|spreadsheets|presentation)/d/([a-zA-Z0-9_-]+)"),
    re.compile(r"/folders/([a-zA-Z0-9_-]+)"),
    re.compile(r"[?&]id=([a-zA-Z0-9_-]+)"),
)

# Export targets for Google-native documents, which have no downloadable bytes.
EXPORT_FORMATS: dict[str, tuple[str, str]] = {
    "pdf": ("application/pdf", ".pdf"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "csv": ("text/csv", ".csv"),
    "txt": ("text/plain", ".txt"),
}

_DEFAULT_EXPORT_BY_NATIVE_MIME: dict[str, str] = {
    "application/vnd.google-apps.document": "pdf",
    "application/vnd.google-apps.spreadsheet": "xlsx",
    "application/vnd.google-apps.presentation": "pptx",
}


def parse_drive_id(id_or_url: str) -> str:
    """Return the Drive file/folder ID from a full URL or a bare ID string."""
    value = str(id_or_url or "").strip()
    for pattern in _ID_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group(1)
    return value


def is_native_google_file(mime_type: str) -> bool:
    """Return True for Google Docs/Sheets/Slides, which must be exported, not downloaded."""
    return str(mime_type or "").startswith(_NATIVE_MIME_PREFIX)


class GoogleDriveService:
    """Sync Google Drive v3 client.

    Manages token refresh and all Drive operations used by the googleDrive node.
    Uses sync httpx + a sync DB session to match the existing executor pattern.
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

    def _raise_for_drive_error(self, resp: httpx.Response, file_id: str) -> None:
        """Translate Drive API failures into actionable node errors."""
        if resp.status_code < 400:
            return
        if resp.status_code == 404:
            raise ValueError(
                f"Google Drive node: file '{file_id}' not found or not accessible "
                "with this credential"
            )
        if resp.status_code == 401:
            raise ValueError(
                "Google Drive node: credential is no longer authorized, reconnect it"
            )
        detail = ""
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except Exception:
            detail = resp.text[:200]
        raise ValueError(f"Google Drive node: Drive API error {resp.status_code}: {detail}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_service.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_drive_service.py backend/tests/test_google_drive_service.py
git commit -m "feat(drive): add GoogleDriveService with ID parsing and token refresh"
```

---

### Task 5: `list_folder_files`

**Files:**
- Modify: `backend/app/services/google_drive_service.py`
- Test: `backend/tests/test_google_drive_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_google_drive_service.py`, before the `if __name__` block:

```python
def _valid_service(db=None) -> GoogleDriveService:
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    return GoogleDriveService("cred-1", _config(future), db or MagicMock())


class TestListFolderFiles(unittest.TestCase):
    def test_builds_query_and_maps_fields(self) -> None:
        service = _valid_service()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "files": [
                {
                    "id": "f1",
                    "name": "report.pdf",
                    "mimeType": "application/pdf",
                    "size": "2048",
                    "modifiedTime": "2026-07-01T10:00:00.000Z",
                    "webViewLink": "https://drive.google.com/file/d/f1/view",
                },
                {
                    "id": "f2",
                    "name": "Subfolder",
                    "mimeType": "application/vnd.google-apps.folder",
                    "modifiedTime": "2026-07-02T10:00:00.000Z",
                    "webViewLink": "https://drive.google.com/drive/folders/f2",
                },
            ]
        }

        with patch("app.services.google_drive_service.httpx.get", return_value=response) as get:
            result = service.list_folder_files("folder-1", max_results=100)
            params = get.call_args.kwargs["params"]

        self.assertIn("'folder-1' in parents", params["q"])
        self.assertIn("trashed = false", params["q"])
        self.assertTrue(params["supportsAllDrives"])
        self.assertTrue(params["includeItemsFromAllDrives"])

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["files"][0]["size_bytes"], 2048)
        self.assertFalse(result["files"][0]["is_folder"])
        # Google-native entries and folders report no size.
        self.assertIsNone(result["files"][1]["size_bytes"])
        self.assertTrue(result["files"][1]["is_folder"])

    def test_defaults_to_root_when_folder_blank(self) -> None:
        service = _valid_service()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"files": []}

        with patch("app.services.google_drive_service.httpx.get", return_value=response) as get:
            result = service.list_folder_files("", max_results=10)
            params = get.call_args.kwargs["params"]

        self.assertIn("'root' in parents", params["q"])
        self.assertEqual(result["folder_id"], "root")

    def test_includes_trashed_when_requested(self) -> None:
        service = _valid_service()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"files": []}

        with patch("app.services.google_drive_service.httpx.get", return_value=response) as get:
            service.list_folder_files("folder-1", max_results=10, include_trashed=True)
            params = get.call_args.kwargs["params"]

        self.assertNotIn("trashed", params["q"])

    def test_appends_user_query(self) -> None:
        service = _valid_service()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"files": []}

        with patch("app.services.google_drive_service.httpx.get", return_value=response) as get:
            service.list_folder_files(
                "folder-1", max_results=10, query="mimeType='application/pdf'"
            )
            params = get.call_args.kwargs["params"]

        self.assertIn("mimeType='application/pdf'", params["q"])

    def test_pages_until_max_results_reached(self) -> None:
        service = _valid_service()
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = {
            "files": [{"id": f"f{i}", "name": f"n{i}", "mimeType": "text/plain"} for i in range(2)],
            "nextPageToken": "token-2",
        }
        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = {
            "files": [{"id": "f9", "name": "n9", "mimeType": "text/plain"}]
        }

        with patch(
            "app.services.google_drive_service.httpx.get", side_effect=[page1, page2]
        ) as get:
            result = service.list_folder_files("folder-1", max_results=3)

        self.assertEqual(get.call_count, 2)
        self.assertEqual(result["count"], 3)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["pageToken"], "token-2")

    def test_truncates_to_max_results(self) -> None:
        service = _valid_service()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "files": [{"id": f"f{i}", "name": f"n{i}", "mimeType": "text/plain"} for i in range(5)]
        }

        with patch("app.services.google_drive_service.httpx.get", return_value=response):
            result = service.list_folder_files("folder-1", max_results=2)

        self.assertEqual(result["count"], 2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_service.py::TestListFolderFiles -v`
Expected: FAIL — `AttributeError: 'GoogleDriveService' object has no attribute 'list_folder_files'`

- [ ] **Step 3: Implement `list_folder_files`**

Append to the `GoogleDriveService` class in `backend/app/services/google_drive_service.py`:

```python
    def list_folder_files(
        self,
        folder_id: str,
        max_results: int = 100,
        query: str = "",
        include_trashed: bool = False,
    ) -> dict:
        """List files inside a folder. Empty folder_id lists the Drive root."""
        target = parse_drive_id(folder_id) or "root"
        clauses = [f"'{target}' in parents"]
        if not include_trashed:
            clauses.append("trashed = false")
        extra = str(query or "").strip()
        if extra:
            clauses.append(f"({extra})")

        files: list[dict[str, Any]] = []
        page_token = ""
        while len(files) < max_results:
            remaining = max_results - len(files)
            params: dict[str, Any] = {
                "q": " and ".join(clauses),
                "pageSize": min(remaining, _MAX_PAGE_SIZE),
                "fields": (
                    "nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink)"
                ),
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            }
            if page_token:
                params["pageToken"] = page_token

            resp = httpx.get(f"{_DRIVE_BASE}/files", headers=self._auth_headers(), params=params)
            self._raise_for_drive_error(resp, target)
            data = resp.json()

            for entry in data.get("files", []):
                raw_size = entry.get("size")
                files.append(
                    {
                        "id": entry.get("id", ""),
                        "name": entry.get("name", ""),
                        "mime_type": entry.get("mimeType", ""),
                        # Folders and Google-native files report no size.
                        "size_bytes": int(raw_size) if raw_size is not None else None,
                        "modified_time": entry.get("modifiedTime", ""),
                        "web_view_link": entry.get("webViewLink", ""),
                        "is_folder": entry.get("mimeType", "") == FOLDER_MIME,
                    }
                )

            page_token = data.get("nextPageToken", "")
            if not page_token:
                break

        files = files[:max_results]
        return {
            "status": "success",
            "operation": "listFolderFiles",
            "folder_id": target,
            "count": len(files),
            "files": files,
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_service.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_drive_service.py backend/tests/test_google_drive_service.py
git commit -m "feat(drive): add list_folder_files with paging and query composition"
```

---

### Task 6: `get_file_metadata` and `download_file` (with export)

**Files:**
- Modify: `backend/app/services/google_drive_service.py`
- Test: `backend/tests/test_google_drive_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_google_drive_service.py`, before the `if __name__` block:

```python
def _meta_response(mime: str, name: str = "thing", size: str | None = "100") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    payload = {"id": "file-1", "name": name, "mimeType": mime, "parents": ["parent-1"]}
    if size is not None:
        payload["size"] = size
    resp.json.return_value = payload
    return resp


def _content_response(body: bytes) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.content = body
    return resp


class TestDownloadFile(unittest.TestCase):
    def test_binary_file_uses_alt_media(self) -> None:
        service = _valid_service()
        responses = [_meta_response("application/pdf", "report.pdf"), _content_response(b"PDFBYTES")]

        with patch(
            "app.services.google_drive_service.httpx.get", side_effect=responses
        ) as get:
            result = service.download_file("file-1")

        self.assertEqual(get.call_args_list[1].kwargs["params"], {"alt": "media", "supportsAllDrives": True})
        self.assertFalse(result["exported"])
        self.assertIsNone(result["export_format"])
        self.assertEqual(result["content"], b"PDFBYTES")
        self.assertEqual(result["filename"], "report.pdf")
        self.assertEqual(result["size_bytes"], 8)

    def test_google_doc_exports_to_pdf_by_default(self) -> None:
        service = _valid_service()
        responses = [
            _meta_response("application/vnd.google-apps.document", "Notes", size=None),
            _content_response(b"PDF"),
        ]

        with patch(
            "app.services.google_drive_service.httpx.get", side_effect=responses
        ) as get:
            result = service.download_file("file-1")

        # Native docs must go through /export, never alt=media.
        self.assertIn("/export", get.call_args_list[1].args[0])
        self.assertEqual(
            get.call_args_list[1].kwargs["params"]["mimeType"], "application/pdf"
        )
        self.assertTrue(result["exported"])
        self.assertEqual(result["export_format"], "pdf")
        # The extension is appended so downstream nodes see a usable filename.
        self.assertEqual(result["filename"], "Notes.pdf")

    def test_google_sheet_exports_to_xlsx_by_default(self) -> None:
        service = _valid_service()
        responses = [
            _meta_response("application/vnd.google-apps.spreadsheet", "Budget", size=None),
            _content_response(b"XLSX"),
        ]

        with patch("app.services.google_drive_service.httpx.get", side_effect=responses):
            result = service.download_file("file-1")

        self.assertEqual(result["export_format"], "xlsx")
        self.assertEqual(result["filename"], "Budget.xlsx")

    def test_google_slides_exports_to_pptx_by_default(self) -> None:
        service = _valid_service()
        responses = [
            _meta_response("application/vnd.google-apps.presentation", "Deck", size=None),
            _content_response(b"PPTX"),
        ]

        with patch("app.services.google_drive_service.httpx.get", side_effect=responses):
            result = service.download_file("file-1")

        self.assertEqual(result["export_format"], "pptx")
        self.assertEqual(result["filename"], "Deck.pptx")

    def test_export_format_override_is_honoured(self) -> None:
        service = _valid_service()
        responses = [
            _meta_response("application/vnd.google-apps.document", "Notes", size=None),
            _content_response(b"TXT"),
        ]

        with patch(
            "app.services.google_drive_service.httpx.get", side_effect=responses
        ) as get:
            result = service.download_file("file-1", export_format="txt")

        self.assertEqual(get.call_args_list[1].kwargs["params"]["mimeType"], "text/plain")
        self.assertEqual(result["filename"], "Notes.txt")

    def test_export_format_ignored_for_binary_file(self) -> None:
        service = _valid_service()
        responses = [
            _meta_response("application/pdf", "report.pdf"),
            _content_response(b"PDFBYTES"),
        ]

        with patch(
            "app.services.google_drive_service.httpx.get", side_effect=responses
        ) as get:
            result = service.download_file("file-1", export_format="txt")

        self.assertEqual(get.call_args_list[1].kwargs["params"]["alt"], "media")
        self.assertFalse(result["exported"])

    def test_unknown_export_format_raises(self) -> None:
        service = _valid_service()
        with patch(
            "app.services.google_drive_service.httpx.get",
            side_effect=[_meta_response("application/vnd.google-apps.document", "Notes", size=None)],
        ):
            with self.assertRaises(ValueError) as ctx:
                service.download_file("file-1", export_format="rtf")
        self.assertIn("rtf", str(ctx.exception))

    def test_download_of_folder_raises(self) -> None:
        service = _valid_service()
        with patch(
            "app.services.google_drive_service.httpx.get",
            side_effect=[_meta_response(
                "application/vnd.google-apps.folder", "Stuff", size=None
            )],
        ):
            with self.assertRaises(ValueError) as ctx:
                service.download_file("file-1")
        self.assertIn("folder", str(ctx.exception).lower())

    def test_oversized_download_raises(self) -> None:
        service = _valid_service()
        responses = [
            _meta_response("application/pdf", "big.pdf"),
            _content_response(b"x" * 2048),
        ]
        with patch("app.services.google_drive_service.httpx.get", side_effect=responses):
            with self.assertRaises(ValueError) as ctx:
                service.download_file("file-1", max_bytes=1024)
        self.assertIn("size limit", str(ctx.exception).lower())

    def test_missing_file_gives_actionable_error(self) -> None:
        service = _valid_service()
        missing = MagicMock()
        missing.status_code = 404
        missing.json.return_value = {"error": {"message": "File not found"}}

        with patch("app.services.google_drive_service.httpx.get", return_value=missing):
            with self.assertRaises(ValueError) as ctx:
                service.download_file("nope")
        self.assertIn("not found", str(ctx.exception))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_service.py::TestDownloadFile -v`
Expected: FAIL — `AttributeError: 'GoogleDriveService' object has no attribute 'download_file'`

- [ ] **Step 3: Implement metadata fetch and download**

Append to the `GoogleDriveService` class:

```python
    def get_file_metadata(self, file_id: str) -> dict:
        """Fetch id, name, mimeType, size, and parents for a file."""
        target = parse_drive_id(file_id)
        if not target:
            raise ValueError("Google Drive node: file ID is required")
        resp = httpx.get(
            f"{_DRIVE_BASE}/files/{target}",
            headers=self._auth_headers(),
            params={"fields": "id, name, mimeType, size, parents", "supportsAllDrives": True},
        )
        self._raise_for_drive_error(resp, target)
        return resp.json()

    def _resolve_export(self, mime_type: str, export_format: str) -> tuple[str, str, str]:
        """Return (format_key, export_mime, extension) for a Google-native file."""
        key = str(export_format or "").strip().lower()
        if not key:
            key = _DEFAULT_EXPORT_BY_NATIVE_MIME.get(mime_type, "pdf")
        if key not in EXPORT_FORMATS:
            supported = ", ".join(sorted(EXPORT_FORMATS))
            raise ValueError(
                f"Google Drive node: unsupported export format '{key}'. Supported: {supported}"
            )
        export_mime, extension = EXPORT_FORMATS[key]
        return key, export_mime, extension

    def download_file(
        self,
        file_id: str,
        export_format: str = "",
        max_bytes: int | None = None,
    ) -> dict:
        """Download a file's bytes, exporting Google-native documents automatically.

        Returns a dict with raw ``content`` bytes; callers decide how to encode it.
        """
        meta = self.get_file_metadata(file_id)
        target = meta.get("id", parse_drive_id(file_id))
        mime_type = meta.get("mimeType", "")
        filename = meta.get("name", target)

        if mime_type == FOLDER_MIME:
            raise ValueError(
                f"Google Drive node: '{filename}' is a folder and cannot be downloaded"
            )

        if is_native_google_file(mime_type):
            format_key, export_mime, extension = self._resolve_export(mime_type, export_format)
            resp = httpx.get(
                f"{_DRIVE_BASE}/files/{target}/export",
                headers=self._auth_headers(),
                params={"mimeType": export_mime, "supportsAllDrives": True},
            )
            self._raise_for_drive_error(resp, target)
            content = resp.content
            if not filename.lower().endswith(extension):
                filename = f"{filename}{extension}"
            out_mime = export_mime
            exported = True
        else:
            resp = httpx.get(
                f"{_DRIVE_BASE}/files/{target}",
                headers=self._auth_headers(),
                params={"alt": "media", "supportsAllDrives": True},
            )
            self._raise_for_drive_error(resp, target)
            content = resp.content
            out_mime = mime_type
            format_key = None
            exported = False

        if max_bytes is not None and len(content) > max_bytes:
            raise ValueError(
                f"Google Drive node: file exceeds size limit ({max_bytes // (1024 * 1024)} MB)"
            )

        return {
            "id": target,
            "filename": filename,
            "mime_type": out_mime,
            "size_bytes": len(content),
            "exported": exported,
            "export_format": format_key,
            "content": content,
        }

    def download_file_base64(
        self,
        file_id: str,
        export_format: str = "",
        max_bytes: int | None = None,
    ) -> dict:
        """Node-facing download: same as download_file but base64-encoded."""
        result = self.download_file(file_id, export_format=export_format, max_bytes=max_bytes)
        content = result.pop("content")
        return {
            "status": "success",
            "operation": "downloadFile",
            **result,
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_service.py -v`
Expected: PASS, 24 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_drive_service.py backend/tests/test_google_drive_service.py
git commit -m "feat(drive): add download with automatic Google-native export"
```

---

### Task 7: `update_file`

**Files:**
- Modify: `backend/app/services/google_drive_service.py`
- Test: `backend/tests/test_google_drive_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_google_drive_service.py`, before the `if __name__` block:

```python
class TestUpdateFile(unittest.TestCase):
    def test_requires_at_least_one_change(self) -> None:
        service = _valid_service()
        with self.assertRaises(ValueError) as ctx:
            service.update_file("file-1")
        self.assertIn("content, a new name, or a new parent", str(ctx.exception))

    def test_renames_via_metadata_patch(self) -> None:
        service = _valid_service()
        patched = MagicMock()
        patched.status_code = 200
        patched.json.return_value = {
            "id": "file-1",
            "name": "renamed.txt",
            "mimeType": "text/plain",
            "modifiedTime": "2026-07-27T10:00:00.000Z",
        }

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "old.txt"),
        ):
            with patch(
                "app.services.google_drive_service.httpx.patch", return_value=patched
            ) as do_patch:
                result = service.update_file("file-1", new_name="renamed.txt")

        self.assertEqual(do_patch.call_args.kwargs["json"], {"name": "renamed.txt"})
        self.assertEqual(result["updated"], ["name"])
        self.assertEqual(result["name"], "renamed.txt")

    def test_move_sends_add_and_remove_parents(self) -> None:
        service = _valid_service()
        patched = MagicMock()
        patched.status_code = 200
        patched.json.return_value = {
            "id": "file-1",
            "name": "thing",
            "mimeType": "text/plain",
            "modifiedTime": "2026-07-27T10:00:00.000Z",
        }

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "thing"),
        ):
            with patch(
                "app.services.google_drive_service.httpx.patch", return_value=patched
            ) as do_patch:
                result = service.update_file("file-1", new_parent_id="parent-2")

        params = do_patch.call_args.kwargs["params"]
        self.assertEqual(params["addParents"], "parent-2")
        # The old parent must be removed or the file ends up in both folders.
        self.assertEqual(params["removeParents"], "parent-1")
        self.assertEqual(result["updated"], ["parent"])

    def test_rename_and_move_share_one_patch(self) -> None:
        service = _valid_service()
        patched = MagicMock()
        patched.status_code = 200
        patched.json.return_value = {
            "id": "file-1",
            "name": "new.txt",
            "mimeType": "text/plain",
            "modifiedTime": "2026-07-27T10:00:00.000Z",
        }

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "old.txt"),
        ):
            with patch(
                "app.services.google_drive_service.httpx.patch", return_value=patched
            ) as do_patch:
                result = service.update_file(
                    "file-1", new_name="new.txt", new_parent_id="parent-2"
                )

        self.assertEqual(do_patch.call_count, 1)
        self.assertEqual(result["updated"], ["name", "parent"])

    def test_content_upload_uses_upload_endpoint(self) -> None:
        service = _valid_service()
        uploaded = MagicMock()
        uploaded.status_code = 200
        uploaded.json.return_value = {
            "id": "file-1",
            "name": "thing",
            "mimeType": "text/plain",
            "modifiedTime": "2026-07-27T10:00:00.000Z",
        }

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "thing"),
        ):
            with patch(
                "app.services.google_drive_service.httpx.patch", return_value=uploaded
            ) as do_patch:
                result = service.update_file("file-1", content=b"hello")

        self.assertIn("/upload/drive/v3/files/file-1", do_patch.call_args.args[0])
        self.assertEqual(do_patch.call_args.kwargs["params"]["uploadType"], "media")
        self.assertEqual(do_patch.call_args.kwargs["content"], b"hello")
        self.assertEqual(result["updated"], ["content"])

    def test_oversized_content_raises(self) -> None:
        service = _valid_service()
        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "thing"),
        ):
            with self.assertRaises(ValueError) as ctx:
                service.update_file("file-1", content=b"x" * 2048, max_bytes=1024)
        self.assertIn("size limit", str(ctx.exception).lower())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_service.py::TestUpdateFile -v`
Expected: FAIL — `AttributeError: 'GoogleDriveService' object has no attribute 'update_file'`

- [ ] **Step 3: Implement `update_file`**

Append to the `GoogleDriveService` class:

```python
    def update_file(
        self,
        file_id: str,
        content: bytes | None = None,
        new_name: str = "",
        new_parent_id: str = "",
        max_bytes: int | None = None,
    ) -> dict:
        """Update a file's content, name, and/or parent folder.

        Blank arguments are left untouched — this is an update, not a replace.
        """
        name = str(new_name or "").strip()
        parent = parse_drive_id(new_parent_id) if str(new_parent_id or "").strip() else ""
        if content is None and not name and not parent:
            raise ValueError(
                "Google Drive node: updateFile requires content, a new name, or a new parent"
            )
        if content is not None and max_bytes is not None and len(content) > max_bytes:
            raise ValueError(
                f"Google Drive node: content exceeds size limit ({max_bytes // (1024 * 1024)} MB)"
            )

        meta = self.get_file_metadata(file_id)
        target = meta.get("id", parse_drive_id(file_id))
        updated: list[str] = []
        latest = meta

        if content is not None:
            resp = httpx.patch(
                f"{_DRIVE_UPLOAD_BASE}/files/{target}",
                headers={
                    **self._auth_headers(),
                    "Content-Type": meta.get("mimeType", "application/octet-stream"),
                },
                params={"uploadType": "media", "supportsAllDrives": True},
                content=content,
            )
            self._raise_for_drive_error(resp, target)
            latest = resp.json()
            updated.append("content")

        if name or parent:
            body: dict[str, Any] = {}
            params: dict[str, Any] = {
                "fields": "id, name, mimeType, size, modifiedTime",
                "supportsAllDrives": True,
            }
            if name:
                body["name"] = name
                updated.append("name")
            if parent:
                params["addParents"] = parent
                params["removeParents"] = ",".join(meta.get("parents", []) or [])
                updated.append("parent")

            resp = httpx.patch(
                f"{_DRIVE_BASE}/files/{target}",
                headers=self._auth_headers(),
                params=params,
                json=body,
            )
            self._raise_for_drive_error(resp, target)
            latest = resp.json()

        raw_size = latest.get("size")
        return {
            "status": "success",
            "operation": "updateFile",
            "id": target,
            "name": latest.get("name", meta.get("name", "")),
            "mime_type": latest.get("mimeType", meta.get("mimeType", "")),
            "size_bytes": int(raw_size) if raw_size is not None else None,
            "modified_time": latest.get("modifiedTime", ""),
            "updated": updated,
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_service.py -v`
Expected: PASS, 30 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_drive_service.py backend/tests/test_google_drive_service.py
git commit -m "feat(drive): add update_file for content, rename, and move"
```

---

### Task 8: `remove_file` and `remove_folder`

**Files:**
- Modify: `backend/app/services/google_drive_service.py`
- Test: `backend/tests/test_google_drive_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_google_drive_service.py`, before the `if __name__` block:

```python
class TestRemove(unittest.TestCase):
    def test_remove_file_trashes_by_default(self) -> None:
        service = _valid_service()
        patched = MagicMock()
        patched.status_code = 200
        patched.json.return_value = {"id": "file-1", "name": "thing"}

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "thing"),
        ):
            with patch(
                "app.services.google_drive_service.httpx.patch", return_value=patched
            ) as do_patch:
                with patch("app.services.google_drive_service.httpx.delete") as do_delete:
                    result = service.remove_file("file-1")

        self.assertEqual(do_patch.call_args.kwargs["json"], {"trashed": True})
        do_delete.assert_not_called()
        self.assertEqual(result["deleted"], "trashed")

    def test_remove_file_permanent_uses_delete(self) -> None:
        service = _valid_service()
        deleted = MagicMock()
        deleted.status_code = 204

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "thing"),
        ):
            with patch(
                "app.services.google_drive_service.httpx.delete", return_value=deleted
            ) as do_delete:
                result = service.remove_file("file-1", permanent=True)

        do_delete.assert_called_once()
        self.assertEqual(result["deleted"], "permanent")

    def test_remove_file_rejects_a_folder(self) -> None:
        """A mistyped ID must not delete a folder through the file operation."""
        service = _valid_service()
        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response(
                "application/vnd.google-apps.folder", "Stuff", size=None
            ),
        ):
            with self.assertRaises(ValueError) as ctx:
                service.remove_file("folder-1")
        self.assertIn("is a folder", str(ctx.exception))

    def test_remove_folder_rejects_a_file(self) -> None:
        service = _valid_service()
        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "thing"),
        ):
            with self.assertRaises(ValueError) as ctx:
                service.remove_folder("file-1")
        self.assertIn("is not a folder", str(ctx.exception))

    def test_remove_folder_trashes_by_default(self) -> None:
        service = _valid_service()
        patched = MagicMock()
        patched.status_code = 200
        patched.json.return_value = {"id": "folder-1", "name": "Stuff"}

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response(
                "application/vnd.google-apps.folder", "Stuff", size=None
            ),
        ):
            with patch(
                "app.services.google_drive_service.httpx.patch", return_value=patched
            ) as do_patch:
                result = service.remove_folder("folder-1")

        self.assertEqual(do_patch.call_args.kwargs["json"], {"trashed": True})
        self.assertEqual(result["operation"], "removeFolder")
        self.assertEqual(result["deleted"], "trashed")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_service.py::TestRemove -v`
Expected: FAIL — `AttributeError: 'GoogleDriveService' object has no attribute 'remove_file'`

- [ ] **Step 3: Implement removal**

Append to the `GoogleDriveService` class:

```python
    def _remove(self, file_id: str, permanent: bool, operation: str) -> dict:
        """Trash or permanently delete a Drive item."""
        meta = self.get_file_metadata(file_id)
        target = meta.get("id", parse_drive_id(file_id))
        name = meta.get("name", "")

        if permanent:
            resp = httpx.delete(
                f"{_DRIVE_BASE}/files/{target}",
                headers=self._auth_headers(),
                params={"supportsAllDrives": True},
            )
            self._raise_for_drive_error(resp, target)
            mode = "permanent"
        else:
            resp = httpx.patch(
                f"{_DRIVE_BASE}/files/{target}",
                headers=self._auth_headers(),
                params={"fields": "id, name", "supportsAllDrives": True},
                json={"trashed": True},
            )
            self._raise_for_drive_error(resp, target)
            mode = "trashed"

        return {
            "status": "success",
            "operation": operation,
            "id": target,
            "name": name,
            "deleted": mode,
        }

    def remove_file(self, file_id: str, permanent: bool = False) -> dict:
        """Trash (default) or permanently delete a file. Refuses folders."""
        meta = self.get_file_metadata(file_id)
        if meta.get("mimeType") == FOLDER_MIME:
            raise ValueError(
                f"Google Drive node: '{meta.get('name', file_id)}' is a folder — "
                "use removeFolder instead"
            )
        return self._remove(file_id, permanent, "removeFile")

    def remove_folder(self, folder_id: str, permanent: bool = False) -> dict:
        """Trash (default) or permanently delete a folder and its contents. Refuses files."""
        meta = self.get_file_metadata(folder_id)
        if meta.get("mimeType") != FOLDER_MIME:
            raise ValueError(
                f"Google Drive node: '{meta.get('name', folder_id)}' is not a folder — "
                "use removeFile instead"
            )
        return self._remove(folder_id, permanent, "removeFolder")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_service.py -v`
Expected: PASS, 35 tests.

- [ ] **Step 5: Lint and format**

Run: `cd backend && uv run ruff format app/services/google_drive_service.py tests/test_google_drive_service.py && uv run ruff check app/services/google_drive_service.py tests/test_google_drive_service.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/google_drive_service.py backend/tests/test_google_drive_service.py
git commit -m "feat(drive): add remove_file and remove_folder with type guards"
```

---

## Phase 3 — Node handler

### Task 9: Handler for list, download, update, and remove

**Files:**
- Create: `backend/app/services/node_execution/nodes/google_drive_node.py`
- Modify: `backend/app/services/node_execution/registry.py:30`
- Test: `backend/tests/test_google_drive_node.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_google_drive_node.py`:

```python
"""Tests for the googleDrive node handler."""

import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext


def _ctx(node_data: dict) -> NodeExecutionContext:
    """Build a handler context.

    NodeExecutionContext is a frozen dataclass with nine required fields — all of
    them must be supplied even though the handler only reads four.
    """
    executor = MagicMock()
    executor.trace_user_id = "00000000-0000-0000-0000-000000000001"
    executor.workflow_id = "00000000-0000-0000-0000-0000000000ff"
    executor._base_url = "https://app.test"
    # The handler resolves every field through this; echo the raw value back.
    executor.evaluate_message_template.side_effect = lambda v, *_args, **_kw: str(v)
    executor._get_accessible_credential.return_value = MagicMock(encrypted_config="enc")
    node = {"id": "node-1", "type": "googleDrive", "data": node_data}
    return NodeExecutionContext(
        executor=executor,
        node_id="node-1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node=node,
        node_type="googleDrive",
        node_data=node_data,
        node_label=node_data.get("label", "GoogleDrive"),
    )


class GoogleDriveNodeTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MagicMock()
        self.patchers = [
            patch(
                "app.services.google_drive_service.GoogleDriveService",
                return_value=self.service,
            ),
            patch("app.db.session.SessionLocal"),
            patch("app.services.encryption.decrypt_config", return_value={"client_id": "cid"}),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self) -> None:
        for p in self.patchers:
            p.stop()


class TestValidation(GoogleDriveNodeTestBase):
    def test_missing_credential_raises(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        with self.assertRaises(ValueError) as ctx:
            google_drive_node.execute(_ctx({"gdOperation": "listFolderFiles"}))
        self.assertIn("credential", str(ctx.exception).lower())

    def test_missing_operation_raises(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        with self.assertRaises(ValueError) as ctx:
            google_drive_node.execute(_ctx({"credentialId": "cred-1"}))
        self.assertIn("operation", str(ctx.exception).lower())

    def test_unknown_operation_raises(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        with self.assertRaises(ValueError) as ctx:
            google_drive_node.execute(
                _ctx({"credentialId": "cred-1", "gdOperation": "teleport"})
            )
        self.assertIn("teleport", str(ctx.exception))


class TestOperationDispatch(GoogleDriveNodeTestBase):
    def test_list_folder_files_passes_parsed_fields(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.list_folder_files.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "listFolderFiles",
                    "gdFolderId": "folder-1",
                    "gdMaxResults": "25",
                    "gdQuery": "mimeType='application/pdf'",
                    "gdIncludeTrashed": True,
                }
            )
        )

        self.service.list_folder_files.assert_called_once_with(
            "folder-1",
            max_results=25,
            query="mimeType='application/pdf'",
            include_trashed=True,
        )

    def test_max_results_falls_back_on_bad_input(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.list_folder_files.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "listFolderFiles",
                    "gdMaxResults": "not-a-number",
                }
            )
        )
        self.assertEqual(self.service.list_folder_files.call_args.kwargs["max_results"], 100)

    def test_download_file_requires_file_id(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        with self.assertRaises(ValueError) as ctx:
            google_drive_node.execute(
                _ctx({"credentialId": "cred-1", "gdOperation": "downloadFile"})
            )
        self.assertIn("file ID is required", str(ctx.exception))

    def test_download_file_dispatches(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.download_file_base64.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "downloadFile",
                    "gdFileId": "file-1",
                    "gdExportFormat": "pdf",
                }
            )
        )
        self.assertEqual(
            self.service.download_file_base64.call_args.kwargs["export_format"], "pdf"
        )

    def test_update_file_decodes_data_url(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.update_file.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "updateFile",
                    "gdFileId": "file-1",
                    # "hello" base64-encoded, wrapped in a data URL
                    "gdBase64Content": "data:text/plain;base64,aGVsbG8=",
                }
            )
        )
        self.assertEqual(self.service.update_file.call_args.kwargs["content"], b"hello")

    def test_update_file_rejects_invalid_base64(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        with self.assertRaises(ValueError) as ctx:
            google_drive_node.execute(
                _ctx(
                    {
                        "credentialId": "cred-1",
                        "gdOperation": "updateFile",
                        "gdFileId": "file-1",
                        "gdBase64Content": "!!!not base64!!!",
                    }
                )
            )
        self.assertIn("invalid base64", str(ctx.exception).lower())

    def test_update_file_passes_none_content_when_blank(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.update_file.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "updateFile",
                    "gdFileId": "file-1",
                    "gdNewName": "renamed.txt",
                }
            )
        )
        self.assertIsNone(self.service.update_file.call_args.kwargs["content"])
        self.assertEqual(self.service.update_file.call_args.kwargs["new_name"], "renamed.txt")

    def test_remove_file_defaults_to_trash(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.remove_file.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "removeFile",
                    "gdFileId": "file-1",
                }
            )
        )
        self.assertFalse(self.service.remove_file.call_args.kwargs["permanent"])

    def test_remove_folder_permanent_flag_is_forwarded(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.remove_folder.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "removeFolder",
                    "gdFolderId": "folder-1",
                    "gdPermanentDelete": True,
                }
            )
        )
        self.assertTrue(self.service.remove_folder.call_args.kwargs["permanent"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_node.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.node_execution.nodes.google_drive_node'`

- [ ] **Step 3: Create the handler**

Create `backend/app/services/node_execution/nodes/google_drive_node.py`:

```python
from __future__ import annotations

import base64

from app.services.node_execution.base import NodeExecutionContext

_VALID_OPERATIONS = (
    "listFolderFiles",
    "downloadFile",
    "syncToHeymDrive",
    "updateFile",
    "removeFile",
    "removeFolder",
)


def _decode_base64_content(raw: str) -> bytes:
    """Decode a base64 string, accepting `data:` URLs."""
    payload = str(raw).strip()
    if payload.startswith("data:"):
        comma_idx = payload.find(",")
        if comma_idx == -1:
            raise ValueError("Google Drive node: invalid base64 data URL")
        payload = payload[comma_idx + 1 :].strip()
    try:
        return base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError("Google Drive node: invalid base64 content") from exc


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the googleDrive node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    from app.config import settings
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config
    from app.services.google_drive_service import GoogleDriveService

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Google Drive node requires a credential")

    operation = node_data.get("gdOperation", "")
    if not operation:
        raise ValueError("Google Drive node requires an operation")
    if operation not in _VALID_OPERATIONS:
        raise ValueError(f"Unknown Google Drive operation: {operation}")

    gd_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            gd_config = decrypt_config(cred.encrypted_config)

    if not gd_config:
        raise ValueError("Google Drive credential not found or invalid")

    def field(name: str, default: str = "") -> str:
        return self.evaluate_message_template(
            str(node_data.get(name, default) or default), inputs, node_id
        ).strip()

    max_bytes = settings.file_max_size_mb * 1024 * 1024
    permanent = bool(node_data.get("gdPermanentDelete", False))
    export_format = field("gdExportFormat")

    with SessionLocal() as db:
        service = GoogleDriveService(credential_id, gd_config, db)

        if operation == "listFolderFiles":
            raw_max = field("gdMaxResults", "100")
            try:
                max_results = int(float(raw_max or "100"))
            except (ValueError, TypeError):
                max_results = 100
            if max_results < 1:
                max_results = 100
            return service.list_folder_files(
                field("gdFolderId"),
                max_results=max_results,
                query=field("gdQuery"),
                include_trashed=bool(node_data.get("gdIncludeTrashed", False)),
            )

        if operation == "downloadFile":
            file_id = field("gdFileId")
            if not file_id:
                raise ValueError("Google Drive node: file ID is required")
            return service.download_file_base64(
                file_id, export_format=export_format, max_bytes=max_bytes
            )

        if operation == "syncToHeymDrive":
            file_id = field("gdFileId")
            if not file_id:
                raise ValueError("Google Drive node: file ID is required")
            return _sync_to_heym_drive(
                ctx,
                service,
                file_id=file_id,
                export_format=export_format,
                filename_override=field("gdFilename"),
                max_bytes=max_bytes,
            )

        if operation == "updateFile":
            file_id = field("gdFileId")
            if not file_id:
                raise ValueError("Google Drive node: file ID is required")
            raw_content = field("gdBase64Content")
            content = _decode_base64_content(raw_content) if raw_content else None
            return service.update_file(
                file_id,
                content=content,
                new_name=field("gdNewName"),
                new_parent_id=field("gdNewParentId"),
                max_bytes=max_bytes,
            )

        if operation == "removeFile":
            file_id = field("gdFileId")
            if not file_id:
                raise ValueError("Google Drive node: file ID is required")
            return service.remove_file(file_id, permanent=permanent)

        folder_id = field("gdFolderId")
        if not folder_id:
            raise ValueError("Google Drive node: folder ID is required")
        return service.remove_folder(folder_id, permanent=permanent)
```

`_sync_to_heym_drive` is added in Task 10. Until then the `syncToHeymDrive` branch will raise `NameError`, which is fine — no test exercises it yet.

- [ ] **Step 4: Register the handler**

In `backend/app/services/node_execution/registry.py`, the mapping has `"drive": "drive_node",` at line 25 and `"googleSheets": "google_sheets_node",` at line 30. Add, keeping alphabetical order within that block:

```python
    "googleDrive": "google_drive_node",
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_node.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/node_execution/nodes/google_drive_node.py backend/app/services/node_execution/registry.py backend/tests/test_google_drive_node.py
git commit -m "feat(nodes): add googleDrive handler for list, download, update, remove"
```

---

### Task 10: `syncToHeymDrive`

**Files:**
- Modify: `backend/app/services/node_execution/nodes/google_drive_node.py`
- Test: `backend/tests/test_google_drive_node.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_google_drive_node.py`, before the `if __name__` block:

```python
class TestSyncToHeymDrive(GoogleDriveNodeTestBase):
    def _download_result(self) -> dict:
        return {
            "id": "gfile-1",
            "filename": "Notes.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 5,
            "exported": True,
            "export_format": "pdf",
            "content": b"HELLO",
        }

    def test_requires_owner_context(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        ctx = _ctx(
            {
                "credentialId": "cred-1",
                "gdOperation": "syncToHeymDrive",
                "gdFileId": "gfile-1",
            }
        )
        ctx.executor.trace_user_id = None

        with self.assertRaises(ValueError) as err:
            google_drive_node.execute(ctx)
        self.assertIn("owner context", str(err.exception))

    def test_writes_file_and_returns_download_url(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.download_file.return_value = self._download_result()
        written: dict = {}

        def fake_write(data: bytes) -> None:
            written["bytes"] = data

        abs_path = MagicMock()
        abs_path.write_bytes.side_effect = fake_write

        with patch(
            "app.services.file_storage._normalize_storage_filename", side_effect=lambda n: n
        ):
            with patch(
                "app.services.file_storage._safe_storage_path", return_value=abs_path
            ):
                with patch(
                    "app.services.file_storage.build_download_url",
                    return_value="https://app.test/api/files/dl/tok",
                ):
                    result = google_drive_node.execute(
                        _ctx(
                            {
                                "credentialId": "cred-1",
                                "gdOperation": "syncToHeymDrive",
                                "gdFileId": "gfile-1",
                            }
                        )
                    )

        self.assertEqual(written["bytes"], b"HELLO")
        self.assertEqual(result["operation"], "syncToHeymDrive")
        self.assertEqual(result["google_file_id"], "gfile-1")
        self.assertEqual(result["filename"], "Notes.pdf")
        self.assertEqual(result["download_url"], "https://app.test/api/files/dl/tok")
        # The Heym Drive file gets its own UUID, distinct from the Google file ID.
        self.assertNotEqual(result["id"], "gfile-1")

    def test_filename_override_is_applied(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.download_file.return_value = self._download_result()
        abs_path = MagicMock()

        with patch(
            "app.services.file_storage._normalize_storage_filename", side_effect=lambda n: n
        ) as normalize:
            with patch("app.services.file_storage._safe_storage_path", return_value=abs_path):
                with patch(
                    "app.services.file_storage.build_download_url", return_value="https://x/dl"
                ):
                    result = google_drive_node.execute(
                        _ctx(
                            {
                                "credentialId": "cred-1",
                                "gdOperation": "syncToHeymDrive",
                                "gdFileId": "gfile-1",
                                "gdFilename": "custom-name.pdf",
                            }
                        )
                    )

        normalize.assert_called_once_with("custom-name.pdf")
        self.assertEqual(result["filename"], "custom-name.pdf")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_node.py::TestSyncToHeymDrive -v`
Expected: FAIL — `NameError: name '_sync_to_heym_drive' is not defined`

- [ ] **Step 3: Implement `_sync_to_heym_drive`**

Add to `backend/app/services/node_execution/nodes/google_drive_node.py`, after `_decode_base64_content` and before `execute`:

```python
def _sync_to_heym_drive(
    ctx: NodeExecutionContext,
    service,
    file_id: str,
    export_format: str,
    filename_override: str,
    max_bytes: int,
) -> dict:
    """Download a Google Drive file and store it in Heym Drive.

    Mirrors the persistence sequence used by the drive node's ``save`` operation so
    the resulting file behaves identically in the Drive UI and download endpoints.
    """
    import secrets

    from app.db.models import FileAccessToken, GeneratedFile
    from app.db.session import SessionLocal
    from app.services.file_storage import (
        _normalize_storage_filename,
        _safe_storage_path,
        build_download_url,
    )

    self = ctx.executor
    owner_id = self.trace_user_id
    if not owner_id:
        raise ValueError("Google Drive node: no owner context available")

    downloaded = service.download_file(
        file_id, export_format=export_format, max_bytes=max_bytes
    )
    content: bytes = downloaded["content"]
    filename = _normalize_storage_filename(filename_override or downloaded["filename"])

    import uuid

    file_uuid = uuid.uuid4()
    rel_path = f"{owner_id}/{file_uuid}/{filename}"
    abs_path = _safe_storage_path(rel_path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)

    token_str = secrets.token_urlsafe(32)
    with SessionLocal() as db:
        db.add(
            GeneratedFile(
                id=file_uuid,
                owner_id=owner_id,
                workflow_id=self.workflow_id,
                filename=filename,
                storage_path=rel_path,
                mime_type=downloaded["mime_type"],
                size_bytes=len(content),
                source_node_id=ctx.node_id,
                source_node_label=ctx.node_data.get("label"),
                metadata_json={"google_file_id": downloaded["id"]},
            )
        )
        db.flush()
        db.add(
            FileAccessToken(
                file_id=file_uuid,
                token=token_str,
                created_by_id=owner_id,
            )
        )
        db.commit()

    return {
        "status": "success",
        "operation": "syncToHeymDrive",
        "id": str(file_uuid),
        "google_file_id": downloaded["id"],
        "filename": filename,
        "mime_type": downloaded["mime_type"],
        "size_bytes": len(content),
        "exported": downloaded["exported"],
        "download_url": build_download_url(self._base_url, token_str),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_google_drive_node.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Lint and format**

Run: `cd backend && uv run ruff format app/services/node_execution/nodes/google_drive_node.py tests/test_google_drive_node.py && uv run ruff check app/services/node_execution/nodes/google_drive_node.py tests/test_google_drive_node.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/node_execution/nodes/google_drive_node.py backend/tests/test_google_drive_node.py
git commit -m "feat(nodes): add syncToHeymDrive to the googleDrive node"
```

---

## Phase 4 — DSL and AI assistant

### Task 11: DSL prompt and autofill registration

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py` (new section after the `googleSheets` section ending near line 2300; rule 23a near line 4507)
- Modify: `backend/app/api/ai_assistant.py:1108-1124`

- [ ] **Step 1: Add the node section to the DSL prompt**

Find where the `googleSheets` section (`### 24. googleSheets (Google Sheets Operations)`, line 2176) ends and the next `### 25.` heading begins. Insert a new section immediately before that next heading, and **renumber the following sections** so numbering stays sequential.

```markdown
### 25. googleDrive (Google Drive Operations)
- **Purpose**: List, download, update, and delete Google Drive files and folders via OAuth2, and copy Drive files into Heym Drive
- **Inputs**: 1 | **Outputs**: 1
- **Data fields**:
  - `label`: Node identifier
  - `credentialId`: UUID of the Google Drive (OAuth2) credential
  - `gdOperation`: Operation type - "listFolderFiles" | "downloadFile" | "syncToHeymDrive" | "updateFile" | "removeFile" | "removeFolder"
  - `gdFolderId`: Folder ID or full Drive folder URL (listFolderFiles, removeFolder). Empty means the Drive root. Supports expressions.
  - `gdFileId`: File ID or full Drive/Docs URL (downloadFile, syncToHeymDrive, updateFile, removeFile). Supports expressions.
  - `gdMaxResults`: for `listFolderFiles` — maximum files to return, default 100. Supports expressions.
  - `gdQuery`: for `listFolderFiles` — optional extra Drive query ANDed with the parent filter, e.g. `mimeType='application/pdf'`. Supports expressions.
  - `gdIncludeTrashed`: boolean, optional for `listFolderFiles` — when true, trashed files are included. Default false.
  - `gdExportFormat`: for `downloadFile` and `syncToHeymDrive` — optional `"pdf"` | `"docx"` | `"xlsx"` | `"pptx"` | `"csv"` | `"txt"`. Empty means automatic. Ignored for non-Google-native files.
  - `gdFilename`: for `syncToHeymDrive` — optional filename override for the stored Heym Drive file. Supports expressions.
  - `gdBase64Content`: for `updateFile` — optional base64 string or `data:` URL that replaces the file content. Supports expressions.
  - `gdNewName`: for `updateFile` — optional new filename (rename). Supports expressions.
  - `gdNewParentId`: for `updateFile` — optional destination folder ID or URL (move). Supports expressions.
  - `gdPermanentDelete`: boolean, optional for `removeFile`/`removeFolder` — when false (default) the item is moved to Drive trash and is recoverable; when true it is permanently deleted.

**SETUP**: Requires a Google Drive credential created via the OAuth2 "Bring Your Own App" flow.
The backend **FRONTEND_URL** env var must be the public app URL (scheme + host); the Google redirect URI is `{FRONTEND_URL}/api/credentials/google-drive/oauth/callback` only (not derived from client headers).
1. Set **FRONTEND_URL** in production (e.g. `https://heym.example.com`).
2. Create a project in Google Cloud Console and enable the Google Drive API.
3. Create OAuth2 credentials (Web application type) and add that exact callback URL as an authorized redirect URI.
4. In Heym Dashboard → Credentials → New → Google Drive (OAuth2), enter your Client ID and Client Secret, then click **Connect** to authorize via browser popup.

The credential requests the full `https://www.googleapis.com/auth/drive` scope, because the node operates on files the user already owns rather than only files it created.

**File and folder IDs**: `gdFileId`, `gdFolderId`, and `gdNewParentId` accept either the bare ID or a full URL (`/file/d/<id>/`, `/drive/folders/<id>`, `/document/d/<id>/`, `?id=<id>`) — Heym extracts the ID automatically.

**Google-native files**: Google Docs, Sheets, and Slides have no downloadable bytes. `downloadFile` and `syncToHeymDrive` detect them and export instead — Docs to PDF, Sheets to XLSX, Slides to PPTX by default — so no operation ever fails purely because the target is a native document. Set `gdExportFormat` to override the target.

**Operations**:

| Operation | Required Fields | Description |
|-----------|-----------------|-------------|
| `listFolderFiles` | (none; `gdFolderId` empty = root) | List files in a folder with optional query filter |
| `downloadFile` | gdFileId | Download file bytes as base64, exporting native docs automatically |
| `syncToHeymDrive` | gdFileId | Download from Google Drive and store the result in Heym Drive |
| `updateFile` | gdFileId + at least one of gdBase64Content, gdNewName, gdNewParentId | Replace content, rename, and/or move |
| `removeFile` | gdFileId | Trash (default) or permanently delete a file |
| `removeFolder` | gdFolderId | Trash (default) or permanently delete a folder and its contents |

**Output Formats**:

**listFolderFiles**:
```json
{
  "status": "success",
  "operation": "listFolderFiles",
  "folder_id": "1FolderXyz",
  "count": 2,
  "files": [
    {
      "id": "1AbC",
      "name": "report.pdf",
      "mime_type": "application/pdf",
      "size_bytes": 20481,
      "modified_time": "2026-07-01T10:00:00.000Z",
      "web_view_link": "https://drive.google.com/file/d/1AbC/view",
      "is_folder": false
    }
  ]
}
```

**downloadFile**:
```json
{
  "status": "success",
  "operation": "downloadFile",
  "id": "1AbC",
  "filename": "Notes.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 20481,
  "exported": true,
  "export_format": "pdf",
  "content_base64": "JVBERi0xLjQ..."
}
```

**syncToHeymDrive**:
```json
{
  "status": "success",
  "operation": "syncToHeymDrive",
  "id": "9f1c2b3d-0000-4000-8000-000000000001",
  "google_file_id": "1AbC",
  "filename": "Notes.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 20481,
  "exported": true,
  "download_url": "https://heym.example.com/api/files/dl/TOKEN"
}
```

**updateFile**:
```json
{
  "status": "success",
  "operation": "updateFile",
  "id": "1AbC",
  "name": "renamed.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 20481,
  "modified_time": "2026-07-27T10:00:00.000Z",
  "updated": ["content", "name"]
}
```

**removeFile / removeFolder**:
```json
{
  "status": "success",
  "operation": "removeFile",
  "id": "1AbC",
  "name": "report.pdf",
  "deleted": "trashed"
}
```

**Example — back up a Drive folder into Heym Drive**:
```json
{
  "id": "list-drive",
  "type": "googleDrive",
  "position": { "x": 300, "y": 100 },
  "data": {
    "label": "ListReports",
    "credentialId": "google-drive-credential-uuid",
    "gdOperation": "listFolderFiles",
    "gdFolderId": "https://drive.google.com/drive/folders/1FolderXyz",
    "gdMaxResults": "50",
    "gdQuery": "mimeType='application/pdf'"
  }
}
```

```json
{
  "id": "sync-drive",
  "type": "googleDrive",
  "position": { "x": 600, "y": 100 },
  "data": {
    "label": "BackupToHeym",
    "credentialId": "google-drive-credential-uuid",
    "gdOperation": "syncToHeymDrive",
    "gdFileId": "$loop.item.id",
    "gdFilename": "$loop.item.name"
  }
}
```
```

- [ ] **Step 2: Add `googleDrive` to the credential rule**

In `backend/app/services/workflow_dsl_prompt.py`, rule 23a (line 4507) lists integrations that must use owner-only credentials. It contains `` `googleSheets`, `bigquery` ``. Change that fragment to:

```
`googleSheets`, `googleDrive`, `bigquery`
```

Also add `google-drive-credential-uuid` to the placeholder list in the same rule, next to `jira-credential-uuid`.

- [ ] **Step 3: Register the node for AI autofill**

In `backend/app/api/ai_assistant.py`, the `_INTEGRATION_CREDENTIAL_NODE_TYPES` set (line 1108) contains `"googleSheets",`. Add after it:

```python
    "googleDrive",
```

And add `"google-drive-credential-uuid",` to the placeholder tuple ending at line 1106.

- [ ] **Step 4: Verify the prompt still builds and the section numbering is sequential**

Run:
```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "
from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT as p
import re
nums = [int(m) for m in re.findall(r'^### (\d+)\.', p, re.M)]
print('googleDrive present:', 'googleDrive (Google Drive Operations)' in p)
print('sequential:', nums == list(range(nums[0], nums[0] + len(nums))))
"
```
Expected: `googleDrive present: True` and `sequential: True`.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./run_tests.sh`
Expected: all tests pass. Some existing tests assert on DSL prompt contents; if any fail because of the renumbering, update those assertions rather than reverting the numbering.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py backend/app/api/ai_assistant.py
git commit -m "feat(dsl): document the googleDrive node and register it for AI autofill"
```

---

## Phase 5 — Frontend

Per standing project preference, **no frontend UI tests are written for heymrun**. Verification is `bun run lint` + `bun run typecheck` + manual check in the editor.

### Task 12: Types, canvas defaults, palette, and icons

**Files:**
- Modify: `frontend/src/types/workflow.ts:166` (union) and `:897` (data fields)
- Modify: `frontend/src/types/node.ts:730` (node definition)
- Modify: `frontend/src/components/Canvas/WorkflowCanvas.vue:1099`
- Modify: `frontend/src/components/Panels/NodePanel.vue:252`
- Modify: `frontend/src/lib/nodeIcons.ts:86` and `:145`

- [ ] **Step 1: Add the node type to the union**

In `frontend/src/types/workflow.ts` line 166 is `| "googleSheets"`. Add after it:

```typescript
  | "googleDrive"
```

- [ ] **Step 2: Add the data fields**

In the same file, after the `gsValues?: string;` field (around line 897), add:

```typescript
  gdOperation?: string;
  gdFolderId?: string;
  gdFileId?: string;
  gdMaxResults?: string;
  gdQuery?: string;
  gdIncludeTrashed?: boolean;
  /** Export target for Google-native files; empty means automatic (Docs→PDF, Sheets→XLSX, Slides→PPTX). */
  gdExportFormat?: string;
  gdFilename?: string;
  gdBase64Content?: string;
  gdNewName?: string;
  gdNewParentId?: string;
  /** When false (default) the item is trashed and recoverable; true deletes permanently. */
  gdPermanentDelete?: boolean;
```

- [ ] **Step 3: Add the node definition**

In `frontend/src/types/node.ts`, after the `googleSheets` definition block that closes at line 730, add:

```typescript
  googleDrive: {
    type: "googleDrive",
    label: "Google Drive",
    description: "List, download, update, and delete Google Drive files via OAuth2",
    color: "node-google-drive",
    icon: "FolderOpen",
    inputs: 1,
    outputs: 1,
    defaultData: {
      label: "googleDrive",
      credentialId: "",
      gdOperation: undefined as string | undefined,
      gdFolderId: "",
      gdFileId: "",
      gdMaxResults: "100",
      gdQuery: "",
      gdIncludeTrashed: false,
      gdExportFormat: "",
      gdFilename: "",
      gdBase64Content: "",
      gdNewName: "",
      gdNewParentId: "",
      gdPermanentDelete: false,
    },
  },
```

- [ ] **Step 4: Add the canvas default data**

In `frontend/src/components/Canvas/WorkflowCanvas.vue`, after the `googleSheets:` line at 1099, add:

```typescript
    googleDrive: { label: "googleDrive", credentialId: "", gdOperation: undefined, gdFolderId: "", gdFileId: "", gdMaxResults: "100", gdQuery: "", gdIncludeTrashed: false, gdExportFormat: "", gdFilename: "", gdBase64Content: "", gdNewName: "", gdNewParentId: "", gdPermanentDelete: false },
```

- [ ] **Step 5: Add the palette and icon entries**

In `frontend/src/components/Panels/NodePanel.vue`, add `FolderOpen` to the `lucide-vue-next` import, then add after the `googleSheets: Sheet,` line at 252:

```typescript
  googleDrive: FolderOpen,
```

In `frontend/src/lib/nodeIcons.ts`, add `FolderOpen` to the `lucide-vue-next` import, then add after line 86:

```typescript
  googleDrive: FolderOpen,
```

and after line 145 in the colour map:

```typescript
  googleDrive: "text-node-google-drive",
```

- [ ] **Step 6: Define the node colour**

`node-google-drive` must exist as a Tailwind token. Find where `node-google-sheets` is defined (`grep -rn "node-google-sheets" frontend/src frontend/tailwind.config.*`) and add a `node-google-drive` entry alongside it, using Google Drive's yellow-green (`#0F9D58` reads as Drive's green; use `#1FA463` if the palette needs a darker variant for contrast).

- [ ] **Step 7: Verify lint and types**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: both pass with no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/types/node.ts frontend/src/components/Canvas/WorkflowCanvas.vue frontend/src/components/Panels/NodePanel.vue frontend/src/lib/nodeIcons.ts
git commit -m "feat(frontend): register the googleDrive node type, palette entry, and icon"
```

---

### Task 13: Operation options and the properties component

**Files:**
- Modify: `frontend/src/components/Panels/propertiesPanel/operationOptions.ts:259`
- Create: `frontend/src/components/Panels/propertiesPanel/nodes/GoogleDriveNodeProperties.vue`
- Modify: `frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue:39` and `:98`

- [ ] **Step 1: Add the operation options**

In `frontend/src/components/Panels/propertiesPanel/operationOptions.ts`, after `googleSheetsOperationOptions` (which closes at line 259), add:

```typescript
export const googleDriveOperationOptions: OperationOption[] = [
  { value: "", label: "Select operation..." },
  { value: "listFolderFiles", label: "List Folder Files" },
  { value: "downloadFile", label: "Download File" },
  { value: "syncToHeymDrive", label: "Sync to Heym Drive" },
  { value: "updateFile", label: "Update File" },
  { value: "removeFile", label: "Remove File" },
  { value: "removeFolder", label: "Remove Folder" },
];

export const googleDriveExportFormatOptions: OperationOption[] = [
  { value: "", label: "Automatic (Docs→PDF, Sheets→XLSX, Slides→PPTX)" },
  { value: "pdf", label: "PDF" },
  { value: "docx", label: "Word (DOCX)" },
  { value: "xlsx", label: "Excel (XLSX)" },
  { value: "pptx", label: "PowerPoint (PPTX)" },
  { value: "csv", label: "CSV" },
  { value: "txt", label: "Plain text" },
];
```

- [ ] **Step 2: Create the properties component**

Create `frontend/src/components/Panels/propertiesPanel/nodes/GoogleDriveNodeProperties.vue`. It follows `GoogleSheetsNodeProperties.vue`: pull everything from the panel context, render the credential picker, the operation picker, then operation-conditional fields.

```vue
<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import Checkbox from "@/components/ui/Checkbox.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  isWorkflowOwner,
  googleDriveFolderIdExpressionInputRef,
  googleDriveFileIdExpressionInputRef,
  googleDriveSecondaryExpressionInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  googleDriveExpressionFieldCount,
  handleGoogleDriveExpressionFieldNavigate,
  onGoogleDriveRegisterExpressionFieldIndex,
  googleDriveCredentialOptions,
  googleDriveOperationOptions,
  googleDriveExportFormatOptions,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Google Drive Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="googleDriveCredentialOptions"
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
      <SearchableSelect
        :model-value="selectedNode.data.gdOperation || ''"
        :options="googleDriveOperationOptions"
        search-placeholder="Search Google Drive operations..."
        @update:model-value="updateNodeData('gdOperation', $event)"
      />
    </div>

    <template v-if="selectedNode.data.gdOperation">
      <!-- Folder-targeted operations -->
      <div
        v-if="['listFolderFiles', 'removeFolder'].includes(selectedNode.data.gdOperation)"
        class="space-y-2"
      >
        <Label>Folder ID or URL</Label>
        <ExpressionInput
          ref="googleDriveFolderIdExpressionInputRef"
          :model-value="selectedNode.data.gdFolderId || ''"
          placeholder="1FolderXyz or https://drive.google.com/drive/folders/..."
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="googleDriveExpressionFieldCount > 1"
          :navigation-index="0"
          :navigation-total="googleDriveExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Folder ID or URL"
          field-key="gdFolderId"
          @navigate="handleGoogleDriveExpressionFieldNavigate"
          @register-index="onGoogleDriveRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('gdFolderId', $event)"
        />
        <p
          v-if="selectedNode.data.gdOperation === 'listFolderFiles'"
          class="text-xs text-muted-foreground"
        >
          Leave empty to list the Drive root.
        </p>
      </div>

      <!-- File-targeted operations -->
      <div
        v-if="
          ['downloadFile', 'syncToHeymDrive', 'updateFile', 'removeFile'].includes(
            selectedNode.data.gdOperation,
          )
        "
        class="space-y-2"
      >
        <Label>File ID or URL</Label>
        <ExpressionInput
          ref="googleDriveFileIdExpressionInputRef"
          :model-value="selectedNode.data.gdFileId || ''"
          placeholder="1AbCdEf or https://drive.google.com/file/d/.../view"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="googleDriveExpressionFieldCount > 1"
          :navigation-index="0"
          :navigation-total="googleDriveExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="File ID or URL"
          field-key="gdFileId"
          @navigate="handleGoogleDriveExpressionFieldNavigate"
          @register-index="onGoogleDriveRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('gdFileId', $event)"
        />
      </div>

      <!-- listFolderFiles extras -->
      <template v-if="selectedNode.data.gdOperation === 'listFolderFiles'">
        <div class="space-y-2">
          <Label>Max Results</Label>
          <ExpressionInput
            ref="googleDriveSecondaryExpressionInputRef"
            :model-value="selectedNode.data.gdMaxResults || '100'"
            placeholder="100"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :navigation-enabled="googleDriveExpressionFieldCount > 1"
            :navigation-index="1"
            :navigation-total="googleDriveExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Max Results"
            field-key="gdMaxResults"
            @navigate="handleGoogleDriveExpressionFieldNavigate"
            @register-index="onGoogleDriveRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('gdMaxResults', $event)"
          />
        </div>
        <div class="space-y-2">
          <Label>Filter Query (optional)</Label>
          <ExpressionInput
            :model-value="selectedNode.data.gdQuery || ''"
            placeholder="mimeType='application/pdf'"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Filter Query"
            field-key="gdQuery"
            @update:model-value="updateNodeData('gdQuery', $event)"
          />
          <p class="text-xs text-muted-foreground">
            Google Drive query syntax, combined with the folder filter.
          </p>
        </div>
        <div class="flex items-center gap-2">
          <Checkbox
            :model-value="selectedNode.data.gdIncludeTrashed === true"
            @update:model-value="updateNodeData('gdIncludeTrashed', $event)"
          />
          <Label>Include trashed files</Label>
        </div>
      </template>

      <!-- Export format for download-shaped operations -->
      <div
        v-if="['downloadFile', 'syncToHeymDrive'].includes(selectedNode.data.gdOperation)"
        class="space-y-2"
      >
        <Label>Export Format</Label>
        <Select
          :model-value="selectedNode.data.gdExportFormat || ''"
          :options="googleDriveExportFormatOptions"
          @update:model-value="updateNodeData('gdExportFormat', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Applies to Google Docs, Sheets, and Slides, which have no downloadable bytes and must be
          exported. Ignored for regular files.
        </p>
      </div>

      <!-- syncToHeymDrive extras -->
      <div v-if="selectedNode.data.gdOperation === 'syncToHeymDrive'" class="space-y-2">
        <Label>Heym Drive Filename (optional)</Label>
        <ExpressionInput
          :model-value="selectedNode.data.gdFilename || ''"
          placeholder="Leave empty to keep the Google Drive name"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Heym Drive Filename"
          field-key="gdFilename"
          @update:model-value="updateNodeData('gdFilename', $event)"
        />
      </div>

      <!-- updateFile extras -->
      <template v-if="selectedNode.data.gdOperation === 'updateFile'">
        <div class="space-y-2">
          <Label>New Content (base64, optional)</Label>
          <ExpressionInput
            :model-value="selectedNode.data.gdBase64Content || ''"
            placeholder="$PreviousNode.content_base64"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="New Content"
            field-key="gdBase64Content"
            @update:model-value="updateNodeData('gdBase64Content', $event)"
          />
        </div>
        <div class="space-y-2">
          <Label>New Name (optional)</Label>
          <ExpressionInput
            :model-value="selectedNode.data.gdNewName || ''"
            placeholder="renamed.pdf"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="New Name"
            field-key="gdNewName"
            @update:model-value="updateNodeData('gdNewName', $event)"
          />
        </div>
        <div class="space-y-2">
          <Label>Move to Folder (optional)</Label>
          <ExpressionInput
            :model-value="selectedNode.data.gdNewParentId || ''"
            placeholder="1DestinationFolderId or folder URL"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Move to Folder"
            field-key="gdNewParentId"
            @update:model-value="updateNodeData('gdNewParentId', $event)"
          />
        </div>
        <p class="text-xs text-muted-foreground">
          Fill at least one of the three. Fields left empty are not changed.
        </p>
      </template>

      <!-- Delete safety -->
      <template v-if="['removeFile', 'removeFolder'].includes(selectedNode.data.gdOperation)">
        <div class="flex items-center gap-2">
          <Checkbox
            :model-value="selectedNode.data.gdPermanentDelete === true"
            @update:model-value="updateNodeData('gdPermanentDelete', $event)"
          />
          <Label>Delete permanently</Label>
        </div>
        <p
          v-if="selectedNode.data.gdPermanentDelete"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          <span v-if="selectedNode.data.gdOperation === 'removeFolder'">
            The folder and everything inside it will be destroyed and cannot be recovered.
          </span>
          <span v-else>This file will be destroyed and cannot be recovered.</span>
        </p>
        <p v-else class="text-xs text-muted-foreground">
          The item is moved to Google Drive trash and can be restored.
        </p>
      </template>
    </template>
  </template>
</template>
```

Before writing this, confirm the checkbox component's real path and prop contract with `grep -rn "Checkbox" frontend/src/components/Panels/propertiesPanel/nodes/*.vue | head -5` and match whatever the sibling node components use — if they use a different component or `:checked`/`@update:checked`, follow that instead.

- [ ] **Step 3: Wire the component into the form**

In `frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue`, add the import after line 39:

```typescript
import GoogleDriveNodeProperties from "./GoogleDriveNodeProperties.vue";
```

and the render branch after line 98:

```vue
  <GoogleDriveNodeProperties v-else-if="selectedNode?.type === 'googleDrive'" />
```

- [ ] **Step 4: Verify lint and types**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: both pass. Type errors here mean the context bindings from Task 14 are missing — that is expected until Task 14 lands, so if `typecheck` reports unknown properties on the context, proceed to Task 14 and re-run.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Panels/propertiesPanel/operationOptions.ts frontend/src/components/Panels/propertiesPanel/nodes/GoogleDriveNodeProperties.vue frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue
git commit -m "feat(frontend): add Google Drive node properties panel"
```

---

### Task 14: Panel controller wiring

**Files:**
- Modify: `frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts`

- [ ] **Step 1: Add the expression input refs**

Near line 759, where `googleSheetsSpreadsheetIdExpressionInputRef` is declared, add:

```typescript
  const googleDriveFolderIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const googleDriveFileIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const googleDriveSecondaryExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const currentGoogleDriveExpressionFieldIndex = ref(0);
```

- [ ] **Step 2: Add the credential list ref, loader, and options computed**

Three separate edits, matching how `googleSheets` does it.

First, next to `const googleSheetsCredentials = ref<CredentialListItem[]>([]);` (line 573), add:

```typescript
  const googleDriveCredentials = ref<CredentialListItem[]>([]);
```

Second, next to the loader branch at line 1122, add a sibling branch. The API argument is the **snake_case credential type**, not the camelCase node type:

```typescript
      if (type === "googleDrive") {
        try {
          googleDriveCredentials.value = await credentialsApi.listByType("google_drive");
        } catch {
          googleDriveCredentials.value = [];
        }
      }
```

Third, next to `googleSheetsCredentialOptions` (line 6091), add:

```typescript
  const googleDriveCredentialOptions = computed(() => {
    const node = selectedNode.value;
    const selectedCredentialId =
      node && node.type === "googleDrive"
        ? (node.data.credentialId as string | undefined)
        : undefined;

    return buildCredentialOptions(
      googleDriveCredentials.value,
      selectedCredentialId,
      "Select Google Drive credential...",
      "Shared Google Drive credential (from owner)",
    );
  });
```

Finally, import the operation options at the top of the file next to `googleSheetsOperationOptions` (line 53):

```typescript
  googleDriveOperationOptions,
  googleDriveExportFormatOptions,
```

- [ ] **Step 3: Add the field count and navigation**

After `onGoogleSheetsRegisterExpressionFieldIndex` (which ends at line 3661), add:

```typescript
  // Every expression-capable field per operation, in navigation order. AGENTS.md
  // requires the evaluate dialog to reach all of them, not just the primary id.
  const GOOGLE_DRIVE_EXPRESSION_FIELDS: Record<string, string[]> = {
    listFolderFiles: ["gdFolderId", "gdMaxResults", "gdQuery"],
    downloadFile: ["gdFileId"],
    syncToHeymDrive: ["gdFileId", "gdFilename"],
    updateFile: ["gdFileId", "gdBase64Content", "gdNewName", "gdNewParentId"],
    removeFile: ["gdFileId"],
    removeFolder: ["gdFolderId"],
  };

  const googleDriveExpressionFieldCount = computed((): number => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "googleDrive") {
      return 1;
    }
    const op = (n.data.gdOperation as string | undefined) || "";
    return GOOGLE_DRIVE_EXPRESSION_FIELDS[op]?.length ?? 1;
  });

  function openGoogleDriveExpressionFieldAtIndex(index: number): void {
    const n = selectedNode.value;
    if (!n || n.type !== "googleDrive") {
      return;
    }
    currentGoogleDriveExpressionFieldIndex.value = index;
    const op = (n.data.gdOperation as string | undefined) || "";
    const folderOp = op === "listFolderFiles" || op === "removeFolder";
    if (index === 0) {
      if (folderOp) {
        googleDriveFolderIdExpressionInputRef.value?.openExpandDialog();
      } else {
        googleDriveFileIdExpressionInputRef.value?.openExpandDialog();
      }
      return;
    }
    if (index === 1 && op === "listFolderFiles") {
      googleDriveSecondaryExpressionInputRef.value?.openExpandDialog();
    }
  }

  function handleGoogleDriveExpressionFieldNavigate(direction: "prev" | "next"): void {
    const n = selectedNode.value;
    if (!n || n.type !== "googleDrive") {
      return;
    }
    const total = googleDriveExpressionFieldCount.value;
    const newIndex =
      direction === "prev"
        ? currentGoogleDriveExpressionFieldIndex.value - 1
        : currentGoogleDriveExpressionFieldIndex.value + 1;
    if (newIndex < 0 || newIndex >= total) {
      return;
    }
    googleDriveFolderIdExpressionInputRef.value?.closeExpandDialog();
    googleDriveFileIdExpressionInputRef.value?.closeExpandDialog();
    googleDriveSecondaryExpressionInputRef.value?.closeExpandDialog();
    currentGoogleDriveExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openGoogleDriveExpressionFieldAtIndex(newIndex);
    });
  }

  function onGoogleDriveRegisterExpressionFieldIndex(index: number): void {
    currentGoogleDriveExpressionFieldIndex.value = index;
  }
```

- [ ] **Step 4: Add the double-click dialog opener**

In the node-type chain that starts around line 2915 with `} else if (nodeType === "googleSheets") {`, add a matching branch:

```typescript
    } else if (nodeType === "googleDrive") {
      currentGoogleDriveExpressionFieldIndex.value = 0;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) {
          return;
        }
        if (
          googleDriveFolderIdExpressionInputRef.value ||
          googleDriveFileIdExpressionInputRef.value
        ) {
          nextTick(() => openGoogleDriveExpressionFieldAtIndex(0));
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      };
      nextTick(() => tryOpenDialog());
```

Also add the three new refs to the `closeExpandDialog()` cleanup block near line 2225, next to `googleSheetsSpreadsheetIdExpressionInputRef.value?.closeExpandDialog();`.

- [ ] **Step 5: Add the icon, colour, and doc-slug map entries**

This file has three maps mirroring the ones in Task 12 — icons (line 131), colours (line 189), doc slugs (line 247). Add to each:

```typescript
    googleDrive: FolderOpen,
```
```typescript
    googleDrive: "node-google-drive",
```
```typescript
    googleDrive: "google-drive-node",
```

Add `FolderOpen` to this file's `lucide-vue-next` import.

- [ ] **Step 6: Export everything from the context**

In the returned object (around lines 8856 and 8984), add:

```typescript
    googleDriveFolderIdExpressionInputRef,
    googleDriveFileIdExpressionInputRef,
    googleDriveSecondaryExpressionInputRef,
    googleDriveCredentialOptions,
    googleDriveOperationOptions,
    googleDriveExportFormatOptions,
    googleDriveExpressionFieldCount,
    handleGoogleDriveExpressionFieldNavigate,
    onGoogleDriveRegisterExpressionFieldIndex,
```

- [ ] **Step 7: Verify lint and types**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: both pass, including the Task 13 component.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts
git commit -m "feat(frontend): wire Google Drive expression navigation and panel context"
```

---

### Task 15: Credential dialog and API client

**Files:**
- Modify: `frontend/src/services/api.ts:1416`
- Modify: `frontend/src/components/Credentials/CredentialDialog.vue` (lines 238, 584, 834, 899, 905, 1419, 1476, 2879, 3335)

- [ ] **Step 1: Add the API client method**

In `frontend/src/services/api.ts`, after `googleSheetsOAuthAuthorize` (ends line 1416), add:

```typescript
  googleDriveOAuthAuthorize: async (credentialId: string): Promise<{ auth_url: string }> => {
    const response = await api.post<{ auth_url: string }>(
      "/credentials/google-drive/oauth/authorize",
      { credential_id: credentialId },
    );
    return response.data;
  },
```

- [ ] **Step 2: Add the credential type to the dialog**

`CredentialDialog.vue` handles `google_sheets` at nine sites. Mirror each one for `google_drive`:

1. **Line 238** — type dropdown: add `{ value: "google_drive", label: CREDENTIAL_TYPE_LABELS.google_drive },`. Add the matching `google_drive: "Google Drive (OAuth2)"` entry wherever `CREDENTIAL_TYPE_LABELS` is defined (`grep -rn "CREDENTIAL_TYPE_LABELS" frontend/src`).
2. **Line 584** — config assembly: build `{ client_id, client_secret }` exactly as the `google_sheets` branch does.
3. **Line 834** — reset/prefill on edit: same handling as `google_sheets`.
4. **Lines 899–905** — the connect handler: create the credential with `type: "google_drive"`, then call `credentialsApi.googleDriveOAuthAuthorize(credId)` and open the returned `auth_url` in the popup. Reuse the existing `postMessage` listener, which already keys off `google-oauth-success` / `google-oauth-error` — the Drive callback emits the same message types, so no listener change is needed.
5. **Line 1419** — the "requires manual save" exclusion list: add `type.value !== "google_drive" &&`.
6. **Line 1476** — connected-state computed: mirror `gsConnectedCredential` with a `gdConnectedCredential`.
7. **Line 2879** — the form template: add `<template v-if="type === 'google_drive'">` with Client ID / Client Secret inputs and the Connect button, copying the `google_sheets` block.
8. **Line 3335** — submit button label: extend the condition to `(type === 'google_drive' && gdOAuthConnected)`.

- [ ] **Step 3: Verify lint and types**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: both pass.

- [ ] **Step 4: Manual verification**

Run `./run.sh`, open the dashboard → Credentials → New → Google Drive (OAuth2). Confirm the Client ID / Client Secret fields render and the Connect button opens a popup. A real Google round-trip needs a Google Cloud project with the callback `http://localhost:4017/api/credentials/google-drive/oauth/callback` registered; if one is not available, verify the popup opens and reports Google's own error rather than a Heym error.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/api.ts frontend/src/components/Credentials/CredentialDialog.vue
git commit -m "feat(frontend): add Google Drive credential type with OAuth connect flow"
```

---

## Phase 6 — heymrun documentation

### Task 16: Node documentation page

**Files:**
- Create: `frontend/src/docs/content/nodes/google-drive-node.md`
- Modify: `frontend/src/docs/manifest.ts:71`

- [ ] **Step 1: Read the reference page for structure**

Run: `cat frontend/src/docs/content/nodes/google-sheets-node.md`

Match its heading structure, frontmatter (if any), operation table style, and cross-link conventions.

- [ ] **Step 2: Write the page**

Create `frontend/src/docs/content/nodes/google-drive-node.md` covering:

- What the node does, and an explicit note that it is **not** the [Drive](./drive-node.md) node — that one is Heym Drive, internal storage.
- Credential setup: Google Cloud project, enable the Google Drive API, Web application OAuth client, the exact redirect URI `{FRONTEND_URL}/api/credentials/google-drive/oauth/callback`, then Dashboard → Credentials → New → Google Drive (OAuth2) → Connect.
- A scope note: the credential requests full `https://www.googleapis.com/auth/drive` access because the node works on files the user already owns.
- An operations table with every field from the DSL section in Task 11.
- The Google-native export behaviour, with the default mapping table.
- Output JSON for each of the six operations (reuse the blocks from Task 11).
- A worked example: back up a Drive folder into Heym Drive using Cron → listFolderFiles → Loop → syncToHeymDrive.
- A safety note that `removeFile`/`removeFolder` trash by default and that "Delete permanently" is unrecoverable, and that `removeFolder` also destroys folder contents.

- [ ] **Step 3: Register the page**

In `frontend/src/docs/manifest.ts`, the nodes section has `{ slug: "google-sheets-node", title: "Google Sheets" },` at line 71. Add before it (alphabetical):

```typescript
      { slug: "google-drive-node", title: "Google Drive" },
```

- [ ] **Step 4: Verify the docs build**

Run: `cd frontend && bun run typecheck && bun run build`
Expected: both succeed. A missing or misnamed slug fails the build.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/docs/content/nodes/google-drive-node.md frontend/src/docs/manifest.ts
git commit -m "docs: add the Google Drive node page"
```

---

### Task 17: Reference documentation

**Files:**
- Modify: `frontend/src/docs/content/reference/features.md:253-265` and `:397`
- Modify: `frontend/src/docs/content/reference/node-types.md`
- Modify: `frontend/src/docs/content/reference/integrations.md`
- Modify: `frontend/src/docs/content/reference/credentials.md`
- Modify: `frontend/src/docs/content/reference/credentials-sharing.md`

- [ ] **Step 1: Add the per-node section to features.md**

`features.md` line 255 begins `#### [Google Sheets](../nodes/google-sheets-node.md)`. Add a sibling section next to it:

```markdown
#### [Google Drive](../nodes/google-drive-node.md)

The Google Drive node lists, downloads, updates, and deletes Drive files and folders via OAuth2, and can copy a Drive file straight into [Heym Drive](../nodes/drive-node.md) with `syncToHeymDrive`. Google Docs, Sheets, and Slides have no downloadable bytes, so the node exports them automatically — Docs to PDF, Sheets to XLSX, Slides to PPTX — and an export format field overrides the target. Deletions move items to Drive trash unless "Delete permanently" is enabled. Like [Google Sheets](../nodes/google-sheets-node.md), it uses a Google-backed integration credential.

Pairs with [Loop](../nodes/loop-node.md), [Drive](../nodes/drive-node.md), [LLM](../nodes/llm-node.md), and [Third-Party Integrations](./integrations.md).
```

- [ ] **Step 2: Add to the node-types summary paragraph**

The long paragraph at line 397 lists integrations. Find `[Google Sheets](../nodes/google-sheets-node.md), [BigQuery](../nodes/bigquery-node.md)` and change it to:

```
[Google Sheets](../nodes/google-sheets-node.md), [Google Drive](../nodes/google-drive-node.md), [BigQuery](../nodes/bigquery-node.md)
```

- [ ] **Step 3: Update the remaining reference pages**

For each of `node-types.md`, `integrations.md`, and `credentials.md`: locate the existing Google Sheets entry (`grep -n "Google Sheets" <file>`) and add a parallel Google Drive entry in the same format and position. In `credentials.md`, document the required `client_id` / `client_secret` fields and the OAuth Connect step.

- [ ] **Step 4: Add the sharing caveat**

In `credentials-sharing.md`, add an explicit warning. This is required, not optional — the scope is broad enough that sharing has real consequences:

```markdown
> **Google Drive credentials grant full Drive access.** The Google Drive credential is authorized with the `https://www.googleapis.com/auth/drive` scope so the node can operate on files you already own. Sharing this credential with a team gives every member the ability to read, modify, and delete **anything in your Google Drive** through a workflow. Share it only with people you would give full Drive access to directly.
```

- [ ] **Step 5: Verify the build**

Run: `cd frontend && bun run build`
Expected: succeeds; all new relative doc links resolve.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/docs/content/reference/
git commit -m "docs: add Google Drive to the reference documentation"
```

---

## Phase 7 — heymweb

All paths in this phase are relative to `/Users/mbakgun/Projects/heym/heymweb`.

### Task 18: Sync docs and DSL prompt

**Files:**
- Modify: `src/content/docs/**` (generated), `src/lib/heymDslPrompt.ts` (generated)

- [ ] **Step 1: Sync the documentation**

Run: `cd /Users/mbakgun/Projects/heym/heymweb && bun run sync-docs`
Expected: pulls `google-drive-node.md` into `src/content/docs/nodes/` and updates the reference pages changed in Task 17.

- [ ] **Step 2: Sync the DSL prompt**

Run: `cd /Users/mbakgun/Projects/heym/heymweb && bun run sync-dsl-prompt`
Expected: `src/lib/heymDslPrompt.ts` picks up the new `googleDrive` section.

- [ ] **Step 3: Verify the sync landed**

Run:
```bash
cd /Users/mbakgun/Projects/heym/heymweb && \
  ls src/content/docs/nodes/google-drive-node.md && \
  grep -c "googleDrive" src/lib/heymDslPrompt.ts
```
Expected: the file exists and the grep count is greater than zero.

- [ ] **Step 4: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/content/docs src/lib/heymDslPrompt.ts
git commit -m "chore: sync Google Drive node docs and DSL prompt from heymrun"
```

---

### Task 19: Marketing node catalog

**Files:**
- Modify: `src/lib/marketingNodeCatalog.ts:48`
- Modify: `src/lib/node-doc-links.ts:41`
- Modify: `src/components/templates/nodePreviewTokens.ts`

- [ ] **Step 1: Add the catalog entry**

In `src/lib/marketingNodeCatalog.ts`, line 48 is `{ id: 'googleSheets', name: 'Google Sheets' },`. Add after it:

```typescript
  { id: 'googleDrive', name: 'Google Drive' },
```

- [ ] **Step 2: Add the doc link**

In `src/lib/node-doc-links.ts`, line 41 is `googleSheets: 'nodes/google-sheets-node.md',`. Add after it:

```typescript
  googleDrive: 'nodes/google-drive-node.md',
```

- [ ] **Step 3: Add the preview token**

Inspect `src/components/templates/nodePreviewTokens.ts` for the `googleSheets` entry (`grep -n "googleSheets" -A4 src/components/templates/nodePreviewTokens.ts`) and add a `googleDrive` entry in the same shape, so the template canvas renders the node with the right icon and colour rather than a fallback.

- [ ] **Step 4: Verify types and build**

Run: `cd /Users/mbakgun/Projects/heym/heymweb && bunx tsc --noEmit && bun run build`
Expected: both succeed. heymweb has no lint or unit test scripts, so these are the verification gates.

- [ ] **Step 5: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/lib/marketingNodeCatalog.ts src/lib/node-doc-links.ts src/components/templates/nodePreviewTokens.ts
git commit -m "feat: add Google Drive to the marketing node catalog"
```

---

### Task 20: Marketing template

**Files:**
- Modify: `src/lib/operationsTemplates.ts`
- Modify: `tests/templates/catalog.test.ts` (only if it fails)

- [ ] **Step 1: Read an existing template end to end**

Run: `sed -n '56,230p' src/lib/operationsTemplates.ts`

Note the exact `StaticTemplate` shape: `slug`, `name`, `description`, `longDescription` (markdown), the `nodes` array of `TemplateNode`, and the edges. Reuse the `setupNote` and `outputNode` helpers already defined at the top of the file.

- [ ] **Step 2: Add the template**

Append a new entry to `OPERATIONS_TEMPLATES`:

- `slug`: `google-drive-to-heym-drive-backup`
- `name`: `Google Drive to Heym Drive Backup`
- `description`: one sentence about scheduled backup of a Drive folder into Heym Drive with a Slack summary.
- `longDescription`: markdown following the existing pattern — what the workflow does as a numbered list, use cases, and setup requirements (Google Drive OAuth credential, Slack credential, the folder ID).
- Nodes:
  1. `cron` trigger — daily schedule.
  2. `googleDrive` — `gdOperation: 'listFolderFiles'`, `gdFolderId` set to a placeholder folder ID, `gdMaxResults: '50'`.
  3. `loop` — iterating the `files` array from the list node.
  4. `googleDrive` — `gdOperation: 'syncToHeymDrive'`, `gdFileId: '$loop.item.id'`, `gdFilename: '$loop.item.name'`.
  5. `slack` — a summary message.
  6. A `setupNote` sticky explaining the credentials and folder ID the user must fill in.
  7. An `outputNode` returning the backup summary.
- Edges connecting them in that order.

Use `credentialId: ''` on both `googleDrive` nodes and the `slack` node — templates must never ship a real credential UUID.

- [ ] **Step 3: Run the template catalog test**

Run: `cd /Users/mbakgun/Projects/heym/heymweb && bun test tests/templates/catalog.test.ts`
Expected: PASS. If it fails on slug uniqueness, node-type coverage, or a required field, fix the template — only edit the test if it hard-codes a template count.

- [ ] **Step 4: Verify types and build**

Run: `cd /Users/mbakgun/Projects/heym/heymweb && bunx tsc --noEmit && bun run build`
Expected: both succeed.

- [ ] **Step 5: Manual check**

Run `bun run dev` and open the template's page. Confirm the canvas preview renders all nodes with the Google Drive icon rather than a fallback box.

- [ ] **Step 6: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/lib/operationsTemplates.ts tests/templates/catalog.test.ts
git commit -m "feat: add the Google Drive to Heym Drive backup template"
```

---

## Phase 8 — Final verification

### Task 21: Full check and review

- [ ] **Step 1: Run the full heymrun check**

Run: `cd /Users/mbakgun/Projects/heym/heymrun && SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
Expected: frontend lint, frontend typecheck, backend ruff, and the full backend test suite all pass.

- [ ] **Step 2: Commit any formatting-only diffs**

`check.sh` applies `ruff format`. If it changed files:

```bash
cd /Users/mbakgun/Projects/heym/heymrun
git add -A && git commit -m "style: apply ruff formatting"
```

- [ ] **Step 3: Run the E2E suite**

Run: `cd /Users/mbakgun/Projects/heym/heymrun && ./run_e2e.sh`
Expected: passes. No new specs were added, but the new node type must not break existing canvas or properties-panel specs.

- [ ] **Step 4: Confirm both trees are clean and nothing is pushed**

Run:
```bash
cd /Users/mbakgun/Projects/heym/heymrun && git status --short && git log --oneline origin/main..HEAD | head -30
cd /Users/mbakgun/Projects/heym/heymweb && git status --short
```
Expected: both working trees clean; the heymrun commit list shows this feature's commits unpushed on `impl/gdrive-node`.

- [ ] **Step 5: Report**

Summarize: what shipped, the full test results verbatim, anything skipped, and that nothing was pushed. Ask whether to push and open a PR.

---

## Verification gates summary

| Gate | Command | Where |
| --- | --- | --- |
| Backend unit tests | `SECRET_KEY=... ./run_tests.sh` | heymrun/backend |
| Backend lint/format | `uv run ruff check . && uv run ruff format --check .` | heymrun/backend |
| Frontend lint + types | `bun run lint && bun run typecheck` | heymrun/frontend |
| Full local check | `SECRET_KEY=... ./check.sh` | heymrun root |
| E2E | `./run_e2e.sh` | heymrun root |
| heymweb types + build | `bunx tsc --noEmit && bun run build` | heymweb |
| heymweb template catalog | `bun test tests/templates/catalog.test.ts` | heymweb |

## Known risks

- **Section renumbering in the DSL prompt** (Task 11) can break tests that assert on section numbers. Task 11 Step 5 catches this; fix the assertions, do not revert the numbering.
- **`CredentialDialog.vue` has nine touch points** (Task 15). Missing one produces a credential that saves but never shows "connected". Step 4's manual check is the guard.
- **Live OAuth is untested without a Google Cloud project.** The unit tests cover state signing, URL construction, and token refresh, but not a real consent round-trip. Flag this explicitly in the final report rather than claiming the flow is verified end to end.
