# Google Sheets Node — Design Spec
**Date:** 2026-04-15  
**Status:** Approved

---

## Overview

Add a Google Sheets node to Heym that enables workflows to read, write, append, and query Google Spreadsheets via the Google Sheets API v4. OAuth2 is used for authentication — users bring their own Google Cloud project credentials (Client ID + Client Secret), Heym manages token acquisition, storage, and refresh transparently.

---

## Decisions Made

| Question | Decision |
|---|---|
| OAuth2 model | "Bring Your Own App" — user provides Google Cloud Client ID + Secret |
| Operations | Basic set: readRange, appendRows, updateRange, clearRange, getSheetInfo |
| OAuth consent flow | Popup (`window.open`) + `postMessage` back to parent |
| Spreadsheet reference | ID or full URL accepted; frontend/backend normalises to ID |

---

## Architecture

### OAuth2 Consent Flow

```
User                  Frontend                  Backend                  Google API
 │                        │                          │                        │
 │ Select "Google Sheets" │                          │                        │
 │ Enter Client ID/Secret │                          │                        │
 │ Click "Connect"        │                          │                        │
 │───────────────────────>│ POST /api/credentials/   │                        │
 │                        │  google-sheets/oauth/    │                        │
 │                        │  authorize               │                        │
 │                        │─────────────────────────>│ Build auth_url         │
 │                        │<─────────────────────────│ {auth_url, state}      │
 │                        │ window.open(auth_url)    │                        │
 │              [popup opens]                        │                        │
 │ User grants consent in Google                     │                        │
 │                        │   GET /api/credentials/google-sheets/oauth/callback?code=&state=
 │                        │                          │<───────────────────────│
 │                        │                          │ Exchange code → tokens │
 │                        │                          │ Save/update Credential │
 │                        │ postMessage({success})   │                        │
 │                        │<─────────────────────────│ HTML script response   │
 │              [popup closes]                        │                        │
 │ "Connected ✓" shown    │                          │                        │
```

### Credential `encrypted_config` Schema

```json
{
  "client_id": "1234.apps.googleusercontent.com",
  "client_secret": "GOCSPX-...",
  "access_token": "ya29...",
  "refresh_token": "1//...",
  "token_expiry": "2026-04-15T12:00:00Z",
  "scope": "https://www.googleapis.com/auth/spreadsheets"
}
```

No new DB tables. Token state lives in the existing encrypted Credential record.

---

## Backend

### 1. New Credential Type

**File:** `backend/app/db/models.py`  
Add `google_sheets = "google_sheets"` to `CredentialType` enum.

**Alembic migration:** Update the `credential_type` PostgreSQL enum to include `google_sheets`.

**File:** `backend/app/models/schemas.py`  
Add:
- `CredentialConfigGoogleSheets` Pydantic model: `client_id`, `client_secret`, `access_token`, `refresh_token`, `token_expiry`, `scope`
- Add `google_sheets` to `CredentialType` union and `CREDENTIAL_TYPE_LABELS`/`CREDENTIAL_TYPE_DESCRIPTIONS`

### 2. OAuth2 API Endpoints

**File:** `backend/app/api/google_sheets_oauth.py` (new)  
Router prefix: `/api/credentials/google-sheets/oauth`

#### `POST /authorize`
- **Auth:** requires `get_current_user`
- **Body:** `{credential_id?: UUID, client_id: str, client_secret: str}`
- **Logic:**
  1. Build Google OAuth2 auth URL with scope `spreadsheets` and `offline` access type
  2. Encode `state` as signed JWT: `{user_id, credential_id_or_null, client_id, client_secret, exp: now+10min}`
  3. Return `{auth_url: str, state: str}`
- **No DB write** at this step

#### `GET /callback`
- **Auth:** none (Google redirects here)
- **Query params:** `code`, `state`
- **Logic:**
  1. Verify and decode `state` JWT — reject if expired or invalid
  2. POST to `https://oauth2.googleapis.com/token` to exchange code → `{access_token, refresh_token, expires_in}`
  3. Calculate `token_expiry = now + expires_in`
  4. If `credential_id` in state: update existing Credential's `encrypted_config`
  5. Else: create new Credential with `type=google_sheets`, save encrypted config
  6. Return HTML: `<script>window.opener?.postMessage({type:'google-oauth-success', credentialId:'...'}, '*'); window.close()</script>`
- **Error case:** Return HTML that posts `{type: 'google-oauth-error', message: '...'}` and closes

**Register router** in `backend/app/main.py`.

### 3. `GoogleSheetsService`

**File:** `backend/app/services/google_sheets_service.py` (new)

```python
class GoogleSheetsService:
    BASE_URL = "https://sheets.googleapis.com/v4/spreadsheets"

    def __init__(self, credential_id: str, encrypted_config: dict, db_session) -> None:
        """Initialise with credential config. db_session used for token refresh writes."""

    @staticmethod
    def parse_spreadsheet_id(id_or_url: str) -> str:
        """Extract spreadsheet ID from a URL or return ID as-is."""
        # Regex: /spreadsheets/d/([a-zA-Z0-9-_]+)

    async def _get_valid_token(self) -> str:
        """Return a valid access token, refreshing via Google if expired."""
        # if token_expiry < now + 60s: call _refresh_token()
        # update Credential.encrypted_config in DB

    async def _refresh_token(self) -> None:
        """POST to https://oauth2.googleapis.com/token with refresh_token."""

    async def read_range(self, spreadsheet_id: str, sheet_name: str, range_a1: str) -> dict:
        """GET /spreadsheets/{id}/values/{sheet}!{range}  → {values: list[list]}"""

    async def append_rows(self, spreadsheet_id: str, sheet_name: str, values: list[list]) -> dict:
        """POST /spreadsheets/{id}/values/{sheet}!A1:append  → {updatedRange, updatedRows}"""

    async def update_range(self, spreadsheet_id: str, sheet_name: str, range_a1: str, values: list[list]) -> dict:
        """PUT /spreadsheets/{id}/values/{sheet}!{range}  → {updatedRange, updatedCells}"""

    async def clear_range(self, spreadsheet_id: str, sheet_name: str, range_a1: str) -> dict:
        """POST /spreadsheets/{id}/values/{sheet}!{range}:clear  → {clearedRange}"""

    async def get_sheet_info(self, spreadsheet_id: str) -> dict:
        """GET /spreadsheets/{id}?fields=sheets.properties  → {sheets: [{title, sheetId, ...}]}"""
```

HTTP client: `httpx.AsyncClient` (no new dependencies).

### 4. Executor Handler

**File:** `backend/app/services/workflow_executor.py`

Add `elif node_type == "googleSheets":` block:

```python
elif node_type == "googleSheets":
    from app.services.google_sheets_service import GoogleSheetsService
    from app.db.models import Credential
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Google Sheets node requires a credential")

    with SessionLocal() as db:
        cred = db.query(Credential).filter(Credential.id == credential_id).first()
        if not cred:
            raise ValueError("Google Sheets credential not found")
        config = decrypt_config(cred.encrypted_config)

    service = GoogleSheetsService(credential_id, config, db)
    operation = node_data.get("gsOperation")

    raw_id = self.evaluate_message_template(node_data.get("gsSpreadsheetId", ""), inputs, node_id)
    spreadsheet_id = GoogleSheetsService.parse_spreadsheet_id(raw_id)
    sheet_name = self.evaluate_message_template(node_data.get("gsSheetName", ""), inputs, node_id)
    range_a1 = self.evaluate_message_template(node_data.get("gsRange", ""), inputs, node_id)

    if operation == "readRange":
        output = await service.read_range(spreadsheet_id, sheet_name, range_a1)
    elif operation == "appendRows":
        values = json.loads(self.evaluate_message_template(node_data.get("gsValues", "[]"), inputs, node_id))
        output = await service.append_rows(spreadsheet_id, sheet_name, values)
    elif operation == "updateRange":
        values = json.loads(self.evaluate_message_template(node_data.get("gsValues", "[]"), inputs, node_id))
        output = await service.update_range(spreadsheet_id, sheet_name, range_a1, values)
    elif operation == "clearRange":
        output = await service.clear_range(spreadsheet_id, sheet_name, range_a1)
    elif operation == "getSheetInfo":
        output = await service.get_sheet_info(spreadsheet_id)
    else:
        raise ValueError(f"Unknown Google Sheets operation: {operation}")
```

**Node output fields:**
- `readRange` → `$label.values` (list of lists)
- `appendRows` / `updateRange` → `$label.updatedRange`, `$label.updatedRows`, `$label.success`
- `clearRange` → `$label.clearedRange`, `$label.success`
- `getSheetInfo` → `$label.sheets` (list of sheet metadata objects)

### 5. Credentials API — masking

**File:** `backend/app/api/credentials.py`  
Add `google_sheets` case in `get_masked_value()`: mask `client_id` value.

---

## Frontend (heymrun)

### 1. `frontend/src/types/credential.ts`

- Add `"google_sheets"` to `CredentialType` union
- Add `CredentialConfigGoogleSheets` interface: `client_id`, `client_secret`, `access_token?`, `refresh_token?`, `token_expiry?`
- Add to `CredentialConfig` union
- Add labels: `google_sheets: "Google Sheets (OAuth2)"`
- Add description

### 2. `frontend/src/types/node.ts`

Add `googleSheets` node default:
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
  }
}
```

### 3. `frontend/src/lib/nodeIcons.ts`

```typescript
import { Sheet } from 'lucide-vue-next'  // or TableProperties
googleSheets: Sheet,
// colour class:
googleSheets: "text-node-google-sheets",
```

### 4. `frontend/src/styles/globals.css`

```css
--node-google-sheets: #0F9D58;
.node-google-sheets { color: var(--node-google-sheets); }
```

### 5. `frontend/src/components/Credentials/CredentialDialog.vue`

- Add `google_sheets` to `typeOptions` array
- Add reactive refs: `gsClientId`, `gsClientSecret`, `gsIsConnected`, `gsCredentialId`
- Add two-phase form for `google_sheets` type:
  - Phase 1: Name + Client ID + Client Secret fields + "Connect with Google" button
  - Phase 2: Green "Connected ✓" badge + "Re-connect" button
- `startGoogleSheetsOAuth()` function:
  1. Call `credentialsApi.googleSheetsOAuthAuthorize(clientId, clientSecret)`
  2. `window.open(auth_url, 'google-oauth', 'width=600,height=700')`
  3. `window.addEventListener('message', ...)` → on `google-oauth-success`: set `gsIsConnected = true`, `gsCredentialId = credentialId`

### 6. `frontend/src/services/api.ts`

Add `googleSheetsOAuthAuthorize(clientId, secret, credentialId?)` method to `credentialsApi`.

### 7. `frontend/src/components/Panels/NodePanel.vue`

Add `googleSheets` configuration block (mirrors Grist pattern):
- Credential picker (filtered to `google_sheets` type)
- Operation dropdown (`readRange`, `appendRows`, `updateRange`, `clearRange`, `getSheetInfo`)
- Spreadsheet ID/URL field (expression-enabled) — hint text explains URL accepted
- Sheet Name field (expression-enabled)
- Range field — visible for `readRange`, `updateRange`, `clearRange`
- Values JSON field — visible for `appendRows`, `updateRange`

---

## DSL Prompt Update

**File:** `backend/app/services/workflow_dsl_prompt.py`

Add a `## Google Sheets Node` section documenting:
- Node type: `googleSheets`
- All parameters with types and descriptions
- Output fields per operation
- 2 example workflow snippets (readRange → LLM, appendRows from LLM output)
- Note that `gsSpreadsheetId` accepts full URL or bare ID

---

## Tests

**File:** `backend/tests/test_google_sheets_service.py`  
Pattern: `unittest.IsolatedAsyncioTestCase` with `AsyncMock` / `MagicMock` for httpx and DB.

| Test | Covers |
|---|---|
| `test_parse_spreadsheet_id_bare` | bare ID returned as-is |
| `test_parse_spreadsheet_id_url` | full URL parsed to ID |
| `test_token_valid_no_refresh` | valid token → no refresh call |
| `test_token_expired_triggers_refresh` | expired token → Google refresh endpoint called, DB updated |
| `test_read_range_success` | mock HTTP → correct values returned |
| `test_append_rows_success` | mock HTTP → updatedRows, updatedRange returned |
| `test_update_range_success` | mock HTTP → updatedCells returned |
| `test_clear_range_success` | mock HTTP → clearedRange returned |
| `test_get_sheet_info_success` | mock HTTP → sheets list returned |
| `test_missing_credential_raises` | executor raises ValueError when credentialId absent |

**File:** `backend/tests/test_google_sheets_oauth.py`  
Pattern: `unittest.IsolatedAsyncioTestCase` with httpx mock.

| Test | Covers |
|---|---|
| `test_authorize_returns_auth_url` | POST /authorize → valid Google auth URL + state |
| `test_callback_exchanges_code_saves_tokens` | GET /callback → tokens stored in Credential |
| `test_callback_invalid_state_rejected` | tampered state → 400 response |
| `test_callback_expired_state_rejected` | expired state JWT → 400 response |

---

## Documentation

### heymrun docs (`heym-documentation` skill)

- `frontend/src/docs/content/nodes/google-sheets-node.md` — new, full reference
- `frontend/src/docs/content/reference/credentials.md` — add `google_sheets` OAuth2 setup steps
- `frontend/src/docs/content/reference/integrations.md` — add Google Sheets section
- `frontend/src/docs/content/reference/node-types.md` — add Google Sheets row

### heymweb (`/Users/mbakgun/Projects/heym/heymweb`)

**`src/components/sections/LogoCarousel.tsx`**  
Add Google Sheets SVG logo entry (same `w-6 h-6` format as existing logos).

**`src/components/sections/NodesSection.tsx`**  
Add to `integrations` category (after Grist):
```typescript
{ icon: Sheet, name: 'Google Sheets', description: 'Read, write, append and update Google Sheets via OAuth2. Supports range queries, row appending, and sheet metadata — connect your Google account, no API key required.' }
```

**Landing page feature block** (new section or addition to `FeaturesSection.tsx`):  
- Heading: "Automate Google Sheets"
- 3 bullet features: read data into workflows, append rows from LLM/form output, query sheet structure
- Example use-cases: auto-log LLM results, write form submissions, read config from sheets

---

## Out of Scope

- Drive API (file listing, upload)
- Creating / deleting sheets
- Batch updates across multiple ranges
- Shared Heym-level Google Cloud app
- Redirect-based OAuth flow (popup-only)
