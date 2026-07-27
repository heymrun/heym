# Google Drive Node — Design

**Date:** 2026-07-27
**Status:** Approved
**Scope:** New `googleDrive` node in heymrun (backend + frontend + docs + DSL), plus heymweb node catalog, doc sync, DSL sync, and a marketing template.

## Goal

Add a Google Drive integration node with interactive (popup) OAuth2, supporting six operations:
`listFolderFiles`, `downloadFile`, `syncToHeymDrive`, `updateFile`, `removeFile`, `removeFolder`.

## Naming and boundaries

The repository already has a `drive` node. That node is **Heym Drive** — internal file storage backed by
the `GeneratedFile` table. It is unrelated to Google Drive and stays unchanged.

The new node type is **`googleDrive`**. Its `syncToHeymDrive` operation is the bridge between the two:
it pulls a file out of Google Drive and stores it in Heym Drive.

## Architecture

Mirrors the existing Google Sheets integration, which is the established pattern for OAuth-backed
Google services in this codebase.

| Concern | Module | Pattern source |
| --- | --- | --- |
| OAuth authorize/callback | `app/api/google_drive_oauth.py` (new) | `app/api/google_sheets_oauth.py` |
| Drive API client + token refresh | `app/services/google_drive_service.py` (new) | `app/services/google_sheets_service.py` |
| Node execution | `app/services/node_execution/nodes/google_drive_node.py` (new) | `nodes/google_sheets_node.py` |
| Heym Drive write | reuses `app/services/file_storage.py` helpers | `nodes/drive_node.py` `save` branch |

The node handler stays thin: it resolves templated fields, dispatches to `GoogleDriveService`, and
returns the service output. All HTTP and token logic lives in the service. This keeps the handler
testable with a mocked service and satisfies the `WorkflowExecutor modularity` policy in `AGENTS.md`.

### Rejected alternatives

- **All logic inside the node handler** (the shape `drive_node.py` has at 793 lines). Rejected: it is the
  anti-pattern `AGENTS.md` warns about, and it makes unit testing require HTTP mocking through the executor.
- **Extending the existing `google_sheets` credential with Drive scope.** Rejected: existing stored tokens
  were granted without the Drive scope, so they would start returning 403 with no visible cause until every
  user re-authorized. It would also force Sheets-only users to grant full Drive access.

## Authentication

New credential type `google_drive` (`CredentialType.google_drive`).

**Scope:** `https://www.googleapis.com/auth/drive` (full access).

The narrower `drive.file` scope only grants access to files the OAuth client itself created. Under that
scope `listFolderFiles`, `updateFile`, `removeFile`, and `removeFolder` would silently see nothing of the
user's existing Drive, which defeats the purpose of the node. Because each user supplies their own
`client_id` / `client_secret` from their own Google Cloud project, the Google app-verification burden for
this restricted scope sits with the user's project, not with Heym.

**Flow** (identical in shape to Google Sheets):

1. Frontend creates a `google_drive` credential holding `client_id` + `client_secret`.
2. `POST /api/google-drive/authorize` returns a Google consent URL. State is a JWT signed with
   `settings.secret_key`, typed `gd_oauth_state`, with a 10-minute TTL, carrying `user_id`,
   `credential_id`, `client_id`, `client_secret`, `redirect_uri`.
3. Popup completes consent, Google redirects to `GET /api/google-drive/callback`.
4. The callback validates the state JWT, exchanges the code for tokens, encrypts
   `{client_id, client_secret, access_token, refresh_token, token_expiry}` into the credential, and
   returns an HTML page that `postMessage`s success/failure to the opener and closes.

Authorization requests use `access_type=offline` and `prompt=consent` so a refresh token is always issued.

`GoogleDriveService` refreshes the access token when it is within 60 seconds of expiry and re-encrypts the
updated config back onto the credential row, exactly as `GoogleSheetsService._refresh_token` does.

## Operations

All field values pass through `evaluate_message_template`, so every field accepts `$` expressions.

All ID fields accept either a bare Drive ID or a full URL. A shared `parse_drive_id` helper extracts the ID
from the common URL shapes:

- `https://drive.google.com/file/d/<ID>/view`
- `https://drive.google.com/drive/folders/<ID>`
- `https://docs.google.com/{document,spreadsheets,presentation}/d/<ID>/edit`
- `https://drive.google.com/open?id=<ID>`

Anything that does not match is passed through stripped, so bare IDs work unchanged.

All Drive API calls set `supportsAllDrives=true` (and `includeItemsFromAllDrives=true` on list) so shared
drives work.

### `listFolderFiles`

| Field | Default | Notes |
| --- | --- | --- |
| `gdFolderId` | `""` | Empty means `root` |
| `gdMaxResults` | `100` | Pages through the API (`pageSize` capped at 1000) until satisfied |
| `gdQuery` | `""` | Extra Drive query, ANDed with the parent clause, e.g. `mimeType='application/pdf'` |
| `gdIncludeTrashed` | `false` | When false, adds `trashed = false` |

`GET /drive/v3/files` with
`q=<parent> and <trashed> and <user query>`,
`fields=nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink)`.

Output:

```json
{
  "status": "success",
  "operation": "listFolderFiles",
  "folder_id": "<id or root>",
  "count": 2,
  "files": [
    {
      "id": "...", "name": "...", "mime_type": "...",
      "size_bytes": 1234, "modified_time": "...",
      "web_view_link": "...", "is_folder": false
    }
  ]
}
```

`is_folder` is derived from `mimeType == "application/vnd.google-apps.folder"`. `size_bytes` is `null` for
Google-native files, which do not report a size.

### `downloadFile`

| Field | Default | Notes |
| --- | --- | --- |
| `gdFileId` | required | |
| `gdExportFormat` | `""` | Empty means automatic. One of `pdf`, `docx`, `xlsx`, `pptx`, `csv`, `txt` |

The node first fetches metadata (`fields=id,name,mimeType,size`), then branches:

- **Binary file** (mimeType is not `application/vnd.google-apps.*`): `GET /drive/v3/files/<id>?alt=media`.
- **Google-native file**: `GET /drive/v3/files/<id>/export?mimeType=<target>`.

Google-native files have no byte content in Drive — they are records on Google's servers — so `alt=media`
returns `403 Only files with binary content can be downloaded`. Export is the only way to retrieve them.

Automatic export defaults:

| Source | Target | MIME |
| --- | --- | --- |
| `application/vnd.google-apps.document` | PDF | `application/pdf` |
| `application/vnd.google-apps.spreadsheet` | XLSX | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| `application/vnd.google-apps.presentation` | PPTX | `application/vnd.openxmlformats-officedocument.presentationml.presentation` |
| any other `google-apps` type | PDF | `application/pdf` |

`gdExportFormat` overrides the target. It is ignored for binary files.

When exported, the returned filename gains the target extension if it does not already have it.

Output:

```json
{
  "status": "success",
  "operation": "downloadFile",
  "id": "...",
  "filename": "Report.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 20481,
  "exported": true,
  "export_format": "pdf",
  "content_base64": "..."
}
```

For a binary file, `exported` is `false` and `export_format` is `null`.

The download is size-checked against `settings.file_max_size_mb` and raises a clear error when exceeded,
so a large file cannot blow up executor memory or the trace payload.

### `syncToHeymDrive`

| Field | Default | Notes |
| --- | --- | --- |
| `gdFileId` | required | |
| `gdFilename` | `""` | Overrides the stored filename; empty uses the Drive name |
| `gdExportFormat` | `""` | Same semantics as `downloadFile` |

Downloads using the exact same fetch-and-export path as `downloadFile`, then persists to Heym Drive using
the same sequence as the `drive` node's `save` branch:

1. `_normalize_storage_filename(filename)`
2. `_safe_storage_path(f"{owner_id}/{uuid4()}/{filename}")`, `mkdir(parents=True)`, `write_bytes`
3. Insert `GeneratedFile` (`owner_id`, `workflow_id`, `filename`, `storage_path`, `mime_type`,
   `size_bytes`, `source_node_id`, `source_node_label`)
4. Insert `FileAccessToken` with `secrets.token_urlsafe(32)`
5. `build_download_url(base_url, token)`

Owner is `self.trace_user_id`; the node raises if there is no owner context, matching `drive_node`.

Output:

```json
{
  "status": "success",
  "operation": "syncToHeymDrive",
  "id": "<heym file uuid>",
  "google_file_id": "...",
  "filename": "Report.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 20481,
  "exported": true,
  "download_url": "https://.../api/files/dl/<token>"
}
```

### `updateFile`

| Field | Default | Notes |
| --- | --- | --- |
| `gdFileId` | required | |
| `gdBase64Content` | `""` | Replaces file content; accepts a raw base64 string or a `data:` URL |
| `gdNewName` | `""` | Renames the file |
| `gdNewParentId` | `""` | Moves the file to this folder |

At least one of the three optional fields must be non-empty; otherwise the node raises
`Google Drive node: updateFile requires content, a new name, or a new parent`.

Blank fields are left untouched — this is an update, not a replace.

API calls, in order, skipping any whose field is blank:

- Content: `PATCH /upload/drive/v3/files/<id>?uploadType=media` with the decoded bytes.
- Name: `PATCH /drive/v3/files/<id>` with body `{"name": ...}`.
- Move: `PATCH /drive/v3/files/<id>?addParents=<new>&removeParents=<current>`, where `<current>` comes from
  the metadata fetch (`fields=parents`).

Name and move are combined into a single `PATCH` when both are requested.

Content upload is size-checked against `settings.file_max_size_mb`.

Output includes an `updated` array naming which aspects changed, e.g. `["content", "name"]`.

### `removeFile` / `removeFolder`

| Field | Default | Notes |
| --- | --- | --- |
| `gdFileId` (`removeFile`) / `gdFolderId` (`removeFolder`) | required | |
| `gdPermanentDelete` | `false` | |

Default is **trash**: `PATCH /drive/v3/files/<id>` with `{"trashed": true}`. Recoverable, which is the right
default for something that may run inside a Loop node on a schedule.

When `gdPermanentDelete` is true: `DELETE /drive/v3/files/<id>`. Unrecoverable, and for a folder this also
destroys its contents.

`removeFolder` first fetches metadata and raises if `mimeType != "application/vnd.google-apps.folder"`, so a
mistyped ID cannot silently delete a file through the folder operation. `removeFile` correspondingly raises
if the target *is* a folder.

Output:

```json
{
  "status": "success",
  "operation": "removeFile",
  "id": "...",
  "name": "...",
  "deleted": "trashed"
}
```

`deleted` is `"trashed"` or `"permanent"`.

## Error handling

The service raises `ValueError` with a message prefixed `Google Drive node:` for user-correctable problems
(missing field, wrong file type, size limit, unknown operation). HTTP failures from Google surface the
Drive API error message and status. The node handler does not catch and repackage these — the executor's
existing retry and `NodeResult` packaging handles them, per the modularity policy.

Common Google errors are translated into actionable messages:

- `403` on `alt=media` for a native file → the export path is taken instead, so this should not reach users.
- `404` → `Google Drive node: file not found or not accessible with this credential`.
- `401` after a refresh attempt → `Google Drive node: credential is no longer authorized, reconnect it`.

## Files to change

### Backend

- `app/db/models.py` — add `google_drive = "google_drive"` to `CredentialType`.
- `alembic/versions/103_add_google_drive_cred_type.py` — new; `down_revision = "102_merge_user_ai_live_heads"`
  (verified sole head). Adds the enum value.
- `app/models/schemas.py` — add `google_drive` to the credential type enum near line 532.
- `app/api/credentials.py` — credential validation branches (two sites, mirroring `google_sheets` at
  lines 210 and 1586).
- `app/api/google_drive_oauth.py` — new router.
- `app/main.py` — import and register the router.
- `app/services/google_drive_service.py` — new.
- `app/services/node_execution/nodes/google_drive_node.py` — new.
- `app/services/node_execution/registry.py` — `"googleDrive": "google_drive_node"`.
- `app/services/workflow_dsl_prompt.py` — new numbered node section documenting all six operations and
  every field, plus add `googleDrive` to the credential list in rule 23a.

### Frontend

- `src/types/node.ts`, `src/types/workflow.ts` — node type and `gd*` data fields.
- `src/components/Panels/NodePanel.vue` — palette entry.
- `src/components/Canvas/WorkflowCanvas.vue` — node registration.
- `src/components/Nodes/BaseNode.vue` — label/icon handling.
- `src/lib/nodeIcons.ts` — icon.
- `src/components/Panels/propertiesPanel/operationOptions.ts` — `googleDriveOperationOptions`.
- `src/components/Panels/propertiesPanel/nodes/GoogleDriveNodeProperties.vue` — new; all node config UI
  lives here, not in `PropertiesPanel.vue`.
- `src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue` — wire the new component.
- `src/components/Panels/propertiesPanel/usePropertiesPanelController.ts` — register `gd*` fields as
  expression-dialog eligible and AI-autofill eligible, so double-click shows `1/n` navigation and the agent
  icon can populate them.
- `src/components/Credentials/CredentialDialog.vue` — `google_drive` type option, OAuth connect button,
  connected state, and the `Done` button behavior that `google_sheets` already has.
- `src/services/api.ts` — `googleDriveOAuthAuthorize`.
- `src/components/Panels/DebugPanel.vue` — node type awareness.

### Docs (heymrun)

- `src/docs/content/nodes/google-drive-node.md` — new page.
- `src/docs/manifest.ts` — register the page.
- `src/docs/content/reference/features.md` — per-node section **and** the node-types summary paragraph
  (currently line 397).
- `src/docs/content/reference/node-types.md`
- `src/docs/content/reference/integrations.md`
- `src/docs/content/reference/credentials.md`
- `src/docs/content/reference/credentials-sharing.md` — must state that a shared `google_drive` credential
  grants the recipient full access to the owner's entire Drive.

### heymweb

- Run `bun run sync-docs` (pulls the new node page) and `bun run sync-dsl-prompt` (pulls the DSL).
- `src/lib/marketingNodeCatalog.ts` — `{ id: 'googleDrive', name: 'Google Drive' }`.
- `src/lib/node-doc-links.ts` — `googleDrive: 'nodes/google-drive-node.md'`.
- `src/components/templates/nodePreviewTokens.ts` — preview token for canvas rendering.
- `src/lib/operationsTemplates.ts` — new template (below).
- `tests/templates/catalog.test.ts` — update if the new template or node id trips an assertion.

## heymweb template

**Google Drive → Heym Drive backup**, in the operations library.

`Cron` → `googleDrive.listFolderFiles` → `Loop` → `googleDrive.syncToHeymDrive` → `Slack` summary.

Chosen because it showcases `syncToHeymDrive`, the operation that is genuinely differentiating rather than
a generic API wrapper, and it avoids headlining destructive operations in marketing material.

## Testing

Backend, `backend/tests/`:

- `test_google_drive_service.py` — mocked `httpx`: token refresh on expiry and persistence back to the
  credential, native-vs-binary download branching, export MIME selection including `gdExportFormat`
  override, list pagination and query composition, trash vs permanent delete, folder/file type guards.
- `test_google_drive_node.py` — per-operation field resolution and error paths, `updateFile` "at least one
  field" rule, `syncToHeymDrive` writing `GeneratedFile` + `FileAccessToken`, unknown operation.
- `test_google_drive_oauth.py` — state JWT signing, TTL expiry, wrong-type rejection, callback error paths.

`SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh` from the repo root must pass.

**No frontend UI tests** for heymrun, per standing project preference. Frontend verification is
`bun run lint` + `bun run typecheck` + manual check.

## Out of scope

- Refactoring the duplicated OAuth state/popup code shared by `google_sheets_oauth.py`,
  `bigquery_oauth.py`, `notion_oauth.py`, and `linear_oauth.py` into a common helper. Worth doing, but it
  touches four working integrations and does not serve this feature.
- Uploading new files to Google Drive (create), folder creation, and permission management. Not requested.
- A Google Drive trigger node. Not requested.
- Text extraction from downloaded files. Explicitly decided against; `downloadFile` returns base64 only.

## Notes

- Work stays on the `impl/gdrive-node` branch. Nothing is pushed without explicit approval.
- The `google_drive` credential grants full Drive access, which is why the sharing caveat is a required
  documentation item rather than a nice-to-have.
