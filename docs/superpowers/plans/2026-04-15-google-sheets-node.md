# Google Sheets Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Google Sheets node to Heym that reads, writes, appends, and queries Google Spreadsheets via OAuth2 ("Bring Your Own App" model) with a popup consent flow.

**Architecture:** New `google_sheets` CredentialType stores `client_id`, `client_secret`, `access_token`, `refresh_token`, and `token_expiry` in the existing encrypted credential config. A dedicated `GoogleSheetsService` (sync httpx) handles token refresh and all Sheets API calls. Two new OAuth2 endpoints (`/authorize` and `/callback`) manage the popup consent flow using a signed JWT as CSRF-safe state.

**Tech Stack:** Python (`python-jose`, `httpx` — already in pyproject.toml), FastAPI, SQLAlchemy sync session (matching grist/sendEmail pattern), Vue 3 + TypeScript strict, `window.open` + `postMessage` for popup OAuth.

---

## File Map

### Created
- `backend/app/api/google_sheets_oauth.py` — OAuth2 authorize + callback endpoints
- `backend/app/services/google_sheets_service.py` — Sheets API client + token refresh
- `backend/alembic/versions/055_add_google_sheets_credential_type.py` — DB enum migration
- `backend/tests/test_google_sheets_service.py` — service unit tests
- `backend/tests/test_google_sheets_oauth.py` — OAuth endpoint tests
- `frontend/src/docs/content/nodes/google-sheets-node.md` — node reference doc

### Modified
- `backend/app/db/models.py` — `CredentialType` enum: add `google_sheets`
- `backend/app/models/schemas.py` — `CredentialType` enum + `CredentialConfigGoogleSheets` model
- `backend/app/api/credentials.py` — `get_masked_value()` for `google_sheets`
- `backend/app/main.py` — register `google_sheets_oauth` router
- `backend/app/services/workflow_executor.py` — `elif node_type == "googleSheets"` handler
- `backend/app/services/workflow_dsl_prompt.py` — Google Sheets node documentation block
- `frontend/src/types/credential.ts` — `google_sheets` type + config interface + labels
- `frontend/src/types/node.ts` — `googleSheets` node default data
- `frontend/src/lib/nodeIcons.ts` — icon + colour class
- `frontend/src/styles/globals.css` — `--node-google-sheets` CSS variable
- `frontend/src/services/api.ts` — `googleSheetsOAuthAuthorize()` method
- `frontend/src/components/Credentials/CredentialDialog.vue` — OAuth2 connect UI
- `frontend/src/components/Panels/PropertiesPanel.vue` — Google Sheets config block
- `frontend/src/components/Panels/NodePanel.vue` — add googleSheets node type entry
- `/Users/mbakgun/Projects/heym/heymweb/src/components/sections/LogoCarousel.tsx` — Google Sheets SVG
- `/Users/mbakgun/Projects/heym/heymweb/src/components/sections/NodesSection.tsx` — node entry
- `/Users/mbakgun/Projects/heym/heymweb/src/components/sections/FeaturesSection.tsx` — feature block
- `frontend/src/docs/content/reference/credentials.md` — google_sheets OAuth2 steps
- `frontend/src/docs/content/reference/integrations.md` — Google Sheets section
- `frontend/src/docs/content/reference/node-types.md` — Google Sheets row

---

## Task 1: DB Enum + Schema Models

**Files:**
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/models/schemas.py`
- Create: `backend/alembic/versions/055_add_google_sheets_credential_type.py`

- [ ] **Step 1: Add `google_sheets` to DB CredentialType enum**

In `backend/app/db/models.py`, find the `CredentialType` class (line ~26) and add:

```python
class CredentialType(str, PyEnum):
    openai = "openai"
    google = "google"
    custom = "custom"
    bearer = "bearer"
    header = "header"
    slack = "slack"
    smtp = "smtp"
    redis = "redis"
    qdrant = "qdrant"
    grist = "grist"
    rabbitmq = "rabbitmq"
    cohere = "cohere"
    flaresolverr = "flaresolverr"
    google_sheets = "google_sheets"   # ← add this line
```

- [ ] **Step 2: Add `google_sheets` to Pydantic CredentialType enum**

In `backend/app/models/schemas.py`, find `class CredentialType(str, Enum)` (~line 421) and add:

```python
class CredentialType(str, Enum):
    openai = "openai"
    google = "google"
    custom = "custom"
    bearer = "bearer"
    header = "header"
    slack = "slack"
    smtp = "smtp"
    redis = "redis"
    qdrant = "qdrant"
    grist = "grist"
    rabbitmq = "rabbitmq"
    cohere = "cohere"
    flaresolverr = "flaresolverr"
    google_sheets = "google_sheets"   # ← add this line
```

- [ ] **Step 3: Add `CredentialConfigGoogleSheets` Pydantic model to schemas.py**

After the `CredentialConfigFlaresolverr` class in `backend/app/models/schemas.py`, add:

```python
class CredentialConfigGoogleSheets(BaseModel):
    client_id: str
    client_secret: str
    access_token: str = ""
    refresh_token: str = ""
    token_expiry: str = ""
    scope: str = "https://www.googleapis.com/auth/spreadsheets"
```

- [ ] **Step 4: Create Alembic migration**

Create `backend/alembic/versions/055_add_google_sheets_credential_type.py`:

```python
"""add google_sheets credential type

Revision ID: 055
Revises: 054
Create Date: 2026-04-15
"""

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'google_sheets'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
```

- [ ] **Step 5: Run migration**

```bash
cd backend && uv run alembic upgrade head
```

Expected: `Running upgrade 054 -> 055, add google_sheets credential type`

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/app/models/schemas.py backend/alembic/versions/055_add_google_sheets_credential_type.py
git commit -m "feat(google-sheets): add google_sheets credential type and schema model"
```

---

## Task 2: GoogleSheetsService (TDD)

**Files:**
- Create: `backend/tests/test_google_sheets_service.py`
- Create: `backend/app/services/google_sheets_service.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_google_sheets_service.py`:

```python
"""Unit tests for GoogleSheetsService."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _make_config(expired: bool = False) -> dict:
    """Return a minimal encrypted_config dict."""
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
        "scope": "https://www.googleapis.com/auth/spreadsheets",
    }


class TestParseSpreadsheetId(unittest.TestCase):
    def setUp(self) -> None:
        from app.services.google_sheets_service import GoogleSheetsService
        self.svc_cls = GoogleSheetsService

    def test_bare_id_returned_as_is(self) -> None:
        result = self.svc_cls.parse_spreadsheet_id("1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms")
        self.assertEqual(result, "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms")

    def test_full_url_parsed_to_id(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit#gid=0"
        result = self.svc_cls.parse_spreadsheet_id(url)
        self.assertEqual(result, "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms")

    def test_url_without_trailing_path_parsed(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/abc123DEF_-456/edit"
        result = self.svc_cls.parse_spreadsheet_id(url)
        self.assertEqual(result, "abc123DEF_-456")


class TestTokenRefresh(unittest.TestCase):
    def _make_service(self, expired: bool = False):
        from app.services.google_sheets_service import GoogleSheetsService
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = MagicMock()
        return GoogleSheetsService("cred-id-1", _make_config(expired=expired), fake_db)

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


class TestReadRange(unittest.TestCase):
    def _make_service(self):
        from app.services.google_sheets_service import GoogleSheetsService
        fake_db = MagicMock()
        return GoogleSheetsService("cred-id-1", _make_config(), fake_db)

    def test_read_range_success(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "range": "Sheet1!A1:B2",
            "values": [["Name", "Age"], ["Alice", "30"]],
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_response):
            result = svc.read_range("spreadsheet-id", "Sheet1", "A1:B2")
        self.assertEqual(result["values"], [["Name", "Age"], ["Alice", "30"]])
        self.assertEqual(result["range"], "Sheet1!A1:B2")
        self.assertTrue(result["success"])


class TestAppendRows(unittest.TestCase):
    def _make_service(self):
        from app.services.google_sheets_service import GoogleSheetsService
        return GoogleSheetsService("cred-id-1", _make_config(), MagicMock())

    def test_append_rows_success(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "updates": {"updatedRange": "Sheet1!A3:B3", "updatedRows": 1}
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response):
            result = svc.append_rows("spreadsheet-id", "Sheet1", [["Bob", "25"]])
        self.assertEqual(result["updatedRows"], 1)
        self.assertEqual(result["updatedRange"], "Sheet1!A3:B3")
        self.assertTrue(result["success"])


class TestUpdateRange(unittest.TestCase):
    def _make_service(self):
        from app.services.google_sheets_service import GoogleSheetsService
        return GoogleSheetsService("cred-id-1", _make_config(), MagicMock())

    def test_update_range_success(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "updatedRange": "Sheet1!A1:B1",
            "updatedCells": 2,
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.put", return_value=mock_response):
            result = svc.update_range("spreadsheet-id", "Sheet1", "A1:B1", [["X", "Y"]])
        self.assertEqual(result["updatedCells"], 2)
        self.assertTrue(result["success"])


class TestClearRange(unittest.TestCase):
    def _make_service(self):
        from app.services.google_sheets_service import GoogleSheetsService
        return GoogleSheetsService("cred-id-1", _make_config(), MagicMock())

    def test_clear_range_success(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {"clearedRange": "Sheet1!A1:B2"}
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response):
            result = svc.clear_range("spreadsheet-id", "Sheet1", "A1:B2")
        self.assertEqual(result["clearedRange"], "Sheet1!A1:B2")
        self.assertTrue(result["success"])


class TestGetSheetInfo(unittest.TestCase):
    def _make_service(self):
        from app.services.google_sheets_service import GoogleSheetsService
        return GoogleSheetsService("cred-id-1", _make_config(), MagicMock())

    def test_get_sheet_info_success(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "sheets": [
                {"properties": {"title": "Sheet1", "sheetId": 0, "index": 0}},
                {"properties": {"title": "Data", "sheetId": 1, "index": 1}},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_response):
            result = svc.get_sheet_info("spreadsheet-id")
        self.assertEqual(len(result["sheets"]), 2)
        self.assertEqual(result["sheets"][0]["title"], "Sheet1")
        self.assertTrue(result["success"])
```

- [ ] **Step 2: Run tests — verify they all FAIL**

```bash
cd backend && uv run pytest tests/test_google_sheets_service.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'app.services.google_sheets_service'`

- [ ] **Step 3: Implement GoogleSheetsService**

Create `backend/app/services/google_sheets_service.py`:

```python
"""Google Sheets API client with OAuth2 token management."""

import re
from datetime import datetime, timedelta, timezone

import httpx

from app.services.encryption import encrypt_config

_SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


class GoogleSheetsService:
    """Sync Google Sheets API client.

    Manages token refresh and all Sheets v4 API operations.
    Uses sync httpx + sync DB session to match the existing executor pattern.
    """

    def __init__(self, credential_id: str, config: dict, db) -> None:
        """Initialise with decrypted credential config and an open sync DB session."""
        self._credential_id = credential_id
        self._config = dict(config)
        self._db = db

    @staticmethod
    def parse_spreadsheet_id(id_or_url: str) -> str:
        """Return spreadsheet ID from a full URL or bare ID string."""
        m = _SPREADSHEET_ID_RE.search(id_or_url)
        return m.group(1) if m else id_or_url.strip()

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

    def read_range(self, spreadsheet_id: str, sheet_name: str, range_a1: str) -> dict:
        """Read values from a sheet range. Returns {values, range, success}."""
        url = f"{_SHEETS_BASE}/{spreadsheet_id}/values/{sheet_name}!{range_a1}"
        resp = httpx.get(url, headers=self._auth_headers())
        resp.raise_for_status()
        data = resp.json()
        return {
            "values": data.get("values", []),
            "range": data.get("range", ""),
            "success": True,
        }

    def append_rows(self, spreadsheet_id: str, sheet_name: str, values: list) -> dict:
        """Append rows below the last row with data. Returns {updatedRange, updatedRows, success}."""
        url = f"{_SHEETS_BASE}/{spreadsheet_id}/values/{sheet_name}!A1:append"
        resp = httpx.post(
            url,
            headers=self._auth_headers(),
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            json={"values": values},
        )
        resp.raise_for_status()
        updates = resp.json().get("updates", {})
        return {
            "updatedRange": updates.get("updatedRange", ""),
            "updatedRows": updates.get("updatedRows", 0),
            "success": True,
        }

    def update_range(
        self, spreadsheet_id: str, sheet_name: str, range_a1: str, values: list
    ) -> dict:
        """Overwrite values in a range. Returns {updatedRange, updatedCells, success}."""
        url = f"{_SHEETS_BASE}/{spreadsheet_id}/values/{sheet_name}!{range_a1}"
        resp = httpx.put(
            url,
            headers=self._auth_headers(),
            params={"valueInputOption": "USER_ENTERED"},
            json={"range": f"{sheet_name}!{range_a1}", "values": values},
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "updatedRange": data.get("updatedRange", ""),
            "updatedCells": data.get("updatedCells", 0),
            "success": True,
        }

    def clear_range(self, spreadsheet_id: str, sheet_name: str, range_a1: str) -> dict:
        """Clear all values in a range. Returns {clearedRange, success}."""
        url = f"{_SHEETS_BASE}/{spreadsheet_id}/values/{sheet_name}!{range_a1}:clear"
        resp = httpx.post(url, headers=self._auth_headers())
        resp.raise_for_status()
        data = resp.json()
        return {"clearedRange": data.get("clearedRange", ""), "success": True}

    def get_sheet_info(self, spreadsheet_id: str) -> dict:
        """Fetch spreadsheet sheet list. Returns {sheets: [{title, sheetId, index}], success}."""
        url = f"{_SHEETS_BASE}/{spreadsheet_id}"
        resp = httpx.get(
            url,
            headers=self._auth_headers(),
            params={"fields": "sheets.properties"},
        )
        resp.raise_for_status()
        sheets = [
            {
                "title": s["properties"]["title"],
                "sheetId": s["properties"]["sheetId"],
                "index": s["properties"]["index"],
            }
            for s in resp.json().get("sheets", [])
        ]
        return {"sheets": sheets, "success": True}
```

- [ ] **Step 4: Run tests — verify they all PASS**

```bash
cd backend && uv run pytest tests/test_google_sheets_service.py -v
```

Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_google_sheets_service.py backend/app/services/google_sheets_service.py
git commit -m "feat(google-sheets): add GoogleSheetsService with token refresh"
```

---

## Task 3: OAuth2 Endpoints (TDD)

**Files:**
- Create: `backend/tests/test_google_sheets_oauth.py`
- Create: `backend/app/api/google_sheets_oauth.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_google_sheets_oauth.py`:

```python
"""Unit tests for Google Sheets OAuth2 endpoints."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from jose import jwt

# The secret key used in tests must match what settings.secret_key returns
_TEST_SECRET = "test-secret-key-for-tests-only"
_ALGORITHM = "HS256"


def _make_valid_state(
    user_id: str | None = None,
    credential_id: str | None = None,
    client_id: str = "test-client-id",
    client_secret: str = "test-secret",
    redirect_uri: str = "http://testserver/api/credentials/google-sheets/oauth/callback",
) -> str:
    return jwt.encode(
        {
            "user_id": user_id or str(uuid.uuid4()),
            "credential_id": credential_id,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "type": "gs_oauth_state",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        _TEST_SECRET,
        algorithm=_ALGORITHM,
    )


def _make_expired_state() -> str:
    return jwt.encode(
        {
            "user_id": str(uuid.uuid4()),
            "credential_id": None,
            "client_id": "c",
            "client_secret": "s",
            "redirect_uri": "http://testserver/api/credentials/google-sheets/oauth/callback",
            "type": "gs_oauth_state",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        },
        _TEST_SECRET,
        algorithm=_ALGORITHM,
    )


class TestGoogleSheetsOAuthAuthorize(unittest.IsolatedAsyncioTestCase):
    async def test_authorize_returns_auth_url(self) -> None:
        from app.api.google_sheets_oauth import build_auth_url

        with patch("app.api.google_sheets_oauth.settings") as mock_settings:
            mock_settings.secret_key = _TEST_SECRET
            mock_settings.jwt_algorithm = _ALGORITHM
            auth_url = build_auth_url(
                client_id="my-client-id",
                redirect_uri="http://testserver/api/credentials/google-sheets/oauth/callback",
                state="some-state",
            )

        self.assertIn("accounts.google.com", auth_url)
        self.assertIn("my-client-id", auth_url)
        self.assertIn("spreadsheets", auth_url)
        self.assertIn("offline", auth_url)

    async def test_authorize_state_is_valid_jwt(self) -> None:
        from app.api.google_sheets_oauth import create_oauth_state

        with patch("app.api.google_sheets_oauth.settings") as mock_settings:
            mock_settings.secret_key = _TEST_SECRET
            mock_settings.jwt_algorithm = _ALGORITHM
            state = create_oauth_state(
                user_id=str(uuid.uuid4()),
                credential_id=None,
                client_id="cid",
                client_secret="csecret",
                redirect_uri="http://testserver/callback",
            )

        decoded = jwt.decode(state, _TEST_SECRET, algorithms=[_ALGORITHM])
        self.assertEqual(decoded["type"], "gs_oauth_state")
        self.assertEqual(decoded["client_id"], "cid")


class TestGoogleSheetsOAuthCallback(unittest.IsolatedAsyncioTestCase):
    async def test_callback_invalid_state_returns_error_html(self) -> None:
        from app.api.google_sheets_oauth import handle_callback_state

        with patch("app.api.google_sheets_oauth.settings") as mock_settings:
            mock_settings.secret_key = _TEST_SECRET
            mock_settings.jwt_algorithm = _ALGORITHM
            result = handle_callback_state("not-a-valid-jwt")

        self.assertIsNone(result)

    async def test_callback_expired_state_returns_none(self) -> None:
        from app.api.google_sheets_oauth import handle_callback_state

        with patch("app.api.google_sheets_oauth.settings") as mock_settings:
            mock_settings.secret_key = _TEST_SECRET
            mock_settings.jwt_algorithm = _ALGORITHM
            expired = _make_expired_state()
            result = handle_callback_state(expired)

        self.assertIsNone(result)

    async def test_callback_valid_state_returns_payload(self) -> None:
        from app.api.google_sheets_oauth import handle_callback_state

        user_id = str(uuid.uuid4())
        valid_state = _make_valid_state(user_id=user_id, client_id="cid", client_secret="cs")

        with patch("app.api.google_sheets_oauth.settings") as mock_settings:
            mock_settings.secret_key = _TEST_SECRET
            mock_settings.jwt_algorithm = _ALGORITHM
            result = handle_callback_state(valid_state)

        self.assertIsNotNone(result)
        self.assertEqual(result["user_id"], user_id)
        self.assertEqual(result["client_id"], "cid")
```

- [ ] **Step 2: Run tests — verify they FAIL**

```bash
cd backend && uv run pytest tests/test_google_sheets_oauth.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'build_auth_url' from 'app.api.google_sheets_oauth'`

- [ ] **Step 3: Implement OAuth2 endpoints**

Create `backend/app/api/google_sheets_oauth.py`:

```python
"""Google Sheets OAuth2 authorization and callback endpoints."""

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db.models import Credential, CredentialType, User
from app.db.session import get_db
from app.services.encryption import encrypt_config

router = APIRouter()

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
_STATE_TYPE = "gs_oauth_state"
_STATE_TTL_MINUTES = 10


class AuthorizeRequest(BaseModel):
    client_id: str
    client_secret: str
    credential_id: str | None = None


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
    """Build the Google OAuth2 authorization URL."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _SHEETS_SCOPE,
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
        script = f"""
            if (window.opener) {{
                window.opener.postMessage(
                    {{type: 'google-oauth-error', message: '{message}'}},
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
) -> dict:
    """Return the Google OAuth2 authorization URL for the popup flow."""
    redirect_uri = str(request.base_url).rstrip("/") + "/api/credentials/google-sheets/oauth/callback"
    state = create_oauth_state(
        user_id=str(current_user.id),
        credential_id=str(body.credential_id) if body.credential_id else None,
        client_id=body.client_id,
        client_secret=body.client_secret,
        redirect_uri=redirect_uri,
    )
    auth_url = build_auth_url(body.client_id, redirect_uri, state)
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

    # Exchange code for tokens
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
        "scope": _SHEETS_SCOPE,
    }
    encrypted = encrypt_config(config)

    from sqlalchemy import select

    if credential_id:
        cred_uuid = uuid.UUID(credential_id)
        result = await db.execute(select(Credential).where(Credential.id == cred_uuid))
        cred = result.scalar_one_or_none()
        if cred:
            cred.encrypted_config = encrypted
            await db.commit()
            return HTMLResponse(_popup_html(True, credential_id=str(cred.id)))

    # Create new credential
    new_cred = Credential(
        name="Google Sheets",
        type=CredentialType.google_sheets,
        owner_id=user_id,
        encrypted_config=encrypted,
    )
    db.add(new_cred)
    await db.commit()
    await db.refresh(new_cred)
    return HTMLResponse(_popup_html(True, credential_id=str(new_cred.id)))
```

- [ ] **Step 4: Register router in `backend/app/main.py`**

Add import and router registration in `backend/app/main.py`:

```python
# Add to existing imports at top:
from app.api import google_sheets_oauth   # add to the existing import block

# Add after the other router includes (e.g., after `app.include_router(oauth.router, ...)`):
app.include_router(
    google_sheets_oauth.router,
    prefix="/api/credentials/google-sheets/oauth",
    tags=["google-sheets-oauth"],
)
```

In the existing `from app.api import (...)` block, add `google_sheets_oauth` to the list.

- [ ] **Step 5: Run tests — verify they PASS**

```bash
cd backend && uv run pytest tests/test_google_sheets_oauth.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
cd backend && uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/google_sheets_oauth.py backend/tests/test_google_sheets_oauth.py backend/app/main.py
git commit -m "feat(google-sheets): add OAuth2 authorize/callback endpoints"
```

---

## Task 4: Executor Handler + Credentials Masking

**Files:**
- Modify: `backend/app/services/workflow_executor.py`
- Modify: `backend/app/api/credentials.py`

- [ ] **Step 1: Add `google_sheets` to `get_masked_value()` in credentials.py**

In `backend/app/api/credentials.py`, find the `get_masked_value` function and add a case for `google_sheets`. The masked value should show the masked `client_id`:

```python
def get_masked_value(credential_type: CredentialType, config: dict) -> str | None:
    if credential_type == CredentialType.header:
        header_value = config.get("header_value", "")
        return mask_api_key(header_value)
    if credential_type == CredentialType.slack:
        webhook_url = config.get("webhook_url", "")
        return mask_api_key(webhook_url)
    elif credential_type in (CredentialType.openai, CredentialType.google, CredentialType.custom):
        api_key = config.get("api_key", "")
        return mask_api_key(api_key)
    elif credential_type == CredentialType.qdrant:
        openai_api_key = config.get("openai_api_key", "")
        return mask_api_key(openai_api_key)
    elif credential_type == CredentialType.grist:
        api_key = config.get("api_key", "")
        return mask_api_key(api_key)
    elif credential_type == CredentialType.flaresolverr:
        flaresolverr_url = config.get("flaresolverr_url", "")
        return mask_api_key(flaresolverr_url)
    elif credential_type == CredentialType.google_sheets:   # ← add this
        client_id = config.get("client_id", "")
        return mask_api_key(client_id)
    return None
```

- [ ] **Step 2: Add executor handler for `googleSheets` node**

In `backend/app/services/workflow_executor.py`, find the large `elif node_type ==` chain (search for `elif node_type == "grist":`). Add the `googleSheets` handler directly after the `grist` block:

```python
            elif node_type == "googleSheets":
                import json as _json

                from app.db.models import Credential
                from app.db.session import SessionLocal
                from app.services.encryption import decrypt_config
                from app.services.google_sheets_service import GoogleSheetsService

                credential_id = node_data.get("credentialId")
                if not credential_id:
                    raise ValueError("Google Sheets node requires a credential")

                gs_config: dict = {}
                with SessionLocal() as db:
                    cred = db.query(Credential).filter(Credential.id == credential_id).first()
                    if cred:
                        gs_config = decrypt_config(cred.encrypted_config)

                if not gs_config:
                    raise ValueError("Google Sheets credential not found or invalid")

                operation = node_data.get("gsOperation", "")
                if not operation:
                    raise ValueError("Google Sheets node requires an operation")

                raw_id = self.evaluate_message_template(
                    node_data.get("gsSpreadsheetId", ""), inputs, node_id
                )
                spreadsheet_id = GoogleSheetsService.parse_spreadsheet_id(raw_id)
                sheet_name = self.evaluate_message_template(
                    node_data.get("gsSheetName", "Sheet1"), inputs, node_id
                )
                range_a1 = self.evaluate_message_template(
                    node_data.get("gsRange", ""), inputs, node_id
                )

                with SessionLocal() as db:
                    service = GoogleSheetsService(credential_id, gs_config, db)

                    if operation == "readRange":
                        output = service.read_range(spreadsheet_id, sheet_name, range_a1)
                    elif operation == "appendRows":
                        raw_values = self.evaluate_message_template(
                            node_data.get("gsValues", "[]"), inputs, node_id
                        )
                        values = _json.loads(raw_values)
                        output = service.append_rows(spreadsheet_id, sheet_name, values)
                    elif operation == "updateRange":
                        raw_values = self.evaluate_message_template(
                            node_data.get("gsValues", "[]"), inputs, node_id
                        )
                        values = _json.loads(raw_values)
                        output = service.update_range(spreadsheet_id, sheet_name, range_a1, values)
                    elif operation == "clearRange":
                        output = service.clear_range(spreadsheet_id, sheet_name, range_a1)
                    elif operation == "getSheetInfo":
                        output = service.get_sheet_info(spreadsheet_id)
                    else:
                        raise ValueError(f"Unknown Google Sheets operation: {operation}")
```

- [ ] **Step 3: Verify ruff passes**

```bash
cd backend && uv run ruff check app/services/workflow_executor.py app/api/credentials.py
```

Expected: No errors.

- [ ] **Step 4: Run full test suite**

```bash
cd backend && uv run pytest tests/ --tb=short 2>&1 | tail -10
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflow_executor.py backend/app/api/credentials.py
git commit -m "feat(google-sheets): add googleSheets executor handler and credential masking"
```

---

## Task 5: Frontend — Types, Icons, CSS

**Files:**
- Modify: `frontend/src/types/credential.ts`
- Modify: `frontend/src/types/node.ts`
- Modify: `frontend/src/lib/nodeIcons.ts`
- Modify: `frontend/src/styles/globals.css`

- [ ] **Step 1: Update `credential.ts`**

In `frontend/src/types/credential.ts`:

1. Add `"google_sheets"` to `CredentialType`:
```typescript
export type CredentialType =
  | "openai"
  | "google"
  | "custom"
  | "bearer"
  | "header"
  | "slack"
  | "smtp"
  | "redis"
  | "qdrant"
  | "grist"
  | "rabbitmq"
  | "cohere"
  | "flaresolverr"
  | "google_sheets";
```

2. Add `CredentialConfigGoogleSheets` interface (after `CredentialConfigFlaresolverr`):
```typescript
export interface CredentialConfigGoogleSheets {
  client_id: string;
  client_secret: string;
  access_token?: string;
  refresh_token?: string;
  token_expiry?: string;
  scope?: string;
}
```

3. Add to `CredentialConfig` union:
```typescript
export type CredentialConfig =
  | CredentialConfigOpenAI
  | CredentialConfigGoogle
  | CredentialConfigCustom
  | CredentialConfigBearer
  | CredentialConfigHeader
  | CredentialConfigSlack
  | CredentialConfigSmtp
  | CredentialConfigRedis
  | CredentialConfigQdrant
  | CredentialConfigGrist
  | CredentialConfigRabbitmq
  | CredentialConfigCohere
  | CredentialConfigFlaresolverr
  | CredentialConfigGoogleSheets;
```

4. Add to `CREDENTIAL_TYPE_LABELS`:
```typescript
google_sheets: "Google Sheets (OAuth2)",
```

5. Add to `CREDENTIAL_TYPE_DESCRIPTIONS`:
```typescript
google_sheets: "Connect to Google Sheets via OAuth2 — read, write, append, and query spreadsheets",
```

- [ ] **Step 2: Add `googleSheets` node default to `node.ts`**

In `frontend/src/types/node.ts`, find the location where other node defaults are defined (look for `grist:` entry) and add after it:

```typescript
googleSheets: {
  type: "googleSheets",
  color: "node-google-sheets",
  defaultData: {
    label: "googleSheets",
    credentialId: "",
    gsOperation: undefined as string | undefined,
    gsSpreadsheetId: "",
    gsSheetName: "Sheet1",
    gsRange: "A1:Z100",
    gsValues: "[]",
  },
},
```

- [ ] **Step 3: Add icon and colour to `nodeIcons.ts`**

In `frontend/src/lib/nodeIcons.ts`, find where `Table2` is imported (used for `grist`) and add `Sheet` to the same import or add its own import. Then add entries:

```typescript
// In the icons map:
googleSheets: Sheet,

// In the colour class map:
googleSheets: "text-node-google-sheets",
```

If `Sheet` is not in the existing lucide import, add it:
```typescript
import { ..., Sheet } from 'lucide-vue-next'
```

- [ ] **Step 4: Add CSS variable to `globals.css`**

In `frontend/src/styles/globals.css`, find the existing node colour variables (look for `--node-grist` or similar) and add:

```css
--node-google-sheets: 140 72% 35%;
```

(HSL for Google Sheets green `#0F9D58`.)

- [ ] **Step 5: Typecheck frontend**

```bash
cd frontend && bun run typecheck
```

Expected: No type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/credential.ts frontend/src/types/node.ts frontend/src/lib/nodeIcons.ts frontend/src/styles/globals.css
git commit -m "feat(google-sheets): add frontend types, icon, and CSS colour"
```

---

## Task 6: Frontend — CredentialDialog OAuth2 Flow

**Files:**
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/components/Credentials/CredentialDialog.vue`

- [ ] **Step 1: Add `googleSheetsOAuthAuthorize` to `api.ts`**

In `frontend/src/services/api.ts`, find the `credentialsApi` object and add:

```typescript
googleSheetsOAuthAuthorize: async (
  clientId: string,
  clientSecret: string,
  credentialId?: string
): Promise<{ auth_url: string; state: string }> => {
  const response = await axios.post(
    `${API_BASE}/credentials/google-sheets/oauth/authorize`,
    { client_id: clientId, client_secret: clientSecret, credential_id: credentialId ?? null },
    { headers: { Authorization: `Bearer ${getToken()}` } }
  );
  return response.data;
},
```

- [ ] **Step 2: Add `google_sheets` refs and form to `CredentialDialog.vue`**

In `frontend/src/components/Credentials/CredentialDialog.vue`:

**Add refs** (after the existing `flaresolverrUrl` ref):
```typescript
const gsClientId = ref("");
const gsClientSecret = ref("");
const gsIsConnected = ref(false);
const gsCredentialId = ref("");
```

**Add to `typeOptions` array** (after `flaresolverr` entry):
```typescript
{ value: "google_sheets", label: CREDENTIAL_TYPE_LABELS.google_sheets },
```

**Add OAuth connect function** (before the `save` function):
```typescript
const startGoogleSheetsOAuth = async (): Promise<void> => {
  if (!gsClientId.value || !gsClientSecret.value) {
    error.value = "Client ID and Client Secret are required";
    return;
  }
  error.value = "";
  try {
    const { auth_url } = await credentialsApi.googleSheetsOAuthAuthorize(
      gsClientId.value,
      gsClientSecret.value,
      gsCredentialId.value || undefined
    );
    const popup = window.open(auth_url, "google-oauth", "width=600,height=700,scrollbars=yes");
    const handleMessage = (event: MessageEvent): void => {
      if (event.data?.type === "google-oauth-success") {
        gsIsConnected.value = true;
        gsCredentialId.value = event.data.credentialId as string;
        window.removeEventListener("message", handleMessage);
        popup?.close();
      } else if (event.data?.type === "google-oauth-error") {
        error.value = (event.data.message as string) || "OAuth failed";
        window.removeEventListener("message", handleMessage);
      }
    };
    window.addEventListener("message", handleMessage);
  } catch (e) {
    error.value = "Failed to start Google OAuth";
  }
};
```

**Add form template** — in the `<template>` section, after the flaresolverr form block and before the save button area, add:

```html
<!-- Google Sheets OAuth2 -->
<template v-if="type === 'google_sheets'">
  <div class="space-y-3">
    <div v-if="gsIsConnected" class="flex items-center gap-2 p-3 rounded-lg bg-green-500/10 border border-green-500/30">
      <span class="text-green-600 text-sm font-medium">✓ Connected to Google Sheets</span>
      <Button variant="outline" size="sm" class="ml-auto" @click="startGoogleSheetsOAuth">Re-connect</Button>
    </div>
    <div v-else>
      <div class="space-y-2">
        <Label>Google Client ID <span class="text-destructive">*</span></Label>
        <Input v-model="gsClientId" placeholder="1234567890.apps.googleusercontent.com" />
      </div>
      <div class="space-y-2 mt-2">
        <Label>Google Client Secret <span class="text-destructive">*</span></Label>
        <Input v-model="gsClientSecret" type="password" placeholder="GOCSPX-..." />
      </div>
      <Button class="w-full mt-3" @click="startGoogleSheetsOAuth">
        Connect with Google
      </Button>
      <p class="text-xs text-muted-foreground mt-2">
        Create credentials at
        <a href="https://console.cloud.google.com/apis/credentials" target="_blank" class="text-primary hover:underline">Google Cloud Console</a>.
        Enable the Google Sheets API and add your server's callback URL as an authorised redirect URI.
      </p>
    </div>
  </div>
</template>
```

**Update reset logic** — in the `watch(() => props.open, ...)` handler, reset Google Sheets refs:
```typescript
gsClientId.value = "";
gsClientSecret.value = "";
gsIsConnected.value = false;
gsCredentialId.value = "";
```

**Update save logic** — the `google_sheets` credential is saved by the OAuth callback (not the save button). Guard the save function:
```typescript
if (type.value === "google_sheets") {
  if (!gsIsConnected.value) {
    error.value = "Please connect with Google first";
    return;
  }
  // credential already saved by callback — just close
  emit("saved", { id: gsCredentialId.value, name: name.value, type: "google_sheets", masked_value: null, header_key: null, created_at: new Date().toISOString() });
  emit("close");
  return;
}
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: No errors.

- [ ] **Step 4: Lint**

```bash
cd frontend && bun run lint
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/api.ts frontend/src/components/Credentials/CredentialDialog.vue
git commit -m "feat(google-sheets): add OAuth2 credential connect UI"
```

---

## Task 7: Frontend — PropertiesPanel Node Config

**Files:**
- Modify: `frontend/src/components/Panels/PropertiesPanel.vue`

- [ ] **Step 1: Add reactive refs and credential loading**

In `PropertiesPanel.vue`, in the `<script setup>` block, add after the `gristCredentials` ref:

```typescript
const googleSheetsCredentials = ref<CredentialListItem[]>([]);
const gsSpreadsheetIdRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const gsSheetNameRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const gsRangeRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const gsValuesRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
```

In the `watch(selectedNode, ...)` (or equivalent `onNodeTypeChange`) block, alongside the grist loading:

```typescript
if (type === "googleSheets") {
  try {
    googleSheetsCredentials.value = await credentialsApi.listByType("google_sheets");
  } catch {
    googleSheetsCredentials.value = [];
  }
}
```

Add computed options:
```typescript
const googleSheetsCredentialOptions = computed(() =>
  googleSheetsCredentials.value.map((c) => ({ value: c.id, label: c.name }))
);

const gsOperationOptions = [
  { value: "readRange", label: "Read Range" },
  { value: "appendRows", label: "Append Rows" },
  { value: "updateRange", label: "Update Range" },
  { value: "clearRange", label: "Clear Range" },
  { value: "getSheetInfo", label: "Get Sheet Info" },
];
```

- [ ] **Step 2: Add template block in PropertiesPanel**

In the `<template>` section, find `<template v-if="selectedNode.type === 'grist'">` and add a new block directly after it (before the closing `</template>` of the grist block's parent):

```html
<template v-if="selectedNode.type === 'googleSheets'">
  <div class="space-y-2">
    <Label>Credential</Label>
    <Select
      :model-value="selectedNode.data.credentialId || ''"
      :options="googleSheetsCredentialOptions"
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
      :model-value="selectedNode.data.gsOperation || ''"
      :options="gsOperationOptions"
      @update:model-value="updateNodeData('gsOperation', $event)"
    />
    <p
      v-if="!selectedNode.data.gsOperation"
      class="text-xs text-amber-500 flex items-center gap-1"
    >
      <AlertTriangle class="h-3 w-3" />
      Operation is required
    </p>
  </div>

  <div class="space-y-2">
    <Label>Spreadsheet ID or URL <span class="text-destructive">*</span></Label>
    <ExpressionInput
      ref="gsSpreadsheetIdRef"
      :model-value="selectedNode.data.gsSpreadsheetId || ''"
      placeholder="Paste spreadsheet URL or ID"
      :rows="1"
      :nodes="workflowStore.nodes"
      :node-results="workflowStore.nodeResults"
      :edges="workflowStore.edges"
      :current-node-id="selectedNode.id"
      :navigation-enabled="false"
      dialog-key-label="Spreadsheet ID or URL"
      @update:model-value="updateNodeData('gsSpreadsheetId', $event)"
    />
    <p class="text-xs text-muted-foreground">Full URL or bare spreadsheet ID both accepted</p>
  </div>

  <div
    v-if="selectedNode.data.gsOperation && selectedNode.data.gsOperation !== 'getSheetInfo'"
    class="space-y-2"
  >
    <Label>Sheet Name <span class="text-destructive">*</span></Label>
    <ExpressionInput
      ref="gsSheetNameRef"
      :model-value="selectedNode.data.gsSheetName || 'Sheet1'"
      placeholder="Sheet1"
      :rows="1"
      :nodes="workflowStore.nodes"
      :node-results="workflowStore.nodeResults"
      :edges="workflowStore.edges"
      :current-node-id="selectedNode.id"
      :navigation-enabled="false"
      dialog-key-label="Sheet Name"
      @update:model-value="updateNodeData('gsSheetName', $event)"
    />
  </div>

  <div
    v-if="selectedNode.data.gsOperation === 'readRange' || selectedNode.data.gsOperation === 'updateRange' || selectedNode.data.gsOperation === 'clearRange'"
    class="space-y-2"
  >
    <Label>Range (A1 notation) <span class="text-destructive">*</span></Label>
    <ExpressionInput
      ref="gsRangeRef"
      :model-value="selectedNode.data.gsRange || 'A1:Z100'"
      placeholder="A1:D10"
      :rows="1"
      :nodes="workflowStore.nodes"
      :node-results="workflowStore.nodeResults"
      :edges="workflowStore.edges"
      :current-node-id="selectedNode.id"
      :navigation-enabled="false"
      dialog-key-label="Range"
      @update:model-value="updateNodeData('gsRange', $event)"
    />
    <p class="text-xs text-muted-foreground">e.g. A1:D10 or A:A</p>
  </div>

  <div
    v-if="selectedNode.data.gsOperation === 'appendRows' || selectedNode.data.gsOperation === 'updateRange'"
    class="space-y-2"
  >
    <Label>Values (JSON array of arrays) <span class="text-destructive">*</span></Label>
    <ExpressionInput
      ref="gsValuesRef"
      :model-value="selectedNode.data.gsValues || '[]'"
      placeholder='[["Name", "Age"], ["Alice", "30"]]'
      :rows="3"
      :nodes="workflowStore.nodes"
      :node-results="workflowStore.nodeResults"
      :edges="workflowStore.edges"
      :current-node-id="selectedNode.id"
      :navigation-enabled="false"
      dialog-key-label="Values"
      @update:model-value="updateNodeData('gsValues', $event)"
    />
    <p class="text-xs text-muted-foreground">Array of rows, each row is an array of cell values</p>
  </div>
</template>
```

- [ ] **Step 3: Add googleSheets entry to NodePanel node list**

In `frontend/src/components/Panels/NodePanel.vue`, find where `grist` node type is listed in the integrations section and add `googleSheets` alongside it using the same pattern.

- [ ] **Step 4: Typecheck + lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Panels/PropertiesPanel.vue frontend/src/components/Panels/NodePanel.vue
git commit -m "feat(google-sheets): add PropertiesPanel config block and NodePanel entry"
```

---

## Task 8: DSL Prompt Update

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py`

- [ ] **Step 1: Add Google Sheets node section**

In `backend/app/services/workflow_dsl_prompt.py`, find the Grist node section (search for `## Grist Node` or `type: "grist"`). Add a new section directly after the entire Grist section:

```python
# In WORKFLOW_DSL_SYSTEM_PROMPT, after the Grist section:

"""
---

## Google Sheets Node

Read, write, and query Google Spreadsheets.

```
"type": "googleSheets"
"data": {
  "label": "camelCaseLabel",
  "credentialId": "<google_sheets-credential-uuid>",
  "gsOperation": "readRange" | "appendRows" | "updateRange" | "clearRange" | "getSheetInfo",
  "gsSpreadsheetId": "<spreadsheet ID or full URL — expressions supported>",
  "gsSheetName": "<sheet tab name, e.g. Sheet1>",
  "gsRange": "<A1 notation, e.g. A1:D10>",   // readRange, updateRange, clearRange
  "gsValues": "<JSON array of arrays>"         // appendRows, updateRange
}
```

### Output Fields

| Operation | Output |
|---|---|
| `readRange` | `$label.values` (list of lists), `$label.range`, `$label.success` |
| `appendRows` | `$label.updatedRange`, `$label.updatedRows`, `$label.success` |
| `updateRange` | `$label.updatedRange`, `$label.updatedCells`, `$label.success` |
| `clearRange` | `$label.clearedRange`, `$label.success` |
| `getSheetInfo` | `$label.sheets` (list of `{title, sheetId, index}`), `$label.success` |

### Notes
- `gsSpreadsheetId` accepts a full Google Sheets URL **or** a bare spreadsheet ID
- `gsValues` must be a JSON string of an array of arrays: `"[[\\"Name\\", \\"Age\\"], [\\"Alice\\", \\"30\\"]]"`
- Credentials are set up via OAuth2 in the Credentials panel (type: Google Sheets)

### Example — Read Range and Summarise with LLM

```json
[
  {"id": "n1", "type": "textInput", "position": {"x": 100, "y": 100}, "data": {"label": "userQuery", "inputFields": [{"key": "text"}]}},
  {"id": "n2", "type": "googleSheets", "position": {"x": 350, "y": 100}, "data": {"label": "readSheet", "credentialId": "gs-credential-uuid", "gsOperation": "readRange", "gsSpreadsheetId": "https://docs.google.com/spreadsheets/d/YOUR_ID/edit", "gsSheetName": "Sheet1", "gsRange": "A1:D50"}},
  {"id": "n3", "type": "llm", "position": {"x": 600, "y": 100}, "data": {"label": "summarise", "credentialId": "llm-credential-uuid", "model": "gpt-4o", "systemInstruction": "Summarise the following spreadsheet data.", "userMessage": "$readSheet.values"}},
  {"id": "n4", "type": "output", "position": {"x": 850, "y": 100}, "data": {"label": "finalOutput", "message": "$summarise.text"}}
]
```

### Example — Append LLM Output to Sheet

```json
[
  {"id": "n1", "type": "textInput", "position": {"x": 100, "y": 100}, "data": {"label": "formData", "inputFields": [{"key": "name"}, {"key": "email"}]}},
  {"id": "n2", "type": "googleSheets", "position": {"x": 350, "y": 100}, "data": {"label": "appendRow", "credentialId": "gs-credential-uuid", "gsOperation": "appendRows", "gsSpreadsheetId": "YOUR_SPREADSHEET_ID", "gsSheetName": "Responses", "gsValues": "[[$formData.body.name, $formData.body.email]]"}},
  {"id": "n3", "type": "output", "position": {"x": 600, "y": 100}, "data": {"label": "done", "message": "Row added: $appendRow.updatedRange"}}
]
```
"""
```

- [ ] **Step 2: Verify the file loads without syntax error**

```bash
cd backend && python -c "from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT; print('OK', len(WORKFLOW_DSL_SYSTEM_PROMPT))"
```

Expected: `OK <number>`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py
git commit -m "feat(google-sheets): add Google Sheets node DSL prompt documentation"
```

---

## Task 9: heymweb — Landing Page Updates

**Files (in `/Users/mbakgun/Projects/heym/heymweb`):**
- Modify: `src/components/sections/LogoCarousel.tsx`
- Modify: `src/components/sections/NodesSection.tsx`
- Modify: `src/components/sections/FeaturesSection.tsx`

- [ ] **Step 1: Add Google Sheets logo to LogoCarousel**

In `/Users/mbakgun/Projects/heym/heymweb/src/components/sections/LogoCarousel.tsx`, add to the `integrations` array (after the `RabbitMQ` entry):

```tsx
{
  name: 'Google Sheets',
  logo: (
    <svg viewBox="0 0 24 24" fill="currentColor" className="w-6 h-6">
      <path d="M11.318 0H2.25C1.009 0 0 1.009 0 2.25v19.5C0 22.992 1.009 24 2.25 24h19.5C22.992 24 24 22.992 24 21.75V12.682L11.318 0z" fill="#23A566"/>
      <path d="M11.318 0l12.68 12.682H14.25c-1.59 0-2.932-1.342-2.932-2.932V0z" fill="#159E56"/>
      <path d="M6 13.5h12v1.5H6v-1.5zm0 3h12v1.5H6V16.5zm0-6h12V12H6v-1.5zm0-3h6V9H6V7.5z" fill="white"/>
    </svg>
  ),
},
```

- [ ] **Step 2: Add Google Sheets node to NodesSection**

In `/Users/mbakgun/Projects/heym/heymweb/src/components/sections/NodesSection.tsx`:

1. Add `Sheet` to the lucide import at the top:
```tsx
import { ..., Sheet } from 'lucide-react'
```

2. In the `integrations` category `nodes` array, add after the `Grist` entry:
```tsx
{
  icon: Sheet,
  name: 'Google Sheets',
  description: 'Read, write, append, and update Google Sheets via OAuth2. Supports range queries, row appending, and sheet metadata — connect your Google account, no API key required.'
},
```

- [ ] **Step 3: Add feature block to FeaturesSection**

In `/Users/mbakgun/Projects/heym/heymweb/src/components/sections/FeaturesSection.tsx`, read the existing file structure and add a Google Sheets feature entry matching the pattern of existing feature items:

```tsx
{
  icon: Sheet,
  title: 'Automate Google Sheets',
  description: 'Connect your Google Sheets directly to your AI workflows via OAuth2. Read rows into prompts, append LLM outputs as new rows, update ranges programmatically, or query sheet structure — all without managing API keys.',
  bullets: [
    'Read ranges into workflow context',
    'Append LLM or form outputs as new rows',
    'Update and clear ranges dynamically',
    'OAuth2 — no API keys, just connect your account',
  ],
},
```

Add `Sheet` to the lucide import in this file too.

- [ ] **Step 4: Build heymweb to verify no TypeScript errors**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npm run build 2>&1 | tail -20
```

Expected: Build succeeds with no type errors.

- [ ] **Step 5: Commit (in heymweb repo)**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/components/sections/LogoCarousel.tsx src/components/sections/NodesSection.tsx src/components/sections/FeaturesSection.tsx
git commit -m "feat: add Google Sheets to integrations, nodes, and feature section"
```

---

## Task 10: Documentation (heym-documentation skill)

**Files:**
- Create: `frontend/src/docs/content/nodes/google-sheets-node.md`
- Modify: `frontend/src/docs/content/reference/credentials.md`
- Modify: `frontend/src/docs/content/reference/integrations.md`
- Modify: `frontend/src/docs/content/reference/node-types.md`

- [ ] **Step 1: Invoke `heym-documentation` skill**

Use the `heym-documentation` skill to write all documentation. The skill knows the existing doc format, nav structure, and writing style.

Brief for the skill:
- **New file:** `google-sheets-node.md` — full node reference (parameters table, operations, output fields, 2 complete examples, related links to credentials and integrations)
- **Update:** `credentials.md` — add `google_sheets` section with step-by-step OAuth2 setup (Google Cloud Console → enable Sheets API → create OAuth credentials → add redirect URI `{your-backend-url}/api/credentials/google-sheets/oauth/callback` → connect in Heym dashboard)
- **Update:** `integrations.md` — add Google Sheets section with credential type, scopes, and redirect URI instructions
- **Update:** `node-types.md` — add Google Sheets row to the integrations table

- [ ] **Step 2: Commit docs**

```bash
git add frontend/src/docs/
git commit -m "docs: add Google Sheets node documentation"
```

---

## Task 11: Final Checks

- [ ] **Step 1: Full backend check**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && ./check.sh
```

Expected: Ruff format + lint pass, all tests pass.

- [ ] **Step 2: Frontend typecheck + lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: No errors.

- [ ] **Step 3: Manual smoke test (dev server)**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && ./run.sh
```

- Open `http://localhost:4017`
- Dashboard → Credentials → New → select "Google Sheets (OAuth2)" → enter a test Client ID/Secret → click "Connect with Google" → verify popup opens
- Editor → drag a Google Sheets node → select the credential → choose "readRange" → verify fields appear

- [ ] **Step 4: Final commit if any stray formatting diffs**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
git add -p   # review any ruff format-only changes
git commit -m "chore: apply ruff formatting"
```
