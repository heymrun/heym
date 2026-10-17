# Google Drive and Google Sheets Triggers: Design

Date: 2026-10-17
Status: approved and implemented

## Goal

Start a workflow when something changes in Google Drive or in a Google Sheet:

- **Google Drive Trigger** fires when a file is created, updated, or deleted in a watched folder, or when one watched file is updated or deleted.
- **Google Sheets Trigger** fires when a row is created, updated, or deleted in a watched sheet tab.

Each change starts exactly one run, including on a multi-worker instance or a multi-instance cluster. Heym does not store cell values or file contents to detect changes.

## Decisions

| Topic | Decision |
|---|---|
| Node shape | Two node types: `googleDriveTrigger` and `googleSheetsTrigger`. They reuse the existing `google_drive` and `google_sheets` credentials. |
| Detection | Polling plus a diff against a persisted fingerprint snapshot. No push webhooks, so no public URL is needed. |
| Old data | Not stored. Sheets keeps keyed HMAC fingerprints per row and per cell. Drive keeps file metadata only (never contents). |
| Run granularity | One run per change, at most 50 runs per node per poll. Remaining changes carry over to later polls. |
| Delivery | Each change fires at most once across all workers and instances. The guarantee comes from database compare-and-swap (CAS), not from leader election. |
| Templates | "Drive Folder Intake Summarizer" and "Sheet Lead Qualifier" on heym.run. |
| Heym Work | No change. Work Chat forwards build turns to the connected Heym instance, so the triggers are available there as soon as that instance runs a release that contains them. |

## 1. Nodes, events, and output

### Google Drive Trigger (`googleDriveTrigger`)

Node data:

| Field | Type | Default | Notes |
|---|---|---|---|
| `credentialId` | uuid | — | A `google_drive` credential the workflow owner can access. |
| `gdtScope` | `"folder"` \| `"file"` | `"folder"` | What to watch. |
| `gdtFolderId` | string | `""` | Folder ID or URL. Empty means My Drive root. Only direct children are watched. |
| `gdtFileId` | string | `""` | File ID or URL; required when scope is `file`. |
| `gdtEvents` | string[] | `["created","updated","deleted"]` | Events that start a run. `created` does not apply to file scope. |
| `gdtIncludeFolders` | bool | `false` | Whether subfolders themselves produce events. |
| `pollIntervalMinutes` | int | `1` | Minimum 1. |

Events:

- `created`: an item appears in the folder. This includes an item moved into the folder.
- `updated`: the item's name, `modifiedTime`, size, or MIME type changed.
- `deleted`: the item is no longer in the folder, because it was trashed, deleted permanently, or moved out. In file scope, `deleted` means the file is trashed or returns 404. A 401 response never produces `deleted`.

Run output (`$<label>.…`):

- `event`: `"created" | "updated" | "deleted"`.
- `file`: `{id, name, mime_type, size_bytes, created_time, modified_time, web_view_link, is_folder}`. For `created` and `updated` this is live metadata from the poll. For `deleted` it is the last stored metadata.
- `changed_fields`: names of the metadata fields that changed. Empty for `created` and `deleted`.
- `folder_id`: the watched folder, or `null` in file scope.
- `triggered_at`: ISO timestamp.

### Google Sheets Trigger (`googleSheetsTrigger`)

Node data:

| Field | Type | Default | Notes |
|---|---|---|---|
| `credentialId` | uuid | — | A `google_sheets` credential the workflow owner can access. |
| `gstSpreadsheetId` | string | `""` | Spreadsheet ID or URL; required. |
| `gstSheetName` | string | `"Sheet1"` | Tab title. |
| `gstHasHeader` | bool | `true` | Row 1 holds column names, as in the Google Sheets node. |
| `gstKeyColumn` | string | `""` | Optional. A header name, or a column letter when there is no header. |
| `gstEvents` | string[] | `["created","updated","deleted"]` | Events that start a run. |
| `pollIntervalMinutes` | int | `1` | Minimum 1. |

Row identity:

- **Key column set (recommended).** A row is identified by the fingerprint of its key value, so inserting, deleting, or sorting rows is detected correctly. A row with an empty key is ignored until the key is filled in. When keys are duplicated, the first occurrence wins and the poller logs a warning.
- **No key column.** A row is identified by its row number. An all-empty row is not an item. Deleting a row in the middle of the sheet shows up as `updated` for every row below it plus one `deleted` at the end. The node docs and the properties form say so.

Events:

- `created`: a new row identity appears.
- `updated`: at least one cell fingerprint changed.
- `deleted`: a row identity disappears.

Run output:

- `event`: `"created" | "updated" | "deleted"`.
- `row`: the cells keyed by header (or by column letter) plus `rowIndex`, in the same shape as the Google Sheets node's `readRange`. The values are read live during the poll that fired the run. For `deleted` the row is only `{rowIndex}`, the last known row number.
- `changed_columns`: header names (or column letters) whose cells changed. For `created` it lists every non-empty column. For `deleted` it is empty.
- `key`: the key column value for `created` and `updated` when a key column is set. It is `null` for `deleted` and when no key column is set.
- `spreadsheet_id`, `sheet_name`, `triggered_at`.

The sheet is read in full from its used range, not limited to columns A to Z. Sheet names are quoted in A1 notation.

### Shared rules

- The first poll records a baseline and fires nothing.
- A **scope change** records a new baseline and fires nothing. The scope is the credential, folder or file, spreadsheet, sheet name, header setting, key column, and include-folders setting; for Sheets it also includes the header row's fingerprint. Editing the header row therefore resets the baseline.
- Changing `gdtEvents` or `gstEvents` does not reset the baseline. Events outside the filter are still consumed, so they advance the snapshot, but they start no run and do not count toward the 50-run cap.
- Limits: a Drive folder may have at most 5,000 entries and a sheet at most 10,000 rows. Over the limit, the poll is skipped with a warning log and the snapshot is left unchanged.
- **Write-back loop:** a workflow that writes to the sheet it watches causes its own `updated` events. The docs, the properties form, and the Lead Qualifier template recommend listening to `created` only in that case.
- The node handlers return the trigger payload from `_initial_inputs`. A manual editor run sees empty values, as with `imapTrigger`.
- Trigger fields are read by the poller, not the executor, so they take plain values. They are not expression-eligible.

## 2. Runtime architecture

### Modules

`backend/app/services/google_triggers/`:

- `fingerprint.py`: keyed fingerprints. The key is derived as `HMAC-SHA256(SECRET_KEY, "heym:trigger-fingerprint:v1")`. Each value is fingerprinted as `HMAC(key, f"{workflow_id}:{node_id}:{value}")`. Cell fingerprints are truncated to 8 hex characters. They are change detectors, and a collision only hides one edit. Key and item fingerprints use 16 hex characters. The `key_id` (a short SHA-256 of the derived key) is stored with the state; when it no longer matches, the poller resets the baseline silently. The module docstring explains why this is not `secret_tokens.hash_secret`: that helper is a plain SHA-256 for high-entropy capability secrets, while cell values have low entropy, so an unkeyed hash of them could be reversed by guessing.
- `drive_source.py`: a pure function that maps the stored items and a live listing to new items and an ordered list of events.
- `sheets_source.py`: a pure function that maps the stored items and live values (plus the header) to new items and an ordered list of events.
- `state_store.py`: async database access for claiming polls, recording baselines, consuming events, and reverting them.
- `poller.py`: `GoogleTriggerPoller`, a leader-gated loop that ticks every 15 seconds. It loads the workflows that contain either node type, claims nodes that are due, fetches from Google in `asyncio.to_thread` through the existing services (so refreshed tokens are still persisted), diffs, and dispatches.

`backend/app/services/trigger_run_dispatch.py`: the dispatch and persist block extracted from `imap_trigger_service._execute_workflow_for_email`. It covers fresh workflow load, the workflow cache, credentials and global-variable contexts, registering cancellation, `dispatch_workflow`, offloaded-run handling, HITL pending persist, history, analytics, sub-workflow history, and the global-variable write-back. It is parametrized by `trigger_source`, `inputs`, and a log label. IMAP switches to it with no behavior change. It keeps raising a "not started" error for failures before `dispatch_workflow`.

The service additions are:

- `GoogleDriveService.list_folder_entries(folder_id, include_folders, limit)`, which adds `createdTime` to the listing;
- `GoogleDriveService.get_file_entry(file_id)` for file scope, which returns `None` once the file is trashed or answers 404;
- `GoogleSheetsService.read_sheet_values(spreadsheet_id, sheet_name)`, which reads the full used range with a quoted sheet name.

The output of existing node operations does not change.

### Persistence

New tables (Alembic migration, UUID primary keys):

`trigger_poll_states`

| Column | Notes |
|---|---|
| `id` | uuid PK |
| `workflow_id` | FK → workflows, `ON DELETE CASCADE`, indexed |
| `node_id` | string |
| `node_type` | string |
| `scope_fingerprint` | SHA-256 of the scope settings (IDs only, not secret) |
| `key_id` | fingerprint key identifier |
| `version` | bigint, CAS counter |
| `next_poll_at` | timestamptz, indexed |
| `updated_at` | timestamptz |

Unique `(workflow_id, node_id)`.

`trigger_poll_items`

| Column | Notes |
|---|---|
| `state_id` | FK → trigger_poll_states, `ON DELETE CASCADE` |
| `item_key` | Drive file ID; Sheets key fingerprint or row number |
| `payload` | JSONB. Drive: stored file metadata. Sheets: `{"r": rowIndex, "c": [cell fingerprints]}` |

Primary key `(state_id, item_key)`.

Each consumed event touches one item row, so a large sheet does not rewrite a multi-megabyte JSONB value on every run. The poller deletes state rows whose node no longer exists or is inactive.

### Exactly-once firing

Leader gating (`lock_service.is_leader`) only keeps all workers from polling Google. Correctness rests on two atomic operations:

1. **Claim.** `UPDATE trigger_poll_states SET next_poll_at = now() + interval WHERE id = :id AND next_poll_at <= now() RETURNING version`. Only one worker polls a node per interval. The first baseline is written with `INSERT … ON CONFLICT (workflow_id, node_id) DO NOTHING` together with its items in one transaction, and the loser discards its copy.
2. **Consume, then dispatch.** For each event, in one transaction: `UPDATE trigger_poll_states SET version = version + 1 WHERE id = :id AND version = :expected`, then upsert or delete that one item. If the update matches no row, another worker advanced the state, and this worker stops the poll without dispatching. A run starts only after the consume commits.
3. **Revert on a failure before dispatch.** A failure before `dispatch_workflow` starts is retried 3 times. If it still fails, the consume is reverted with the same CAS (version check plus restoring the previous item), so the next poll fires the event again. Once a run has started it is never retried.
4. The only remaining gap is a process crash between the consume commit and the start of dispatch. In that case the event is lost, never duplicated. The docs describe this at-most-once behaviour.

Resetting the baseline (scope change or `key_id` mismatch) is a CAS on `version`: delete all items, insert the new ones, and update `scope_fingerprint` and `key_id`.

### Errors and security

- Before every poll, the credential is checked with `credential_access.get_accessible_credential(db, credential_id, workflow.owner_id)` and must have the expected `CredentialType`. If the check fails, the poll is skipped with a warning.
- Google 401, 403, 404 on the watched folder or spreadsheet, 429, 5xx, network errors, or a limit overrun: the poll is skipped, the snapshot is unchanged, and the poller logs a warning. A transient failure never produces `deleted` events.
- `trigger_source` is `google_drive` or `google_sheets`. Run inputs are `{triggered_by, trigger_node_id, triggered_at, event: <payload>}`.
- Plain `logger` lines only. `audit()` is not called from the poller, per the audit rule in AGENTS.md.

### Registrations

- `node_execution/nodes/google_drive_trigger_node.py` and `google_sheets_trigger_node.py`, registered in `registry.py`.
- `cluster/node_placement.py`: both `ANYWHERE`. Polling runs on the leader, and the run itself has no local state.
- `trigger_inputs.INITIAL_INPUT_TRIGGER_TYPES`, `workflow_status.TRIGGER_NODE_TYPES` (shows `listening`), `dashboard_widget_policy`, and `credential_catalog` (field and description entries for both credentials).
- `main.py`: start and stop the poller next to the IMAP manager.

## 3. Frontend, DSL, docs, release tour

- **Canvas:**
  - `types/workflow.ts` node types;
  - `NodePanel` Triggers group;
  - `nodeIcons` (Drive uses `FolderOpen`, Sheets uses `Sheet`, both with existing colors);
  - `BaseNode` color and trigger handling;
  - `WorkflowCanvas` defaults;
  - `canvasConnectionRules` (no inputs);
  - `workflowPreview`;
  - `stores/workflow.ts` validation: credential set, spreadsheet ID set, file ID set in file scope, poll interval of at least 1.
- **Properties:** `propertiesPanel/nodes/GoogleDriveTriggerNodeProperties.vue` and `GoogleSheetsTriggerNodeProperties.vue`, with credential options from the controller. `PropertiesPanel.vue` gets no `selectedNode.type` branches. Each form lists the available output fields and states the row-identity and write-back notes.
- **Schema metadata / AI autofill:** labels, defaults, and autofill hints for every field. None is expression-eligible.
- **DSL** (`workflow_dsl_prompt.py`):
  - sections `3g. googleDriveTrigger` and `3h. googleSheetsTrigger` after the other triggers, with fields, events, output paths, a JSON example, and the write-back warning;
  - both node types added to the owned-credential rule's list.
- **Docs** (via the `heym-documentation` skill):
  - new `nodes/google-drive-trigger-node.md` and `nodes/google-sheets-trigger-node.md`, registered in `manifest.ts`;
  - updates to `reference/features.md` (per-node section and summary list), `node-types.md`, `triggers.md`, `integrations.md`, `credentials.md`, and `credentials-sharing.md`;
  - cross-links from the Google Drive and Google Sheets node pages;
  - the privacy note (fingerprints only) and the at-most-once note.
- **Release tour:**
  - Add a "Google Drive & Sheets triggers" section to the current unreleased entry. If `2026.19` has already shipped, start `2026.20` with `tourEnabled: false`.
  - List the section in `sectionOrder`.
  - Add a looping mock in `components/visuals/` (a file lands in a folder and a run starts; a row is added and a run starts), registered in `tourVisuals.ts`.

## 4. heym.run and Heym Work

- **heymweb** (feature branch, because `main` deploys live; goes live only when the user says so, and only after a Heym release contains these nodes):
  - run `bun run sync-docs` and `bun run sync-dsl-prompt`;
  - add `NodesSection.tsx` entries, `node-doc-links.ts`, and `nodePreviewTokens.ts` / `TemplateCanvasNode.tsx` tokens.
- **Template 1, Drive Folder Intake Summarizer** (`document-ops`): Drive Trigger (folder; `created` and `deleted`), then a Switch on `event`.
  - `created`: Google Drive `syncToHeymDrive`, then an LLM summary with key points, then a Slack post with the summary and `web_view_link`.
  - `deleted`: a Slack "file removed" notice.
- **Template 2, Sheet Lead Qualifier** (`sales-crm`): Sheets Trigger (`created` only), then an LLM structured score and reason, then Google Sheets `updateRange` writing to `$trigger.row.rowIndex`, then a Condition (hot lead), then Slack. The long description teaches the `created`-only rule.
- **Heym Work:** no change. Work Chat sends build turns to the connected Heym instance's `/api/chats/{id}/messages` with `allow_build`, so Heym builds the workflow with its own DSL and runs it. Work can use the triggers as soon as that instance is upgraded. Work does not map trigger sources to labels, so `google_drive` and `google_sheets` show up as they are. The `vendor/heymrun` pin only keeps Work's borrowed types, components, and read modules in sync. It is not required for this feature and can follow in the next routine re-pin.

## 5. Testing

- **Backend unit tests** (`unittest`, `AsyncMock`):
  - Drive diff: create, update, delete, move in and out, include folders, file scope with trashed and 404.
  - Sheets diff: key and row-number modes, empty rows and keys, duplicate keys, `changed_columns`, created columns.
  - Fingerprints: per-node salt; a `key_id` mismatch resets the baseline.
  - Scope change resets the baseline.
  - Event filter consumes events without dispatching.
  - Poller: the 50-run cap and carryover, errors leave the snapshot unchanged, credential access denied, one dispatch per event.
  - Handler output.
  - IMAP regression after the dispatch extraction.
  - `test_cluster_node_placement` passes with the new entries.
- **PostgreSQL race tests** (alongside `test_active_execution_registry_resilience.py`):
  - two claimers, one poll;
  - two consumers of the same event, one dispatch;
  - a failure before dispatch reverts the consume, and the next poll dispatches once;
  - concurrent baselines, one wins.
- **Vitest:** the properties forms, store validation, and discovery of autofill fields.
- **Playwright:** add both triggers from the panel, configure them, see the validation errors and the output field lists.

## Out of scope

- Watching a whole Drive or recursive subfolders. The Drive Changes API can add this later.
- Push notifications (`changes.watch`).
- Any change to the IMAP trigger beyond the dispatch extraction.
