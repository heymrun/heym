# Slack Trigger Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `slackTrigger` entrypoint node that auto-generates a static webhook URL, handles Slack's URL verification challenge, verifies request signatures, and executes the workflow with the event payload.

**Architecture:** A new `POST /api/slack/webhook/{node_id}` FastAPI endpoint looks up the workflow by node_id via a JSONB containment query, responds to Slack's challenge immediately, verifies HMAC-SHA256 signature via a new `slack_trigger` credential type, and fires workflow execution as a background task (to satisfy Slack's 3s response requirement). The `slackTrigger` node type is a 0-input entrypoint node identical in structure to `cron`; it injects the received event payload as initial output.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, PostgreSQL JSONB, Python hmac/hashlib, Vue 3 Composition API, TypeScript strict mode, Alembic

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/app/db/models.py` | Modify | Add `slack_trigger` to `CredentialType` enum |
| `backend/alembic/versions/056_add_slack_trigger_credential_type.py` | Create | DB migration for new enum value |
| `backend/app/api/credentials.py` | Modify | Masking + validation for `slack_trigger` |
| `backend/app/api/slack.py` | Create | Webhook endpoint (challenge, verify, execute) |
| `backend/app/main.py` | Modify | Register slack router |
| `backend/app/services/workflow_executor.py` | Modify | Handle `slackTrigger` node type (output + initial_inputs) |
| `backend/app/services/workflow_dsl_prompt.py` | Modify | Document `slackTrigger` node for AI DSL |
| `backend/tests/test_slack_trigger.py` | Create | 5 unit test cases |
| `frontend/src/types/workflow.ts` | Modify | Add `slackTrigger` to `NodeType` union |
| `frontend/src/types/node.ts` | Modify | Add `slackTrigger` to `NODE_DEFINITIONS` |
| `frontend/src/components/Panels/NodePanel.vue` | Modify | Add icon/color, add to `noInputTypes` |
| `frontend/src/components/Panels/PropertiesPanel.vue` | Modify | Add UI template for `slackTrigger` config |
| `heymweb/src/components/sections/DocumentationSection.tsx` | Modify | Add Slack Trigger to feature/integration list |

---

## Task 1: Add `slack_trigger` credential type to DB model

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/056_add_slack_trigger_credential_type.py`

- [ ] **Step 1: Add enum value to CredentialType**

In `backend/app/db/models.py`, find the `CredentialType` class (around line 26). Add `slack_trigger` after the `slack` entry:

```python
class CredentialType(str, PyEnum):
    ...
    slack = "slack"
    slack_trigger = "slack_trigger"   # ← add this line
    ...
```

- [ ] **Step 2: Create Alembic migration**

Create `backend/alembic/versions/056_add_slack_trigger_credential_type.py`:

```python
"""add slack_trigger credential type

Revision ID: 056
Revises: 055
Create Date: 2026-04-16
"""

from alembic import op

revision: str = "056"
down_revision: str = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'slack_trigger'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
```

- [ ] **Step 3: Run migration**

```bash
cd backend && uv run alembic upgrade head
```

Expected output: `Running upgrade 055 -> 056, add slack_trigger credential type`

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/056_add_slack_trigger_credential_type.py
git commit -m "feat: add slack_trigger credential type to DB enum"
```

---

## Task 2: Add masking + validation for `slack_trigger` in credentials API

**Files:**
- Modify: `backend/app/api/credentials.py`

- [ ] **Step 1: Add masking handler**

In `backend/app/api/credentials.py`, find the `get_masked_value` function (around line 35). Add a branch for `slack_trigger` right after the `slack` branch:

```python
if credential_type == CredentialType.slack:
    webhook_url = config.get("webhook_url", "")
    return mask_api_key(webhook_url)
if credential_type == CredentialType.slack_trigger:      # ← add this block
    signing_secret = config.get("signing_secret", "")
    return mask_api_key(signing_secret)
```

- [ ] **Step 2: Add validation in create/update endpoint**

In the same file, find the credential validation block (around line 676 where `CredentialType.slack` is validated). Add right after the `slack` block:

```python
elif credential_type == CredentialType.slack_trigger:
    if "signing_secret" not in config or not config["signing_secret"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slack Trigger credential requires signing_secret",
        )
```

- [ ] **Step 3: Run linter**

```bash
cd backend && uv run ruff check app/api/credentials.py && uv run ruff format app/api/credentials.py
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/credentials.py
git commit -m "feat: add slack_trigger credential masking and validation"
```

---

## Task 3: Create the Slack webhook endpoint

**Files:**
- Create: `backend/app/api/slack.py`

- [ ] **Step 1: Write the failing tests first** (see Task 6 — tests are written before the endpoint, but since this is a new file we write the skeleton first, then tests, then fill in)

Actually — write the endpoint file fully now so tests can import it:

Create `backend/app/api/slack.py`:

```python
import asyncio
import hashlib
import hmac
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.workflows import collect_referenced_workflows, get_credentials_context
from app.db.models import Credential, CredentialType, ExecutionHistory, Workflow
from app.db.session import async_session_maker
from app.services.encryption import decrypt_config
from app.services.global_variables_service import get_global_variables_context
from app.services.workflow_executor import execute_workflow

logger = logging.getLogger("slack_webhook")

router = APIRouter()

_SLACK_TIMESTAMP_TOLERANCE_SECONDS = 300


def _verify_slack_signature(
    signing_secret: str,
    raw_body: bytes,
    timestamp: str,
    signature: str,
) -> bool:
    """Verify X-Slack-Signature HMAC-SHA256. Returns True if valid."""
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False
    if abs(time.time() - ts) > _SLACK_TIMESTAMP_TOLERANCE_SECONDS:
        return False
    base_string = f"v0:{timestamp}:{raw_body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _find_workflow_by_node_id(
    db: AsyncSession, node_id: str
) -> Workflow | None:
    """Use JSONB containment to find the workflow containing this node_id."""
    result = await db.execute(
        select(Workflow).where(
            text("nodes @> :fragment::jsonb").bindparams(
                fragment=f'[{{"id": "{node_id}"}}]'
            )
        )
    )
    return result.scalar_one_or_none()


async def _get_signing_secret(db: AsyncSession, credential_id: str) -> str | None:
    """Decrypt and return the signing_secret from a slack_trigger credential."""
    result = await db.execute(
        select(Credential).where(
            Credential.id == uuid.UUID(credential_id),
            Credential.type == CredentialType.slack_trigger,
        )
    )
    credential = result.scalar_one_or_none()
    if not credential:
        return None
    config = decrypt_config(credential.encrypted_config)
    return config.get("signing_secret")


async def _execute_workflow_background(
    workflow: Workflow,
    node_id: str,
    event_body: dict[str, Any],
    safe_headers: dict[str, str],
) -> None:
    """Run workflow execution in background after returning 200 to Slack."""
    try:
        async with async_session_maker() as db:
            credentials_context = await get_credentials_context(workflow, db)
            global_vars = await get_global_variables_context(db, workflow.owner_id)
            referenced_workflows = await collect_referenced_workflows(workflow, db)

        initial_inputs: dict[str, Any] = {
            "event": event_body,
            "headers": safe_headers,
        }

        # Inject _initial_inputs into the slackTrigger node data
        nodes = [dict(n) for n in workflow.nodes]
        for node in nodes:
            if node.get("id") == node_id and node.get("type") == "slackTrigger":
                node["data"] = dict(node.get("data", {}))
                node["data"]["_initial_inputs"] = initial_inputs

        async with async_session_maker() as db:
            history_entry = ExecutionHistory(
                workflow_id=workflow.id,
                status="running",
                trigger_source="Slack",
            )
            db.add(history_entry)
            await db.commit()
            await db.refresh(history_entry)

            result = await execute_workflow(
                nodes=nodes,
                edges=workflow.edges,
                initial_inputs=initial_inputs,
                credentials_context=credentials_context,
                global_variables=global_vars,
                referenced_workflows=referenced_workflows,
                workflow_id=workflow.id,
                owner_id=workflow.owner_id,
                execution_history_id=history_entry.id,
                trigger_source="Slack",
            )

            history_entry.status = "success" if result.success else "error"
            history_entry.output = result.output
            history_entry.error = result.error
            await db.commit()

    except Exception:
        logger.exception("Error executing workflow %s via Slack trigger", workflow.id)


_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-slack-signature",
        "x-execution-token",
        "proxy-authorization",
        "x-api-key",
        "x-auth-token",
        "x-session-token",
    }
)


@router.post("/webhook/{node_id}")
async def slack_webhook(node_id: str, request: Request) -> dict[str, Any]:
    """
    Receive Slack Events API webhooks.

    Handles:
    - url_verification challenge (responds immediately, no workflow execution)
    - Signature verification via slackTrigger credential
    - Workflow execution as background task
    """
    raw_body = await request.body()

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body"
        )

    # Handle Slack URL verification challenge immediately
    if body.get("type") == "url_verification":
        challenge = body.get("challenge", "")
        logger.info("Slack URL verification challenge received for node %s", node_id)
        return {"challenge": challenge}

    async with async_session_maker() as db:
        workflow = await _find_workflow_by_node_id(db, node_id)

    if not workflow:
        logger.warning("No workflow found for Slack trigger node_id=%s", node_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No workflow found for this webhook URL",
        )

    # Find the trigger node's credentialId
    trigger_node = next(
        (n for n in workflow.nodes if n.get("id") == node_id),
        None,
    )
    credential_id: str | None = None
    if trigger_node:
        credential_id = trigger_node.get("data", {}).get("credentialId") or None

    # Verify Slack signature if credential is configured
    if credential_id:
        async with async_session_maker() as db:
            signing_secret = await _get_signing_secret(db, credential_id)

        if signing_secret:
            timestamp = request.headers.get("x-slack-request-timestamp", "")
            signature = request.headers.get("x-slack-signature", "")
            if not _verify_slack_signature(signing_secret, raw_body, timestamp, signature):
                logger.warning(
                    "Invalid Slack signature for node_id=%s", node_id
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid Slack signature",
                )
    else:
        logger.warning(
            "No credential configured for Slack trigger node_id=%s — running without verification",
            node_id,
        )

    # Build safe headers (strip sensitive ones)
    safe_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _SENSITIVE_HEADERS
    }

    # Fire workflow execution as background task (Slack requires 200 within 3s)
    asyncio.create_task(
        _execute_workflow_background(workflow, node_id, body, safe_headers)
    )

    return {"ok": True}
```

- [ ] **Step 2: Run ruff**

```bash
cd backend && uv run ruff check app/api/slack.py && uv run ruff format app/api/slack.py
```

Expected: no errors.

- [ ] **Step 3: Verify `execute_workflow` signature**

Before finalizing `_execute_workflow_background`, read `backend/app/services/cron_scheduler.py` (the `_execute_for_node` method) — it follows the identical pattern (no user context, creates history entry, calls `execute_workflow`). Adjust the call in `_execute_workflow_background` to match the exact keyword arguments used there.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/slack.py
git commit -m "feat: add Slack webhook endpoint with signature verification"
```

---

## Task 4: Register the Slack router in main.py

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add import and router registration**

In `backend/app/main.py`, find the imports section near the top where other API modules are imported. Add:

```python
from app.api import slack as slack_api
```

Then find the `app.include_router(teams.router, ...)` line (the last `include_router` call around line 205). Add after it:

```python
app.include_router(slack_api.router, prefix="/api/slack", tags=["Slack"])
```

- [ ] **Step 2: Verify server starts**

```bash
cd backend && uv run uvicorn app.main:app --reload --port 10105 &
sleep 3 && curl -s http://localhost:10105/api/slack/webhook/test-node-id -X POST -H "Content-Type: application/json" -d '{"type":"url_verification","challenge":"abc123"}' && kill %1
```

Expected: `{"challenge":"abc123"}`

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: register Slack webhook router"
```

---

## Task 5: Handle `slackTrigger` node type in workflow executor

**Files:**
- Modify: `backend/app/services/workflow_executor.py`

- [ ] **Step 1: Add output handler**

In `workflow_executor.py`, find the `elif node_type == "cron":` block (around line 5017). Add a new branch right after it:

```python
elif node_type == "cron":
    output = {
        "cron": node_data.get("cronExpression", ""),
        "triggered_at": datetime.now(timezone.utc).isoformat(),
    }
elif node_type == "slackTrigger":                               # ← add this block
    trigger_inputs = node_data.get("_initial_inputs", {})
    output = {
        "event": trigger_inputs.get("event", {}),
        "headers": trigger_inputs.get("headers", {}),
    }
```

- [ ] **Step 2: Run ruff**

```bash
cd backend && uv run ruff check app/services/workflow_executor.py
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/workflow_executor.py
git commit -m "feat: handle slackTrigger node type in workflow executor"
```

---

## Task 6: Write backend unit tests

**Files:**
- Create: `backend/tests/test_slack_trigger.py`

- [ ] **Step 1: Write all 5 tests**

Create `backend/tests/test_slack_trigger.py`:

```python
"""Unit tests for the Slack webhook endpoint."""

import hashlib
import hmac
import json
import time
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


def _make_signature(signing_secret: str, timestamp: str, body: str) -> str:
    base = f"v0:{timestamp}:{body}"
    return "v0=" + hmac.new(
        signing_secret.encode(), base.encode(), hashlib.sha256
    ).hexdigest()


class TestSlackWebhookUrlVerification(unittest.IsolatedAsyncioTestCase):
    async def test_url_verification_returns_challenge(self) -> None:
        """Slack sends url_verification; endpoint must echo challenge without executing workflow."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        body = {"type": "url_verification", "challenge": "abc123xyz"}
        response = client.post(
            "/api/slack/webhook/some-node-id",
            json=body,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"challenge": "abc123xyz"})


class TestSlackWebhookValidSignature(unittest.IsolatedAsyncioTestCase):
    async def test_valid_event_triggers_workflow(self) -> None:
        """Valid signature + known node_id → 200 ok, background task created."""
        from app.api.slack import slack_webhook, _find_workflow_by_node_id, _get_signing_secret

        node_id = str(uuid.uuid4())
        signing_secret = "test_secret_abc"
        timestamp = str(int(time.time()))
        body_dict = {"type": "message", "event": {"type": "message", "text": "hello"}}
        raw_body = json.dumps(body_dict).encode()
        signature = _make_signature(signing_secret, timestamp, raw_body.decode())

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.owner_id = uuid.uuid4()
        mock_workflow.nodes = [
            {"id": node_id, "type": "slackTrigger", "data": {"label": "slackTrigger", "credentialId": "cred-1"}}
        ]
        mock_workflow.edges = []

        with (
            patch("app.api.slack._find_workflow_by_node_id", new=AsyncMock(return_value=mock_workflow)),
            patch("app.api.slack._get_signing_secret", new=AsyncMock(return_value=signing_secret)),
            patch("app.api.slack._execute_workflow_background", new=AsyncMock()),
            patch("asyncio.create_task"),
        ):
            from fastapi import Request
            from starlette.datastructures import Headers
            scope = {
                "type": "http",
                "method": "POST",
                "path": f"/api/slack/webhook/{node_id}",
                "headers": Headers({
                    "x-slack-request-timestamp": timestamp,
                    "x-slack-signature": signature,
                    "content-type": "application/json",
                }).raw,
                "query_string": b"",
            }

            async def receive():
                return {"type": "http.request", "body": raw_body, "more_body": False}

            request = Request(scope, receive)
            response = await slack_webhook(node_id, request)
            self.assertEqual(response, {"ok": True})


class TestSlackWebhookInvalidSignature(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_signature_returns_403(self) -> None:
        """Wrong HMAC → 403, workflow not executed."""
        from app.api.slack import slack_webhook
        from fastapi import HTTPException

        node_id = str(uuid.uuid4())
        timestamp = str(int(time.time()))
        body_dict = {"type": "message", "event": {}}
        raw_body = json.dumps(body_dict).encode()
        bad_signature = "v0=badhash"

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {"id": node_id, "type": "slackTrigger", "data": {"credentialId": "cred-1"}}
        ]

        with (
            patch("app.api.slack._find_workflow_by_node_id", new=AsyncMock(return_value=mock_workflow)),
            patch("app.api.slack._get_signing_secret", new=AsyncMock(return_value="real_secret")),
        ):
            from starlette.datastructures import Headers
            scope = {
                "type": "http",
                "method": "POST",
                "path": f"/api/slack/webhook/{node_id}",
                "headers": Headers({
                    "x-slack-request-timestamp": timestamp,
                    "x-slack-signature": bad_signature,
                    "content-type": "application/json",
                }).raw,
                "query_string": b"",
            }

            async def receive():
                return {"type": "http.request", "body": raw_body, "more_body": False}

            from fastapi import Request
            request = Request(scope, receive)
            with self.assertRaises(HTTPException) as ctx:
                await slack_webhook(node_id, request)
            self.assertEqual(ctx.exception.status_code, 403)


class TestSlackWebhookReplayAttack(unittest.IsolatedAsyncioTestCase):
    async def test_old_timestamp_returns_403(self) -> None:
        """Timestamp > 5 min old → 403 regardless of valid signature."""
        from app.api.slack import slack_webhook
        from fastapi import HTTPException

        node_id = str(uuid.uuid4())
        signing_secret = "secret"
        old_timestamp = str(int(time.time()) - 400)  # 400 seconds ago
        body_dict = {"type": "message", "event": {}}
        raw_body = json.dumps(body_dict).encode()
        signature = _make_signature(signing_secret, old_timestamp, raw_body.decode())

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {"id": node_id, "type": "slackTrigger", "data": {"credentialId": "cred-1"}}
        ]

        with (
            patch("app.api.slack._find_workflow_by_node_id", new=AsyncMock(return_value=mock_workflow)),
            patch("app.api.slack._get_signing_secret", new=AsyncMock(return_value=signing_secret)),
        ):
            from starlette.datastructures import Headers
            scope = {
                "type": "http",
                "method": "POST",
                "path": f"/api/slack/webhook/{node_id}",
                "headers": Headers({
                    "x-slack-request-timestamp": old_timestamp,
                    "x-slack-signature": signature,
                    "content-type": "application/json",
                }).raw,
                "query_string": b"",
            }

            async def receive():
                return {"type": "http.request", "body": raw_body, "more_body": False}

            from fastapi import Request
            request = Request(scope, receive)
            with self.assertRaises(HTTPException) as ctx:
                await slack_webhook(node_id, request)
            self.assertEqual(ctx.exception.status_code, 403)


class TestSlackWebhookUnknownNode(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_node_id_returns_404(self) -> None:
        """node_id not found in any workflow → 404."""
        from app.api.slack import slack_webhook
        from fastapi import HTTPException

        node_id = str(uuid.uuid4())
        body_dict = {"type": "message", "event": {}}
        raw_body = json.dumps(body_dict).encode()

        with patch("app.api.slack._find_workflow_by_node_id", new=AsyncMock(return_value=None)):
            from starlette.datastructures import Headers
            scope = {
                "type": "http",
                "method": "POST",
                "path": f"/api/slack/webhook/{node_id}",
                "headers": Headers({"content-type": "application/json"}).raw,
                "query_string": b"",
            }

            async def receive():
                return {"type": "http.request", "body": raw_body, "more_body": False}

            from fastapi import Request
            request = Request(scope, receive)
            with self.assertRaises(HTTPException) as ctx:
                await slack_webhook(node_id, request)
            self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests**

```bash
cd backend && uv run pytest tests/test_slack_trigger.py -v
```

Expected:
```
PASSED tests/test_slack_trigger.py::TestSlackWebhookUrlVerification::test_url_verification_returns_challenge
PASSED tests/test_slack_trigger.py::TestSlackWebhookValidSignature::test_valid_event_triggers_workflow
PASSED tests/test_slack_trigger.py::TestSlackWebhookInvalidSignature::test_invalid_signature_returns_403
PASSED tests/test_slack_trigger.py::TestSlackWebhookReplayAttack::test_old_timestamp_returns_403
PASSED tests/test_slack_trigger.py::TestSlackWebhookUnknownNode::test_unknown_node_id_returns_404
```

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_slack_trigger.py
git commit -m "test: add unit tests for Slack webhook endpoint"
```

---

## Task 7: Update Workflow DSL prompt

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py`

- [ ] **Step 1: Add slackTrigger section**

In `workflow_dsl_prompt.py`, find the `### 2. cron (Scheduled Trigger)` section. Add a new section right after the cron section ends:

```
### 3. slackTrigger (Slack Event Entry Point)
- **inputs: 0, outputs: 1** — zero-input entrypoint, like `cron`
- **WHEN TO USE**: When workflow must react to Slack events (messages, reactions, mentions, app_home_opened, etc.)
- **DO NOT use** `textInput` as entry point for Slack-triggered workflows
- **Required field**: `credentialId` — must point to a `slack_trigger` credential containing the signing secret
- **Output fields available downstream**:
  - `$slackTrigger.event` — full Slack event object
  - `$slackTrigger.event.type` — event type (e.g. `"message"`, `"reaction_added"`)
  - `$slackTrigger.event.text` — message text (when applicable)
  - `$slackTrigger.event.user` — Slack user ID who triggered the event
  - `$slackTrigger.headers` — sanitized HTTP headers

**Example node JSON:**
```json
{
  "id": "n1",
  "type": "slackTrigger",
  "position": {"x": 100, "y": 100},
  "data": {
    "label": "slackEvent",
    "credentialId": "<slack_trigger_credential_id>"
  }
}
```

**Example downstream usage:**
- LLM user message: `"Slack user $slackEvent.event.user said: $slackEvent.event.text"`
- Condition: `$slackEvent.event.type == "message"`
```

- [ ] **Step 2: Run ruff**

```bash
cd backend && uv run ruff check app/services/workflow_dsl_prompt.py
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py
git commit -m "feat: add slackTrigger node documentation to workflow DSL prompt"
```

---

## Task 8: Add `slackTrigger` to frontend types

**Files:**
- Modify: `frontend/src/types/workflow.ts`
- Modify: `frontend/src/types/node.ts`

- [ ] **Step 1: Add to NodeType union**

In `frontend/src/types/workflow.ts`, find the `NodeType` union (around line 115). Add `"slackTrigger"` after `"drive"`:

```typescript
export type NodeType =
  | "textInput"
  | "cron"
  | ...
  | "drive"
  | "slackTrigger";    // ← add this
```

- [ ] **Step 2: Add to NODE_DEFINITIONS**

In `frontend/src/types/node.ts`, find the `slack` entry (around line 245). Add `slackTrigger` entry after `slack`:

```typescript
slackTrigger: {
  type: "slackTrigger",
  label: "Slack Trigger",
  description: "Receive Slack events and trigger the workflow",
  color: "node-slack",
  icon: "MessageSquare",
  inputs: 0,
  outputs: 1,
  defaultData: {
    label: "slackTrigger",
    credentialId: "",
  },
},
```

- [ ] **Step 3: Run typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/types/node.ts
git commit -m "feat: add slackTrigger to frontend NodeType and NODE_DEFINITIONS"
```

---

## Task 9: Update NodePanel.vue

**Files:**
- Modify: `frontend/src/components/Panels/NodePanel.vue`

- [ ] **Step 1: Add to icon map**

In `NodePanel.vue`, find the icon map object (around line 131 where `slack: MessageSquare` etc. are listed). Add:

```typescript
slackTrigger: MessageSquare,    // ← add after slack entry
```

- [ ] **Step 2: Add to color map**

In the color map object (around line where `slack: "node-slack"` is), add:

```typescript
slackTrigger: "node-slack",    // ← add after slack entry
```

- [ ] **Step 3: Add to noInputTypes arrays**

In `NodePanel.vue`, find both `noInputTypes` arrays (around lines 272 and 336). Add `"slackTrigger"` to each:

```typescript
const noInputTypes: NodeType[] = ["textInput", "cron", "sticky", "merge", "errorHandler", "slackTrigger"];
```

- [ ] **Step 4: Run typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Panels/NodePanel.vue
git commit -m "feat: add slackTrigger to NodePanel icon/color maps and noInputTypes"
```

---

## Task 10: Add PropertiesPanel UI for `slackTrigger`

**Files:**
- Modify: `frontend/src/components/Panels/PropertiesPanel.vue`

- [ ] **Step 1: Add to icon map and color map**

In `PropertiesPanel.vue`, find the icon map (around line 54 where `slack: MessageSquare` is). Add:

```typescript
slackTrigger: MessageSquare,    // ← add after slack
```

Find the color map (around line 88 where `slack: "node-slack"` is). Add:

```typescript
slackTrigger: "node-slack",    // ← add after slack
```

Find the component label map (around line 122 where `slack: "slack-node"` is). Add:

```typescript
slackTrigger: "slack-trigger-node",    // ← add after slack
```

- [ ] **Step 2: Add slackTrigger credentials ref**

In the `<script setup>` section, near the other credential refs (around line 280 where `rabbitmqCredentials` is defined). Add:

```typescript
const slackTriggerCredentials = ref<CredentialListItem[]>([]);
```

- [ ] **Step 3: Add credential fetch in the type-switch block**

Find the block that loads credentials when a node type is selected (around line 530 where `if (type === "rabbitmq")`). Add:

```typescript
if (type === "slackTrigger") {
  try {
    slackTriggerCredentials.value = await credentialsApi.listByType("slack_trigger");
  } catch {
    slackTriggerCredentials.value = [];
  }
}
```

- [ ] **Step 4: Add noInputTypes entry in PropertiesPanel**

In `PropertiesPanel.vue`, find the condition around line 9209:
```
v-if="!['textInput', 'cron', 'sticky', 'errorHandler', 'output', 'throwError'].includes(selectedNode.type) && ..."
```
Add `'slackTrigger'` to this list.

- [ ] **Step 5: Add webhook URL computed**

In the `<script setup>` section near other computed values, add:

```typescript
const slackTriggerWebhookUrl = computed((): string => {
  if (!selectedNode.value || selectedNode.value.type !== "slackTrigger") return "";
  const base = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";
  return `${base}/api/slack/webhook/${selectedNode.value.id}`;
});
```

- [ ] **Step 6: Add UI template**

Find the `<template v-if="selectedNode.type === 'cron'">` block (around line 4461). Add a new template block right after the closing `</template>` of the cron block:

```html
<template v-if="selectedNode.type === 'slackTrigger'">
  <div class="space-y-4">
    <div class="space-y-2">
      <Label>Signing Secret Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="slackTriggerCredentials.map((c) => ({ value: c.id, label: c.name }))"
        placeholder="Select Slack Trigger credential"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <p
        v-if="!selectedNode.data.credentialId"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        No credential set — requests will not be verified
      </p>
      <p
        v-else
        class="text-xs text-muted-foreground"
      >
        Used to verify incoming Slack request signatures
      </p>
    </div>

    <div class="space-y-2">
      <Label>Webhook URL</Label>
      <div class="flex gap-2">
        <Input
          :model-value="slackTriggerWebhookUrl"
          readonly
          class="font-mono text-xs"
        />
        <Button
          variant="outline"
          size="sm"
          @click="() => navigator.clipboard.writeText(slackTriggerWebhookUrl)"
        >
          Copy
        </Button>
      </div>
      <p class="text-xs text-muted-foreground">
        Paste this URL into your Slack App → Event Subscriptions → Request URL.
        The challenge is verified automatically.
      </p>
    </div>

    <div class="space-y-2 pt-2 border-t">
      <Label class="text-xs text-muted-foreground">Available output fields</Label>
      <div class="text-xs text-muted-foreground space-y-1 font-mono">
        <div>${{ selectedNode.data.label }}.event — full Slack event object</div>
        <div>${{ selectedNode.data.label }}.event.type — event type</div>
        <div>${{ selectedNode.data.label }}.event.text — message text</div>
        <div>${{ selectedNode.data.label }}.event.user — Slack user ID</div>
        <div>${{ selectedNode.data.label }}.headers — HTTP headers</div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 7: Run typecheck and lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Panels/PropertiesPanel.vue
git commit -m "feat: add slackTrigger properties panel with webhook URL and credential picker"
```

---

## Task 11: Update heymweb landing page

**Files:**
- Modify: `heymweb/src/components/sections/DocumentationSection.tsx` (or wherever integrations are listed)

- [ ] **Step 1: Read the file first**

Read `heymweb/src/components/sections/DocumentationSection.tsx` to find the integrations list pattern.

- [ ] **Step 2: Add Slack Trigger entry**

Following the existing pattern in the file, add a Slack Trigger entry to the integrations/feature list. Example (adapt to match the actual component structure):

```tsx
{
  name: "Slack Trigger",
  description: "Receive Slack events and automate workflows instantly",
  icon: "slack", // or whatever icon system is used
}
```

- [ ] **Step 3: Run typecheck (if applicable)**

```bash
cd heymweb && bun run typecheck 2>/dev/null || npx tsc --noEmit 2>/dev/null || echo "skip"
```

- [ ] **Step 4: Commit**

```bash
git add heymweb/src/components/sections/DocumentationSection.tsx
git commit -m "feat: add Slack Trigger to heymweb landing page integrations"
```

---

## Task 12: Documentation (heym-documentation skill)

- [ ] **Step 1: Invoke heym-documentation skill**

Use the `heym-documentation` skill to create a Slack Trigger documentation page covering:
- Creating a Slack App and enabling Event Subscriptions
- Creating a `slack_trigger` credential in Heym (where to find signing secret in Slack App settings)
- Adding the `slackTrigger` node to the canvas and copying the webhook URL
- How the URL verification challenge works (automatic, no action needed)
- Expression examples: `$slackTrigger.event.type`, `$slackTrigger.event.text`, `$slackTrigger.event.user`
- Example workflow: Slack message → LLM response → Slack reply

- [ ] **Step 2: Commit docs**

```bash
git add <doc files>
git commit -m "docs: add Slack Trigger node documentation"
```

---

## Task 13: Final check

- [ ] **Step 1: Run full check suite**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && ./check.sh
```

Expected: all backend tests pass, ruff clean, frontend lint + typecheck pass.

- [ ] **Step 2: Manual smoke test**

1. Start services: `./run.sh`
2. Open editor, drag `slackTrigger` node onto canvas
3. Verify node shows "Slack Trigger" label with 0 inputs, 1 output
4. Click node → right panel shows credential picker + webhook URL
5. Copy the webhook URL
6. Create a `slack_trigger` credential with any signing secret
7. Select credential in node panel
8. Simulate Slack challenge:
   ```bash
   curl -X POST <webhook_url> \
     -H "Content-Type: application/json" \
     -d '{"type":"url_verification","challenge":"test_challenge"}'
   ```
   Expected: `{"challenge":"test_challenge"}`
9. Simulate event with bad signature → expect 403
10. Simulate event with valid HMAC → expect 200 + workflow execution in history

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: Slack Trigger node - complete implementation" 2>/dev/null || echo "nothing to commit"
```
