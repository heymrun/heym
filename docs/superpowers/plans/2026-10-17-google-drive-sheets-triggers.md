# Google Drive and Google Sheets Triggers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `googleDriveTrigger` and `googleSheetsTrigger` nodes. They poll Google, diff a persisted snapshot, and start exactly one run per file change or row change. They do not store cell values.

**Architecture:** Pure diff modules (`drive_source.py`, `sheets_source.py`) turn live Google data and the stored snapshot into an ordered list of `TriggerEvent`s. `state_store.py` holds the snapshot in two new tables. It claims polls through `next_poll_at` and consumes each event with a compare-and-swap on `version`, so a change fires once across workers and instances. A leader-gated `GoogleTriggerPoller` ties these together and starts runs through `trigger_run_dispatch.py`, a helper extracted from the IMAP trigger that IMAP keeps using.

**Tech Stack:**
- Backend: Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, httpx, `unittest` with `AsyncMock`, real PostgreSQL for the race tests.
- Frontend: Vue 3 `<script setup>` with TypeScript strict, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-17-google-drive-sheets-triggers-design.md`

**Out of this plan:** heym.run work (templates, marketing surfaces, docs sync). That lives in `heymweb/docs/superpowers/plans/2026-10-17-google-drive-sheets-triggers-site.md` and runs after a Heym release ships these nodes.

---

## File map

**Backend: create**

| File | Responsibility |
|---|---|
| `backend/app/services/google_triggers/__init__.py` | Package marker |
| `backend/app/services/google_triggers/fingerprint.py` | Keyed HMAC fingerprints, `key_id` |
| `backend/app/services/google_triggers/config.py` | Parse node data into `DriveTriggerConfig` / `SheetsTriggerConfig` |
| `backend/app/services/google_triggers/events.py` | `ItemWrite`, `TriggerEvent`, `PollSkippedError`, `MOVED` |
| `backend/app/services/google_triggers/drive_source.py` | Drive metadata fetch and diff (pure apart from the service call) |
| `backend/app/services/google_triggers/sheets_source.py` | Sheet snapshot, row identity, fingerprint diff (pure) |
| `backend/app/services/google_triggers/state_store.py` | Claim, baseline, consume (CAS), reset, cleanup |
| `backend/app/services/google_triggers/sources.py` | Poller adapters `DriveSource`, `SheetsSource`, `build_source` |
| `backend/app/services/google_triggers/poller.py` | Leader loop; claim, read, diff, consume, dispatch |
| `backend/app/services/trigger_run_dispatch.py` | Shared "run a triggered workflow and persist history" helper |
| `backend/app/services/node_execution/nodes/google_drive_trigger_node.py` | Node handler |
| `backend/app/services/node_execution/nodes/google_sheets_trigger_node.py` | Node handler |
| `backend/alembic/versions/140_add_trigger_poll_state.py` | `trigger_poll_states`, `trigger_poll_items` |

**Backend: modify**
- `app/db/models.py`
- `app/services/google_drive_service.py`
- `app/services/google_sheets_service.py`
- `app/services/imap_trigger_service.py`
- `app/services/node_execution/registry.py`
- `app/services/cluster/node_placement.py`
- `app/services/trigger_inputs.py`
- `app/services/workflow_status.py`
- `app/services/dashboard_widget_policy.py`
- `app/services/credential_catalog.py`
- `app/main.py`
- `app/services/workflow_dsl_prompt.py`

**Backend tests: create**
- `test_google_trigger_fingerprint.py`
- `test_google_trigger_config.py`
- `test_google_drive_trigger_source.py`
- `test_google_sheets_trigger_source.py`
- `test_google_trigger_state_store.py` (real PostgreSQL)
- `test_trigger_run_dispatch.py`
- `test_google_trigger_nodes.py`
- `test_google_trigger_sources.py`
- `test_google_trigger_poller.py`

**Backend tests: modify**
- `test_google_drive_service.py`
- `test_google_sheets_service.py`
- `test_imap_trigger_service.py`
- `test_trigger_pending_hitl.py`
- `test_build_assistant_prompt_node_templates.py`

**Frontend: create**
- `src/lib/googleTriggerConfig.ts` and `src/lib/googleTriggerConfig.test.ts`
- `src/components/Panels/propertiesPanel/nodes/GoogleDriveTriggerNodeProperties.vue`
- `src/components/Panels/propertiesPanel/nodes/GoogleSheetsTriggerNodeProperties.vue`
- `src/features/release-tour/components/visuals/GoogleTriggersTourVisual.vue`
- `e2e/google-triggers.spec.ts`
- `src/docs/content/nodes/google-drive-trigger-node.md`
- `src/docs/content/nodes/google-sheets-trigger-node.md`

**Frontend: modify**
- `src/types/workflow.ts`
- `src/types/node.ts`
- `src/components/Canvas/WorkflowCanvas.vue`
- `src/lib/nodeIcons.ts`
- `src/components/Nodes/BaseNode.vue`
- `src/lib/canvasConnectionRules.ts`
- `src/lib/workflowPreview.ts`
- `src/components/Panels/NodePanel.vue`
- `src/components/Panels/propertiesPanel/NodeErrorHandlingSection.vue`
- `src/components/Panels/propertiesPanel/usePropertiesPanelController.ts`
- `src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue`
- `src/stores/workflow.ts`
- `src/features/release-tour/releaseRegistry.ts`
- `src/features/release-tour/tourVisuals.ts`
- Docs: `manifest.ts`, `reference/features.md`, `node-types.md`, `triggers.md`, `integrations.md`, `credentials.md`, `credentials-sharing.md`, `nodes/google-drive-node.md`, `nodes/google-sheets-node.md`

**Frontend: delete**
- `src/features/release-tour/components/visuals/DashboardHitlTourVisual.vue`. The registry keeps only the five newest sections.

---

## Task 0: Environment

**Files:** none

- [ ] **Step 1: Pick the branch with the user** (straight to `main`, or a feature branch and a PR).

- [ ] **Step 2: Start a throwaway PostgreSQL for tests.** Docker is OrbStack.

```bash
orb start
docker run -d --name heym-trigger-pg -e POSTGRES_USER=heym -e POSTGRES_PASSWORD=heym -e POSTGRES_DB=heym -p 6543:5432 postgres:16
export DATABASE_URL=postgresql+asyncpg://heym:heym@localhost:6543/heym
export SECRET_KEY=test-secret-key-for-tests-only-32-bytes
cd backend && uv run alembic upgrade head
```

Expected: Alembic ends at `139_add_slack_bot_credential (head)`.

- [ ] **Step 3: Confirm a green baseline.**

```bash
cd backend && uv run pytest tests/test_imap_trigger_service.py tests/test_trigger_pending_hitl.py tests/test_cluster_node_placement.py -q
```

Expected: all pass.

---

## Task 1: Keyed fingerprints

**Files:**
- Create: `backend/app/services/google_triggers/__init__.py`
- Create: `backend/app/services/google_triggers/fingerprint.py`
- Test: `backend/tests/test_google_trigger_fingerprint.py`

- [ ] **Step 1: Write the failing test**

```python
"""Keyed fingerprints for Google trigger snapshots."""

import unittest

from app.services.google_triggers.fingerprint import (
    CELL_DIGEST_CHARS,
    ITEM_DIGEST_CHARS,
    Fingerprinter,
)

SECRET = "test-secret-key-for-tests-only-32-bytes"


class FingerprinterTests(unittest.TestCase):
    def test_same_value_on_the_same_node_matches(self) -> None:
        fingerprinter = Fingerprinter.for_node(SECRET, "wf-1", "node-1")
        self.assertEqual(fingerprinter.cell("Paid"), fingerprinter.cell("Paid"))

    def test_digests_have_fixed_lengths(self) -> None:
        fingerprinter = Fingerprinter.for_node(SECRET, "wf-1", "node-1")
        self.assertEqual(len(fingerprinter.cell("Paid")), CELL_DIGEST_CHARS)
        self.assertEqual(len(fingerprinter.item("Paid")), ITEM_DIGEST_CHARS)

    def test_another_node_fingerprints_the_same_value_differently(self) -> None:
        first = Fingerprinter.for_node(SECRET, "wf-1", "node-1")
        second = Fingerprinter.for_node(SECRET, "wf-1", "node-2")
        self.assertNotEqual(first.item("ada@example.com"), second.item("ada@example.com"))

    def test_rotating_the_secret_changes_key_id_and_digests(self) -> None:
        before = Fingerprinter.for_node(SECRET, "wf-1", "node-1")
        after = Fingerprinter.for_node(SECRET + "-rotated", "wf-1", "node-1")
        self.assertNotEqual(before.key_id, after.key_id)
        self.assertNotEqual(before.cell("yes"), after.cell("yes"))

    def test_key_id_is_the_same_for_every_node(self) -> None:
        first = Fingerprinter.for_node(SECRET, "wf-1", "node-1")
        second = Fingerprinter.for_node(SECRET, "wf-2", "node-9")
        self.assertEqual(first.key_id, second.key_id)

    def test_repr_does_not_expose_the_key(self) -> None:
        fingerprinter = Fingerprinter.for_node(SECRET, "wf-1", "node-1")
        self.assertNotIn(repr(fingerprinter.key), repr(fingerprinter))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd backend && uv run pytest tests/test_google_trigger_fingerprint.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.google_triggers'`.

- [ ] **Step 3: Implement**

`backend/app/services/google_triggers/__init__.py`:

```python
"""Google Drive and Google Sheets polling triggers."""
```

`backend/app/services/google_triggers/fingerprint.py`:

```python
"""Keyed fingerprints for polling-trigger snapshots.

A Google Sheets Trigger has to tell that a row or a cell changed without keeping what it
said, so the snapshot stores fingerprints instead of values.

This is deliberately not ``secret_tokens.hash_secret``. That helper is a plain SHA-256 for
high-entropy capability secrets, where there is nothing to guess. Cell values have low
entropy ("yes", "100", a status name), so an unkeyed hash of them could be reversed by
hashing likely values and comparing. An HMAC keyed with a value derived from SECRET_KEY
means a reader of the database or a backup cannot run that guess loop.

Each fingerprint is also salted with the workflow and node, so the same value watched by
two triggers does not produce the same fingerprint.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field

_DERIVATION_LABEL = b"heym:trigger-fingerprint:v1"

#: Cell fingerprints only detect change; a collision hides one edit, nothing more.
CELL_DIGEST_CHARS = 8
#: Row keys and header rows identify items, so they get more bits.
ITEM_DIGEST_CHARS = 16


@dataclass(frozen=True)
class Fingerprinter:
    """Fingerprints values for one trigger node."""

    key: bytes = field(repr=False)
    salt: str

    @classmethod
    def for_node(cls, secret: str, workflow_id: str, node_id: str) -> Fingerprinter:
        """Derive the fingerprint key from ``secret`` and salt it with the node's identity."""
        key = hmac.new(secret.encode("utf-8"), _DERIVATION_LABEL, hashlib.sha256).digest()
        return cls(key=key, salt=f"{workflow_id}:{node_id}:")

    @property
    def key_id(self) -> str:
        """Short identifier of the key; a change means stored fingerprints no longer compare."""
        return hashlib.sha256(self.key).hexdigest()[:16]

    def cell(self, value: str) -> str:
        """Fingerprint of one cell value."""
        return self._digest(value, CELL_DIGEST_CHARS)

    def item(self, value: str) -> str:
        """Fingerprint of a row key or a header row."""
        return self._digest(value, ITEM_DIGEST_CHARS)

    def _digest(self, value: str, length: int) -> str:
        message = (self.salt + value).encode("utf-8")
        return hmac.new(self.key, message, hashlib.sha256).hexdigest()[:length]
```

- [ ] **Step 4: Run the test to see it pass**

Run: `cd backend && uv run pytest tests/test_google_trigger_fingerprint.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_triggers/__init__.py backend/app/services/google_triggers/fingerprint.py backend/tests/test_google_trigger_fingerprint.py
git commit -m "feat(triggers): keyed fingerprints for Google trigger snapshots"
```

---

## Task 2: Trigger config parsing

**Files:**
- Create: `backend/app/services/google_triggers/config.py`
- Test: `backend/tests/test_google_trigger_config.py`

- [ ] **Step 1: Write the failing test**

```python
"""Google trigger node data parsed into configs."""

import unittest

from app.services.google_triggers.config import (
    TRIGGER_EVENTS,
    parse_drive_config,
    parse_poll_minutes,
    parse_sheets_config,
)


class DriveConfigTests(unittest.TestCase):
    def test_defaults_watch_my_drive_root_for_every_event(self) -> None:
        config = parse_drive_config({"credentialId": "cred"})
        self.assertEqual(config.scope, "folder")
        self.assertEqual(config.folder_id, "")
        self.assertEqual(config.events, frozenset(TRIGGER_EVENTS))
        self.assertFalse(config.include_folders)
        self.assertEqual(config.poll_minutes, 1)
        self.assertIsNone(config.problem())

    def test_folder_url_is_parsed_to_an_id(self) -> None:
        config = parse_drive_config(
            {
                "credentialId": "cred",
                "gdtFolderId": "https://drive.google.com/drive/folders/1FolderXyz_9",
            }
        )
        self.assertEqual(config.folder_id, "1FolderXyz_9")

    def test_file_scope_never_fires_created(self) -> None:
        config = parse_drive_config(
            {
                "credentialId": "cred",
                "gdtScope": "file",
                "gdtFileId": "https://drive.google.com/file/d/1AbC/view",
                "gdtEvents": ["created", "updated"],
            }
        )
        self.assertEqual(config.file_id, "1AbC")
        self.assertEqual(config.events, frozenset({"updated"}))

    def test_file_scope_without_a_file_is_a_problem(self) -> None:
        config = parse_drive_config({"credentialId": "cred", "gdtScope": "file"})
        self.assertEqual(config.problem(), "no file selected")

    def test_missing_credential_is_a_problem(self) -> None:
        self.assertEqual(parse_drive_config({}).problem(), "no credential selected")

    def test_unknown_events_are_dropped(self) -> None:
        config = parse_drive_config({"credentialId": "c", "gdtEvents": ["created", "renamed"]})
        self.assertEqual(config.events, frozenset({"created"}))

    def test_scope_fingerprint_ignores_events_and_interval(self) -> None:
        base = {"credentialId": "c", "gdtFolderId": "F1"}
        first = parse_drive_config({**base, "gdtEvents": ["created"], "pollIntervalMinutes": 1})
        second = parse_drive_config({**base, "gdtEvents": ["deleted"], "pollIntervalMinutes": 9})
        other_folder = parse_drive_config({**base, "gdtFolderId": "F2"})
        self.assertEqual(first.scope_fingerprint(), second.scope_fingerprint())
        self.assertNotEqual(first.scope_fingerprint(), other_folder.scope_fingerprint())


class SheetsConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        config = parse_sheets_config({"credentialId": "c", "gstSpreadsheetId": "S1"})
        self.assertEqual(config.sheet_name, "Sheet1")
        self.assertTrue(config.has_header)
        self.assertEqual(config.key_column, "")
        self.assertEqual(config.events, frozenset(TRIGGER_EVENTS))
        self.assertIsNone(config.problem())

    def test_spreadsheet_url_is_parsed_to_an_id(self) -> None:
        config = parse_sheets_config(
            {
                "credentialId": "c",
                "gstSpreadsheetId": "https://docs.google.com/spreadsheets/d/1SheetId_7/edit#gid=0",
            }
        )
        self.assertEqual(config.spreadsheet_id, "1SheetId_7")

    def test_missing_spreadsheet_is_a_problem(self) -> None:
        config = parse_sheets_config({"credentialId": "c"})
        self.assertEqual(config.problem(), "no spreadsheet selected")

    def test_header_is_off_only_when_set_false(self) -> None:
        base = {"credentialId": "c", "gstSpreadsheetId": "S1"}
        self.assertTrue(parse_sheets_config({**base, "gstHasHeader": None}).has_header)
        self.assertFalse(parse_sheets_config({**base, "gstHasHeader": False}).has_header)

    def test_scope_fingerprint_tracks_header_and_key_column(self) -> None:
        base = {"credentialId": "c", "gstSpreadsheetId": "S1"}
        plain = parse_sheets_config(base)
        keyed = parse_sheets_config({**base, "gstKeyColumn": "Email"})
        self.assertNotEqual(plain.scope_fingerprint("h1"), plain.scope_fingerprint("h2"))
        self.assertNotEqual(plain.scope_fingerprint("h1"), keyed.scope_fingerprint("h1"))


class PollMinutesTests(unittest.TestCase):
    def test_interval_is_at_least_one_minute(self) -> None:
        self.assertEqual(parse_poll_minutes("0"), 1)
        self.assertEqual(parse_poll_minutes("abc"), 1)
        self.assertEqual(parse_poll_minutes(None), 1)
        self.assertEqual(parse_poll_minutes(15), 15)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd backend && uv run pytest tests/test_google_trigger_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.google_triggers.config'`.

- [ ] **Step 3: Implement** `backend/app/services/google_triggers/config.py`

```python
"""Google trigger node settings, read from a node's data.

These fields are read by the poller, never by the executor, so they hold plain values
rather than `$` expressions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.services.google_drive_service import parse_drive_id
from app.services.google_sheets_service import GoogleSheetsService

DRIVE_TRIGGER = "googleDriveTrigger"
SHEETS_TRIGGER = "googleSheetsTrigger"
TRIGGER_EVENTS: tuple[str, ...] = ("created", "updated", "deleted")
DEFAULT_POLL_MINUTES = 1


def parse_poll_minutes(raw: Any) -> int:
    """Poll interval in whole minutes; missing or invalid means 1, and never below 1."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_POLL_MINUTES
    return max(1, value)


def parse_events(raw: Any, allowed: tuple[str, ...]) -> frozenset[str]:
    """Events that start a run. A missing value means all of them; unknown names are dropped."""
    if not isinstance(raw, list):
        return frozenset(allowed)
    return frozenset(str(item) for item in raw if str(item) in allowed)


def _fingerprint(parts: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DriveTriggerConfig:
    """What one Google Drive Trigger node watches."""

    credential_id: str
    scope: str
    folder_id: str
    file_id: str
    events: frozenset[str]
    include_folders: bool
    poll_minutes: int

    def problem(self) -> str | None:
        """Why this node cannot be polled yet, or None."""
        if not self.credential_id:
            return "no credential selected"
        if self.scope == "file" and not self.file_id:
            return "no file selected"
        return None

    def scope_fingerprint(self) -> str:
        """Changes when what is watched changes; events and interval are left out."""
        return _fingerprint(
            {
                "type": DRIVE_TRIGGER,
                "credential": self.credential_id,
                "scope": self.scope,
                "folder": self.folder_id,
                "file": self.file_id,
                "include_folders": self.include_folders,
            }
        )


def parse_drive_config(data: dict[str, Any]) -> DriveTriggerConfig:
    """Read a googleDriveTrigger node's data."""
    scope = "file" if data.get("gdtScope") == "file" else "folder"
    allowed = ("updated", "deleted") if scope == "file" else TRIGGER_EVENTS
    return DriveTriggerConfig(
        credential_id=str(data.get("credentialId") or "").strip(),
        scope=scope,
        folder_id=parse_drive_id(str(data.get("gdtFolderId") or "")) if scope == "folder" else "",
        file_id=parse_drive_id(str(data.get("gdtFileId") or "")) if scope == "file" else "",
        events=parse_events(data.get("gdtEvents"), allowed),
        include_folders=scope == "folder" and data.get("gdtIncludeFolders") is True,
        poll_minutes=parse_poll_minutes(data.get("pollIntervalMinutes")),
    )


@dataclass(frozen=True)
class SheetsTriggerConfig:
    """What one Google Sheets Trigger node watches."""

    credential_id: str
    spreadsheet_id: str
    sheet_name: str
    has_header: bool
    key_column: str
    events: frozenset[str]
    poll_minutes: int

    def problem(self) -> str | None:
        """Why this node cannot be polled yet, or None."""
        if not self.credential_id:
            return "no credential selected"
        if not self.spreadsheet_id:
            return "no spreadsheet selected"
        if not self.sheet_name:
            return "no sheet name"
        return None

    def scope_fingerprint(self, header_fingerprint: str) -> str:
        """Changes when the watched tab, row identity, or header row changes."""
        return _fingerprint(
            {
                "type": SHEETS_TRIGGER,
                "credential": self.credential_id,
                "spreadsheet": self.spreadsheet_id,
                "sheet": self.sheet_name,
                "has_header": self.has_header,
                "key_column": self.key_column,
                "header": header_fingerprint,
            }
        )


def parse_sheets_config(data: dict[str, Any]) -> SheetsTriggerConfig:
    """Read a googleSheetsTrigger node's data."""
    raw_id = str(data.get("gstSpreadsheetId") or "").strip()
    return SheetsTriggerConfig(
        credential_id=str(data.get("credentialId") or "").strip(),
        spreadsheet_id=GoogleSheetsService.parse_spreadsheet_id(raw_id) if raw_id else "",
        sheet_name=str(data.get("gstSheetName") or "Sheet1"),
        has_header=data.get("gstHasHeader") is not False,
        key_column=str(data.get("gstKeyColumn") or "").strip(),
        events=parse_events(data.get("gstEvents"), TRIGGER_EVENTS),
        poll_minutes=parse_poll_minutes(data.get("pollIntervalMinutes")),
    )
```

- [ ] **Step 4: Run the test to see it pass**

Run: `cd backend && uv run pytest tests/test_google_trigger_config.py -q`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_triggers/config.py backend/tests/test_google_trigger_config.py
git commit -m "feat(triggers): parse Google Drive and Sheets trigger settings"
```

---

## Task 3: Drive service reads for the trigger

**Files:**
- Modify: `backend/app/services/google_drive_service.py` (add two methods after `list_folder_files`)
- Test: `backend/tests/test_google_drive_service.py` (append a class)

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_google_drive_service.py`. Change the module's import line to `from app.services.google_drive_service import FOLDER_MIME, GoogleDriveService, parse_drive_id`.

```python
def _ok(payload: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


def _status(code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = code
    response.json.return_value = {"error": {"message": "nope"}}
    response.text = "nope"
    return response


class TestTriggerReads(unittest.TestCase):
    def setUp(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        self.service = GoogleDriveService("cred-1", _config(future), MagicMock())

    def test_list_folder_entries_checks_the_folder_then_lists_files_only(self) -> None:
        folder = _ok({"id": "F1", "mimeType": FOLDER_MIME, "trashed": False})
        listing = _ok({"files": [{"id": "a", "name": "a.pdf"}]})
        with patch(
            "app.services.google_drive_service.httpx.get", side_effect=[folder, listing]
        ) as get:
            entries = self.service.list_folder_entries("F1", include_folders=False, max_entries=10)

        self.assertEqual(entries, [{"id": "a", "name": "a.pdf"}])
        params = get.call_args_list[1].kwargs["params"]
        self.assertIn("'F1' in parents", params["q"])
        self.assertIn("trashed = false", params["q"])
        self.assertIn(f"mimeType != '{FOLDER_MIME}'", params["q"])
        self.assertIn("createdTime", params["fields"])
        self.assertEqual(params["pageSize"], 10)

    def test_include_folders_drops_the_mime_filter(self) -> None:
        folder = _ok({"id": "F1", "mimeType": FOLDER_MIME, "trashed": False})
        with patch(
            "app.services.google_drive_service.httpx.get", side_effect=[folder, _ok({"files": []})]
        ) as get:
            self.service.list_folder_entries("F1", include_folders=True, max_entries=10)

        self.assertNotIn("mimeType", get.call_args_list[1].kwargs["params"]["q"])

    def test_root_is_listed_without_a_folder_check(self) -> None:
        with patch(
            "app.services.google_drive_service.httpx.get", return_value=_ok({"files": []})
        ) as get:
            self.service.list_folder_entries("", include_folders=False, max_entries=10)

        self.assertEqual(get.call_count, 1)
        self.assertIn("'root' in parents", get.call_args.kwargs["params"]["q"])

    def test_trashed_folder_raises(self) -> None:
        folder = _ok({"id": "F1", "mimeType": FOLDER_MIME, "trashed": True})
        with patch("app.services.google_drive_service.httpx.get", return_value=folder):
            with self.assertRaises(ValueError):
                self.service.list_folder_entries("F1", include_folders=False, max_entries=10)

    def test_missing_folder_raises(self) -> None:
        with patch("app.services.google_drive_service.httpx.get", return_value=_status(404)):
            with self.assertRaises(ValueError):
                self.service.list_folder_entries("F1", include_folders=False, max_entries=10)

    def test_get_file_entry_returns_none_when_missing(self) -> None:
        with patch("app.services.google_drive_service.httpx.get", return_value=_status(404)):
            self.assertIsNone(self.service.get_file_entry("A1"))

    def test_get_file_entry_returns_none_when_trashed(self) -> None:
        trashed = _ok({"id": "A1", "name": "a.pdf", "trashed": True})
        with patch("app.services.google_drive_service.httpx.get", return_value=trashed):
            self.assertIsNone(self.service.get_file_entry("A1"))

    def test_get_file_entry_returns_the_entry(self) -> None:
        live = _ok({"id": "A1", "name": "a.pdf", "trashed": False})
        with patch("app.services.google_drive_service.httpx.get", return_value=live):
            self.assertEqual(self.service.get_file_entry("A1")["name"], "a.pdf")
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd backend && uv run pytest tests/test_google_drive_service.py::TestTriggerReads -q`
Expected: FAIL with `AttributeError: 'GoogleDriveService' object has no attribute 'list_folder_entries'`.

- [ ] **Step 3: Implement.** In `backend/app/services/google_drive_service.py`, add below the `_MAX_PAGE_SIZE` constant:

```python
# Fields the Google Drive Trigger stores and hands to runs.
_TRIGGER_FIELDS = "id, name, mimeType, size, createdTime, modifiedTime, webViewLink"
```

Add these methods to `GoogleDriveService`, after `list_folder_files`:

```python
    def list_folder_entries(
        self, folder_id: str, *, include_folders: bool, max_entries: int
    ) -> list[dict[str, Any]]:
        """Raw Drive entries directly inside a folder, for the Google Drive Trigger.

        Stops after ``max_entries`` so a caller can detect an oversized folder without
        paging all of it. Raises ValueError when the folder is missing, trashed, or not a
        folder: an empty listing must never be read as "every file was deleted".
        """
        target = parse_drive_id(folder_id) or "root"
        if target != "root":
            resp = httpx.get(
                f"{_DRIVE_BASE}/files/{target}",
                headers=self._auth_headers(),
                params={"fields": "id, mimeType, trashed", "supportsAllDrives": True},
            )
            self._raise_for_drive_error(resp, target)
            meta = resp.json()
            if meta.get("trashed") or meta.get("mimeType") != FOLDER_MIME:
                raise ValueError(f"Google Drive Trigger: '{target}' is not an available folder")

        clauses = [f"'{target}' in parents", "trashed = false"]
        if not include_folders:
            clauses.append(f"mimeType != '{FOLDER_MIME}'")

        entries: list[dict[str, Any]] = []
        page_token = ""
        while len(entries) < max_entries:
            params: dict[str, Any] = {
                "q": " and ".join(clauses),
                "pageSize": min(max_entries - len(entries), _MAX_PAGE_SIZE),
                "fields": f"nextPageToken, files({_TRIGGER_FIELDS})",
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            }
            if page_token:
                params["pageToken"] = page_token
            resp = httpx.get(f"{_DRIVE_BASE}/files", headers=self._auth_headers(), params=params)
            self._raise_for_drive_error(resp, target)
            data = resp.json()
            entries.extend(data.get("files", []))
            page_token = data.get("nextPageToken", "")
            if not page_token:
                break
        return entries[:max_entries]

    def get_file_entry(self, file_id: str) -> dict[str, Any] | None:
        """Raw Drive entry for one file, or None once it is trashed or no longer visible."""
        target = parse_drive_id(file_id)
        resp = httpx.get(
            f"{_DRIVE_BASE}/files/{target}",
            headers=self._auth_headers(),
            params={"fields": f"{_TRIGGER_FIELDS}, trashed", "supportsAllDrives": True},
        )
        if resp.status_code == 404:
            return None
        self._raise_for_drive_error(resp, target)
        data = resp.json()
        if data.get("trashed"):
            return None
        return data
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd backend && uv run pytest tests/test_google_drive_service.py -q`
Expected: all pass, including the 8 new tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_drive_service.py backend/tests/test_google_drive_service.py
git commit -m "feat(drive): folder and file reads for the Google Drive Trigger"
```

---

## Task 4: Sheets service read for the trigger

**Files:**
- Modify: `backend/app/services/google_sheets_service.py`
- Test: `backend/tests/test_google_sheets_service.py` (append a class)

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_google_sheets_service.py`:

```python
class TestReadSheetValues(unittest.TestCase):
    def setUp(self) -> None:
        from app.services.google_sheets_service import GoogleSheetsService

        self.service = GoogleSheetsService("cred-1", _make_config(), MagicMock())

    def _response(self, values: list) -> MagicMock:
        response = MagicMock()
        response.json.return_value = {"values": values}
        return response

    def test_returns_every_value_as_text(self) -> None:
        with patch(
            "app.services.google_sheets_service.httpx.get",
            return_value=self._response([["Name", "Score"], ["Ada", 3]]),
        ):
            values = self.service.read_sheet_values("S1", "Leads")
        self.assertEqual(values, [["Name", "Score"], ["Ada", "3"]])

    def test_quotes_the_sheet_name(self) -> None:
        with patch(
            "app.services.google_sheets_service.httpx.get", return_value=self._response([])
        ) as get:
            self.service.read_sheet_values("S1", "Q1's Leads")
        url = get.call_args.args[0]
        self.assertTrue(url.endswith("/S1/values/%27Q1%27%27s%20Leads%27"), url)

    def test_raises_on_http_error(self) -> None:
        response = self._response([])
        response.raise_for_status.side_effect = RuntimeError("403")
        with patch("app.services.google_sheets_service.httpx.get", return_value=response):
            with self.assertRaises(RuntimeError):
                self.service.read_sheet_values("S1", "Leads")
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd backend && uv run pytest tests/test_google_sheets_service.py::TestReadSheetValues -q`
Expected: FAIL with `AttributeError: ... no attribute 'read_sheet_values'`.

- [ ] **Step 3: Implement.** Add `from urllib.parse import quote` to the standard-library imports in `backend/app/services/google_sheets_service.py`, then add this method after `read_range`:

```python
    def read_sheet_values(self, spreadsheet_id: str, sheet_name: str) -> list[list[str]]:
        """Every value in the tab's used range as text, for the Google Sheets Trigger.

        Unlike read_range this is not limited to columns A to Z. The sheet name is quoted
        so names with spaces or apostrophes resolve.
        """
        quoted = "'" + sheet_name.replace("'", "''") + "'"
        url = f"{_SHEETS_BASE}/{spreadsheet_id}/values/{quote(quoted, safe='')}"
        resp = httpx.get(
            url,
            headers=self._auth_headers(),
            params={"majorDimension": "ROWS", "valueRenderOption": "FORMATTED_VALUE"},
        )
        resp.raise_for_status()
        return [[str(cell) for cell in row] for row in resp.json().get("values", [])]
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd backend && uv run pytest tests/test_google_sheets_service.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_sheets_service.py backend/tests/test_google_sheets_service.py
git commit -m "feat(sheets): full-tab read for the Google Sheets Trigger"
```

---

## Task 5: Events and the Drive diff

**Files:**
- Create: `backend/app/services/google_triggers/events.py`
- Create: `backend/app/services/google_triggers/drive_source.py`
- Test: `backend/tests/test_google_drive_trigger_source.py`

- [ ] **Step 1: Write the failing test**

```python
"""Google Drive Trigger diff: created, updated, deleted from stored metadata."""

import unittest
from unittest.mock import MagicMock

from app.services.google_drive_service import FOLDER_MIME
from app.services.google_triggers.config import parse_drive_config
from app.services.google_triggers.drive_source import (
    DRIVE_ENTRY_LIMIT,
    diff_drive,
    entry_metadata,
    fetch_drive_entries,
)
from app.services.google_triggers.events import ItemWrite, PollSkippedError

FOLDER = parse_drive_config({"credentialId": "c", "gdtFolderId": "F1"})


def _raw(file_id: str, name: str = "a.pdf", modified: str = "2026-10-17T10:00:00Z") -> dict:
    return {
        "id": file_id,
        "name": name,
        "mimeType": "application/pdf",
        "size": "10",
        "createdTime": "2026-10-17T09:00:00Z",
        "modifiedTime": modified,
        "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
    }


class EntryMetadataTests(unittest.TestCase):
    def test_maps_drive_fields(self) -> None:
        meta = entry_metadata(_raw("a"))
        self.assertEqual(meta["size_bytes"], 10)
        self.assertEqual(meta["mime_type"], "application/pdf")
        self.assertFalse(meta["is_folder"])

    def test_folders_have_no_size(self) -> None:
        meta = entry_metadata({"id": "f", "name": "Q4", "mimeType": FOLDER_MIME})
        self.assertTrue(meta["is_folder"])
        self.assertIsNone(meta["size_bytes"])


class DiffDriveTests(unittest.TestCase):
    def test_new_file_is_created(self) -> None:
        live = [entry_metadata(_raw("a"))]
        [change] = diff_drive({}, live, FOLDER)
        self.assertEqual(change.event, "created")
        self.assertEqual(change.payload["file"]["id"], "a")
        self.assertEqual(change.payload["changed_fields"], [])
        self.assertEqual(change.payload["folder_id"], "F1")
        self.assertEqual(change.write, ItemWrite("a", live[0]))
        self.assertEqual(change.revert, ItemWrite("a", None))

    def test_rename_is_updated_with_changed_fields(self) -> None:
        before = entry_metadata(_raw("a"))
        after = entry_metadata(_raw("a", name="b.pdf"))
        [change] = diff_drive({"a": before}, [after], FOLDER)
        self.assertEqual(change.event, "updated")
        self.assertEqual(change.payload["changed_fields"], ["name"])
        self.assertEqual(change.revert, ItemWrite("a", before))

    def test_unchanged_file_is_quiet(self) -> None:
        meta = entry_metadata(_raw("a"))
        self.assertEqual(diff_drive({"a": meta}, [meta], FOLDER), [])

    def test_missing_file_is_deleted_with_its_last_known_metadata(self) -> None:
        before = entry_metadata(_raw("a", name="contract.pdf"))
        [change] = diff_drive({"a": before}, [], FOLDER)
        self.assertEqual(change.event, "deleted")
        self.assertEqual(change.payload["file"]["name"], "contract.pdf")
        self.assertEqual(change.write, ItemWrite("a", None))
        self.assertEqual(change.revert, ItemWrite("a", before))

    def test_root_folder_reports_root(self) -> None:
        root = parse_drive_config({"credentialId": "c"})
        [change] = diff_drive({}, [entry_metadata(_raw("a"))], root)
        self.assertEqual(change.payload["folder_id"], "root")

    def test_file_scope_reports_no_folder(self) -> None:
        one_file = parse_drive_config({"credentialId": "c", "gdtScope": "file", "gdtFileId": "a"})
        before = entry_metadata(_raw("a"))
        [change] = diff_drive({"a": before}, [entry_metadata(_raw("a", name="b"))], one_file)
        self.assertIsNone(change.payload["folder_id"])


class FetchDriveEntriesTests(unittest.TestCase):
    def test_file_scope_returns_nothing_for_a_missing_file(self) -> None:
        one_file = parse_drive_config({"credentialId": "c", "gdtScope": "file", "gdtFileId": "a"})
        service = MagicMock()
        service.get_file_entry.return_value = None
        self.assertEqual(fetch_drive_entries(service, one_file), [])

    def test_folder_over_the_limit_is_skipped(self) -> None:
        service = MagicMock()
        service.list_folder_entries.return_value = [
            _raw(str(index)) for index in range(DRIVE_ENTRY_LIMIT + 1)
        ]
        with self.assertRaises(PollSkippedError):
            fetch_drive_entries(service, FOLDER)
        service.list_folder_entries.assert_called_once_with(
            "F1", include_folders=False, max_entries=DRIVE_ENTRY_LIMIT + 1
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd backend && uv run pytest tests/test_google_drive_trigger_source.py -q`
Expected: FAIL with `ModuleNotFoundError: ... drive_source`.

- [ ] **Step 3: Implement**

`backend/app/services/google_triggers/events.py`:

```python
"""What a trigger diff produces: run payloads plus the snapshot writes that consume them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: A sheet row whose key moved to another row number: the snapshot follows it, no run starts.
MOVED = "moved"


@dataclass(frozen=True)
class ItemWrite:
    """Set one stored item to ``payload``, or remove it when ``payload`` is None."""

    item_key: str
    payload: dict[str, Any] | None


@dataclass(frozen=True)
class TriggerEvent:
    """One change: what the run receives, the write that consumes it, and the write that undoes it."""

    event: str
    payload: dict[str, Any]
    write: ItemWrite
    revert: ItemWrite


class PollSkippedError(Exception):
    """The poll cannot produce a trustworthy snapshot; the stored one must stay as it is."""
```

`backend/app/services/google_triggers/drive_source.py`:

```python
"""Google Drive Trigger: read a folder or one file and diff it against stored metadata.

Only metadata is kept (id, name, type, size, times, link). File contents are never read.
"""

from __future__ import annotations

from typing import Any

from app.services.google_drive_service import FOLDER_MIME, GoogleDriveService
from app.services.google_triggers.config import DriveTriggerConfig
from app.services.google_triggers.events import ItemWrite, PollSkippedError, TriggerEvent

DRIVE_ENTRY_LIMIT = 5000
_TRACKED_FIELDS = ("name", "modified_time", "size_bytes", "mime_type")


def entry_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a Drive API file resource to the metadata a run receives and the snapshot stores."""
    raw_size = raw.get("size")
    mime_type = str(raw.get("mimeType") or "")
    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or ""),
        "mime_type": mime_type,
        "size_bytes": int(raw_size) if raw_size is not None else None,
        "created_time": str(raw.get("createdTime") or ""),
        "modified_time": str(raw.get("modifiedTime") or ""),
        "web_view_link": str(raw.get("webViewLink") or ""),
        "is_folder": mime_type == FOLDER_MIME,
    }


def fetch_drive_entries(
    service: GoogleDriveService, config: DriveTriggerConfig
) -> list[dict[str, Any]]:
    """Live metadata for the watched scope. Raises PollSkippedError for an oversized folder."""
    if config.scope == "file":
        raw = service.get_file_entry(config.file_id)
        return [entry_metadata(raw)] if raw else []
    raw_entries = service.list_folder_entries(
        config.folder_id,
        include_folders=config.include_folders,
        max_entries=DRIVE_ENTRY_LIMIT + 1,
    )
    if len(raw_entries) > DRIVE_ENTRY_LIMIT:
        raise PollSkippedError(f"folder has more than {DRIVE_ENTRY_LIMIT} entries")
    return [entry_metadata(raw) for raw in raw_entries]


def drive_items(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Snapshot items keyed by file ID."""
    return {entry["id"]: entry for entry in entries if entry["id"]}


def diff_drive(
    stored: dict[str, dict[str, Any]],
    entries: list[dict[str, Any]],
    config: DriveTriggerConfig,
) -> list[TriggerEvent]:
    """Changes between the stored metadata and the live entries, oldest edit first."""
    live = drive_items(entries)
    folder_id = (config.folder_id or "root") if config.scope == "folder" else None
    changes: list[TriggerEvent] = []

    for key, entry in sorted(live.items(), key=lambda item: (item[1]["modified_time"], item[0])):
        before = stored.get(key)
        if before is None:
            changes.append(
                _event("created", entry, [], folder_id, ItemWrite(key, entry), ItemWrite(key, None))
            )
            continue
        fields = [name for name in _TRACKED_FIELDS if before.get(name) != entry.get(name)]
        if fields:
            changes.append(
                _event(
                    "updated", entry, fields, folder_id, ItemWrite(key, entry), ItemWrite(key, before)
                )
            )

    for key in sorted(set(stored) - set(live)):
        before = stored[key]
        changes.append(
            _event("deleted", before, [], folder_id, ItemWrite(key, None), ItemWrite(key, before))
        )
    return changes


def _event(
    kind: str,
    file: dict[str, Any],
    changed_fields: list[str],
    folder_id: str | None,
    write: ItemWrite,
    revert: ItemWrite,
) -> TriggerEvent:
    payload = {
        "event": kind,
        "file": dict(file),
        "changed_fields": changed_fields,
        "folder_id": folder_id,
    }
    return TriggerEvent(event=kind, payload=payload, write=write, revert=revert)
```

- [ ] **Step 4: Run the test to see it pass**

Run: `cd backend && uv run pytest tests/test_google_drive_trigger_source.py -q`
Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_triggers/events.py backend/app/services/google_triggers/drive_source.py backend/tests/test_google_drive_trigger_source.py
git commit -m "feat(triggers): Google Drive Trigger metadata diff"
```

---

## Task 6: The Sheets diff

**Files:**
- Create: `backend/app/services/google_triggers/sheets_source.py`
- Test: `backend/tests/test_google_sheets_trigger_source.py`

- [ ] **Step 1: Write the failing test**

```python
"""Google Sheets Trigger diff over keyed fingerprints; cell values are never stored."""

import json
import unittest

from app.services.google_triggers.config import parse_sheets_config
from app.services.google_triggers.events import MOVED, PollSkippedError
from app.services.google_triggers.fingerprint import Fingerprinter
from app.services.google_triggers.sheets_source import (
    SHEET_ROW_LIMIT,
    build_snapshot,
    diff_sheet,
    header_fingerprint,
    sheet_items,
)

FP = Fingerprinter.for_node("test-secret-key-for-tests-only-32-bytes", "wf", "node")
BASE = {"credentialId": "c", "gstSpreadsheetId": "S1", "gstSheetName": "Leads"}
BY_ROW = parse_sheets_config(BASE)
BY_EMAIL = parse_sheets_config({**BASE, "gstKeyColumn": "Email"})
HEADER = ["Name", "Email", "Status"]


def _items(values: list[list[str]], config=BY_ROW) -> dict:
    return sheet_items(build_snapshot(values, config.has_header), FP, config)


def _diff(before: list[list[str]], after: list[list[str]], config=BY_ROW) -> list:
    return diff_sheet(_items(before, config), build_snapshot(after, config.has_header), FP, config)


class BuildSnapshotTests(unittest.TestCase):
    def test_skips_header_and_blank_rows_and_keeps_sheet_row_numbers(self) -> None:
        snapshot = build_snapshot([HEADER, ["Ada", "a@x", ""], ["", " "], ["Grace"]], True)
        self.assertEqual(snapshot.header, HEADER)
        self.assertEqual([row.row_index for row in snapshot.rows], [2, 4])
        self.assertEqual(snapshot.rows[0].cells, ["Ada", "a@x"])

    def test_without_a_header_rows_start_at_one(self) -> None:
        snapshot = build_snapshot([["Ada"], ["Grace"]], False)
        self.assertEqual(snapshot.header, [])
        self.assertEqual([row.row_index for row in snapshot.rows], [1, 2])

    def test_too_many_rows_skip_the_poll(self) -> None:
        values = [HEADER] + [[str(index)] for index in range(SHEET_ROW_LIMIT + 1)]
        with self.assertRaises(PollSkippedError):
            build_snapshot(values, True)


class DiffSheetTests(unittest.TestCase):
    def test_new_row_is_created_with_its_live_values(self) -> None:
        [change] = _diff([HEADER, ["Ada", "a@x"]], [HEADER, ["Ada", "a@x"], ["Grace", "g@x"]])
        self.assertEqual(change.event, "created")
        self.assertEqual(
            change.payload["row"], {"Name": "Grace", "Email": "g@x", "Status": "", "rowIndex": 3}
        )
        self.assertEqual(change.payload["changed_columns"], ["Name", "Email"])
        self.assertEqual(change.payload["spreadsheet_id"], "S1")
        self.assertEqual(change.payload["sheet_name"], "Leads")
        self.assertIsNone(change.payload["key"])

    def test_edit_lists_only_the_changed_column(self) -> None:
        [change] = _diff([HEADER, ["Ada", "a@x", "New"]], [HEADER, ["Ada", "a@x", "Paid"]])
        self.assertEqual(change.event, "updated")
        self.assertEqual(change.payload["changed_columns"], ["Status"])
        self.assertEqual(change.payload["row"]["Status"], "Paid")

    def test_clearing_the_last_cell_is_an_update(self) -> None:
        [change] = _diff([HEADER, ["Ada", "a@x", "Paid"]], [HEADER, ["Ada", "a@x"]])
        self.assertEqual(change.event, "updated")
        self.assertEqual(change.payload["changed_columns"], ["Status"])

    def test_deleted_row_reports_only_its_row_number(self) -> None:
        [change] = _diff([HEADER, ["Ada"], ["Grace"]], [HEADER, ["Ada"]])
        self.assertEqual(change.event, "deleted")
        self.assertEqual(change.payload["row"], {"rowIndex": 3})
        self.assertEqual(change.payload["changed_columns"], [])

    def test_row_numbers_shift_when_a_row_is_inserted_above(self) -> None:
        changes = _diff([HEADER, ["Ada"]], [HEADER, ["New"], ["Ada"]])
        self.assertEqual([change.event for change in changes], ["updated", "created"])

    def test_key_column_follows_a_row_that_moved(self) -> None:
        before = [HEADER, ["Ada", "a@x"]]
        after = [HEADER, ["New", "n@x"], ["Ada", "a@x"]]
        changes = _diff(before, after, BY_EMAIL)
        self.assertEqual([change.event for change in changes], ["created", MOVED])
        self.assertEqual(changes[0].payload["key"], "n@x")
        self.assertEqual(changes[1].write.payload["r"], 3)

    def test_rows_without_a_key_are_ignored(self) -> None:
        self.assertEqual(_diff([HEADER], [HEADER, ["Ada", ""]], BY_EMAIL), [])

    def test_duplicate_keys_keep_the_first_row(self) -> None:
        items = _items([HEADER, ["Ada", "a@x"], ["Ada again", "a@x"]], BY_EMAIL)
        self.assertEqual([item["r"] for item in items.values()], [2])

    def test_missing_key_column_skips_the_poll(self) -> None:
        config = parse_sheets_config({**BASE, "gstKeyColumn": "Phone"})
        with self.assertRaises(PollSkippedError):
            _items([HEADER, ["Ada"]], config)

    def test_column_letter_key_without_a_header(self) -> None:
        config = parse_sheets_config({**BASE, "gstHasHeader": False, "gstKeyColumn": "B"})
        [change] = _diff([["Ada", "a@x"]], [["Ada", "a@x"], ["Grace", "g@x"]], config)
        self.assertEqual(change.payload["key"], "g@x")
        self.assertEqual(change.payload["row"], {"A": "Grace", "B": "g@x", "rowIndex": 2})

    def test_stored_items_hold_no_cell_values(self) -> None:
        stored = json.dumps(_items([HEADER, ["Ada Lovelace", "ada@example.com"]], BY_EMAIL))
        self.assertNotIn("Ada", stored)
        self.assertNotIn("ada@example.com", stored)

    def test_header_fingerprint_changes_with_the_header(self) -> None:
        first = header_fingerprint(build_snapshot([HEADER], True), FP)
        second = header_fingerprint(build_snapshot([["Name", "Mail", "Status"]], True), FP)
        self.assertNotEqual(first, second)
        self.assertEqual(header_fingerprint(build_snapshot([["Ada"]], False), FP), "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd backend && uv run pytest tests/test_google_sheets_trigger_source.py -q`
Expected: FAIL with `ModuleNotFoundError: ... sheets_source`.

- [ ] **Step 3: Implement** `backend/app/services/google_triggers/sheets_source.py`

```python
"""Google Sheets Trigger: read one tab and diff its rows against stored fingerprints.

The snapshot keeps, per row, its last row number and one keyed fingerprint per cell
(see fingerprint.py). It never keeps a cell value, so a run gets the row's live values
and the names of the columns that changed, not what they used to say.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.services.google_sheets_service import _column_letter_zero_based
from app.services.google_triggers.config import SheetsTriggerConfig
from app.services.google_triggers.events import MOVED, ItemWrite, PollSkippedError, TriggerEvent
from app.services.google_triggers.fingerprint import Fingerprinter

logger = logging.getLogger("google_triggers")

SHEET_ROW_LIMIT = 10_000
_COLUMN_LETTERS = re.compile(r"[A-Za-z]{1,3}")


@dataclass(frozen=True)
class SheetRow:
    """One non-empty row: its sheet row number and its cells without trailing blanks."""

    row_index: int
    cells: list[str]


@dataclass(frozen=True)
class SheetSnapshot:
    """A tab as read during one poll. ``header`` is empty when the tab has no header row."""

    header: list[str]
    rows: list[SheetRow]


@dataclass(frozen=True)
class LiveRow:
    """A row with its identity and the payload the snapshot would store for it."""

    item_key: str
    row: SheetRow
    key_value: str | None
    payload: dict[str, Any]


def build_snapshot(values: list[list[Any]], has_header: bool) -> SheetSnapshot:
    """Turn the Sheets API values into rows, skipping blank rows. Raises PollSkippedError when too big."""
    header: list[str] = []
    first_data_row = 1
    if has_header:
        header = [str(cell) for cell in values[0]] if values else []
        first_data_row = 2

    rows: list[SheetRow] = []
    for offset, raw in enumerate(values[first_data_row - 1 :]):
        cells = [str(cell) for cell in raw]
        while cells and cells[-1] == "":
            cells.pop()
        if not any(cell.strip() for cell in cells):
            continue
        rows.append(SheetRow(row_index=first_data_row + offset, cells=cells))

    if len(rows) > SHEET_ROW_LIMIT:
        raise PollSkippedError(f"sheet has more than {SHEET_ROW_LIMIT} rows")
    return SheetSnapshot(header=header, rows=rows)


def header_fingerprint(snapshot: SheetSnapshot, fingerprinter: Fingerprinter) -> str:
    """Fingerprint of the header row, or empty when there is none."""
    if not snapshot.header:
        return ""
    return fingerprinter.item(json.dumps(snapshot.header))


def key_column_index(key_column: str, snapshot: SheetSnapshot, has_header: bool) -> int | None:
    """Position of the key column, or None for row-number identity. Raises PollSkippedError if absent."""
    if not key_column:
        return None
    if has_header:
        for index, title in enumerate(snapshot.header):
            if title.strip() == key_column:
                return index
        for index, title in enumerate(snapshot.header):
            if title.strip().casefold() == key_column.casefold():
                return index
        raise PollSkippedError(f"key column '{key_column}' is not in the header row")
    if _COLUMN_LETTERS.fullmatch(key_column):
        index = 0
        for char in key_column.upper():
            index = index * 26 + (ord(char) - 64)
        return index - 1
    raise PollSkippedError(f"key column '{key_column}' is not a column letter")


def column_name(index: int, snapshot: SheetSnapshot, has_header: bool) -> str:
    """Header text for a column, or its letter when there is no header text."""
    if has_header and index < len(snapshot.header) and snapshot.header[index]:
        return snapshot.header[index]
    return _column_letter_zero_based(index)


def row_object(row: SheetRow, snapshot: SheetSnapshot, has_header: bool) -> dict[str, Any]:
    """A row in the shape the Google Sheets node's readRange returns."""
    if has_header:
        cells = {
            title: (row.cells[index] if index < len(row.cells) else "")
            for index, title in enumerate(snapshot.header)
        }
    else:
        cells = {
            _column_letter_zero_based(index): value for index, value in enumerate(row.cells)
        }
    return {**cells, "rowIndex": row.row_index}


def live_rows(
    snapshot: SheetSnapshot, fingerprinter: Fingerprinter, key_index: int | None
) -> dict[str, LiveRow]:
    """Rows keyed by identity: key fingerprint when a key column is set, else row number."""
    live: dict[str, LiveRow] = {}
    for row in snapshot.rows:
        key_value: str | None = None
        if key_index is None:
            item_key = str(row.row_index)
        else:
            key_value = row.cells[key_index] if key_index < len(row.cells) else ""
            if not key_value.strip():
                continue
            item_key = fingerprinter.item(key_value)
            if item_key in live:
                # Never log the key itself: it is sheet data.
                logger.warning("Google Sheets Trigger: duplicate key at row %s ignored", row.row_index)
                continue
        payload = {"r": row.row_index, "c": [fingerprinter.cell(cell) for cell in row.cells]}
        live[item_key] = LiveRow(item_key, row, key_value, payload)
    return live


def sheet_items(
    snapshot: SheetSnapshot, fingerprinter: Fingerprinter, config: SheetsTriggerConfig
) -> dict[str, dict[str, Any]]:
    """Snapshot items for a baseline."""
    key_index = key_column_index(config.key_column, snapshot, config.has_header)
    return {key: row.payload for key, row in live_rows(snapshot, fingerprinter, key_index).items()}


def diff_sheet(
    stored: dict[str, dict[str, Any]],
    snapshot: SheetSnapshot,
    fingerprinter: Fingerprinter,
    config: SheetsTriggerConfig,
) -> list[TriggerEvent]:
    """Row changes between the stored fingerprints and the live tab, top row first."""
    key_index = key_column_index(config.key_column, snapshot, config.has_header)
    live = live_rows(snapshot, fingerprinter, key_index)
    empty = fingerprinter.cell("")
    base = {"spreadsheet_id": config.spreadsheet_id, "sheet_name": config.sheet_name}
    changes: list[TriggerEvent] = []

    for item_key, current in sorted(live.items(), key=lambda item: item[1].row.row_index):
        before = stored.get(item_key)
        write = ItemWrite(item_key, current.payload)
        row = row_object(current.row, snapshot, config.has_header)
        if before is None:
            columns = [
                column_name(index, snapshot, config.has_header)
                for index, cell in enumerate(current.row.cells)
                if cell.strip()
            ]
            payload = {**base, "event": "created", "row": row, "changed_columns": columns,
                       "key": current.key_value}
            changes.append(TriggerEvent("created", payload, write, ItemWrite(item_key, None)))
            continue

        old_cells = list(before.get("c") or [])
        new_cells = current.payload["c"]
        width = max(len(old_cells), len(new_cells))
        differing = [
            index
            for index in range(width)
            if (old_cells[index] if index < len(old_cells) else empty)
            != (new_cells[index] if index < len(new_cells) else empty)
        ]
        if differing:
            columns = [column_name(index, snapshot, config.has_header) for index in differing]
            payload = {**base, "event": "updated", "row": row, "changed_columns": columns,
                       "key": current.key_value}
            changes.append(TriggerEvent("updated", payload, write, ItemWrite(item_key, before)))
        elif before.get("r") != current.payload["r"]:
            changes.append(TriggerEvent(MOVED, {}, write, ItemWrite(item_key, before)))

    gone = sorted(set(stored) - set(live), key=lambda key: stored[key].get("r", 0))
    for item_key in gone:
        before = stored[item_key]
        payload = {**base, "event": "deleted", "row": {"rowIndex": before.get("r")},
                   "changed_columns": [], "key": None}
        changes.append(
            TriggerEvent("deleted", payload, ItemWrite(item_key, None), ItemWrite(item_key, before))
        )
    return changes
```

Run `uv run ruff format app/services/google_triggers/sheets_source.py` afterwards. It reflows the hand-wrapped payload dicts.

- [ ] **Step 4: Run the test to see it pass**

Run: `cd backend && uv run pytest tests/test_google_sheets_trigger_source.py -q`
Expected: `15 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_triggers/sheets_source.py backend/tests/test_google_sheets_trigger_source.py
git commit -m "feat(triggers): Google Sheets Trigger row diff over keyed fingerprints"
```

---

## Task 7: Snapshot tables

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/140_add_trigger_poll_state.py`

- [ ] **Step 1: Add the models.** In `backend/app/db/models.py`, add `BigInteger,` to the `from sqlalchemy import (...)` list in alphabetical position (before `Boolean`). Append at the end of the file:

```python
class TriggerPollState(Base):
    """Snapshot header of a polling trigger node (Google Drive / Google Sheets Trigger).

    ``next_poll_at`` is the claim that keeps two workers from polling one node together.
    ``version`` is the compare-and-swap counter that lets exactly one worker consume each
    change. See ``app/services/google_triggers/state_store.py``.
    """

    __tablename__ = "trigger_poll_states"
    __table_args__ = (
        UniqueConstraint("workflow_id", "node_id", name="uq_trigger_poll_state_node"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    key_id: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    next_poll_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TriggerPollItem(Base):
    """One watched item: Drive file metadata, or a sheet row's keyed fingerprints. Never cell values."""

    __tablename__ = "trigger_poll_items"
    __table_args__ = (
        UniqueConstraint("state_id", "item_key", name="uq_trigger_poll_item_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trigger_poll_states.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
```

- [ ] **Step 2: Write the migration** `backend/alembic/versions/140_add_trigger_poll_state.py`

```python
"""add trigger poll state for Google Drive and Google Sheets triggers

Revision ID: 140_add_trigger_poll_state
Revises: 139_add_slack_bot_credential
Create Date: 2026-10-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "140_add_trigger_poll_state"
down_revision: str | Sequence[str] | None = "139_add_slack_bot_credential"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trigger_poll_states",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("key_id", sa.String(32), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "next_poll_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("workflow_id", "node_id", name="uq_trigger_poll_state_node"),
    )
    op.create_index("ix_trigger_poll_states_workflow_id", "trigger_poll_states", ["workflow_id"])
    op.create_index("ix_trigger_poll_states_next_poll_at", "trigger_poll_states", ["next_poll_at"])

    op.create_table(
        "trigger_poll_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "state_id",
            UUID(as_uuid=True),
            sa.ForeignKey("trigger_poll_states.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_key", sa.String(255), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.UniqueConstraint("state_id", "item_key", name="uq_trigger_poll_item_key"),
    )


def downgrade() -> None:
    op.drop_table("trigger_poll_items")
    op.drop_index("ix_trigger_poll_states_next_poll_at", table_name="trigger_poll_states")
    op.drop_index("ix_trigger_poll_states_workflow_id", table_name="trigger_poll_states")
    op.drop_table("trigger_poll_states")
```

- [ ] **Step 3: Apply and round-trip**

```bash
cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head && uv run alembic heads
```

Expected: ends with `140_add_trigger_poll_state (head)`, with no errors.

- [ ] **Step 4: Confirm the importable-models guard still passes**

Run: `cd backend && uv run pytest tests/test_models_importable.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/140_add_trigger_poll_state.py
git commit -m "feat(triggers): tables for polling trigger snapshots"
```

---

## Task 8: State store with claim and compare-and-swap

**Files:**
- Create: `backend/app/services/google_triggers/state_store.py`
- Test: `backend/tests/test_google_trigger_state_store.py` (real PostgreSQL)

- [ ] **Step 1: Write the failing test**

```python
"""Snapshot store against real PostgreSQL: one poll per interval, one consumer per change.

Requires a reachable PostgreSQL with migrations applied (see AGENTS.md, PostgreSQL
Integration Tests).
"""

import asyncio
import unittest
import uuid

from sqlalchemy import delete, func, update

from app.services.google_triggers.events import ItemWrite
from app.services.google_triggers.state_store import TriggerStateStore


class TriggerStateStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from app.db.models import User, Workflow
        from app.db.session import async_session_maker, engine

        await engine.dispose()
        self.store = TriggerStateStore()
        self.user_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        # A node type of its own, so delete_except never touches rows of tests running in
        # parallel against the same database.
        self.node_type = f"testTrigger{self.workflow_id.hex[:8]}"
        async with async_session_maker() as session:
            session.add(
                User(
                    id=self.user_id,
                    email=f"trigger_state_{self.user_id.hex[:8]}@example.com",
                    hashed_password="test_hashed_password",
                    name="Trigger State",
                )
            )
            session.add(
                Workflow(
                    id=self.workflow_id,
                    name="Trigger state",
                    owner_id=self.user_id,
                    nodes=[],
                    edges=[],
                )
            )
            await session.commit()

    async def asyncTearDown(self) -> None:
        from app.db.models import User, Workflow
        from app.db.session import async_session_maker, engine

        async with async_session_maker() as session:
            await session.execute(delete(Workflow).where(Workflow.id == self.workflow_id))
            await session.execute(delete(User).where(User.id == self.user_id))
            await session.commit()
        await engine.dispose()

    async def _baseline(self, items: dict | None = None) -> bool:
        return await self.store.insert_baseline(
            workflow_id=self.workflow_id,
            node_id="n1",
            node_type=self.node_type,
            scope_fingerprint="scope",
            key_id="key",
            items={"a": {"r": 2, "c": ["x"]}} if items is None else items,
            poll_minutes=1,
        )

    async def _make_due(self) -> None:
        from app.db.models import TriggerPollState
        from app.db.session import async_session_maker

        async with async_session_maker() as session:
            await session.execute(
                update(TriggerPollState)
                .where(TriggerPollState.workflow_id == self.workflow_id)
                .values(next_poll_at=func.now() - func.make_interval(0, 0, 0, 0, 0, 1))
            )
            await session.commit()

    async def _claim(self):
        return await self.store.claim(self.workflow_id, "n1", 1)

    async def test_a_node_without_state_needs_a_baseline(self) -> None:
        claim = await self._claim()
        self.assertTrue(claim.due)
        self.assertIsNone(claim.poll)

    async def test_a_fresh_baseline_is_not_due_again_yet(self) -> None:
        self.assertTrue(await self._baseline())
        self.assertFalse((await self._claim()).due)

    async def test_concurrent_baselines_record_one(self) -> None:
        results = await asyncio.gather(self._baseline(), self._baseline())
        self.assertEqual(sorted(results), [False, True])

    async def test_concurrent_claims_poll_once(self) -> None:
        await self._baseline()
        await self._make_due()
        claims = await asyncio.gather(self._claim(), self._claim())
        polls = [claim.poll for claim in claims if claim.poll is not None]
        self.assertEqual(len(polls), 1)
        self.assertEqual(polls[0].items, {"a": {"r": 2, "c": ["x"]}})
        self.assertEqual(polls[0].version, 0)

    async def test_one_consumer_wins_a_change(self) -> None:
        await self._baseline()
        await self._make_due()
        poll = (await self._claim()).poll
        results = await asyncio.gather(
            self.store.consume(poll.state_id, poll.version, [ItemWrite("b", {"r": 3, "c": ["1"]})]),
            self.store.consume(poll.state_id, poll.version, [ItemWrite("b", {"r": 3, "c": ["2"]})]),
        )
        self.assertEqual(sorted(results), [False, True])
        await self._make_due()
        after = (await self._claim()).poll
        self.assertEqual(after.version, 1)
        self.assertIn("b", after.items)

    async def test_revert_restores_the_previous_item(self) -> None:
        await self._baseline()
        await self._make_due()
        poll = (await self._claim()).poll
        old = poll.items["a"]
        self.assertTrue(
            await self.store.consume(poll.state_id, 0, [ItemWrite("a", {"r": 2, "c": ["y"]})])
        )
        self.assertTrue(await self.store.consume(poll.state_id, 1, [ItemWrite("a", old)]))
        await self._make_due()
        after = (await self._claim()).poll
        self.assertEqual(after.items["a"], old)
        self.assertEqual(after.version, 2)

    async def test_a_delete_write_removes_the_item(self) -> None:
        await self._baseline()
        await self._make_due()
        poll = (await self._claim()).poll
        self.assertTrue(await self.store.consume(poll.state_id, 0, [ItemWrite("a", None)]))
        await self._make_due()
        self.assertEqual((await self._claim()).poll.items, {})

    async def test_reset_baseline_replaces_items_and_fingerprint(self) -> None:
        await self._baseline()
        await self._make_due()
        poll = (await self._claim()).poll
        self.assertFalse(
            await self.store.reset_baseline(
                poll.state_id, 7, scope_fingerprint="other", key_id="key", items={}
            )
        )
        self.assertTrue(
            await self.store.reset_baseline(
                poll.state_id,
                0,
                scope_fingerprint="other",
                key_id="key2",
                items={"z": {"r": 9, "c": []}},
            )
        )
        await self._make_due()
        after = (await self._claim()).poll
        self.assertEqual(after.scope_fingerprint, "other")
        self.assertEqual(after.key_id, "key2")
        self.assertEqual(after.items, {"z": {"r": 9, "c": []}})

    async def test_delete_except_drops_states_that_are_not_kept(self) -> None:
        await self._baseline()
        removed = await self.store.delete_except((self.node_type,), set())
        self.assertEqual(removed, 1)
        self.assertTrue((await self._claim()).due)
        self.assertIsNone((await self._claim()).poll)

    async def test_delete_except_keeps_listed_states(self) -> None:
        await self._baseline()
        removed = await self.store.delete_except(
            (self.node_type,), {(self.workflow_id, "n1")}
        )
        self.assertEqual(removed, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd backend && uv run pytest tests/test_google_trigger_state_store.py -q`
Expected: FAIL with `ModuleNotFoundError: ... state_store`.

- [ ] **Step 3: Implement** `backend/app/services/google_triggers/state_store.py`

```python
"""Snapshot storage for polling triggers, with the claims that make each change fire once.

Leader election keeps the other workers from polling Google, but correctness does not
rely on it: during a leader handoff two processes can briefly both believe they lead.
Two statements carry the guarantee instead:

- ``claim`` moves ``next_poll_at`` forward only when it is due, so one worker polls a
  node per interval.
- ``consume`` bumps ``version`` only while it still holds the expected value, so each
  change is consumed, and its run started, by exactly one worker.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import TriggerPollItem, TriggerPollState
from app.db.session import async_session_maker
from app.services.google_triggers.events import ItemWrite


@dataclass(frozen=True)
class ClaimedPoll:
    """A node this worker may poll now, with its stored snapshot."""

    state_id: uuid.UUID
    version: int
    scope_fingerprint: str
    key_id: str
    items: dict[str, dict[str, Any]] = field(repr=False)


@dataclass(frozen=True)
class Claim:
    """Outcome of asking to poll a node. ``due`` with no ``poll`` means record a baseline."""

    due: bool
    poll: ClaimedPoll | None = None


NOT_DUE = Claim(due=False)


class TriggerStateStore:
    """Async access to ``trigger_poll_states`` and ``trigger_poll_items``."""

    def __init__(
        self, session_maker: async_sessionmaker[AsyncSession] = async_session_maker
    ) -> None:
        self._session_maker = session_maker

    async def claim(self, workflow_id: uuid.UUID, node_id: str, poll_minutes: int) -> Claim:
        """Claim the node for this interval. Only one concurrent caller gets a ClaimedPoll."""
        async with self._session_maker() as db:
            row = (
                await db.execute(
                    update(TriggerPollState)
                    .where(
                        TriggerPollState.workflow_id == workflow_id,
                        TriggerPollState.node_id == node_id,
                        TriggerPollState.next_poll_at <= func.now(),
                    )
                    .values(next_poll_at=func.now() + timedelta(minutes=poll_minutes))
                    .returning(
                        TriggerPollState.id,
                        TriggerPollState.version,
                        TriggerPollState.scope_fingerprint,
                        TriggerPollState.key_id,
                    )
                    .execution_options(synchronize_session=False)
                )
            ).first()
            if row is None:
                exists = (
                    await db.execute(
                        select(TriggerPollState.id).where(
                            TriggerPollState.workflow_id == workflow_id,
                            TriggerPollState.node_id == node_id,
                        )
                    )
                ).first()
                await db.commit()
                return NOT_DUE if exists else Claim(due=True)

            item_rows = await db.execute(
                select(TriggerPollItem.item_key, TriggerPollItem.payload).where(
                    TriggerPollItem.state_id == row.id
                )
            )
            items = {item.item_key: item.payload for item in item_rows}
            await db.commit()
        return Claim(
            due=True,
            poll=ClaimedPoll(row.id, row.version, row.scope_fingerprint, row.key_id, items),
        )

    async def insert_baseline(
        self,
        *,
        workflow_id: uuid.UUID,
        node_id: str,
        node_type: str,
        scope_fingerprint: str,
        key_id: str,
        items: dict[str, dict[str, Any]],
        poll_minutes: int,
    ) -> bool:
        """Record the first snapshot. False when another worker recorded it first."""
        async with self._session_maker() as db:
            state_id = (
                await db.execute(
                    pg_insert(TriggerPollState)
                    .values(
                        id=uuid.uuid4(),
                        workflow_id=workflow_id,
                        node_id=node_id,
                        node_type=node_type,
                        scope_fingerprint=scope_fingerprint,
                        key_id=key_id,
                        version=0,
                        next_poll_at=func.now() + timedelta(minutes=poll_minutes),
                    )
                    .on_conflict_do_nothing(constraint="uq_trigger_poll_state_node")
                    .returning(TriggerPollState.id)
                )
            ).scalar_one_or_none()
            if state_id is None:
                await db.rollback()
                return False
            await self._insert_items(db, state_id, items)
            await db.commit()
            return True

    async def consume(
        self, state_id: uuid.UUID, expected_version: int, writes: list[ItemWrite]
    ) -> bool:
        """Apply writes and bump the version, only if no one else has moved it. True when applied."""
        async with self._session_maker() as db:
            if not await self._bump(db, state_id, expected_version):
                await db.rollback()
                return False
            for write in writes:
                await self._apply(db, state_id, write)
            await db.commit()
            return True

    async def reset_baseline(
        self,
        state_id: uuid.UUID,
        expected_version: int,
        *,
        scope_fingerprint: str,
        key_id: str,
        items: dict[str, dict[str, Any]],
    ) -> bool:
        """Replace the whole snapshot after a scope or key change. No events fire for it."""
        async with self._session_maker() as db:
            if not await self._bump(
                db,
                state_id,
                expected_version,
                scope_fingerprint=scope_fingerprint,
                key_id=key_id,
            ):
                await db.rollback()
                return False
            await db.execute(delete(TriggerPollItem).where(TriggerPollItem.state_id == state_id))
            await self._insert_items(db, state_id, items)
            await db.commit()
            return True

    async def delete_except(
        self, node_types: tuple[str, ...], keep: set[tuple[uuid.UUID, str]]
    ) -> int:
        """Drop snapshots of nodes that are gone or inactive. Returns how many were dropped."""
        async with self._session_maker() as db:
            rows = (
                await db.execute(
                    select(
                        TriggerPollState.id,
                        TriggerPollState.workflow_id,
                        TriggerPollState.node_id,
                    ).where(TriggerPollState.node_type.in_(node_types))
                )
            ).all()
            stale = [row.id for row in rows if (row.workflow_id, row.node_id) not in keep]
            if stale:
                await db.execute(delete(TriggerPollState).where(TriggerPollState.id.in_(stale)))
            await db.commit()
            return len(stale)

    async def _bump(
        self, db: AsyncSession, state_id: uuid.UUID, expected_version: int, **values: Any
    ) -> bool:
        bumped = (
            await db.execute(
                update(TriggerPollState)
                .where(
                    TriggerPollState.id == state_id,
                    TriggerPollState.version == expected_version,
                )
                .values(version=TriggerPollState.version + 1, updated_at=func.now(), **values)
                .returning(TriggerPollState.id)
                .execution_options(synchronize_session=False)
            )
        ).first()
        return bumped is not None

    async def _apply(self, db: AsyncSession, state_id: uuid.UUID, write: ItemWrite) -> None:
        if write.payload is None:
            await db.execute(
                delete(TriggerPollItem).where(
                    TriggerPollItem.state_id == state_id,
                    TriggerPollItem.item_key == write.item_key,
                )
            )
            return
        await db.execute(
            pg_insert(TriggerPollItem)
            .values(
                id=uuid.uuid4(),
                state_id=state_id,
                item_key=write.item_key,
                payload=write.payload,
            )
            .on_conflict_do_update(
                constraint="uq_trigger_poll_item_key", set_={"payload": write.payload}
            )
        )

    async def _insert_items(
        self, db: AsyncSession, state_id: uuid.UUID, items: dict[str, dict[str, Any]]
    ) -> None:
        if not items:
            return
        await db.execute(
            insert(TriggerPollItem),
            [
                {"id": uuid.uuid4(), "state_id": state_id, "item_key": key, "payload": payload}
                for key, payload in items.items()
            ],
        )
```

- [ ] **Step 4: Run the test to see it pass**

Run: `cd backend && uv run pytest tests/test_google_trigger_state_store.py -q`
Expected: `10 passed`. If `func.now() + timedelta(...)` raises a type error under asyncpg, replace both uses with `func.now() + func.make_interval(0, 0, 0, 0, 0, poll_minutes)` and rerun.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_triggers/state_store.py backend/tests/test_google_trigger_state_store.py
git commit -m "feat(triggers): snapshot store with poll claims and compare-and-swap consume"
```

---

## Task 9: Shared trigger run dispatch (extract from IMAP)

**Files:**
- Create: `backend/app/services/trigger_run_dispatch.py`
- Modify: `backend/app/services/imap_trigger_service.py`
- Create: `backend/tests/test_trigger_run_dispatch.py`
- Modify: `backend/tests/test_imap_trigger_service.py`
- Modify: `backend/tests/test_trigger_pending_hitl.py:131`

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_trigger_run_dispatch.py`. Its two history tests are the ones that live in `test_imap_trigger_service.py::ImapTriggerExecutionHistoryTests` today, now pointed at the shared module, plus one for a Google source.

```python
"""Shared dispatch for background triggers: start the run, then persist its history."""

import logging
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.db.models import ExecutionHistory
from app.services.trigger_run_dispatch import (
    TriggerDispatchNotStartedError,
    run_trigger_workflow,
)
from app.services.workflow_executor import ExecutionResult, SubWorkflowExecution

_MODULE = "app.services.trigger_run_dispatch"
_LOG = logging.getLogger("test_trigger_run_dispatch")


def _patched(execution_result: ExecutionResult, session_maker: object):
    return (
        patch(f"{_MODULE}.async_session_maker", session_maker),
        patch(f"{_MODULE}.collect_referenced_workflows", AsyncMock(return_value={})),
        patch(f"{_MODULE}.get_credentials_context", AsyncMock(return_value={})),
        patch(f"{_MODULE}.get_global_variables_context", AsyncMock(return_value={})),
        patch(f"{_MODULE}.dispatch_workflow", AsyncMock(return_value=execution_result)),
        patch(f"{_MODULE}.upsert_workflow_analytics_snapshot", AsyncMock()),
        patch(f"{_MODULE}._persist_global_variables_from_execution", AsyncMock()),
    )


class RunTriggerWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def _session(self, workflow: object, added_rows: list) -> AsyncMock:
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: workflow)),
            add=added_rows.append,
            commit=AsyncMock(),
        )
        session = AsyncMock()
        session.__aenter__.return_value = db
        session.__aexit__.return_value = None
        return session

    async def _run(self, trigger_source: str, inputs: dict, sub_runs: list) -> list:
        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id, owner_id=owner_id, name="wf", nodes=[], edges=[]
        )
        result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"ok": True},
            execution_time_ms=14.2,
            node_results=[],
            sub_workflow_executions=sub_runs,
        )
        added: list = []
        session_maker = lambda: self._session(workflow, added)  # noqa: E731
        patches = _patched(result, session_maker)
        for active in patches:
            active.start()
            self.addCleanup(active.stop)
        await run_trigger_workflow(
            workflow_id=workflow_id,
            inputs=inputs,
            trigger_source=trigger_source,
            trigger_label="Test trigger",
            log=_LOG,
        )
        self.workflow_id = workflow_id
        return [row for row in added if isinstance(row, ExecutionHistory)]

    async def test_persists_the_trigger_source_and_sub_workflow_history(self) -> None:
        sub_id = uuid.uuid4()
        rows = await self._run(
            "imap",
            {"triggered_by": "imap", "trigger_node_id": "imap-node", "email": {"subject": "Hi"}},
            [
                SubWorkflowExecution(
                    workflow_id=str(sub_id),
                    inputs={"source": "imap"},
                    outputs={"done": True},
                    status="success",
                    execution_time_ms=4.1,
                    node_results=[],
                    workflow_name="Child workflow",
                )
            ],
        )
        self.assertEqual(len(rows), 2)
        parent = next(row for row in rows if row.workflow_id == self.workflow_id)
        child = next(row for row in rows if row.workflow_id == sub_id)
        self.assertEqual(parent.trigger_source, "imap")
        self.assertEqual(child.trigger_source, "SUB_WORKFLOW")
        self.assertEqual(parent.inputs["email"]["subject"], "Hi")

    async def test_google_sheets_runs_record_their_source(self) -> None:
        rows = await self._run(
            "google_sheets", {"triggered_by": "google_sheets", "change": {"event": "created"}}, []
        )
        self.assertEqual(rows[0].trigger_source, "google_sheets")
        self.assertEqual(rows[0].inputs["change"]["event"], "created")

    async def test_failure_before_dispatch_is_retriable(self) -> None:
        db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("db unreachable")))
        session = AsyncMock()
        session.__aenter__.return_value = db
        session.__aexit__.return_value = None
        with (
            patch(f"{_MODULE}.async_session_maker", return_value=session),
            patch(f"{_MODULE}.dispatch_workflow", AsyncMock()) as dispatch,
        ):
            with self.assertRaises(TriggerDispatchNotStartedError):
                await run_trigger_workflow(
                    workflow_id=uuid.uuid4(),
                    inputs={},
                    trigger_source="imap",
                    trigger_label="IMAP trigger",
                    log=_LOG,
                )
        dispatch.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd backend && uv run pytest tests/test_trigger_run_dispatch.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.trigger_run_dispatch'`.

- [ ] **Step 3: Create** `backend/app/services/trigger_run_dispatch.py`. The body is `ImapTriggerManager._execute_workflow_for_email` moved verbatim. Only these differ: the fresh workflow is loaded by `workflow_id`, `"imap"` becomes `trigger_source`, the two log texts take `trigger_label`, and the caller's logger is used.

```python
"""Start a workflow run for a background trigger and persist what it produced.

Shared by the IMAP trigger and the Google Drive and Google Sheets triggers. A failure
before ``dispatch_workflow`` starts raises TriggerDispatchNotStartedError, which is safe
to retry because nothing has run yet. Once dispatch has started, errors propagate as they
are and must not be retried: the run may already have had side effects.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.workflows import (
    _persist_global_variables_from_execution,
    collect_referenced_workflows,
    get_credentials_context,
)
from app.db.models import ExecutionHistory, Workflow
from app.db.session import async_session_maker
from app.services.cluster.dispatch import dispatch_workflow, log_offloaded_run
from app.services.global_variables_service import get_global_variables_context
from app.services.hitl_service import build_default_public_base_url
from app.services.pending_execution import (
    needs_local_pending_persist,
    persist_pending_execution,
)


class TriggerDispatchNotStartedError(Exception):
    """Preparing the run failed before dispatch_workflow was invoked; safe to retry."""


async def run_trigger_workflow(
    *,
    workflow_id: uuid.UUID,
    inputs: dict[str, Any],
    trigger_source: str,
    trigger_label: str,
    log: logging.Logger,
) -> None:
    """Run the workflow with ``inputs`` as a ``trigger_source`` run and write its history."""
    async with async_session_maker() as db:
        try:
            workflow_result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
            fresh_workflow = workflow_result.scalar_one_or_none()
            if not fresh_workflow:
                log.warning("Workflow %s disappeared before %s execution", workflow_id, trigger_label)
                return

            workflow_cache = await collect_referenced_workflows(
                db, fresh_workflow.nodes, actor_user_id=fresh_workflow.owner_id
            )
            credentials_context = await get_credentials_context(db, fresh_workflow.owner_id)
            global_variables_context = await get_global_variables_context(
                db, fresh_workflow.owner_id
            )

            from app.services.execution_cancellation import (
                clear_execution,
                register_execution,
            )

            execution_id = uuid.uuid4()
            cancel_event = register_execution(
                workflow_id=fresh_workflow.id,
                execution_id=execution_id,
                inputs=inputs,
                trigger_source=trigger_source,
                actor_user_id=fresh_workflow.owner_id,
            )
        except Exception as exc:
            raise TriggerDispatchNotStartedError(str(exc)) from exc

        try:
            result = await dispatch_workflow(
                workflow_id=fresh_workflow.id,
                nodes=fresh_workflow.nodes,
                edges=fresh_workflow.edges,
                inputs=inputs,
                workflow_cache=workflow_cache,
                trigger_source=trigger_source,
                credentials_owner_id=fresh_workflow.owner_id,
                execution_id=execution_id,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=fresh_workflow.owner_id,
                actor_user_id=fresh_workflow.owner_id,
                cancel_event=cancel_event,
            )
        finally:
            clear_execution(execution_id, handle=getattr(cancel_event, "_execution_handle", None))

        # An offloaded run's history is written where it ran, or by the
        # dispatcher itself when the queue retired it before it ran.
        if getattr(result, "history_written", False):
            log_offloaded_run(log, workflow_id=fresh_workflow.id, trigger=trigger_label, result=result)
            return

        if needs_local_pending_persist(result):
            history_entry, _ = await persist_pending_execution(
                db=db,
                workflow=fresh_workflow,
                enriched_inputs=inputs,
                execution_result=result,
                trigger_source=trigger_source,
                credentials_owner_id=fresh_workflow.owner_id,
                trace_user_id=fresh_workflow.owner_id,
                public_base_url=build_default_public_base_url(),
                history_entry_id=execution_id,
            )
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=fresh_workflow.id,
                owner_id=fresh_workflow.owner_id,
                workflow_name_snapshot=fresh_workflow.name,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
                started_at=getattr(history_entry, "started_at", None),
            )
            await db.commit()
            log.info("Workflow %s paused for human review via %s", fresh_workflow.id, trigger_label)
            return

        history_entry = ExecutionHistory(
            id=execution_id,
            workflow_id=fresh_workflow.id,
            inputs=inputs,
            outputs=result.outputs,
            node_results=result.node_results,
            status=result.status,
            execution_time_ms=result.execution_time_ms,
            trigger_source=trigger_source,
        )
        db.add(history_entry)
        await upsert_workflow_analytics_snapshot(
            db,
            workflow_id=fresh_workflow.id,
            owner_id=fresh_workflow.owner_id,
            workflow_name_snapshot=fresh_workflow.name,
            status=result.status,
            execution_time_ms=result.execution_time_ms,
        )

        for sub_exec in result.sub_workflow_executions:
            sub_history = ExecutionHistory(
                workflow_id=uuid.UUID(sub_exec.workflow_id),
                inputs=sub_exec.inputs,
                outputs=sub_exec.outputs,
                node_results=sub_exec.node_results,
                status=sub_exec.status,
                execution_time_ms=sub_exec.execution_time_ms,
                trigger_source=sub_exec.trigger_source,
            )
            db.add(sub_history)
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=uuid.UUID(sub_exec.workflow_id),
                owner_id=None,
                workflow_name_snapshot=sub_exec.workflow_name or "Sub-workflow",
                status=sub_exec.status,
                execution_time_ms=sub_exec.execution_time_ms,
            )

        await _persist_global_variables_from_execution(
            db,
            fresh_workflow.owner_id,
            fresh_workflow.nodes,
            workflow_cache,
            result.node_results,
            result.sub_workflow_executions,
        )

        await db.commit()
```

- [ ] **Step 4: Point IMAP at it.** In `backend/app/services/imap_trigger_service.py`:

1. Replace the import block from `from sqlalchemy import select` down to the `pending_execution` import with:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Credential, CredentialType, Workflow
from app.db.session import async_session_maker
from app.services.distributed_lock import lock_service
from app.services.encryption import decrypt_config
from app.services.trigger_run_dispatch import (
    TriggerDispatchNotStartedError,
    run_trigger_workflow,
)
```

2. Replace the `class ImapDispatchNotStartedError(Exception): ...` definition (docstring included) with:

```python
# Kept under its old name for existing imports; the retry loop below catches it.
ImapDispatchNotStartedError = TriggerDispatchNotStartedError
```

3. Replace the whole body of `_execute_workflow_for_email`, from after the `inputs = {...}` dict to the end of the method, with:

```python
        await run_trigger_workflow(
            workflow_id=workflow.id,
            inputs=inputs,
            trigger_source="imap",
            trigger_label="IMAP trigger",
            log=logger,
        )
```

- [ ] **Step 5: Move the IMAP history tests.** In `backend/tests/test_imap_trigger_service.py`:
  - Delete the class `ImapTriggerExecutionHistoryTests`. Its cases now live in `test_trigger_run_dispatch.py`.
  - Delete the imports it alone used: `ExecutionHistory`, `ExecutionResult`, `SubWorkflowExecution`.
  - Add this class in its place:

```python
class ImapTriggerDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_workflow_hands_the_email_to_the_shared_dispatch(self) -> None:
        manager = ImapTriggerManager()
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4())

        with patch(
            "app.services.imap_trigger_service.run_trigger_workflow", AsyncMock()
        ) as run:
            await manager._execute_workflow_for_email(workflow, "imap-node", {"uid": "7"})

        kwargs = run.await_args.kwargs
        self.assertEqual(kwargs["workflow_id"], workflow.id)
        self.assertEqual(kwargs["trigger_source"], "imap")
        self.assertEqual(kwargs["inputs"]["triggered_by"], "imap")
        self.assertEqual(kwargs["inputs"]["trigger_node_id"], "imap-node")
        self.assertEqual(kwargs["inputs"]["email"], {"uid": "7"})
```

In `backend/tests/test_trigger_pending_hitl.py`, replace the `TRIGGERS` entry `"app/services/imap_trigger_service.py",` with `"app/services/trigger_run_dispatch.py",`.

- [ ] **Step 6: Run the tests**

Run: `cd backend && uv run ruff format app/services/imap_trigger_service.py app/services/trigger_run_dispatch.py tests/test_trigger_run_dispatch.py && uv run pytest tests/test_trigger_run_dispatch.py tests/test_imap_trigger_service.py tests/test_trigger_pending_hitl.py -q && uv run ruff check app/services/imap_trigger_service.py app/services/trigger_run_dispatch.py`
Expected: all pass, and Ruff is clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/trigger_run_dispatch.py backend/app/services/imap_trigger_service.py backend/tests/test_trigger_run_dispatch.py backend/tests/test_imap_trigger_service.py backend/tests/test_trigger_pending_hitl.py
git commit -m "refactor(triggers): share the IMAP run-and-persist path with other polling triggers"
```

---

## Task 10: Node handlers and registrations

**Files:**
- Create: `backend/app/services/node_execution/nodes/google_drive_trigger_node.py`
- Create: `backend/app/services/node_execution/nodes/google_sheets_trigger_node.py`
- Modify:
  - `backend/app/services/node_execution/registry.py`
  - `backend/app/services/cluster/node_placement.py`
  - `backend/app/services/trigger_inputs.py`
  - `backend/app/services/workflow_status.py`
  - `backend/app/services/dashboard_widget_policy.py`
  - `backend/app/services/credential_catalog.py`
- Test: `backend/tests/test_google_trigger_nodes.py`

- [ ] **Step 1: Write the failing test**

```python
"""Google trigger nodes: handler output and every registry they must appear in."""

import unittest
from types import SimpleNamespace

from app.db.models import CredentialType
from app.services.cluster.node_placement import Placement, node_placement
from app.services.credential_catalog import NODE_CREDENTIAL_FIELDS
from app.services.dashboard_widget_policy import DASHBOARD_WIDGET_BLOCKED_NODE_TYPES
from app.services.node_execution.registry import get_node_handler
from app.services.trigger_inputs import receives_initial_inputs
from app.services.workflow_status import compute_trigger_status

TYPES = ("googleDriveTrigger", "googleSheetsTrigger")


def _ctx(node_type: str, initial_inputs: dict | None) -> SimpleNamespace:
    data = {"label": "t"}
    if initial_inputs is not None:
        data["_initial_inputs"] = initial_inputs
    return SimpleNamespace(node_data=data, node_type=node_type)


class HandlerTests(unittest.TestCase):
    def test_drive_handler_returns_the_change(self) -> None:
        handler = get_node_handler("googleDriveTrigger")
        output = handler(
            _ctx(
                "googleDriveTrigger",
                {
                    "triggered_at": "2026-10-17T10:00:00+00:00",
                    "change": {
                        "event": "created",
                        "file": {"id": "a", "name": "a.pdf"},
                        "changed_fields": [],
                        "folder_id": "F1",
                    },
                },
            )
        )
        self.assertEqual(output["event"], "created")
        self.assertEqual(output["file"]["name"], "a.pdf")
        self.assertEqual(output["folder_id"], "F1")
        self.assertEqual(output["triggered_at"], "2026-10-17T10:00:00+00:00")

    def test_sheets_handler_returns_the_change(self) -> None:
        handler = get_node_handler("googleSheetsTrigger")
        output = handler(
            _ctx(
                "googleSheetsTrigger",
                {
                    "triggered_at": "t",
                    "change": {
                        "event": "updated",
                        "row": {"Status": "Paid", "rowIndex": 4},
                        "changed_columns": ["Status"],
                        "key": "a@x",
                        "spreadsheet_id": "S1",
                        "sheet_name": "Leads",
                    },
                },
            )
        )
        self.assertEqual(output["row"]["rowIndex"], 4)
        self.assertEqual(output["changed_columns"], ["Status"])
        self.assertEqual(output["key"], "a@x")

    def test_a_manual_editor_run_gets_empty_fields(self) -> None:
        drive = get_node_handler("googleDriveTrigger")(_ctx("googleDriveTrigger", None))
        sheets = get_node_handler("googleSheetsTrigger")(_ctx("googleSheetsTrigger", None))
        self.assertIsNone(drive["event"])
        self.assertEqual(drive["file"], {})
        self.assertIsNone(sheets["event"])
        self.assertEqual(sheets["row"], {})


class RegistrationTests(unittest.TestCase):
    def test_both_receive_initial_inputs(self) -> None:
        for node_type in TYPES:
            with self.subTest(node_type=node_type):
                self.assertTrue(receives_initial_inputs({"type": node_type, "data": {}}))

    def test_both_make_a_workflow_listen(self) -> None:
        for node_type in TYPES:
            with self.subTest(node_type=node_type):
                active = {"type": node_type, "data": {}}
                paused = {"type": node_type, "data": {"active": False}}
                self.assertEqual(compute_trigger_status([active]), "listening")
                self.assertEqual(compute_trigger_status([paused]), "paused")

    def test_dashboard_widgets_cannot_run_them(self) -> None:
        for node_type in TYPES:
            self.assertIn(node_type, DASHBOARD_WIDGET_BLOCKED_NODE_TYPES)

    def test_runs_may_execute_anywhere(self) -> None:
        for node_type in TYPES:
            self.assertEqual(node_placement({"type": node_type, "data": {}}), Placement.ANYWHERE)

    def test_credential_fields(self) -> None:
        [drive] = NODE_CREDENTIAL_FIELDS["googleDriveTrigger"]
        [sheets] = NODE_CREDENTIAL_FIELDS["googleSheetsTrigger"]
        self.assertEqual(drive.types, frozenset({CredentialType.google_drive}))
        self.assertEqual(sheets.types, frozenset({CredentialType.google_sheets}))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd backend && uv run pytest tests/test_google_trigger_nodes.py -q`
Expected: FAIL, because `get_node_handler("googleDriveTrigger")` returns None and calling it raises `TypeError`.

- [ ] **Step 3: Implement the handlers**

`backend/app/services/node_execution/nodes/google_drive_trigger_node.py`:

```python
from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the googleDriveTrigger node: hand the detected file change downstream."""
    trigger_inputs = ctx.node_data.get("_initial_inputs") or {}
    change = trigger_inputs.get("change") or {}
    return {
        "event": change.get("event"),
        "file": change.get("file", {}),
        "changed_fields": change.get("changed_fields", []),
        "folder_id": change.get("folder_id"),
        "triggered_at": trigger_inputs.get("triggered_at"),
    }
```

`backend/app/services/node_execution/nodes/google_sheets_trigger_node.py`:

```python
from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the googleSheetsTrigger node: hand the detected row change downstream."""
    trigger_inputs = ctx.node_data.get("_initial_inputs") or {}
    change = trigger_inputs.get("change") or {}
    return {
        "event": change.get("event"),
        "row": change.get("row", {}),
        "changed_columns": change.get("changed_columns", []),
        "key": change.get("key"),
        "spreadsheet_id": change.get("spreadsheet_id"),
        "sheet_name": change.get("sheet_name"),
        "triggered_at": trigger_inputs.get("triggered_at"),
    }
```

- [ ] **Step 4: Register them everywhere.** Keep alphabetical order where the file uses it.

`registry.py`, in `_HANDLER_MODULES`, after `"googleDrive": "google_drive_node",`:

```python
    "googleDriveTrigger": "google_drive_trigger_node",
```

and after `"googleSheets": "google_sheets_node",`:

```python
    "googleSheetsTrigger": "google_sheets_trigger_node",
```

`node_placement.py`, in `NODE_PLACEMENT`, after `"googleDrive": _MAIN,` and after `"googleSheets": _ANY,` respectively:

```python
    "googleDriveTrigger": _ANY,  # polling runs on the leader; the run keeps no local state
```

```python
    "googleSheetsTrigger": _ANY,  # polling runs on the leader; the run keeps no local state
```

`trigger_inputs.py`, add to `INITIAL_INPUT_TRIGGER_TYPES`:

```python
        "googleDriveTrigger",
        "googleSheetsTrigger",
```

`workflow_status.py`, add to `TRIGGER_NODE_TYPES`, after `"imapTrigger",`:

```python
        "googleDriveTrigger",
        "googleSheetsTrigger",
```

`dashboard_widget_policy.py`, add to `DASHBOARD_WIDGET_BLOCKED_NODE_TYPES`, after `"imapTrigger",`:

```python
        "googleDriveTrigger",
        "googleSheetsTrigger",
```

`credential_catalog.py`, in `NODE_CREDENTIAL_FIELDS`, after the `"googleDrive"` and `"googleSheets"` entries respectively:

```python
    "googleDriveTrigger": (_field("credentialId", CredentialType.google_drive),),
```

```python
    "googleSheetsTrigger": (_field("credentialId", CredentialType.google_sheets),),
```

and replace the two purposes in `CREDENTIAL_TYPE_PURPOSE`:

```python
    CredentialType.google_sheets: (
        "Google OAuth client for Google Sheets; Google Sheets and Google Sheets Trigger nodes, "
        "Sheets API over http for operations the node lacks"
    ),
    CredentialType.google_drive: (
        "Google OAuth client for Google Drive; Google Drive and Google Drive Trigger nodes, "
        "Drive API over http for operations the node lacks"
    ),
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && uv run pytest tests/test_google_trigger_nodes.py tests/test_cluster_node_placement.py tests/test_credential_catalog.py tests/test_trigger_inputs.py tests/test_workflow_trigger_status.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/node_execution/nodes/google_drive_trigger_node.py backend/app/services/node_execution/nodes/google_sheets_trigger_node.py backend/app/services/node_execution/registry.py backend/app/services/cluster/node_placement.py backend/app/services/trigger_inputs.py backend/app/services/workflow_status.py backend/app/services/dashboard_widget_policy.py backend/app/services/credential_catalog.py backend/tests/test_google_trigger_nodes.py
git commit -m "feat(triggers): register Google Drive and Google Sheets trigger nodes"
```

---

## Task 11: Poller adapters

**Files:**
- Create: `backend/app/services/google_triggers/sources.py`
- Test: `backend/tests/test_google_trigger_sources.py`

- [ ] **Step 1: Write the failing test**

```python
"""Poller adapters wrap config, Google reads, and diffs for one node."""

import unittest
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.google_triggers.fingerprint import Fingerprinter
from app.services.google_triggers.sources import DriveSource, SheetsSource, build_source

FP = Fingerprinter.for_node("test-secret-key-for-tests-only-32-bytes", "wf", "node")


class BuildSourceTests(unittest.TestCase):
    def test_builds_a_drive_source(self) -> None:
        source = build_source(
            {"type": "googleDriveTrigger", "data": {"credentialId": "c", "gdtFolderId": "F1"}}, FP
        )
        self.assertIsInstance(source, DriveSource)
        self.assertEqual(source.trigger_source, "google_drive")
        self.assertEqual(source.credential_type, CredentialType.google_drive)
        self.assertEqual(source.credential_id, "c")

    def test_builds_a_sheets_source(self) -> None:
        source = build_source(
            {"type": "googleSheetsTrigger", "data": {"credentialId": "c", "gstSpreadsheetId": "S"}},
            FP,
        )
        self.assertIsInstance(source, SheetsSource)
        self.assertEqual(source.trigger_source, "google_sheets")

    def test_rejects_other_nodes(self) -> None:
        with self.assertRaises(ValueError):
            build_source({"type": "imapTrigger", "data": {}}, FP)


class DriveSourceTests(unittest.TestCase):
    def test_fetch_lists_the_folder_with_the_credential(self) -> None:
        source = build_source(
            {"type": "googleDriveTrigger", "data": {"credentialId": "c", "gdtFolderId": "F1"}}, FP
        )
        service = MagicMock()
        service.list_folder_entries.return_value = [{"id": "a", "name": "a.pdf"}]
        with (
            patch("app.services.google_triggers.sources.SessionLocal"),
            patch(
                "app.services.google_triggers.sources.GoogleDriveService", return_value=service
            ) as service_class,
        ):
            live = source.fetch({"access_token": "t"})
        self.assertEqual(service_class.call_args.args[0], "c")
        self.assertEqual(live[0]["name"], "a.pdf")
        self.assertEqual(set(source.items(live)), {"a"})


class SheetsSourceTests(unittest.TestCase):
    def _source(self) -> SheetsSource:
        return build_source(
            {"type": "googleSheetsTrigger", "data": {"credentialId": "c", "gstSpreadsheetId": "S"}},
            FP,
        )

    def _fetch(self, source: SheetsSource, values: list) -> object:
        service = MagicMock()
        service.read_sheet_values.return_value = values
        with (
            patch("app.services.google_triggers.sources.SessionLocal"),
            patch("app.services.google_triggers.sources.GoogleSheetsService", return_value=service),
        ):
            return source.fetch({"access_token": "t"})

    def test_scope_follows_the_header_row(self) -> None:
        source = self._source()
        first = source.scope_fingerprint(self._fetch(source, [["Name"], ["Ada"]]))
        renamed = source.scope_fingerprint(self._fetch(source, [["Full name"], ["Ada"]]))
        self.assertNotEqual(first, renamed)

    def test_diff_finds_a_new_row(self) -> None:
        source = self._source()
        stored = source.items(self._fetch(source, [["Name"], ["Ada"]]))
        changes = source.diff(stored, self._fetch(source, [["Name"], ["Ada"], ["Grace"]]))
        self.assertEqual([change.event for change in changes], ["created"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd backend && uv run pytest tests/test_google_trigger_sources.py -q`
Expected: FAIL with `ModuleNotFoundError: ... sources`.

- [ ] **Step 3: Implement** `backend/app/services/google_triggers/sources.py`

```python
"""Poller adapters: one per Google trigger node type.

Each adapter answers the same questions for the poller: is the node configured, what is
live in Google right now, which scope does that belong to, and what changed. ``fetch``
runs in a worker thread because the Google services are synchronous, and it opens a sync
session so a refreshed OAuth token is saved on the credential.
"""

from __future__ import annotations

from typing import Any

from app.db.models import CredentialType
from app.db.session import SessionLocal
from app.services.google_drive_service import GoogleDriveService
from app.services.google_sheets_service import GoogleSheetsService
from app.services.google_triggers.config import (
    DRIVE_TRIGGER,
    SHEETS_TRIGGER,
    DriveTriggerConfig,
    SheetsTriggerConfig,
    parse_drive_config,
    parse_sheets_config,
)
from app.services.google_triggers.drive_source import diff_drive, drive_items, fetch_drive_entries
from app.services.google_triggers.events import TriggerEvent
from app.services.google_triggers.fingerprint import Fingerprinter
from app.services.google_triggers.sheets_source import (
    SheetSnapshot,
    build_snapshot,
    diff_sheet,
    header_fingerprint,
    sheet_items,
)

TRIGGER_NODE_TYPES: tuple[str, ...] = (DRIVE_TRIGGER, SHEETS_TRIGGER)


class DriveSource:
    """Google Drive Trigger node, as the poller sees it."""

    node_type = DRIVE_TRIGGER
    trigger_source = "google_drive"
    label = "Google Drive Trigger"
    credential_type = CredentialType.google_drive

    def __init__(self, config: DriveTriggerConfig) -> None:
        self.config = config
        self.credential_id = config.credential_id
        self.poll_minutes = config.poll_minutes
        self.events = config.events

    def problem(self) -> str | None:
        return self.config.problem()

    def fetch(self, credential_config: dict[str, Any]) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            service = GoogleDriveService(self.credential_id, credential_config, db)
            return fetch_drive_entries(service, self.config)

    def scope_fingerprint(self, live: list[dict[str, Any]]) -> str:
        return self.config.scope_fingerprint()

    def items(self, live: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return drive_items(live)

    def diff(
        self, stored: dict[str, dict[str, Any]], live: list[dict[str, Any]]
    ) -> list[TriggerEvent]:
        return diff_drive(stored, live, self.config)


class SheetsSource:
    """Google Sheets Trigger node, as the poller sees it."""

    node_type = SHEETS_TRIGGER
    trigger_source = "google_sheets"
    label = "Google Sheets Trigger"
    credential_type = CredentialType.google_sheets

    def __init__(self, config: SheetsTriggerConfig, fingerprinter: Fingerprinter) -> None:
        self.config = config
        self.fingerprinter = fingerprinter
        self.credential_id = config.credential_id
        self.poll_minutes = config.poll_minutes
        self.events = config.events

    def problem(self) -> str | None:
        return self.config.problem()

    def fetch(self, credential_config: dict[str, Any]) -> SheetSnapshot:
        with SessionLocal() as db:
            service = GoogleSheetsService(self.credential_id, credential_config, db)
            values = service.read_sheet_values(self.config.spreadsheet_id, self.config.sheet_name)
        return build_snapshot(values, self.config.has_header)

    def scope_fingerprint(self, live: SheetSnapshot) -> str:
        return self.config.scope_fingerprint(header_fingerprint(live, self.fingerprinter))

    def items(self, live: SheetSnapshot) -> dict[str, dict[str, Any]]:
        return sheet_items(live, self.fingerprinter, self.config)

    def diff(self, stored: dict[str, dict[str, Any]], live: SheetSnapshot) -> list[TriggerEvent]:
        return diff_sheet(stored, live, self.fingerprinter, self.config)


def build_source(node: dict[str, Any], fingerprinter: Fingerprinter) -> DriveSource | SheetsSource:
    """Adapter for a Google trigger node. Raises ValueError for any other node type."""
    data = node.get("data") or {}
    node_type = node.get("type")
    if node_type == DRIVE_TRIGGER:
        return DriveSource(parse_drive_config(data))
    if node_type == SHEETS_TRIGGER:
        return SheetsSource(parse_sheets_config(data), fingerprinter)
    raise ValueError(f"not a Google trigger node: {node_type}")
```

- [ ] **Step 4: Run the test to see it pass**

Run: `cd backend && uv run pytest tests/test_google_trigger_sources.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_triggers/sources.py backend/tests/test_google_trigger_sources.py
git commit -m "feat(triggers): poller adapters for Google Drive and Sheets triggers"
```

---

## Task 12: The poller

**Files:**
- Create: `backend/app/services/google_triggers/poller.py`
- Test: `backend/tests/test_google_trigger_poller.py`

- [ ] **Step 1: Write the failing test**

```python
"""Poller: baseline, one run per change, carryover, CAS loss, revert, skip on errors."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.db.models import CredentialType
from app.services.google_triggers.config import TRIGGER_EVENTS
from app.services.google_triggers.events import MOVED, ItemWrite, PollSkippedError, TriggerEvent
from app.services.google_triggers.poller import MAX_RUNS_PER_POLL, GoogleTriggerPoller
from app.services.google_triggers.state_store import Claim, ClaimedPoll
from app.services.trigger_run_dispatch import TriggerDispatchNotStartedError

SECRET = "test-secret-key-for-tests-only-32-bytes"


class FakeStore:
    """In-memory TriggerStateStore with the same compare-and-swap rule."""

    def __init__(self) -> None:
        self.state_id: uuid.UUID | None = None
        self.version = 0
        self.scope = ""
        self.key_id = ""
        self.items: dict = {}
        self.lose_next_consume = False
        self.kept: set | None = None

    async def claim(self, workflow_id, node_id, poll_minutes) -> Claim:
        if self.state_id is None:
            return Claim(due=True)
        return Claim(
            due=True,
            poll=ClaimedPoll(self.state_id, self.version, self.scope, self.key_id, dict(self.items)),
        )

    async def insert_baseline(self, *, scope_fingerprint, key_id, items, **_kwargs) -> bool:
        self.state_id = uuid.uuid4()
        self.scope, self.key_id, self.items, self.version = scope_fingerprint, key_id, dict(items), 0
        return True

    async def consume(self, state_id, expected_version, writes) -> bool:
        if self.lose_next_consume:
            self.lose_next_consume = False
            self.version += 1
            return False
        if expected_version != self.version:
            return False
        self.version += 1
        for write in writes:
            if write.payload is None:
                self.items.pop(write.item_key, None)
            else:
                self.items[write.item_key] = write.payload
        return True

    async def reset_baseline(self, state_id, expected_version, *, scope_fingerprint, key_id, items):
        if expected_version != self.version:
            return False
        self.version += 1
        self.scope, self.key_id, self.items = scope_fingerprint, key_id, dict(items)
        return True

    async def delete_except(self, node_types, keep) -> int:
        self.kept = keep
        return 0


class FakeSource:
    node_type = "googleSheetsTrigger"
    trigger_source = "google_sheets"
    label = "Google Sheets Trigger"
    credential_type = CredentialType.google_sheets
    poll_minutes = 1

    def __init__(self, changes=None, events=frozenset(TRIGGER_EVENTS), scope="scope-a",
                 fetch_error=None, live_items=None) -> None:
        self.credential_id = str(uuid.uuid4())
        self.changes = changes or []
        self.events = events
        self.scope = scope
        self.fetch_error = fetch_error
        self.live_items = live_items or {"a": {"r": 2, "c": ["x"]}}

    def problem(self):
        return None

    def fetch(self, credential_config):
        if self.fetch_error:
            raise self.fetch_error
        return "live"

    def scope_fingerprint(self, live):
        return self.scope

    def items(self, live):
        return self.live_items

    def diff(self, stored, live):
        return self.changes


def _change(key: str, event: str = "created") -> TriggerEvent:
    return TriggerEvent(
        event=event,
        payload={"event": event, "row": {"rowIndex": 2}},
        write=ItemWrite(key, {"r": 2, "c": [key]}),
        revert=ItemWrite(key, None),
    )


WORKFLOW = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4())
NODE = {"id": "n1", "type": "googleSheetsTrigger", "data": {}}


class PollerTests(unittest.IsolatedAsyncioTestCase):
    async def _poll(self, store: FakeStore, source: FakeSource, dispatch: AsyncMock) -> None:
        poller = GoogleTriggerPoller(store=store, dispatch=dispatch, secret=SECRET)
        with (
            patch("app.services.google_triggers.poller.build_source", return_value=source),
            patch.object(poller, "_load_credential", AsyncMock(return_value={"t": 1})),
        ):
            await poller.poll_node(WORKFLOW, NODE)

    async def _baselined(self, source: FakeSource) -> FakeStore:
        store = FakeStore()
        await self._poll(store, source, AsyncMock())
        return store

    async def test_first_poll_records_a_baseline_and_runs_nothing(self) -> None:
        store = FakeStore()
        dispatch = AsyncMock()
        await self._poll(store, FakeSource(changes=[_change("b")]), dispatch)
        self.assertIsNotNone(store.state_id)
        self.assertEqual(store.items, {"a": {"r": 2, "c": ["x"]}})
        dispatch.assert_not_awaited()

    async def test_a_change_is_consumed_then_run_once(self) -> None:
        source = FakeSource(changes=[_change("b")])
        store = await self._baselined(source)
        dispatch = AsyncMock()
        await self._poll(store, source, dispatch)
        dispatch.assert_awaited_once()
        kwargs = dispatch.await_args.kwargs
        self.assertEqual(kwargs["trigger_source"], "google_sheets")
        self.assertEqual(kwargs["inputs"]["triggered_by"], "google_sheets")
        self.assertEqual(kwargs["inputs"]["trigger_node_id"], "n1")
        self.assertEqual(kwargs["inputs"]["change"]["event"], "created")
        self.assertIn("b", store.items)
        self.assertEqual(store.version, 1)

    async def test_filtered_and_moved_changes_are_consumed_silently(self) -> None:
        source = FakeSource(
            changes=[_change("b", "deleted"), _change("c", MOVED), _change("d", "created")],
            events=frozenset({"created"}),
        )
        store = await self._baselined(source)
        dispatch = AsyncMock()
        await self._poll(store, source, dispatch)
        self.assertEqual(dispatch.await_count, 1)
        self.assertEqual(dispatch.await_args.kwargs["inputs"]["change"]["event"], "created")
        self.assertEqual(store.version, 2)
        self.assertIn("c", store.items)

    async def test_at_most_fifty_runs_per_poll_and_the_rest_wait(self) -> None:
        source = FakeSource(changes=[_change(f"k{index}") for index in range(60)])
        store = await self._baselined(source)
        dispatch = AsyncMock()
        await self._poll(store, source, dispatch)
        self.assertEqual(dispatch.await_count, MAX_RUNS_PER_POLL)
        self.assertNotIn("k59", store.items)

    async def test_losing_the_compare_and_swap_starts_no_run(self) -> None:
        source = FakeSource(changes=[_change("b")])
        store = await self._baselined(source)
        store.lose_next_consume = True
        dispatch = AsyncMock()
        await self._poll(store, source, dispatch)
        dispatch.assert_not_awaited()

    async def test_failure_before_dispatch_is_reverted_for_the_next_poll(self) -> None:
        source = FakeSource(changes=[_change("b")])
        store = await self._baselined(source)
        dispatch = AsyncMock(side_effect=TriggerDispatchNotStartedError("db down"))
        await self._poll(store, source, dispatch)
        self.assertEqual(dispatch.await_count, 3)
        self.assertNotIn("b", store.items)
        self.assertEqual(store.version, 2)

        retry = AsyncMock()
        await self._poll(store, source, retry)
        retry.assert_awaited_once()

    async def test_failure_after_dispatch_started_is_not_retried(self) -> None:
        source = FakeSource(changes=[_change("b"), _change("c")])
        store = await self._baselined(source)
        dispatch = AsyncMock(side_effect=RuntimeError("node failed"))
        await self._poll(store, source, dispatch)
        self.assertEqual(dispatch.await_count, 2)
        self.assertIn("b", store.items)
        self.assertIn("c", store.items)

    async def test_a_google_error_leaves_the_snapshot_alone(self) -> None:
        source = FakeSource(changes=[_change("b")])
        store = await self._baselined(source)
        version = store.version
        failing = FakeSource(changes=[_change("b")], fetch_error=PollSkippedError("403"))
        dispatch = AsyncMock()
        await self._poll(store, failing, dispatch)
        dispatch.assert_not_awaited()
        self.assertEqual(store.version, version)

    async def test_an_unavailable_credential_skips_the_poll(self) -> None:
        store = FakeStore()
        poller = GoogleTriggerPoller(store=store, dispatch=AsyncMock(), secret=SECRET)
        with (
            patch("app.services.google_triggers.poller.build_source", return_value=FakeSource()),
            patch.object(poller, "_load_credential", AsyncMock(return_value=None)),
        ):
            await poller.poll_node(WORKFLOW, NODE)
        self.assertIsNone(store.state_id)

    async def test_a_scope_change_resets_the_baseline_without_runs(self) -> None:
        store = await self._baselined(FakeSource())
        moved = FakeSource(scope="scope-b", changes=[_change("b")], live_items={"z": {"r": 9}})
        dispatch = AsyncMock()
        await self._poll(store, moved, dispatch)
        dispatch.assert_not_awaited()
        self.assertEqual(store.scope, "scope-b")
        self.assertEqual(store.items, {"z": {"r": 9}})

    async def test_a_new_secret_resets_the_baseline_without_runs(self) -> None:
        source = FakeSource(changes=[_change("b")])
        store = await self._baselined(source)
        store.key_id = "older-key"
        dispatch = AsyncMock()
        await self._poll(store, source, dispatch)
        dispatch.assert_not_awaited()
        self.assertNotEqual(store.key_id, "older-key")


class PollOnceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_keeps_only_active_trigger_nodes(self) -> None:
        store = FakeStore()
        poller = GoogleTriggerPoller(store=store, dispatch=AsyncMock(), secret=SECRET)
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=[
                {"id": "on", "type": "googleDriveTrigger", "data": {}},
                {"id": "off", "type": "googleSheetsTrigger", "data": {"active": False}},
                {"id": "other", "type": "http", "data": {}},
            ],
        )
        with (
            patch.object(poller, "_load_workflows", AsyncMock(return_value=[workflow])),
            patch.object(poller, "poll_node", AsyncMock()) as poll_node,
        ):
            await poller.poll_once()
        poll_node.assert_awaited_once()
        self.assertEqual(store.kept, {(workflow.id, "on")})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd backend && uv run pytest tests/test_google_trigger_poller.py -q`
Expected: FAIL with `ModuleNotFoundError: ... poller`.

- [ ] **Step 3: Implement** `backend/app/services/google_triggers/poller.py`

```python
"""Polls Google Drive and Google Sheets trigger nodes and starts one run per change.

Runs on the leader worker only, like the IMAP trigger, but its correctness does not
depend on that: polls are claimed and changes consumed through the state store's
compare-and-swap, so a change starts at most one run across all workers and instances.

A change is consumed before its run starts. If preparing the run fails before dispatch
begins, the consume is reverted and the next poll fires the change again. Once a run has
started it is never retried. A crash between the consume and the dispatch loses that one
change; it never duplicates it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Text, cast, or_, select

from app.config import settings
from app.db.models import Workflow
from app.db.session import async_session_maker
from app.services.credential_access import get_accessible_credential
from app.services.distributed_lock import lock_service
from app.services.encryption import decrypt_config
from app.services.google_triggers.events import TriggerEvent
from app.services.google_triggers.fingerprint import Fingerprinter
from app.services.google_triggers.sources import (
    TRIGGER_NODE_TYPES,
    DriveSource,
    SheetsSource,
    build_source,
)
from app.services.google_triggers.state_store import ClaimedPoll, TriggerStateStore
from app.services.trigger_run_dispatch import (
    TriggerDispatchNotStartedError,
    run_trigger_workflow,
)

logger = logging.getLogger("google_triggers")

MAX_RUNS_PER_POLL = 50
TICK_SECONDS = 15
PRE_DISPATCH_ATTEMPTS = 3

Dispatch = Callable[..., Awaitable[None]]
Source = DriveSource | SheetsSource


@dataclass(frozen=True)
class _LiveRead:
    scope_fingerprint: str
    items: dict[str, dict[str, Any]]
    changes: list[TriggerEvent]


def _active_trigger_nodes(nodes: Any) -> list[dict[str, Any]]:
    return [
        node
        for node in nodes or []
        if isinstance(node, dict)
        and node.get("type") in TRIGGER_NODE_TYPES
        and (node.get("data") or {}).get("active", True) is not False
    ]


def _read_live(
    source: Source, credential_config: dict[str, Any], stored: dict[str, dict[str, Any]] | None
) -> _LiveRead:
    """Fetch and diff in one worker-thread call; HMAC over a large sheet is CPU work."""
    live = source.fetch(credential_config)
    return _LiveRead(
        scope_fingerprint=source.scope_fingerprint(live),
        items=source.items(live),
        changes=source.diff(stored, live) if stored is not None else [],
    )


class GoogleTriggerPoller:
    """Leader loop for googleDriveTrigger and googleSheetsTrigger nodes."""

    def __init__(
        self,
        *,
        store: TriggerStateStore | None = None,
        dispatch: Dispatch = run_trigger_workflow,
        secret: str | None = None,
    ) -> None:
        self._store = store or TriggerStateStore()
        self._dispatch = dispatch
        self._secret = secret
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Google trigger poller started (worker_id=%s)", lock_service.worker_id)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Google trigger poller stopped")

    async def _run_loop(self) -> None:
        await asyncio.sleep(5)
        while self._running:
            try:
                if lock_service.is_leader:
                    await self.poll_once()
            except Exception as exc:
                logger.exception("Error in Google trigger loop: %s", exc)
            await asyncio.sleep(TICK_SECONDS)

    async def poll_once(self) -> None:
        """Poll every due node once, then drop snapshots of nodes that are gone or inactive."""
        workflows = await self._load_workflows()
        keep: set[tuple[uuid.UUID, str]] = set()
        for workflow in workflows:
            for node in _active_trigger_nodes(workflow.nodes):
                node_id = str(node.get("id") or "").strip()
                if not node_id:
                    continue
                keep.add((workflow.id, node_id))
                try:
                    await self.poll_node(workflow, node)
                except Exception:
                    logger.exception(
                        "Google trigger poll failed for workflow %s node %s", workflow.id, node_id
                    )
        await self._store.delete_except(TRIGGER_NODE_TYPES, keep)

    async def poll_node(self, workflow: Any, node: dict[str, Any]) -> None:
        """Claim, read, diff and dispatch for one trigger node."""
        node_id = str(node.get("id") or "").strip()
        fingerprinter = Fingerprinter.for_node(
            self._secret or settings.secret_key, str(workflow.id), node_id
        )
        source = build_source(node, fingerprinter)
        problem = source.problem()
        if problem:
            logger.debug("%s for workflow %s node %s: %s", source.label, workflow.id, node_id, problem)
            return

        claim = await self._store.claim(workflow.id, node_id, source.poll_minutes)
        if not claim.due:
            return

        credential_config = await self._load_credential(source, workflow.owner_id)
        if credential_config is None:
            logger.warning(
                "Skipping %s for workflow %s node %s: credential unavailable",
                source.label,
                workflow.id,
                node_id,
            )
            return

        stored = claim.poll.items if claim.poll is not None else None
        try:
            read = await asyncio.to_thread(_read_live, source, credential_config, stored)
        except Exception as exc:
            logger.warning(
                "Skipping %s poll for workflow %s node %s: %s",
                source.label,
                workflow.id,
                node_id,
                exc,
            )
            return

        if claim.poll is None:
            await self._store.insert_baseline(
                workflow_id=workflow.id,
                node_id=node_id,
                node_type=source.node_type,
                scope_fingerprint=read.scope_fingerprint,
                key_id=fingerprinter.key_id,
                items=read.items,
                poll_minutes=source.poll_minutes,
            )
            return

        poll = claim.poll
        if poll.scope_fingerprint != read.scope_fingerprint or poll.key_id != fingerprinter.key_id:
            await self._store.reset_baseline(
                poll.state_id,
                poll.version,
                scope_fingerprint=read.scope_fingerprint,
                key_id=fingerprinter.key_id,
                items=read.items,
            )
            return

        await self._consume_and_dispatch(workflow, node_id, source, poll, read.changes)

    async def _consume_and_dispatch(
        self,
        workflow: Any,
        node_id: str,
        source: Source,
        poll: ClaimedPoll,
        changes: list[TriggerEvent],
    ) -> None:
        version = poll.version
        silent = [change for change in changes if change.event not in source.events]
        loud = [change for change in changes if change.event in source.events]

        if silent:
            if not await self._store.consume(
                poll.state_id, version, [change.write for change in silent]
            ):
                return
            version += 1

        for change in loud[:MAX_RUNS_PER_POLL]:
            if not await self._store.consume(poll.state_id, version, [change.write]):
                logger.info(
                    "%s for workflow %s node %s: another worker moved on, stopping this poll",
                    source.label,
                    workflow.id,
                    node_id,
                )
                return
            version += 1
            if await self._start_run(workflow, node_id, source, change):
                continue
            if await self._store.consume(poll.state_id, version, [change.revert]):
                logger.warning(
                    "%s for workflow %s node %s: run could not start, retrying next poll",
                    source.label,
                    workflow.id,
                    node_id,
                )
            return

        if len(loud) > MAX_RUNS_PER_POLL:
            logger.info(
                "%s for workflow %s node %s: %d more changes wait for the next poll",
                source.label,
                workflow.id,
                node_id,
                len(loud) - MAX_RUNS_PER_POLL,
            )

    async def _start_run(
        self, workflow: Any, node_id: str, source: Source, change: TriggerEvent
    ) -> bool:
        """Start one run. False only when every attempt failed before dispatch started."""
        inputs = {
            "triggered_by": source.trigger_source,
            "trigger_node_id": node_id,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "change": change.payload,
        }
        for attempt in range(1, PRE_DISPATCH_ATTEMPTS + 1):
            try:
                await self._dispatch(
                    workflow_id=workflow.id,
                    inputs=inputs,
                    trigger_source=source.trigger_source,
                    trigger_label=source.label,
                    log=logger,
                )
                return True
            except TriggerDispatchNotStartedError as exc:
                logger.warning(
                    "%s for workflow %s node %s: run not started (attempt %d/%d): %s",
                    source.label,
                    workflow.id,
                    node_id,
                    attempt,
                    PRE_DISPATCH_ATTEMPTS,
                    exc,
                )
            except Exception:
                logger.exception(
                    "%s for workflow %s node %s: run failed after it started; not retrying",
                    source.label,
                    workflow.id,
                    node_id,
                )
                return True
        return False

    async def _load_workflows(self) -> list[Any]:
        """Workflows whose nodes mention a Google trigger type; exact checks happen per node."""
        nodes_text = cast(Workflow.nodes, Text)
        async with async_session_maker() as db:
            result = await db.execute(
                select(Workflow.id, Workflow.owner_id, Workflow.nodes).where(
                    or_(*(nodes_text.contains(f'"{node_type}"') for node_type in TRIGGER_NODE_TYPES))
                )
            )
            return list(result.all())

    async def _load_credential(self, source: Source, owner_id: uuid.UUID) -> dict[str, Any] | None:
        """The credential's config, only if the workflow owner may use it and its type fits."""
        try:
            credential_uuid = uuid.UUID(source.credential_id)
        except ValueError:
            return None
        async with async_session_maker() as db:
            credential = await get_accessible_credential(db, credential_uuid, owner_id)
        if credential is None or credential.type != source.credential_type:
            return None
        return decrypt_config(credential.encrypted_config)


google_trigger_poller = GoogleTriggerPoller()
```

- [ ] **Step 4: Run the test to see it pass**

Run: `cd backend && uv run ruff format app/services/google_triggers tests/test_google_trigger_poller.py && uv run pytest tests/test_google_trigger_poller.py -q && uv run ruff check app/services/google_triggers`
Expected: `12 passed`; Ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_triggers/poller.py backend/tests/test_google_trigger_poller.py
git commit -m "feat(triggers): leader poller that fires each Google change once"
```

---

## Task 13: Start the poller with the app

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Wire it.** Next to `from app.services.imap_trigger_service import imap_trigger_manager` (line ~100), add:

```python
from app.services.google_triggers.poller import google_trigger_poller
```

After `await imap_trigger_manager.start()` add `await google_trigger_poller.start()`. Before `await imap_trigger_manager.stop()` add `await google_trigger_poller.stop()`.

- [ ] **Step 2: Check that the app imports and that nothing touched by the extraction regressed**

Run: `cd backend && uv run python -c "import app.main" && uv run pytest tests/test_google_trigger_poller.py tests/test_imap_trigger_service.py -q`
Expected: no import error; tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(triggers): start the Google trigger poller with the app"
```

---

## Task 14: DSL prompt

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py`
- Test: `backend/tests/test_build_assistant_prompt_node_templates.py`

- [ ] **Step 1: Write the failing test.** Add to the test class that holds `test_includes_imap_trigger_guidance`:

```python
    def test_includes_google_trigger_guidance(self) -> None:
        prompt = build_assistant_prompt()

        self.assertIn("googleDriveTrigger", prompt)
        self.assertIn("googleSheetsTrigger", prompt)
        self.assertIn("gstKeyColumn", prompt)
        self.assertIn("google-sheets-credential-uuid", prompt)
        self.assertIn("writes to the sheet it watches", prompt)
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd backend && uv run pytest tests/test_build_assistant_prompt_node_templates.py -q -k google_trigger`
Expected: FAIL on `googleDriveTrigger` not in the prompt.

- [ ] **Step 3: Add the sections.** Insert immediately before the line `### 4. llm (Language Model)`:

````markdown
### 3g. googleDriveTrigger (Google Drive Change Trigger)
- **Purpose**: Poll a Google Drive folder, or one file, and start the workflow once for each file that is created, updated, or deleted
- **Inputs**: 0 | **Outputs**: 1
- **WHEN TO USE**: When the workflow should react to files landing in, changing in, or leaving a Drive folder (intake folders, shared contract folders, report drops)
- **DO NOT use** `cron` plus a `googleDrive` `listFolderFiles` step to detect new files; this trigger keeps the snapshot and fires once per change
- **Data fields** (plain values, not `$` expressions):
  - `label`: Node identifier (e.g., "contractsFolder")
  - `credentialId`: UUID of a `google_drive` credential
  - `gdtScope`: `"folder"` (default) or `"file"`
  - `gdtFolderId`: Folder ID or URL when scope is `folder`; empty means My Drive root. Only direct children are watched
  - `gdtFileId`: File ID or URL when scope is `file`
  - `gdtEvents`: Array of `"created"`, `"updated"`, `"deleted"` (default all three; `created` does not apply to `file` scope)
  - `gdtIncludeFolders`: Boolean, default `false`; when `true`, subfolders themselves also start runs
  - `pollIntervalMinutes`: Integer, minimum `1`, default `1`
- **Behavior**: The first poll records the folder as it is and starts nothing. `deleted` means the item left the folder: trashed, deleted, or moved out. Moving a file in counts as `created`. Each change starts at most one run, also on multi-worker and multi-instance installs. Heym stores file metadata only, never file contents.
- **Output fields available downstream**:
  - `$<label>.event`: `"created"`, `"updated"`, or `"deleted"`
  - `$<label>.file.id`, `$<label>.file.name`, `$<label>.file.mime_type`, `$<label>.file.size_bytes`, `$<label>.file.created_time`, `$<label>.file.modified_time`, `$<label>.file.web_view_link`, `$<label>.file.is_folder`
  - `$<label>.changed_fields`: Metadata fields that changed (`updated` only)
  - `$<label>.folder_id`: Watched folder (`"root"` for My Drive), `null` in file scope
  - `$<label>.triggered_at`: ISO timestamp
- To read the file, follow with `googleDrive` (`downloadFile` or `syncToHeymDrive`) and `gdFileId: "$<label>.file.id"`.

**Example node JSON:**
```json
{"id": "n1", "type": "googleDriveTrigger", "position": {"x": 100, "y": 100}, "data": {"label": "contractsFolder", "credentialId": "google-drive-credential-uuid", "gdtScope": "folder", "gdtFolderId": "https://drive.google.com/drive/folders/FOLDER_ID", "gdtEvents": ["created"], "gdtIncludeFolders": false, "pollIntervalMinutes": 1}}
```

### 3h. googleSheetsTrigger (Google Sheets Row Trigger)
- **Purpose**: Poll one sheet tab and start the workflow once for each row that is added, updated, or deleted
- **Inputs**: 0 | **Outputs**: 1
- **WHEN TO USE**: When the workflow should react to rows in a spreadsheet: form responses, a lead list, a status column someone edits
- **DO NOT use** `cron` plus `googleSheets` `readRange` to find new rows; this trigger tracks rows and fires once per change
- **Data fields** (plain values, not `$` expressions):
  - `label`: Node identifier (e.g., "newLead")
  - `credentialId`: UUID of a `google_sheets` credential
  - `gstSpreadsheetId`: Spreadsheet ID or URL (required)
  - `gstSheetName`: Tab title (default `"Sheet1"`)
  - `gstHasHeader`: Boolean, default `true`; row 1 holds column names
  - `gstKeyColumn`: Optional, recommended. Header name (or column letter without a header) whose value identifies a row, so inserting, deleting, or sorting rows is detected correctly. Without it rows are matched by row number, and deleting a row in the middle reads as updates for the rows below it plus one delete at the end
  - `gstEvents`: Array of `"created"`, `"updated"`, `"deleted"` (default all three)
  - `pollIntervalMinutes`: Integer, minimum `1`, default `1`
- **Behavior**: The first poll records the tab as it is and starts nothing. Blank rows are ignored; rows with an empty key are ignored until the key is filled. Editing the header row records the tab again without starting runs. Heym stores only keyed fingerprints of cells, never cell values, so a run gets the row's current values and which columns changed, not the old values.
- **⚠️ Write-back loop**: A workflow that writes to the sheet it watches causes its own `updated` events. In that case set `gstEvents` to `["created"]`.
- **Output fields available downstream**:
  - `$<label>.event`: `"created"`, `"updated"`, or `"deleted"`
  - `$<label>.row`: Current cells keyed by header (or column letter) plus `rowIndex`; for `deleted` only `rowIndex`
  - `$<label>.row.rowIndex`: 1-based sheet row number
  - `$<label>.changed_columns`: Columns that changed (`created` lists every non-empty column)
  - `$<label>.key`: Key column value (`null` for `deleted` or without a key column)
  - `$<label>.spreadsheet_id`, `$<label>.sheet_name`, `$<label>.triggered_at`
- To write back to the same row, use `googleSheets` `updateRange` with `gsUpdateRow: "$<label>.row.rowIndex"`.

**Example node JSON:**
```json
{"id": "n1", "type": "googleSheetsTrigger", "position": {"x": 100, "y": 100}, "data": {"label": "newLead", "credentialId": "google-sheets-credential-uuid", "gstSpreadsheetId": "https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit", "gstSheetName": "Leads", "gstHasHeader": true, "gstKeyColumn": "Email", "gstEvents": ["created"], "pollIntervalMinutes": 1}}
```
````

In rule `23a.` (owned credentials only), make two edits:
- Change `` `google-drive-credential-uuid`, `` to `` `google-drive-credential-uuid`, `google-sheets-credential-uuid`, ``.
- Change `` `googleSheets`, `googleDrive`, `` in the "Applies to" list to `` `googleSheets`, `googleDrive`, `googleSheetsTrigger`, `googleDriveTrigger`, ``.

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_build_assistant_prompt_node_templates.py tests/test_workflow_dsl_prompt_highlight.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py backend/tests/test_build_assistant_prompt_node_templates.py
git commit -m "feat(dsl): describe the Google Drive and Google Sheets triggers"
```

---

## Task 15: Frontend node types and canvas affordances

**Files:**
- Modify:
  - `frontend/src/types/workflow.ts`
  - `frontend/src/types/node.ts`
  - `frontend/src/components/Canvas/WorkflowCanvas.vue:1156`
  - `frontend/src/lib/nodeIcons.ts`
  - `frontend/src/components/Nodes/BaseNode.vue`
  - `frontend/src/lib/canvasConnectionRules.ts`
  - `frontend/src/lib/workflowPreview.ts`
  - `frontend/src/components/Panels/NodePanel.vue`
  - `frontend/src/components/Panels/propertiesPanel/NodeErrorHandlingSection.vue`
  - `frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts`
- Test: `frontend/src/lib/workflowPreview.test.ts` (extend)

- [ ] **Step 1: Write the failing test.** Append to `frontend/src/lib/workflowPreview.test.ts`:

```ts
describe("Google triggers", () => {
  it("count as triggers that start a workflow on their own", () => {
    expect(TRIGGER_NODE_TYPES.has("googleDriveTrigger")).toBe(true);
    expect(TRIGGER_NODE_TYPES.has("googleSheetsTrigger")).toBe(true);
  });
});
```

Add `TRIGGER_NODE_TYPES` to the file's existing import from `./workflowPreview` if it is not already imported.

- [ ] **Step 2: Run the test to see it fail**

Run: `cd frontend && bun run test -- src/lib/workflowPreview.test.ts`
Expected: FAIL, `expected false to be true`.

- [ ] **Step 3: Add the types.** In `frontend/src/types/workflow.ts`, add `| "googleDriveTrigger"` and `| "googleSheetsTrigger"` to the `NodeType` union after `| "googleDrive"`. Add, just above the `NodeType` union:

```ts
/** Changes a Google Drive or Google Sheets trigger can start a run for. */
export type GoogleTriggerEvent = "created" | "updated" | "deleted";
```

After `gdPermanentDelete?: boolean;` in the node data interface, add:

```ts
  /** googleDriveTrigger: "folder" (default) watches direct children; "file" watches one file. */
  gdtScope?: "folder" | "file";
  gdtFolderId?: string;
  gdtFileId?: string;
  /** googleDriveTrigger: changes that start a run. */
  gdtEvents?: GoogleTriggerEvent[];
  /** googleDriveTrigger: subfolders themselves also start runs. */
  gdtIncludeFolders?: boolean;
  gstSpreadsheetId?: string;
  gstSheetName?: string;
  gstHasHeader?: boolean;
  /** googleSheetsTrigger: header name (or column letter without a header) that identifies a row. */
  gstKeyColumn?: string;
  /** googleSheetsTrigger: changes that start a run. */
  gstEvents?: GoogleTriggerEvent[];
```

- [ ] **Step 4: Add the definitions.** In `frontend/src/types/node.ts`, after the `imapTrigger` entry:

```ts
  googleDriveTrigger: {
    type: "googleDriveTrigger",
    label: "Google Drive Trigger",
    description: "Start a run when a file is created, updated, or deleted in a Drive folder",
    color: "node-google-drive",
    icon: "FolderOpen",
    inputs: 0,
    outputs: 1,
    defaultData: {
      label: "driveTrigger",
      credentialId: "",
      gdtScope: "folder",
      gdtFolderId: "",
      gdtFileId: "",
      gdtEvents: ["created", "updated", "deleted"],
      gdtIncludeFolders: false,
      pollIntervalMinutes: 1,
    },
  },
  googleSheetsTrigger: {
    type: "googleSheetsTrigger",
    label: "Google Sheets Trigger",
    description: "Start a run when a row is added, updated, or deleted in a sheet",
    color: "node-google-sheets",
    icon: "Sheet",
    inputs: 0,
    outputs: 1,
    defaultData: {
      label: "sheetTrigger",
      credentialId: "",
      gstSpreadsheetId: "",
      gstSheetName: "Sheet1",
      gstHasHeader: true,
      gstKeyColumn: "",
      gstEvents: ["created", "updated", "deleted"],
      pollIntervalMinutes: 1,
    },
  },
```

In `WorkflowCanvas.vue`, after the `imapTrigger:` default-data line:

```ts
    googleDriveTrigger: { label: "driveTrigger", credentialId: "", gdtScope: "folder", gdtFolderId: "", gdtFileId: "", gdtEvents: ["created", "updated", "deleted"], gdtIncludeFolders: false, pollIntervalMinutes: 1 },
    googleSheetsTrigger: { label: "sheetTrigger", credentialId: "", gstSpreadsheetId: "", gstSheetName: "Sheet1", gstHasHeader: true, gstKeyColumn: "", gstEvents: ["created", "updated", "deleted"], pollIntervalMinutes: 1 },
```

- [ ] **Step 5: Wire icons, colors, inputs, and lists**
  - `nodeIcons.ts`:
    - In the icon map add `googleDriveTrigger: FolderOpen,` and `googleSheetsTrigger: Sheet,`.
    - In the color map add `googleDriveTrigger: "text-node-google-drive",` and `googleSheetsTrigger: "text-node-google-sheets",`.
  - `BaseNode.vue`:
    - In the color map add `googleDriveTrigger: "node-google-drive",` and `googleSheetsTrigger: "node-google-sheets",`.
    - In `hasInput`, after `&& props.type !== "imapTrigger"` add `&& props.type !== "googleDriveTrigger"` and `&& props.type !== "googleSheetsTrigger"`.
  - `canvasConnectionRules.ts`: add `"googleDriveTrigger",` and `"googleSheetsTrigger",` after `"imapTrigger",` in both `BLOCKED_AS_TOOL_NODE_TYPES` and `NO_REGULAR_INPUT_NODE_TYPES`.
  - `workflowPreview.ts`: add both after `"imapTrigger",` in `TRIGGER_NODE_TYPES`.
  - `NodePanel.vue`: add both after `"imapTrigger",` in `DASHBOARD_HIDDEN_NODE_TYPES`.
  - `NodeErrorHandlingSection.vue`: add `'googleDriveTrigger', 'googleSheetsTrigger'` after `'imapTrigger'` in the `v-if` array.
  - `usePropertiesPanelController.ts`:
    - In the color map (near `imapTrigger: "node-email",`) add `googleDriveTrigger: "node-google-drive",` and `googleSheetsTrigger: "node-google-sheets",`.
    - In the docs slug map (near `imapTrigger: "imap-trigger-node",`) add `googleDriveTrigger: "google-drive-trigger-node",` and `googleSheetsTrigger: "google-sheets-trigger-node",`.
    - Change `if (type === "googleSheets") {` to `if (type === "googleSheets" || type === "googleSheetsTrigger") {`, and `if (type === "googleDrive") {` to `if (type === "googleDrive" || type === "googleDriveTrigger") {`, so the credential lists load.
    - In `googleDriveCredentialOptions`, change `node && node.type === "googleDrive"` to `node && (node.type === "googleDrive" || node.type === "googleDriveTrigger")`. In `googleSheetsCredentialOptions`, change `node && node.type === "googleSheets"` to `node && (node.type === "googleSheets" || node.type === "googleSheetsTrigger")`.

- [ ] **Step 6: Run the tests and checks**

Run: `cd frontend && bun run test -- src/lib/workflowPreview.test.ts src/lib/nodeIcons.test.ts && bun run typecheck`
Expected: pass. `nodeIcons.test.ts` checks every definition has an icon and color.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/types/node.ts frontend/src/components/Canvas/WorkflowCanvas.vue frontend/src/lib/nodeIcons.ts frontend/src/components/Nodes/BaseNode.vue frontend/src/lib/canvasConnectionRules.ts frontend/src/lib/workflowPreview.ts frontend/src/lib/workflowPreview.test.ts frontend/src/components/Panels/NodePanel.vue frontend/src/components/Panels/propertiesPanel/NodeErrorHandlingSection.vue frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts
git commit -m "feat(editor): Google Drive and Google Sheets trigger nodes on the canvas"
```

---

## Task 16: Event helpers and validation

**Files:**
- Create: `frontend/src/lib/googleTriggerConfig.ts`
- Test: `frontend/src/lib/googleTriggerConfig.test.ts`
- Modify: `frontend/src/stores/workflow.ts` (in `validateWorkflow`, after the `imapTrigger` block)

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";

import {
  SHEETS_EVENT_OPTIONS,
  driveEventOptions,
  googleTriggerProblems,
  selectedEvents,
  toggleEvent,
} from "./googleTriggerConfig";

describe("googleTriggerConfig", () => {
  it("offers created only for folder scope", () => {
    expect(driveEventOptions("folder").map((o) => o.value)).toEqual(["created", "updated", "deleted"]);
    expect(driveEventOptions("file").map((o) => o.value)).toEqual(["updated", "deleted"]);
    expect(SHEETS_EVENT_OPTIONS.map((o) => o.label)).toEqual(["Row added", "Row updated", "Row deleted"]);
  });

  it("treats a missing event list as every event", () => {
    expect(selectedEvents(undefined)).toEqual(["created", "updated", "deleted"]);
    expect(selectedEvents(["deleted", "bogus"])).toEqual(["deleted"]);
  });

  it("toggles events in a stable order", () => {
    expect(toggleEvent(["deleted"], "created", true)).toEqual(["created", "deleted"]);
    expect(toggleEvent(["created", "deleted"], "created", false)).toEqual(["deleted"]);
  });

  it("flags a Drive file scope without a file", () => {
    expect(googleTriggerProblems("googleDriveTrigger", { label: "t", gdtScope: "file" })).toContain(
      "File is not specified",
    );
  });

  it("flags a file scope whose only event is created", () => {
    expect(
      googleTriggerProblems("googleDriveTrigger", {
        label: "t",
        gdtScope: "file",
        gdtFileId: "abc",
        gdtEvents: ["created"],
      }),
    ).toContain("Select at least one event");
  });

  it("flags a Sheets trigger without a spreadsheet or sheet name", () => {
    const problems = googleTriggerProblems("googleSheetsTrigger", { label: "t", gstSheetName: "" });
    expect(problems).toContain("Spreadsheet is not specified");
    expect(problems).toContain("Sheet name is not specified");
  });

  it("flags a poll interval below one minute", () => {
    expect(
      googleTriggerProblems("googleSheetsTrigger", {
        label: "t",
        gstSpreadsheetId: "S1",
        pollIntervalMinutes: 0,
      }),
    ).toContain("Poll interval must be at least 1 minute");
  });

  it("accepts a complete Sheets trigger", () => {
    expect(
      googleTriggerProblems("googleSheetsTrigger", {
        label: "t",
        gstSpreadsheetId: "S1",
        gstSheetName: "Leads",
        pollIntervalMinutes: 1,
      }),
    ).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd frontend && bun run test -- src/lib/googleTriggerConfig.test.ts`
Expected: FAIL, the module cannot be resolved.

- [ ] **Step 3: Implement** `frontend/src/lib/googleTriggerConfig.ts`

```ts
import type { GoogleTriggerEvent, NodeData, NodeType } from "@/types/workflow";

export const GOOGLE_TRIGGER_EVENTS: readonly GoogleTriggerEvent[] = ["created", "updated", "deleted"];

export interface GoogleTriggerEventOption {
  value: GoogleTriggerEvent;
  label: string;
}

const DRIVE_EVENT_OPTIONS: GoogleTriggerEventOption[] = [
  { value: "created", label: "File created" },
  { value: "updated", label: "File updated" },
  { value: "deleted", label: "File deleted" },
];

export const SHEETS_EVENT_OPTIONS: GoogleTriggerEventOption[] = [
  { value: "created", label: "Row added" },
  { value: "updated", label: "Row updated" },
  { value: "deleted", label: "Row deleted" },
];

/** A single watched file cannot be created, so file scope offers update and delete only. */
export function driveEventOptions(scope: "folder" | "file"): GoogleTriggerEventOption[] {
  return scope === "file"
    ? DRIVE_EVENT_OPTIONS.filter((option) => option.value !== "created")
    : DRIVE_EVENT_OPTIONS;
}

/** Events stored on the node; a missing list means every event, as on the backend. */
export function selectedEvents(raw: unknown): GoogleTriggerEvent[] {
  if (!Array.isArray(raw)) return [...GOOGLE_TRIGGER_EVENTS];
  return GOOGLE_TRIGGER_EVENTS.filter((event) => raw.includes(event));
}

export function toggleEvent(
  current: GoogleTriggerEvent[],
  event: GoogleTriggerEvent,
  enabled: boolean,
): GoogleTriggerEvent[] {
  const next = new Set(current);
  if (enabled) next.add(event);
  else next.delete(event);
  return GOOGLE_TRIGGER_EVENTS.filter((item) => next.has(item));
}

/** Validation messages for a Google trigger node, excluding the credential check. */
export function googleTriggerProblems(type: NodeType, data: NodeData): string[] {
  const problems: string[] = [];
  if (type === "googleDriveTrigger") {
    const scope = data.gdtScope === "file" ? "file" : "folder";
    if (scope === "file" && !String(data.gdtFileId ?? "").trim()) {
      problems.push("File is not specified");
    }
    const allowed = driveEventOptions(scope).map((option) => option.value);
    if (!selectedEvents(data.gdtEvents).some((event) => allowed.includes(event))) {
      problems.push("Select at least one event");
    }
  } else if (type === "googleSheetsTrigger") {
    if (!String(data.gstSpreadsheetId ?? "").trim()) problems.push("Spreadsheet is not specified");
    if (data.gstSheetName !== undefined && !String(data.gstSheetName).trim()) {
      problems.push("Sheet name is not specified");
    }
    if (selectedEvents(data.gstEvents).length === 0) problems.push("Select at least one event");
  } else {
    return problems;
  }
  const interval =
    typeof data.pollIntervalMinutes === "number"
      ? data.pollIntervalMinutes
      : Number.parseInt(String(data.pollIntervalMinutes ?? "1"), 10);
  if (!Number.isInteger(interval) || interval < 1) {
    problems.push("Poll interval must be at least 1 minute");
  }
  return problems;
}
```

- [ ] **Step 4: Use it in the store.** In `frontend/src/stores/workflow.ts`, import `googleTriggerProblems` from `@/lib/googleTriggerConfig` alongside the other `@/lib` imports. Add after the `imapTrigger` block in `validateWorkflow`:

```ts
      if (node.type === "googleDriveTrigger" || node.type === "googleSheetsTrigger") {
        const nodeType =
          node.type === "googleDriveTrigger" ? "Google Drive Trigger" : "Google Sheets Trigger";
        if (!node.data.credentialId || !isValidUUID(node.data.credentialId)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType,
            message: "Credential is not selected",
          });
        }
        for (const message of googleTriggerProblems(node.type, node.data)) {
          errors.push({ nodeId: node.id, nodeLabel: node.data.label, nodeType, message });
        }
      }
```

- [ ] **Step 5: Run the tests and checks**

Run: `cd frontend && bun run test -- src/lib/googleTriggerConfig.test.ts src/stores/workflow.test.ts && bun run typecheck && bun run lint`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/googleTriggerConfig.ts frontend/src/lib/googleTriggerConfig.test.ts frontend/src/stores/workflow.ts
git commit -m "feat(editor): event options and validation for Google triggers"
```

---

## Task 17: Properties forms

**Files:**
- Create: `frontend/src/components/Panels/propertiesPanel/nodes/GoogleDriveTriggerNodeProperties.vue`
- Create: `frontend/src/components/Panels/propertiesPanel/nodes/GoogleSheetsTriggerNodeProperties.vue`
- Modify: `frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue`

- [ ] **Step 1: Create** `GoogleDriveTriggerNodeProperties.vue`

```vue
<script setup lang="ts">
import { computed } from "vue";
import { AlertTriangle } from "lucide-vue-next";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { driveEventOptions, selectedEvents, toggleEvent } from "@/lib/googleTriggerConfig";
import type { GoogleTriggerEvent } from "@/types/workflow";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const { selectedNode, isWorkflowOwner, googleDriveCredentialOptions, updateNodeData } =
  usePropertiesPanelContext();

const scopeOptions = [
  { value: "folder", label: "Files in a folder" },
  { value: "file", label: "One file" },
];

const scope = computed<"folder" | "file">(() =>
  selectedNode.value?.data.gdtScope === "file" ? "file" : "folder",
);
const eventOptions = computed(() => driveEventOptions(scope.value));
const events = computed<GoogleTriggerEvent[]>(() => selectedEvents(selectedNode.value?.data.gdtEvents));

function setEvent(event: GoogleTriggerEvent, enabled: boolean): void {
  updateNodeData("gdtEvents", toggleEvent(events.value, event, enabled));
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div
        class="space-y-2"
        data-testid="gdt-credential-field"
      >
        <Label>Google Drive Credential</Label>
        <Select
          :model-value="selectedNode.data.credentialId || ''"
          :options="googleDriveCredentialOptions"
          :disabled="!isWorkflowOwner"
          @update:model-value="updateNodeData('credentialId', $event)"
        />
        <p
          v-if="!selectedNode.data.credentialId"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          No Google Drive credential set: polling is off
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="gdt-scope-field"
      >
        <Label>Watch</Label>
        <Select
          :model-value="scope"
          :options="scopeOptions"
          @update:model-value="updateNodeData('gdtScope', $event || 'folder')"
        />
      </div>

      <div
        v-if="scope === 'folder'"
        class="space-y-2"
        data-testid="gdt-folder-field"
      >
        <Label for="gdt-folder-id">Folder ID or URL</Label>
        <Input
          id="gdt-folder-id"
          :model-value="selectedNode.data.gdtFolderId || ''"
          placeholder="Empty watches My Drive"
          @update:model-value="updateNodeData('gdtFolderId', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Only files directly inside this folder are watched.
        </p>
      </div>

      <div
        v-else
        class="space-y-2"
        data-testid="gdt-file-field"
      >
        <Label for="gdt-file-id">File ID or URL</Label>
        <Input
          id="gdt-file-id"
          :model-value="selectedNode.data.gdtFileId || ''"
          @update:model-value="updateNodeData('gdtFileId', $event)"
        />
      </div>

      <div
        class="space-y-2"
        data-testid="gdt-events-field"
      >
        <Label>Start a run when</Label>
        <div
          v-for="option in eventOptions"
          :key="option.value"
          class="flex items-center gap-2"
        >
          <input
            :id="`gdt-event-${option.value}`"
            type="checkbox"
            class="rounded border-border"
            :checked="events.includes(option.value)"
            @change="setEvent(option.value, ($event.target as HTMLInputElement).checked)"
          >
          <label
            :for="`gdt-event-${option.value}`"
            class="text-xs cursor-pointer select-none"
          >{{ option.label }}</label>
        </div>
        <p class="text-xs text-muted-foreground">
          Deleted also covers files moved to the trash or out of the folder.
        </p>
      </div>

      <div
        v-if="scope === 'folder'"
        class="flex items-center gap-2"
        data-testid="gdt-include-folders-field"
      >
        <input
          id="gdt-include-folders"
          type="checkbox"
          class="rounded border-border"
          :checked="selectedNode.data.gdtIncludeFolders === true"
          @change="updateNodeData('gdtIncludeFolders', ($event.target as HTMLInputElement).checked)"
        >
        <label
          for="gdt-include-folders"
          class="text-xs cursor-pointer select-none"
        >Subfolders also start runs</label>
      </div>

      <div
        class="space-y-2"
        data-testid="gdt-poll-field"
      >
        <Label for="gdt-poll-interval">Poll Interval (Minutes)</Label>
        <Input
          id="gdt-poll-interval"
          :model-value="String(selectedNode.data.pollIntervalMinutes ?? 1)"
          type="number"
          min="1"
          step="1"
          @update:model-value="updateNodeData('pollIntervalMinutes', Number.parseInt($event, 10) || 1)"
        />
        <p class="text-xs text-muted-foreground">
          The first poll records the folder as it is. After that, each change starts one run.
        </p>
      </div>

      <div
        class="space-y-2 pt-2 border-t"
        data-testid="gdt-output-fields"
      >
        <Label class="text-xs text-muted-foreground">Available output fields</Label>
        <div class="text-xs text-muted-foreground space-y-1 font-mono">
          <div>${{ selectedNode.data.label }}.event: created, updated, or deleted</div>
          <div>${{ selectedNode.data.label }}.file.id: Drive file ID</div>
          <div>${{ selectedNode.data.label }}.file.name: file name</div>
          <div>${{ selectedNode.data.label }}.file.mime_type: file type</div>
          <div>${{ selectedNode.data.label }}.file.web_view_link: link to open the file</div>
          <div>${{ selectedNode.data.label }}.changed_fields: what changed on update</div>
          <div>${{ selectedNode.data.label }}.triggered_at: when the change was seen</div>
        </div>
      </div>
    </div>
  </template>
</template>
```

- [ ] **Step 2: Create** `GoogleSheetsTriggerNodeProperties.vue`

```vue
<script setup lang="ts">
import { computed } from "vue";
import { AlertTriangle } from "lucide-vue-next";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { SHEETS_EVENT_OPTIONS, selectedEvents, toggleEvent } from "@/lib/googleTriggerConfig";
import type { GoogleTriggerEvent } from "@/types/workflow";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const { selectedNode, isWorkflowOwner, googleSheetsCredentialOptions, updateNodeData } =
  usePropertiesPanelContext();

const events = computed<GoogleTriggerEvent[]>(() => selectedEvents(selectedNode.value?.data.gstEvents));
const hasHeader = computed<boolean>(() => selectedNode.value?.data.gstHasHeader !== false);

function setEvent(event: GoogleTriggerEvent, enabled: boolean): void {
  updateNodeData("gstEvents", toggleEvent(events.value, event, enabled));
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div
        class="space-y-2"
        data-testid="gst-credential-field"
      >
        <Label>Google Sheets Credential</Label>
        <Select
          :model-value="selectedNode.data.credentialId || ''"
          :options="googleSheetsCredentialOptions"
          :disabled="!isWorkflowOwner"
          @update:model-value="updateNodeData('credentialId', $event)"
        />
        <p
          v-if="!selectedNode.data.credentialId"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          No Google Sheets credential set: polling is off
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="gst-spreadsheet-field"
      >
        <Label for="gst-spreadsheet-id">Spreadsheet ID or URL</Label>
        <Input
          id="gst-spreadsheet-id"
          :model-value="selectedNode.data.gstSpreadsheetId || ''"
          @update:model-value="updateNodeData('gstSpreadsheetId', $event)"
        />
      </div>

      <div
        class="space-y-2"
        data-testid="gst-sheet-name-field"
      >
        <Label for="gst-sheet-name">Sheet Name</Label>
        <Input
          id="gst-sheet-name"
          :model-value="selectedNode.data.gstSheetName ?? 'Sheet1'"
          @update:model-value="updateNodeData('gstSheetName', $event)"
        />
      </div>

      <div
        class="flex items-center gap-2"
        data-testid="gst-has-header-field"
      >
        <input
          id="gst-has-header"
          type="checkbox"
          class="rounded border-border"
          :checked="hasHeader"
          @change="updateNodeData('gstHasHeader', ($event.target as HTMLInputElement).checked)"
        >
        <label
          for="gst-has-header"
          class="text-xs cursor-pointer select-none"
        >First row is header</label>
      </div>

      <div
        class="space-y-2"
        data-testid="gst-key-column-field"
      >
        <Label for="gst-key-column">Key Column (recommended)</Label>
        <Input
          id="gst-key-column"
          :model-value="selectedNode.data.gstKeyColumn || ''"
          :placeholder="hasHeader ? 'e.g. Email' : 'e.g. B'"
          @update:model-value="updateNodeData('gstKeyColumn', $event)"
        />
        <p class="text-xs text-muted-foreground">
          A column whose value is unique per row. With it, inserting, deleting, or sorting rows is
          detected correctly. Without it, rows are matched by row number.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="gst-events-field"
      >
        <Label>Start a run when</Label>
        <div
          v-for="option in SHEETS_EVENT_OPTIONS"
          :key="option.value"
          class="flex items-center gap-2"
        >
          <input
            :id="`gst-event-${option.value}`"
            type="checkbox"
            class="rounded border-border"
            :checked="events.includes(option.value)"
            @change="setEvent(option.value, ($event.target as HTMLInputElement).checked)"
          >
          <label
            :for="`gst-event-${option.value}`"
            class="text-xs cursor-pointer select-none"
          >{{ option.label }}</label>
        </div>
        <p
          class="text-xs text-amber-500 flex items-start gap-1"
          data-testid="gst-write-back-warning"
        >
          <AlertTriangle class="h-3 w-3 mt-0.5 shrink-0" />
          If this workflow writes to the same sheet, keep only "Row added" on, or its own writes
          start new runs.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="gst-poll-field"
      >
        <Label for="gst-poll-interval">Poll Interval (Minutes)</Label>
        <Input
          id="gst-poll-interval"
          :model-value="String(selectedNode.data.pollIntervalMinutes ?? 1)"
          type="number"
          min="1"
          step="1"
          @update:model-value="updateNodeData('pollIntervalMinutes', Number.parseInt($event, 10) || 1)"
        />
        <p class="text-xs text-muted-foreground">
          The first poll records the sheet as it is. Heym keeps only fingerprints of cells, never
          their values.
        </p>
      </div>

      <div
        class="space-y-2 pt-2 border-t"
        data-testid="gst-output-fields"
      >
        <Label class="text-xs text-muted-foreground">Available output fields</Label>
        <div class="text-xs text-muted-foreground space-y-1 font-mono">
          <div>${{ selectedNode.data.label }}.event: created, updated, or deleted</div>
          <div>${{ selectedNode.data.label }}.row: current cells by column name</div>
          <div>${{ selectedNode.data.label }}.row.rowIndex: sheet row number</div>
          <div>${{ selectedNode.data.label }}.changed_columns: columns that changed</div>
          <div>${{ selectedNode.data.label }}.key: key column value</div>
          <div>${{ selectedNode.data.label }}.triggered_at: when the change was seen</div>
        </div>
      </div>
    </div>
  </template>
</template>
```

- [ ] **Step 3: Register both in** `NodePropertiesForm.vue`. Below the `ImapTriggerNodeProperties` import add:

```ts
import GoogleDriveTriggerNodeProperties from "./GoogleDriveTriggerNodeProperties.vue";
import GoogleSheetsTriggerNodeProperties from "./GoogleSheetsTriggerNodeProperties.vue";
```

Below `<ImapTriggerNodeProperties v-else-if="selectedNode?.type === 'imapTrigger'" />` add:

```vue
  <GoogleDriveTriggerNodeProperties v-else-if="selectedNode?.type === 'googleDriveTrigger'" />
  <GoogleSheetsTriggerNodeProperties v-else-if="selectedNode?.type === 'googleSheetsTrigger'" />
```

- [ ] **Step 4: Run the checks**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: pass. If `typecheck` reports `selectedNode.value` as possibly null inside a computed, the `?.` already guards it. Keep the guard and do not add non-null assertions.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Panels/propertiesPanel/nodes/GoogleDriveTriggerNodeProperties.vue frontend/src/components/Panels/propertiesPanel/nodes/GoogleSheetsTriggerNodeProperties.vue frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue
git commit -m "feat(editor): properties forms for Google Drive and Sheets triggers"
```

---

## Task 18: Playwright coverage

**Files:**
- Create: `frontend/e2e/google-triggers.spec.ts`

- [ ] **Step 1: Write the spec**

```ts
import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("Google Drive Trigger switches between folder and file scope", async ({ page }) => {
  const workflow = await createWorkflow(page, `Drive Trigger ${Date.now()}`, [
    {
      id: "drive-trigger",
      type: "googleDriveTrigger",
      position: { x: 120, y: 160 },
      data: {
        label: "contractsFolder",
        credentialId: "",
        gdtScope: "folder",
        gdtFolderId: "",
        gdtFileId: "",
        gdtEvents: ["created", "updated", "deleted"],
        gdtIncludeFolders: false,
        pollIntervalMinutes: 1,
      },
    },
  ]);

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="drive-trigger"]').click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("gdt-credential-field")).toBeVisible();
    await expect(panel.getByTestId("gdt-folder-field")).toBeVisible();
    await expect(panel.getByTestId("gdt-events-field").getByLabel("File created")).toBeChecked();
    await expect(panel.getByTestId("gdt-output-fields")).toContainText("$contractsFolder.file.id");

    await panel.getByTestId("gdt-scope-field").locator("select").selectOption("file");
    await expect(panel.getByTestId("gdt-file-field")).toBeVisible();
    await expect(panel.getByTestId("gdt-folder-field")).toHaveCount(0);
    await expect(panel.getByTestId("gdt-events-field").getByLabel("File created")).toHaveCount(0);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("Google Sheets Trigger shows key column, write-back warning and outputs", async ({ page }) => {
  const workflow = await createWorkflow(page, `Sheets Trigger ${Date.now()}`, [
    {
      id: "sheet-trigger",
      type: "googleSheetsTrigger",
      position: { x: 120, y: 160 },
      data: {
        label: "newLead",
        credentialId: "",
        gstSpreadsheetId: "",
        gstSheetName: "Leads",
        gstHasHeader: true,
        gstKeyColumn: "",
        gstEvents: ["created"],
        pollIntervalMinutes: 1,
      },
    },
  ]);

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="sheet-trigger"]').click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("gst-spreadsheet-field")).toBeVisible();
    await expect(panel.getByTestId("gst-key-column-field")).toBeVisible();
    await expect(panel.getByTestId("gst-write-back-warning")).toBeVisible();
    const events = panel.getByTestId("gst-events-field");
    await expect(events.getByLabel("Row added")).toBeChecked();
    await expect(events.getByLabel("Row updated")).not.toBeChecked();
    await expect(panel.getByTestId("gst-output-fields")).toContainText("$newLead.row.rowIndex");
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
```

- [ ] **Step 2: Run it.** Use the full stack. The memory note on E2E: close the AI panel and click Properties before node props, as the spec does.

Run: `./run_e2e.sh e2e/google-triggers.spec.ts` from the repo root. If the script takes no file argument, run `cd frontend && bunx playwright test e2e/google-triggers.spec.ts` with the stack running.
Expected: `2 passed`.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/google-triggers.spec.ts
git commit -m "test(e2e): Google Drive and Sheets trigger properties"
```

---

## Task 19: Docs

Use the `heym-documentation` skill (`.cursor/skills/heym-documentation/SKILL.md`). New text has no em dashes, because these pages are also published on heym.run.

**Files:**
- Create: `frontend/src/docs/content/nodes/google-drive-trigger-node.md`
- Create: `frontend/src/docs/content/nodes/google-sheets-trigger-node.md`
- Modify:
  - `frontend/src/docs/manifest.ts`
  - `content/reference/features.md`
  - `content/reference/node-types.md`
  - `content/reference/triggers.md`
  - `content/reference/integrations.md`
  - `content/reference/credentials.md`
  - `content/reference/credentials-sharing.md`
  - `content/nodes/google-drive-node.md`
  - `content/nodes/google-sheets-node.md`

- [ ] **Step 1: Create** `google-drive-trigger-node.md`

````markdown
# Google Drive Trigger

The **Google Drive Trigger** node watches a Google Drive folder, or one file, and starts a workflow once for each file that is created, updated, or deleted. It is a zero-input trigger for intake folders, shared contract folders, and report drops.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.event`, `$nodeLabel.file`, `$nodeLabel.changed_fields`, `$nodeLabel.folder_id`, `$nodeLabel.triggered_at` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `google_drive` credential |
| `gdtScope` | `folder` \| `file` | Watch the files in a folder (default) or one file |
| `gdtFolderId` | String | Folder ID or URL. Empty watches My Drive. Only files directly inside the folder are watched |
| `gdtFileId` | String | File ID or URL, for file scope |
| `gdtEvents` | Array | Any of `created`, `updated`, `deleted` (default all three). File scope has no `created` |
| `gdtIncludeFolders` | Boolean | Subfolders themselves also start runs (default off) |
| `pollIntervalMinutes` | Integer | How often Heym checks Drive (minimum and default 1) |

These fields take plain values, not `$` expressions.

## Setup Guide

1. Create a **Google Drive (OAuth2)** credential. See [Third-Party Integrations](../reference/integrations.md#google-drive-oauth2).
2. Drag **Google Drive Trigger** onto the canvas and select the credential.
3. Paste the folder URL from your browser, choose the events, and save.

## Trigger Semantics

- The first poll records the folder as it is and starts nothing. Only later changes start runs.
- `created`: a file appears in the folder, including a file moved into it.
- `updated`: the file's name, modification time, size, or type changed.
- `deleted`: the file is no longer in the folder. It was trashed, deleted, or moved out. In file scope, a file you can no longer see counts as deleted.
- Each change starts exactly one run with `trigger_source = "google_drive"`, also when Heym runs several workers or instances. If a run cannot start, the change is tried again on the next poll. A server crash in the moment between recording a change and starting its run can drop that one change; it is never run twice.
- At most 50 runs start per poll; the rest follow on the next polls.
- A folder with more than 5,000 files is skipped with a warning in the logs.
- Changing the credential, folder, file, or the subfolder setting records the folder again without starting runs. Deactivating the node forgets the folder; changes made while it is inactive do not start runs.

## Output Fields

| Expression | Description |
|------------|-------------|
| `$nodeLabel.event` | `created`, `updated`, or `deleted` |
| `$nodeLabel.file.id` | Drive file ID |
| `$nodeLabel.file.name` | File name |
| `$nodeLabel.file.mime_type` | File type |
| `$nodeLabel.file.size_bytes` | Size, `null` for Google Docs, Sheets, Slides and folders |
| `$nodeLabel.file.created_time` | Creation time |
| `$nodeLabel.file.modified_time` | Last modification time |
| `$nodeLabel.file.web_view_link` | Link to open the file |
| `$nodeLabel.file.is_folder` | `true` for subfolders |
| `$nodeLabel.changed_fields` | Fields that changed, on `updated` |
| `$nodeLabel.folder_id` | Watched folder, `root` for My Drive, `null` in file scope |
| `$nodeLabel.triggered_at` | When the change was seen |

For `deleted`, `file` holds the last metadata Heym saw.

## What Heym Stores

Heym keeps the metadata of the watched files (ID, name, type, size, times, link) to tell what changed. It never reads or stores file contents.

## Example Workflow

**New contract in a folder: summarize and post to Slack**

```
googleDriveTrigger → condition → googleDrive (syncToHeymDrive) → converter (pdfToText) → llm → slack
```

- **Condition**: `$contractsFolder.event == "created"`
- **Google Drive**: `gdFileId` is `$contractsFolder.file.id`

## Related

- [Google Drive](./google-drive-node.md): read, update, or remove the file that triggered the run
- [Google Sheets Trigger](./google-sheets-trigger-node.md)
- [Triggers](../reference/triggers.md)
- [Credential Sharing](../reference/credentials-sharing.md)
````

- [ ] **Step 2: Create** `google-sheets-trigger-node.md`

````markdown
# Google Sheets Trigger

The **Google Sheets Trigger** node watches one sheet tab and starts a workflow once for each row that is added, updated, or deleted. Use it for form responses, lead lists, and status columns your team edits.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.event`, `$nodeLabel.row`, `$nodeLabel.changed_columns`, `$nodeLabel.key`, `$nodeLabel.spreadsheet_id`, `$nodeLabel.sheet_name`, `$nodeLabel.triggered_at` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `google_sheets` credential |
| `gstSpreadsheetId` | String | Spreadsheet ID or URL |
| `gstSheetName` | String | Tab name (default `Sheet1`) |
| `gstHasHeader` | Boolean | Row 1 holds column names (default on) |
| `gstKeyColumn` | String | Optional, recommended. Header name (or column letter without a header) whose value is unique per row |
| `gstEvents` | Array | Any of `created`, `updated`, `deleted` (default all three) |
| `pollIntervalMinutes` | Integer | How often Heym checks the sheet (minimum and default 1) |

These fields take plain values, not `$` expressions.

## Setup Guide

1. Create a **Google Sheets (OAuth2)** credential. See [Third-Party Integrations](../reference/integrations.md#google-sheets-oauth2).
2. Drag **Google Sheets Trigger** onto the canvas and select the credential.
3. Paste the spreadsheet URL, enter the tab name, and set a key column such as `Email` or `ID`.

## Row Identity

- **With a key column**, a row is matched by its key value. Inserting, deleting, or sorting rows is detected correctly. A row with an empty key is ignored until the key is filled in. If two rows share a key, the first one is used.
- **Without a key column**, a row is matched by its row number. Deleting a row in the middle of the sheet then reads as `updated` for every row below it plus one `deleted` at the end.

## Trigger Semantics

- The first poll records the sheet as it is and starts nothing.
- Blank rows are ignored.
- Editing the header row records the sheet again without starting runs.
- Each change starts exactly one run with `trigger_source = "google_sheets"`, also when Heym runs several workers or instances. If a run cannot start, the change is tried again on the next poll. A server crash in the moment between recording a change and starting its run can drop that one change; it is never run twice.
- At most 50 runs start per poll; the rest follow on the next polls.
- A tab with more than 10,000 rows is skipped with a warning in the logs.

## Writing Back to the Same Sheet

A workflow that writes to the sheet it watches causes its own `updated` events. If your workflow writes a score or status back into the row, keep only **Row added** (`created`) on.

## Output Fields

| Expression | Description |
|------------|-------------|
| `$nodeLabel.event` | `created`, `updated`, or `deleted` |
| `$nodeLabel.row` | The row's current cells by column name, plus `rowIndex` |
| `$nodeLabel.row.rowIndex` | Sheet row number |
| `$nodeLabel.changed_columns` | Columns that changed. On `created`, every non-empty column |
| `$nodeLabel.key` | Key column value, `null` on `deleted` or without a key column |
| `$nodeLabel.spreadsheet_id` | Watched spreadsheet |
| `$nodeLabel.sheet_name` | Watched tab |
| `$nodeLabel.triggered_at` | When the change was seen |

For `deleted`, `row` holds only `rowIndex`, the row number it last had.

## What Heym Stores

Heym does not store cell values. For each row it keeps the last row number and a keyed fingerprint per cell, derived from the instance's `SECRET_KEY`. That is enough to tell which columns changed, but not what they said before. Runs read the row's current values from Google.

## Example Workflow

**New lead row: score it and write the score back**

```
googleSheetsTrigger (created only) → llm → googleSheets (updateRange) → condition → slack
```

- **Google Sheets** `gsUpdateRow`: `$newLead.row.rowIndex`

## Related

- [Google Sheets](./google-sheets-node.md): read or write rows in the run
- [Google Drive Trigger](./google-drive-trigger-node.md)
- [Triggers](../reference/triggers.md)
````

- [ ] **Step 3: Register both in** `manifest.ts`. After `{ slug: "imap-trigger-node", title: "IMAP Trigger" },` add:

```ts
      { slug: "google-drive-trigger-node", title: "Google Drive Trigger" },
      { slug: "google-sheets-trigger-node", title: "Google Sheets Trigger" },
```

- [ ] **Step 4: Update the reference docs**
  - `node-types.md`: after the IMAP Trigger row add:

```markdown
| [Google Drive Trigger](../nodes/google-drive-trigger-node.md) | Trigger when a file is created, updated, or deleted in a Drive folder | 1 |
| [Google Sheets Trigger](../nodes/google-sheets-trigger-node.md) | Trigger when a row is added, updated, or deleted in a sheet | 1 |
```

  - `triggers.md`:
    - Trigger Nodes table, after the IMAP row:

```markdown
| [Google Drive Trigger](../nodes/google-drive-trigger-node.md) | Polls a Drive folder or file and starts once per created, updated, or deleted file. |
| [Google Sheets Trigger](../nodes/google-sheets-trigger-node.md) | Polls a sheet tab and starts once per added, updated, or deleted row. |
```

    - Entry Points table, after the IMAP row:

```markdown
| **Google Drive / Sheets** | Google trigger poller (leader worker, per-node polling interval) | Google OAuth2 credential |
```

    - New section after `### IMAP`:

```markdown
### Google Drive and Google Sheets

The Google trigger poller runs in the leader worker and checks active `googleDriveTrigger` and `googleSheetsTrigger` nodes on their `pollIntervalMinutes`. Each node keeps a snapshot in the database: file metadata for Drive, keyed fingerprints of cells for Sheets (never cell values). Polls are claimed per node and each change is consumed with a compare-and-swap, so a change starts one run across every worker and instance. Input includes `change`, `triggered_by` (`"google_drive"` or `"google_sheets"`), `trigger_node_id`, and `triggered_at`.
```

    - `trigger_source` table, after `"imap"`:

```markdown
| `"google_drive"` | Google Drive Trigger poller |
| `"google_sheets"` | Google Sheets Trigger poller |
```

    - Inputs by Trigger, after the IMAP line:

```markdown
- **Google Drive / Sheets**: `change` + `triggered_by: "google_drive"` or `"google_sheets"` + `trigger_node_id` + `triggered_at`
```

    - Related: add `[Google Drive Trigger](../nodes/google-drive-trigger-node.md), [Google Sheets Trigger](../nodes/google-sheets-trigger-node.md)` after the IMAP Trigger link in the Node Types line.

  - `features.md`:
    - After the IMAP Trigger per-node section (the paragraph ending "...inbound triage and response workflows."), add:

```markdown
#### [Google Drive Trigger](../nodes/google-drive-trigger-node.md)

The Google Drive Trigger node watches a Drive folder, or one file, and starts a workflow once for each file that is created, updated, or deleted. It hands the file's metadata downstream, so a [Google Drive](../nodes/google-drive-node.md) node can read the file and an [LLM](../nodes/llm-node.md) can summarize it. Heym stores file metadata only.

#### [Google Sheets Trigger](../nodes/google-sheets-trigger-node.md)

The Google Sheets Trigger node watches one tab and starts a workflow once for each row that is added, updated, or deleted. It outputs the row's current values and the columns that changed. Set a key column so inserts and sorting are detected correctly. Heym stores keyed fingerprints of cells, never cell values.
```

    - In the four trigger lists (lines ~29, ~439, ~586, and the intro on line ~11), add `[Google Drive Trigger](../nodes/google-drive-trigger-node.md), [Google Sheets Trigger](../nodes/google-sheets-trigger-node.md)` after each `[IMAP Trigger](../nodes/imap-trigger-node.md)` occurrence. On line ~586 also add "Google trigger poller" after "IMAP trigger manager".

  - `integrations.md`:
    - In the summary table, change the Google Sheets row's node cell to `[Google Sheets node](../nodes/google-sheets-node.md), [Google Sheets Trigger](../nodes/google-sheets-trigger-node.md)` and the Google Drive row's to `[Google Drive node](../nodes/google-drive-node.md), [Google Drive Trigger](../nodes/google-drive-trigger-node.md)`.
    - Add `- [Google Sheets Trigger node](../nodes/google-sheets-trigger-node.md)` and `- [Google Drive Trigger node](../nodes/google-drive-trigger-node.md)` to the matching "Used By" lists.
  - `credentials.md`: after the Google Sheets and Google Drive rows add:

```markdown
| [Google Sheets Trigger](../nodes/google-sheets-trigger-node.md) | Google Sheets (OAuth2) | Same credential as the Google Sheets node |
| [Google Drive Trigger](../nodes/google-drive-trigger-node.md) | Google Drive (OAuth2) | Same credential as the Google Drive node |
```

  - `credentials-sharing.md`: append to the Google Drive warning paragraph:

```markdown
The same applies to the [Google Drive Trigger](../nodes/google-drive-trigger-node.md): a shared credential lets that person's workflows watch any folder in your Drive.
```

  - `google-drive-node.md` "See Also": add `- [Google Drive Trigger](./google-drive-trigger-node.md)`.
  - `google-sheets-node.md` "Related": add `- [Google Sheets Trigger](./google-sheets-trigger-node.md): start a workflow when a row changes`.

- [ ] **Step 5: Check the docs build and links**

Run: `cd frontend && bun run typecheck && bun run lint && grep -rn "—" src/docs/content/nodes/google-drive-trigger-node.md src/docs/content/nodes/google-sheets-trigger-node.md`
Expected: typecheck and lint pass. The final grep prints nothing, because the new pages have no em dashes. Then open `/docs/nodes/google-drive-trigger-node` and `/docs/nodes/google-sheets-trigger-node` in the running app and check that both render and their links resolve.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/docs
git commit -m "docs: Google Drive and Google Sheets trigger nodes"
```

---

## Task 20: Release tour

**Files:**
- Create: `frontend/src/features/release-tour/components/visuals/GoogleTriggersTourVisual.vue`
- Modify: `frontend/src/features/release-tour/tourVisuals.ts`
- Modify: `frontend/src/features/release-tour/releaseRegistry.ts`
- Delete: `frontend/src/features/release-tour/components/visuals/DashboardHitlTourVisual.vue`

- [ ] **Step 1: Pick the release entry.** Run `git tag --sort=-creatordate | head -1` and `cat VERSION`.
  - If the newest tag is still `v0.0.130`, `2026.20` (Slack Bot) has not shipped. Add the section to `2026.20`.
  - If a newer tag exists whose release contains #748, create `2026.21` with today's `publishedAt` and `tourEnabled: false`. Use `2026.20`'s intro fields and put the section there.

- [ ] **Step 2: Add the visual** `GoogleTriggersTourVisual.vue`

```vue
<script setup lang="ts">
import { computed } from "vue";
import { FileText, FolderOpen, Play, Sheet } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: a file lands in the folder · 1: its run starts ·
// 2: a row is added to the sheet · 3: its run starts.
const step = useCycleStep(4, 1500);

const fileLanded = computed<boolean>(() => step.value >= 0 && step.value <= 1);
const driveRun = computed<boolean>(() => step.value === 1);
const rowAdded = computed<boolean>(() => step.value >= 2);
const sheetRun = computed<boolean>(() => step.value === 3);

const caption = computed<string>(() => {
  if (step.value === 0) return "contract.pdf lands in Intake";
  if (step.value === 1) return "Google Drive Trigger starts one run";
  if (step.value === 2) return "A lead row is added to Leads";
  return "Google Sheets Trigger starts one run";
});
</script>

<template>
  <div class="flex h-full w-full flex-col justify-between rounded-lg bg-card p-3">
    <div class="flex items-center gap-2">
      <span class="flex items-center gap-1 rounded-md border border-border/60 bg-background px-2 py-1 text-[10px] leading-none text-muted-foreground">
        <FolderOpen class="h-3 w-3" />
        Intake
        <span
          class="ml-1 flex items-center gap-0.5 rounded px-1 py-0.5 text-[9px] leading-none transition-opacity duration-500"
          :class="fileLanded ? 'bg-primary/15 text-foreground opacity-100' : 'opacity-0'"
        >
          <FileText class="h-2 w-2" />
          contract.pdf
        </span>
      </span>
      <span class="h-px w-4 bg-border" />
      <span
        class="flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] leading-none transition-colors duration-500"
        :class="driveRun ? 'border-primary/60 bg-primary/10 text-foreground' : 'border-border/60 bg-background text-muted-foreground'"
      >
        <Play class="h-3 w-3" />
        run
      </span>
    </div>

    <div class="flex items-center gap-2">
      <span class="flex items-center gap-1 rounded-md border border-border/60 bg-background px-2 py-1 text-[10px] leading-none text-muted-foreground">
        <Sheet class="h-3 w-3" />
        Leads
        <span
          class="ml-1 rounded px-1 py-0.5 text-[9px] leading-none transition-opacity duration-500"
          :class="rowAdded ? 'bg-primary/15 text-foreground opacity-100' : 'opacity-0'"
        >
          row 14
        </span>
      </span>
      <span class="h-px w-4 bg-border" />
      <span
        class="flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] leading-none transition-colors duration-500"
        :class="sheetRun ? 'border-primary/60 bg-primary/10 text-foreground' : 'border-border/60 bg-background text-muted-foreground'"
      >
        <Play class="h-3 w-3" />
        run
      </span>
    </div>

    <p class="truncate text-[10px] leading-none text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
```

- [ ] **Step 3: Register the visual and drop the oldest one.** In `tourVisuals.ts`:
  - Remove the `DashboardHitlTourVisual` import and its `"dashboard-hitl"` entry.
  - Add `import GoogleTriggersTourVisual from "@/features/release-tour/components/visuals/GoogleTriggersTourVisual.vue";` and `"google-triggers": GoogleTriggersTourVisual,`.

Then delete the visual file:

```bash
git rm frontend/src/features/release-tour/components/visuals/DashboardHitlTourVisual.vue
```

- [ ] **Step 4: Add the section.** In `releaseRegistry.ts`:
  - Delete the whole `2026.17` entry. Its only section was `dashboard-hitl`; the registry keeps the five newest sections.
  - In the target release from Step 1, append `"google-triggers"` to `sectionOrder` and append this section to `sections`:

```ts
      {
        id: "google-triggers",
        title: "Start a run when a Drive file or a sheet row changes",
        publishedAt: new Date("2026-10-17T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Two new trigger nodes. **Google Drive Trigger** starts a run when a file is created, updated, or deleted in a folder you choose. **Google Sheets Trigger** starts a run when a row is added, updated, or deleted, and tells the run which columns changed.",
          },
          {
            type: "prose",
            markdown:
              "Each change starts exactly one run, even on a multi-instance install. Heym keeps file metadata and keyed fingerprints of cells, never cell values. Set a key column such as `Email` so inserted or sorted rows are matched correctly.",
          },
        ],
        tour: {
          description:
            "Start a run when a file lands in a Drive folder or a row changes in a sheet, once per change.",
          useCases: [
            "Summarize every contract dropped into a shared folder",
            "Score each new lead as soon as its row appears",
            "Notify an owner when a status column changes",
          ],
          tourVisual: "google-triggers",
          docTarget: {
            categoryId: "nodes",
            slug: "google-sheets-trigger-node",
            title: "Google Sheets Trigger",
          },
        },
      },
```

- [ ] **Step 5: Run the tests**

Run: `cd frontend && bun run test -- src/features/release-tour && bun run typecheck && bun run lint`
Expected: pass. `releaseTourMapper.test.ts` resolves every slide to a registered visual. `e2e/support.ts` derives the seen id from the registry, so it needs no edit.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/release-tour
git commit -m "feat(release-tour): announce Google Drive and Google Sheets triggers"
```

---

## Task 21: Full verification and hand-off

**Files:** none (formatting fixes only)

- [ ] **Step 1: Run the full local check**

Run: `DATABASE_URL=postgresql+asyncpg://heym:heym@localhost:6543/heym SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
Expected: frontend lint and typecheck, Ruff, and every backend test pass. `check.sh` applies `ruff format`; commit any formatting-only diff.

- [ ] **Step 2: Run the frontend unit tests** (CI runs them; `check.sh` does not)

Run: `cd frontend && bun run test`
Expected: all pass.

- [ ] **Step 3: Run the new E2E spec and the release tour spec**

Run: `./run_e2e.sh` (or `cd frontend && bunx playwright test e2e/google-triggers.spec.ts e2e/release-tour.spec.ts`)
Expected: pass.

- [ ] **Step 4: Manual smoke test with real Google credentials**, on a local stack (`./run.sh`):
  1. Create a Google Drive Trigger on a test folder with a 1-minute interval and activate it.
     - Wait for the baseline, then drop a file into the folder. Within about 75 seconds one run appears with `trigger_source = google_drive`.
     - Rename the file: one `updated` run with `changed_fields: ["name"]`.
     - Trash it: one `deleted` run.
  2. Create a Google Sheets Trigger with key column `Email`.
     - Add a row: one `created` run.
     - Edit `Status`: one `updated` run with `changed_columns: ["Status"]`.
     - Sort the sheet: no runs.
     - Delete the row: one `deleted` run.
  3. Inspect the stored rows:

```bash
docker exec -it heym-trigger-pg psql -U heym -c "select item_key, payload from trigger_poll_items limit 5"
```

     Sheets payloads show only `r` and hex `c` values; no cell text.
  4. With two backend processes running against the same database, repeat one sheet edit. Exactly one run appears.

- [ ] **Step 5: Hand off.** Push the branch the user picked in Task 0 and open the PR, following the user's choices from Task 0. The PR description covers:
  - the two nodes;
  - the once-per-change guarantee;
  - the no-cell-values storage rule;
  - the IMAP dispatch extraction (behavior unchanged);
  - the migration;
  - the release tour entry.
