# Decision Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `decision` node that calls a decision model (TypeSafe Jev and compatible endpoints) with a `state` plus typed `questions`, and returns its typed judgments to the workflow — plus a `decision` credential type, AI-assisted question generation, and the missing `maxToolIterations` input on the Agent node.

**Architecture:** A new node type with its own handler under `node_execution/nodes/`, backed by a single provider module (`decision_models.py`) that owns body construction, the guarded HTTP call, error mapping and trace writing. Credentials get a new `decision` type carrying `base_url` + optional `api_key`. The properties panel gets a structured question-row editor with a raw-JSON escape hatch for non-Jev contracts. Question generation reuses the existing `generate-schema` shape: an LLM writes the questions, the decision model answers them.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + Pydantic (backend); Vue 3 `<script setup>` + TypeScript strict + Pinia + Vue Flow (frontend); pytest for backend tests.

**Spec:** `docs/superpowers/specs/2026-09-21-decision-node-design.md`

---

## Ground rules for this plan

- **Never run `git push`.** Every commit stays local. No step in this plan pushes.
- Work directly on `main`. No worktrees, no feature branches.
- Backend tests are required; frontend UI tests are not written for this repo. Verification
  is `./check.sh` plus `bun run lint` and `bun run typecheck`.
- If `SECRET_KEY` is not exported locally, prefix full-suite commands with
  `SECRET_KEY=test-secret-key-for-tests-only-32-bytes`.
- If `.env` sets `HEYM_OTEL_ENABLED=true` with no collector running, pytest hangs. Prefix
  test commands with `HEYM_OTEL_ENABLED=false` when that happens.

## What a decision model is (context for the implementer)

You send one request describing the situation and the judgments you want:

```json
{
  "model": "jev-latest",
  "state": "Help! My payouts have been failing for 3 days.",
  "questions": {
    "is_urgent":  { "type": "noul",   "instructions": "Does this convey urgency?",
                    "criteria": { "true": "Explicitly time-sensitive", "false": "No urgency expressed" } },
    "department": { "type": "choice", "instructions": "Which team should handle this?",
                    "criteria": { "billing": "Payments, invoicing, refunds",
                                  "technical": "Bugs, outages, integrations" } },
    "frustration":{ "type": "score",  "instructions": "How frustrated is the customer?",
                    "criteria": ["Calm", "Frustrated", "Very angry"] }
  }
}
```

and you get back typed answers with probabilities:

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "is_urgent":  { "type": "noul", "noul": 0.95 },
    "department": { "type": "choice", "choice": "billing",
                    "probabilities": { "billing": 0.88, "technical": 0.12 }, "confidence": 0.81 },
    "frustration":{ "type": "score", "score": 1.05,
                    "legend": { "0": "Calm", "1": "Frustrated", "2": "Very angry" },
                    "probabilities": { "0": 0.0, "1": 0.95, "2": 0.05 }, "confidence": 0.92 }
  },
  "usage": { "input_tokens": 296, "output_tokens": 20 }
}
```

Endpoint: `POST {base_url}/v1/systemone`, `Authorization: Bearer <key>`. Error codes that
matter: 401 bad key, 422 malformed question, 429 rate limited, 529 overloaded.

The node passes the response through unchanged, so a workflow reads
`$decision.answers.department.choice`.

---

## File structure

**Backend — new files**

| File | Responsibility |
| --- | --- |
| `backend/app/services/decision_models.py` | Build the request body from node data; call the provider through the SSRF-guarded client; map errors; write the trace. All provider knowledge lives here. |
| `backend/app/services/node_execution/nodes/decision_node.py` | Resolve expressions from node data, call the service, return the response. No retry/tracing/packaging — the executor owns those. |
| `backend/app/api/decisions.py` | `POST /api/decisions/generate-questions` — LLM-assisted question drafting. |
| `backend/alembic/versions/123_add_decision_credential_type.py` | `ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'decision'`. |
| `backend/tests/test_decision_models.py` | Body construction and error mapping. |
| `backend/tests/test_decision_node.py` | Handler behaviour through a fake executor. |
| `backend/tests/test_decision_question_generation.py` | The generation endpoint. |

**Backend — modified**

`app/models/schemas.py`, `app/db/models.py`, `app/api/credentials.py`, `app/main.py`,
`app/services/node_execution/registry.py`, `app/services/cluster/node_placement.py`,
`app/services/workflow_dsl_prompt.py`, `backend/tests/test_cluster_node_placement.py`.

**Frontend — new files**

| File | Responsibility |
| --- | --- |
| `src/components/Panels/propertiesPanel/nodes/DecisionNodeProperties.vue` | The node's panel: credential, model, state, questions, custom body, timeout. |
| `src/components/Panels/propertiesPanel/nodes/DecisionQuestionsEditor.vue` | The repeatable question rows and their type-dependent criteria editors. |
| `src/components/Decision/DecisionAIQuestionsDialog.vue` | Sparkle dialog: prompt → review → apply. |
| `src/features/release-tour/components/visuals/DecisionNodeTourVisual.vue` | Animated mock for the tour. |
| `src/docs/content/nodes/decision-node.md` | Node documentation page. |

**Frontend — modified**

`src/types/workflow.ts`, `src/types/node.ts`, `src/types/credential.ts`,
`src/services/api.ts`, `src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue`,
`src/components/Panels/propertiesPanel/nodes/AgentNodeProperties.vue`,
`src/components/Panels/propertiesPanel/usePropertiesPanelController.ts`,
`src/components/Canvas/readonlyPreviewFields.ts`, `src/components/Canvas/WorkflowCanvas.vue`,
`src/components/Credentials/CredentialDialog.vue`, `src/components/Traces/TracesPanel.vue`,
`src/docs/manifest.ts`, `src/docs/content/reference/features.md`,
`src/docs/content/reference/node-types.md`, `src/docs/content/reference/integrations.md`,
`src/docs/content/reference/credentials.md`,
`src/docs/content/reference/credentials-sharing.md`,
`src/features/release-tour/releaseRegistry.ts`, `src/features/release-tour/tourVisuals.ts`.

---

## Task 1: Decision credential type — enum, config model, migration

**Files:**
- Modify: `backend/app/models/schemas.py:580` (enum), and the `CredentialConfig*` block near line 583
- Modify: `backend/app/db/models.py:29-50` (enum)
- Create: `backend/alembic/versions/123_add_decision_credential_type.py`
- Test: `backend/tests/test_decision_models.py`

- [ ] **Step 1: Confirm the current Alembic head**

```bash
cd backend && ls alembic/versions/ | grep -E "^1[0-9][0-9]_" | sort | tail -3
```

Expected: the highest numbered file is `122_add_vector_store_metadata_index.py`. If a
higher number exists, use `<highest+1>` as the new file's prefix and as `revision`, and set
`down_revision` to the actual head. Confirm the head with:

```bash
cd backend && grep -L "down_revision" /dev/null; grep -rho "revision = \"[^\"]*\"" alembic/versions/*.py | sort > /tmp/revs.txt; grep -rho "down_revision = \"[^\"]*\"" alembic/versions/*.py | sed 's/down_//' | sort > /tmp/downs.txt; comm -23 /tmp/revs.txt /tmp/downs.txt
```

Expected: exactly one revision id printed — that is the head. Use it as `down_revision`.

- [ ] **Step 2: Add the enum value to the Pydantic schema**

In `backend/app/models/schemas.py`, inside `class CredentialType(str, Enum)`, after the
`rag = "rag"` line:

```python
    decision = "decision"
```

- [ ] **Step 3: Add the enum value to the SQLAlchemy model**

In `backend/app/db/models.py`, inside `class CredentialType(str, PyEnum)`, after the
`rag = "rag"` line:

```python
    decision = "decision"
```

- [ ] **Step 4: Add the Pydantic config model**

In `backend/app/models/schemas.py`, next to `CredentialConfigOpenCode`:

```python
class CredentialConfigDecision(BaseModel):
    """Connection settings for a decision model endpoint (e.g. TypeSafe Jev)."""

    base_url: str
    api_key: str | None = None
```

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/123_add_decision_credential_type.py`:

```python
"""Add the decision credential type.

Revision ID: 123_add_decision_credential_type
"""

from alembic import op

revision = "123_add_decision_credential_type"
down_revision = "122_add_vector_store_metadata_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'decision'")


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an enum type in place, and rebuilding the
    # type would break any credential row still using it. Leaving the value present
    # is harmless: nothing reads it once the code is rolled back.
    pass
```

Replace `down_revision` with the head id found in Step 1 if it differs.

- [ ] **Step 6: Run the migration**

```bash
cd backend && uv run alembic upgrade head
```

Expected: `Running upgrade 122_... -> 123_add_decision_credential_type`.

- [ ] **Step 7: Verify the enum value exists**

```bash
cd backend && uv run python -c "
from app.models.schemas import CredentialType as S
from app.db.models import CredentialType as D
print(S.decision.value, D.decision.value)
"
```

Expected: `decision decision`

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/schemas.py backend/app/db/models.py backend/alembic/versions/123_add_decision_credential_type.py
git commit -m "feat(credentials): add the decision credential type

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Decision credential — validation, masking, public fields, listing

**Files:**
- Modify: `backend/app/api/credentials.py` (validation near line 1810, masking near line 237, public fields near line 353, new route near line 723)
- Test: `backend/tests/test_decision_credentials.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_decision_credentials.py`:

```python
"""Validation, masking and public-field exposure for the decision credential."""

import unittest

from fastapi import HTTPException

from app.api.credentials import (
    get_credential_public_fields,
    get_credential_summary,
    validate_credential_config,
)
from app.models.schemas import CredentialType


class DecisionCredentialValidationTests(unittest.TestCase):
    def test_base_url_is_required(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.decision, {"api_key": "k"})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("base_url", str(ctx.exception.detail))

    def test_api_key_is_optional(self) -> None:
        validate_credential_config(
            CredentialType.decision, {"base_url": "https://api.typesafe.ai"}
        )

    def test_base_url_must_be_http(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.decision, {"base_url": "ftp://x.test"})
        self.assertEqual(ctx.exception.status_code, 400)


class DecisionCredentialExposureTests(unittest.TestCase):
    def test_summary_masks_the_api_key(self) -> None:
        summary = get_credential_summary(
            CredentialType.decision,
            {"base_url": "https://api.typesafe.ai", "api_key": "sk-abcdef123456"},
        )
        self.assertIsNotNone(summary)
        self.assertNotIn("abcdef123456", str(summary))

    def test_summary_falls_back_to_the_host_without_a_key(self) -> None:
        summary = get_credential_summary(
            CredentialType.decision, {"base_url": "https://api.typesafe.ai"}
        )
        self.assertEqual(summary, "api.typesafe.ai")

    def test_public_fields_expose_base_url_but_never_the_key(self) -> None:
        fields = get_credential_public_fields(
            CredentialType.decision,
            {"base_url": "https://api.typesafe.ai", "api_key": "sk-abcdef123456"},
        )
        self.assertEqual(fields.get("base_url"), "https://api.typesafe.ai")
        self.assertNotIn("api_key", fields)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && uv run pytest tests/test_decision_credentials.py -v
```

Expected: FAIL. Errors will name whichever helper does not yet handle `CredentialType.decision`.
If `get_credential_summary` or `get_credential_public_fields` is not the exact name in this
file, run `grep -n "def get_credential_summary\|def get_credential_public_fields\|def validate_credential_config" backend/app/api/credentials.py`
and rename the imports in the test to match. Do not change the assertions.

- [ ] **Step 3: Add validation**

In `backend/app/api/credentials.py`, in `validate_credential_config`, next to the
`elif credential_type == CredentialType.rag:` branch (around line 1810):

```python
    elif credential_type == CredentialType.decision:
        base_url = str(config.get("base_url", "") or "").strip()
        if not base_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Decision credential requires base_url",
            )
        if not base_url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Decision credential base_url must start with http:// or https://",
            )
```

- [ ] **Step 4: Add masking**

In the summary helper, next to the `CredentialType.rag` branch (around line 237):

```python
    elif credential_type == CredentialType.decision:
        api_key = str(config.get("api_key", "") or "").strip()
        if api_key:
            return mask_api_key(api_key)
        base_url = str(config.get("base_url", "") or "").strip()
        return urlsplit(base_url).hostname or None
```

Add `from urllib.parse import urlsplit` to the file's imports if it is not already there.

- [ ] **Step 5: Add public fields**

In the public-fields helper, next to the `CredentialType.rag` branch (around line 353):

```python
    if credential_type == CredentialType.decision:
        return {"base_url": str(config.get("base_url", "")).strip() or None}
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
cd backend && uv run pytest tests/test_decision_credentials.py -v
```

Expected: 6 passed.

- [ ] **Step 7: Add the listing route**

In `backend/app/api/credentials.py`, immediately after the `list_llm_credentials` function
(it ends around line 770), add a route with the same three-query shape — owned, shared with
the user, shared with the user's teams. Copy `list_llm_credentials` verbatim, then change
exactly three things: the decorator path, the function name, and the type filter:

```python
@router.get("/decision", response_model=list[CredentialListResponse])
async def list_decision_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CredentialListResponse]:
    decision_types = [CredentialType.decision]
    # ... body copied from list_llm_credentials, with llm_types -> decision_types
```

Read `list_llm_credentials` first and reproduce its owned/shared/team-shared queries and its
deduplication exactly. Do not invent a shorter version — the sharing semantics matter.

- [ ] **Step 8: Verify the route is registered**

```bash
cd backend && uv run python -c "
from app.main import app
print([r.path for r in app.routes if 'credentials' in r.path and r.path.endswith('/decision')])
"
```

Expected: `['/api/credentials/decision']`

- [ ] **Step 9: Commit**

```bash
git add backend/app/api/credentials.py backend/tests/test_decision_credentials.py
git commit -m "feat(credentials): validate, mask and list decision credentials

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Request body construction

**Files:**
- Create: `backend/app/services/decision_models.py`
- Test: `backend/tests/test_decision_models.py`

This task builds only the pure function. The HTTP call comes in Task 4.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_decision_models.py`:

```python
"""Request body construction for decision models."""

import unittest

from app.services.decision_models import DecisionRequestError, build_decision_body


class BuildDecisionBodyTests(unittest.TestCase):
    def test_noul_question_with_criteria(self) -> None:
        body = build_decision_body(
            model="jev-latest",
            state="Payouts failing for 3 days",
            questions=[
                {
                    "id": "is_urgent",
                    "type": "noul",
                    "instructions": "Does this convey urgency?",
                    "criteriaTrue": "Explicitly time-sensitive",
                    "criteriaFalse": "No urgency expressed",
                }
            ],
        )
        self.assertEqual(
            body,
            {
                "model": "jev-latest",
                "state": "Payouts failing for 3 days",
                "questions": {
                    "is_urgent": {
                        "type": "noul",
                        "instructions": "Does this convey urgency?",
                        "criteria": {
                            "true": "Explicitly time-sensitive",
                            "false": "No urgency expressed",
                        },
                    }
                },
            },
        )

    def test_noul_criteria_omitted_when_both_sides_blank(self) -> None:
        body = build_decision_body(
            model="jev-latest",
            state="x",
            questions=[
                {"id": "q", "type": "noul", "instructions": "Is it?", "criteriaTrue": "",
                 "criteriaFalse": "   "}
            ],
        )
        self.assertNotIn("criteria", body["questions"]["q"])

    def test_choice_question_builds_an_option_map(self) -> None:
        body = build_decision_body(
            model="jev-latest",
            state="x",
            questions=[
                {
                    "id": "department",
                    "type": "choice",
                    "instructions": "Which team?",
                    "options": [
                        {"key": "billing", "description": "Payments and refunds"},
                        {"key": "technical", "description": "Bugs and outages"},
                    ],
                }
            ],
        )
        self.assertEqual(
            body["questions"]["department"]["criteria"],
            {"billing": "Payments and refunds", "technical": "Bugs and outages"},
        )

    def test_choice_option_without_a_description_becomes_null(self) -> None:
        body = build_decision_body(
            model="jev-latest",
            state="x",
            questions=[
                {
                    "id": "d",
                    "type": "choice",
                    "instructions": "Which?",
                    "options": [{"key": "a", "description": ""}, {"key": "b", "description": "B"}],
                }
            ],
        )
        self.assertIsNone(body["questions"]["d"]["criteria"]["a"])

    def test_score_question_builds_an_ordered_level_array(self) -> None:
        body = build_decision_body(
            model="jev-latest",
            state="x",
            questions=[
                {
                    "id": "frustration",
                    "type": "score",
                    "instructions": "How frustrated?",
                    "levels": ["Calm", "Frustrated", "Very angry"],
                }
            ],
        )
        self.assertEqual(
            body["questions"]["frustration"]["criteria"],
            ["Calm", "Frustrated", "Very angry"],
        )

    def test_structured_state_is_preserved(self) -> None:
        state = {"ticket": {"messages": [{"text": "hi"}]}}
        body = build_decision_body(model="jev-latest", state=state, questions=[
            {"id": "q", "type": "noul", "instructions": "Is it?"}
        ])
        self.assertEqual(body["state"], state)

    def test_row_order_is_preserved(self) -> None:
        body = build_decision_body(
            model="jev-latest",
            state="x",
            questions=[
                {"id": "b", "type": "noul", "instructions": "B?"},
                {"id": "a", "type": "noul", "instructions": "A?"},
            ],
        )
        self.assertEqual(list(body["questions"]), ["b", "a"])

    def test_empty_id_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(model="m", state="x", questions=[
                {"id": "  ", "type": "noul", "instructions": "Is it?"}
            ])
        self.assertIn("id", str(ctx.exception))

    def test_duplicate_id_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(model="m", state="x", questions=[
                {"id": "q", "type": "noul", "instructions": "A?"},
                {"id": "q", "type": "noul", "instructions": "B?"},
            ])
        self.assertIn("duplicate", str(ctx.exception).lower())

    def test_unknown_type_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError):
            build_decision_body(model="m", state="x", questions=[
                {"id": "q", "type": "nuol", "instructions": "A?"}
            ])

    def test_blank_instructions_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(model="m", state="x", questions=[
                {"id": "q", "type": "noul", "instructions": "   "}
            ])
        self.assertIn("instructions", str(ctx.exception))

    def test_choice_without_options_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(model="m", state="x", questions=[
                {"id": "q", "type": "choice", "instructions": "Which?", "options": []}
            ])
        self.assertIn("option", str(ctx.exception).lower())

    def test_score_with_one_level_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(model="m", state="x", questions=[
                {"id": "q", "type": "score", "instructions": "How much?", "levels": ["Calm"]}
            ])
        self.assertIn("level", str(ctx.exception).lower())

    def test_no_questions_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError):
            build_decision_body(model="m", state="x", questions=[])

    def test_blank_model_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(model="  ", state="x", questions=[
                {"id": "q", "type": "noul", "instructions": "Is it?"}
            ])
        self.assertIn("model", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && uv run pytest tests/test_decision_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.decision_models'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/decision_models.py`:

```python
"""Decision model (System One) requests: body construction, transport, tracing.

Decision models answer typed questions about a state instead of generating text.
The canonical contract is TypeSafe's: POST {base_url}/v1/systemone with
{model, state, questions} and back {model, answers, usage}. Everything a provider
knows lives in this module.
"""

from __future__ import annotations

from typing import Any

QUESTION_TYPES = ("noul", "choice", "score")

DEFAULT_ENDPOINT_PATH = "/v1/systemone"


class DecisionRequestError(ValueError):
    """Raised when node configuration cannot be turned into a valid request."""


def _text(value: object) -> str:
    return str(value or "").strip()


def _build_noul_criteria(question: dict) -> dict[str, str] | None:
    true_side = _text(question.get("criteriaTrue"))
    false_side = _text(question.get("criteriaFalse"))
    if not true_side and not false_side:
        return None
    criteria: dict[str, str] = {}
    if true_side:
        criteria["true"] = true_side
    if false_side:
        criteria["false"] = false_side
    return criteria


def _build_choice_criteria(question: dict, question_id: str) -> dict[str, str | None]:
    options = question.get("options") or []
    if not isinstance(options, list) or not options:
        raise DecisionRequestError(
            f"Question '{question_id}' is a choice and needs at least one option"
        )
    criteria: dict[str, str | None] = {}
    for option in options:
        if not isinstance(option, dict):
            raise DecisionRequestError(f"Question '{question_id}' has a malformed option")
        key = _text(option.get("key"))
        if not key:
            raise DecisionRequestError(f"Question '{question_id}' has an option with no name")
        if key in criteria:
            raise DecisionRequestError(
                f"Question '{question_id}' has a duplicate option '{key}'"
            )
        description = _text(option.get("description"))
        criteria[key] = description or None
    return criteria


def _build_score_criteria(question: dict, question_id: str) -> list[str]:
    levels = question.get("levels") or []
    if not isinstance(levels, list):
        raise DecisionRequestError(f"Question '{question_id}' has malformed levels")
    cleaned = [_text(level) for level in levels if _text(level)]
    if len(cleaned) < 2:
        raise DecisionRequestError(
            f"Question '{question_id}' is a score and needs at least two levels"
        )
    return cleaned


def build_decision_body(
    *,
    model: str,
    state: Any,
    questions: list[dict],
) -> dict[str, Any]:
    """Turn node configuration into a decision model request body."""
    resolved_model = _text(model)
    if not resolved_model:
        raise DecisionRequestError("Decision node requires a model")
    if not questions:
        raise DecisionRequestError("Decision node requires at least one question")

    built: dict[str, Any] = {}
    for question in questions:
        if not isinstance(question, dict):
            raise DecisionRequestError("Decision node has a malformed question row")
        question_id = _text(question.get("id"))
        if not question_id:
            raise DecisionRequestError("Every decision question needs an id")
        if question_id in built:
            raise DecisionRequestError(f"Duplicate decision question id '{question_id}'")

        question_type = _text(question.get("type"))
        if question_type not in QUESTION_TYPES:
            raise DecisionRequestError(
                f"Question '{question_id}' has an unknown type '{question_type}'"
            )

        instructions = _text(question.get("instructions"))
        if not instructions:
            raise DecisionRequestError(f"Question '{question_id}' needs instructions")

        payload: dict[str, Any] = {"type": question_type, "instructions": instructions}
        if question_type == "noul":
            criteria = _build_noul_criteria(question)
            if criteria is not None:
                payload["criteria"] = criteria
        elif question_type == "choice":
            payload["criteria"] = _build_choice_criteria(question, question_id)
        else:
            payload["criteria"] = _build_score_criteria(question, question_id)

        built[question_id] = payload

    return {"model": resolved_model, "state": state, "questions": built}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && uv run pytest tests/test_decision_models.py -v
```

Expected: 15 passed.

- [ ] **Step 5: Format and lint**

```bash
cd backend && uv run ruff format app/services/decision_models.py tests/test_decision_models.py && uv run ruff check app/services/decision_models.py tests/test_decision_models.py
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/decision_models.py backend/tests/test_decision_models.py
git commit -m "feat(decision): build decision model request bodies from node config

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Provider transport — guarded HTTP, error mapping, tracing

**Files:**
- Modify: `backend/app/services/decision_models.py`
- Test: `backend/tests/test_decision_models.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_decision_models.py` (add the imports at the top of the file):

```python
import unittest.mock as mock
import uuid

import httpx

from app.services.decision_models import DecisionProviderError, call_decision_model
from app.services.llm_trace import LLMTraceContext


def _trace_context() -> LLMTraceContext:
    return LLMTraceContext(user_id=uuid.uuid4(), credential_id=uuid.uuid4())


def _response(status_code: int, payload: object) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=payload,
        request=httpx.Request("POST", "https://api.typesafe.ai/v1/systemone"),
    )


class CallDecisionModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.body = {"model": "jev-latest", "state": "x", "questions": {}}

    def _call(self, response: httpx.Response, **kwargs: object) -> object:
        client = mock.MagicMock()
        client.post.return_value = response
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        with (
            mock.patch("app.services.decision_models.guard_http_url") as guard,
            mock.patch(
                "app.services.decision_models.build_guarded_http_client", return_value=client
            ),
            mock.patch("app.services.decision_models.record_llm_trace", return_value=None) as rec,
        ):
            self.guard = guard
            self.record = rec
            self.client = client
            return call_decision_model(
                base_url=str(kwargs.get("base_url", "https://api.typesafe.ai")),
                api_key=str(kwargs.get("api_key", "sk-test")),
                body=self.body,
                timeout=30.0,
                trace_context=_trace_context(),
            )

    def test_successful_call_returns_the_payload_unchanged(self) -> None:
        payload = {
            "model": "jev-1.13.0",
            "answers": {"is_urgent": {"type": "noul", "noul": 0.95}},
            "usage": {"input_tokens": 296, "output_tokens": 20},
        }
        result = self._call(_response(200, payload))
        self.assertEqual(result, payload)

    def test_the_url_is_guarded_before_dialling(self) -> None:
        self._call(_response(200, {"answers": {}}))
        self.guard.assert_called_once()
        self.assertIn("typesafe", self.guard.call_args.args[0])

    def test_the_endpoint_path_is_appended_once(self) -> None:
        self._call(_response(200, {"answers": {}}), base_url="https://api.typesafe.ai/")
        url = self.client.post.call_args.args[0]
        self.assertEqual(url, "https://api.typesafe.ai/v1/systemone")

    def test_the_api_key_travels_in_the_authorization_header(self) -> None:
        self._call(_response(200, {"answers": {}}))
        headers = self.client.post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer sk-test")

    def test_no_authorization_header_without_a_key(self) -> None:
        self._call(_response(200, {"answers": {}}), api_key="")
        headers = self.client.post.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)

    def test_a_trace_is_recorded_with_usage(self) -> None:
        self._call(
            _response(
                200,
                {
                    "model": "jev-1.13.0",
                    "answers": {},
                    "usage": {"input_tokens": 296, "output_tokens": 20},
                },
            )
        )
        self.record.assert_called_once()
        kwargs = self.record.call_args.kwargs
        self.assertEqual(kwargs["request_type"], "decision.systemone")
        self.assertEqual(kwargs["prompt_tokens"], 296)
        self.assertEqual(kwargs["completion_tokens"], 20)
        self.assertEqual(kwargs["model"], "jev-1.13.0")

    def test_401_names_the_credential(self) -> None:
        with self.assertRaises(DecisionProviderError) as ctx:
            self._call(_response(401, {"error": "bad key"}))
        self.assertIn("API key", str(ctx.exception))

    def test_422_carries_the_provider_detail(self) -> None:
        with self.assertRaises(DecisionProviderError) as ctx:
            self._call(_response(422, {"detail": "questions.q.criteria must be an array"}))
        self.assertIn("criteria must be an array", str(ctx.exception))

    def test_429_says_the_condition_is_transient(self) -> None:
        with self.assertRaises(DecisionProviderError) as ctx:
            self._call(_response(429, {"error": "slow down"}))
        self.assertIn("transient", str(ctx.exception).lower())

    def test_529_says_the_condition_is_transient(self) -> None:
        with self.assertRaises(DecisionProviderError) as ctx:
            self._call(_response(529, {"error": "overloaded"}))
        self.assertIn("transient", str(ctx.exception).lower())

    def test_a_failure_is_traced_too(self) -> None:
        with self.assertRaises(DecisionProviderError):
            self._call(_response(401, {"error": "bad key"}))
        self.record.assert_called_once()
        self.assertIsNotNone(self.record.call_args.kwargs["error"])

    def test_a_non_json_response_is_reported_clearly(self) -> None:
        raw = httpx.Response(
            status_code=200,
            text="<html>gateway</html>",
            request=httpx.Request("POST", "https://api.typesafe.ai/v1/systemone"),
        )
        with self.assertRaises(DecisionProviderError) as ctx:
            self._call(raw)
        self.assertIn("JSON", str(ctx.exception))
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && uv run pytest tests/test_decision_models.py -k CallDecisionModel -v
```

Expected: FAIL with `ImportError: cannot import name 'DecisionProviderError'`.

- [ ] **Step 3: Write the implementation**

Add to `backend/app/services/decision_models.py` — imports at the top:

```python
import json
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.http_identity import merge_outbound_headers
from app.services.llm_trace import LLMTraceContext, record_llm_trace
from app.services.ssrf_guard import build_guarded_http_client, guard_http_url
```

and the transport below `build_decision_body`:

```python
class DecisionProviderError(RuntimeError):
    """Raised when the decision model endpoint refuses or fails a request."""


def _endpoint_url(base_url: str) -> str:
    """Join the credential's base URL with the evaluation path exactly once."""
    parts = urlsplit(base_url.strip())
    path = (parts.path or "").rstrip("/")
    if not path.endswith(DEFAULT_ENDPOINT_PATH):
        path = f"{path}{DEFAULT_ENDPOINT_PATH}"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _error_message(status_code: int, payload: object, text: str) -> str:
    detail = ""
    if isinstance(payload, dict):
        for key in ("detail", "error", "message"):
            value = payload.get(key)
            if value:
                detail = value if isinstance(value, str) else json.dumps(value)
                break
    if not detail:
        detail = text[:300]
    if status_code == 401:
        return "Decision model rejected the API key on this credential"
    if status_code == 422:
        return f"Decision model rejected the request: {detail}"
    if status_code in (429, 529):
        cause = "rate limited" if status_code == 429 else "overloaded"
        return (
            f"Decision model is {cause} ({status_code}). This is a transient condition; "
            "enable retry on this node to ride it out."
        )
    return f"Decision model returned {status_code}: {detail}"


def call_decision_model(
    *,
    base_url: str,
    api_key: str,
    body: dict,
    timeout: float,
    trace_context: LLMTraceContext | None = None,
) -> dict:
    """Send one evaluation request and return the provider response unchanged."""
    url = _endpoint_url(base_url)
    guard_http_url(url, "decision model endpoint")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    started = time.monotonic()
    payload: object = None
    error: str | None = None
    status_code = 0
    text = ""
    try:
        with build_guarded_http_client(timeout=timeout, follow_redirects=True) as client:
            response = client.post(
                url, headers=merge_outbound_headers(headers), json=body
            )
            status_code = response.status_code
            text = response.text
            try:
                payload = response.json()
            except (json.JSONDecodeError, ValueError):
                payload = None
            if status_code >= 400:
                error = _error_message(status_code, payload, text)
            elif not isinstance(payload, dict):
                error = "Decision model did not return a JSON object"
    except httpx.HTTPError as exc:
        error = f"Decision model request failed: {exc}"
    finally:
        elapsed_ms = (time.monotonic() - started) * 1000
        if trace_context is not None:
            usage = payload.get("usage") if isinstance(payload, dict) else None
            usage = usage if isinstance(usage, dict) else {}
            prompt_tokens = usage.get("input_tokens")
            completion_tokens = usage.get("output_tokens")
            record_llm_trace(
                trace_context,
                request_type="decision.systemone",
                request=body,
                response=payload if isinstance(payload, dict) else {"raw": text[:2000]},
                model=(payload.get("model") if isinstance(payload, dict) else None)
                or str(body.get("model") or ""),
                provider="decision",
                error=error,
                prompt_tokens=int(prompt_tokens) if isinstance(prompt_tokens, int) else None,
                completion_tokens=(
                    int(completion_tokens) if isinstance(completion_tokens, int) else None
                ),
                total_tokens=(
                    int(prompt_tokens) + int(completion_tokens)
                    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int)
                    else None
                ),
                elapsed_ms=elapsed_ms,
            )

    if error:
        raise DecisionProviderError(error)
    assert isinstance(payload, dict)
    return payload
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && uv run pytest tests/test_decision_models.py -v
```

Expected: 27 passed. If `record_llm_trace`'s first argument is positional in this codebase,
the test's `call_args.kwargs` reads still work because the remaining arguments are keyword.
Confirm with `grep -n "def record_llm_trace" -A 3 backend/app/services/llm_trace.py`.

- [ ] **Step 5: Format, lint and commit**

```bash
cd backend && uv run ruff format app/services/decision_models.py tests/test_decision_models.py && uv run ruff check app/services/decision_models.py tests/test_decision_models.py
git add backend/app/services/decision_models.py backend/tests/test_decision_models.py
git commit -m "feat(decision): call decision endpoints through the SSRF-guarded client

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: The node handler

**Files:**
- Create: `backend/app/services/node_execution/nodes/decision_node.py`
- Modify: `backend/app/services/node_execution/registry.py:15` (alphabetical position after `dataTable`)
- Modify: `backend/app/services/cluster/node_placement.py`
- Modify: `backend/tests/test_cluster_node_placement.py`
- Test: `backend/tests/test_decision_node.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_decision_node.py`:

```python
"""Decision node handler: expression resolution, credential loading, output."""

import unittest
import unittest.mock as mock
import uuid

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import decision_node


class _FakeExecutor:
    """Minimal stand-in for WorkflowExecutor's expression surface."""

    def __init__(self) -> None:
        self.user_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.llm_session_id = None

    def _visible_inputs(self, inputs: dict) -> dict:
        return inputs

    def _is_single_dollar_expression(self, template: str) -> bool:
        return str(template).strip().startswith("$") and " " not in str(template).strip()

    def resolve_expression(self, template, inputs, node_id, preserve_type=False):
        return {"ticket": "structured"} if preserve_type else "resolved"

    def _resolve_template(self, template, inputs, node_id):
        return str(template).replace("$input.text", "payouts failing")


def _ctx(node_data: dict) -> NodeExecutionContext:
    return NodeExecutionContext(
        executor=_FakeExecutor(),
        node_id="n1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={"id": "n1", "type": "decision", "data": node_data},
        node_type="decision",
        node_data=node_data,
        node_label="decision",
    )


_CREDENTIAL = {"base_url": "https://api.typesafe.ai", "api_key": "sk-test"}


class DecisionNodeTests(unittest.TestCase):
    def _run(self, node_data: dict, response: dict | None = None):
        response = response or {"answers": {"q": {"type": "noul", "noul": 0.9}}}
        with (
            mock.patch.object(
                decision_node, "load_decision_credential", return_value=_CREDENTIAL
            ),
            mock.patch.object(
                decision_node, "call_decision_model", return_value=response
            ) as call,
        ):
            self.call = call
            return decision_node.execute(_ctx(node_data))

    def test_response_is_passed_through_untouched(self) -> None:
        payload = {
            "model": "jev-1.13.0",
            "answers": {"department": {"type": "choice", "choice": "billing"}},
            "usage": {"input_tokens": 10, "output_tokens": 2},
        }
        self.assertEqual(self._run(_base_node(), payload), payload)

    def test_a_template_state_is_resolved_as_text(self) -> None:
        self._run(_base_node(state="Ticket: $input.text"))
        self.assertEqual(self.call.call_args.kwargs["body"]["state"], "Ticket: payouts failing")

    def test_a_single_expression_state_preserves_its_type(self) -> None:
        self._run(_base_node(state="$input"))
        self.assertEqual(self.call.call_args.kwargs["body"]["state"], {"ticket": "structured"})

    def test_instructions_and_criteria_are_resolved(self) -> None:
        self._run(
            _base_node(
                questions=[
                    {
                        "id": "q",
                        "type": "noul",
                        "instructions": "About $input.text?",
                        "criteriaTrue": "Yes for $input.text",
                        "criteriaFalse": "No",
                    }
                ]
            )
        )
        question = self.call.call_args.kwargs["body"]["questions"]["q"]
        self.assertEqual(question["instructions"], "About payouts failing?")
        self.assertEqual(question["criteria"]["true"], "Yes for payouts failing")

    def test_custom_body_replaces_the_form(self) -> None:
        self._run(
            _base_node(
                customBodyEnabled=True,
                customBody='{"model": "other-1", "state": "$input.text", "questions": {}}',
            )
        )
        body = self.call.call_args.kwargs["body"]
        self.assertEqual(body["model"], "other-1")
        self.assertEqual(body["state"], "payouts failing")

    def test_malformed_custom_body_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._run(_base_node(customBodyEnabled=True, customBody="{not json"))
        self.assertIn("JSON", str(ctx.exception))

    def test_missing_credential_id_raises(self) -> None:
        node_data = _base_node()
        node_data["credentialId"] = ""
        with self.assertRaises(ValueError) as ctx:
            decision_node.execute(_ctx(node_data))
        self.assertIn("credential", str(ctx.exception).lower())

    def test_timeout_is_taken_from_node_data(self) -> None:
        self._run(_base_node(requestTimeoutSeconds=12))
        self.assertEqual(self.call.call_args.kwargs["timeout"], 12.0)


def _base_node(**overrides) -> dict:
    node_data = {
        "label": "decision",
        "credentialId": str(uuid.uuid4()),
        "model": "jev-latest",
        "state": "$input.text",
        "questions": [{"id": "q", "type": "noul", "instructions": "Urgent?"}],
        "customBodyEnabled": False,
        "customBody": "",
        "requestTimeoutSeconds": 60,
    }
    node_data.update(overrides)
    return node_data


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && uv run pytest tests/test_decision_node.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.node_execution.nodes.decision_node'`.

- [ ] **Step 3: Add the credential loader to the service**

Append to `backend/app/services/decision_models.py`:

```python
def load_decision_credential(credential_id: str) -> dict:
    """Read and decrypt a decision credential by id.

    Imported lazily inside the function body by callers that must not pull the DB
    layer at module import time.
    """
    import uuid as _uuid

    from app.db.models import Credential, CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    with SessionLocal() as db:
        credential = db.get(Credential, _uuid.UUID(str(credential_id)))
        if credential is None:
            raise DecisionRequestError("Decision credential not found")
        if credential.type != CredentialType.decision:
            raise DecisionRequestError("Node credential is not a decision credential")
        config = decrypt_config(credential.encrypted_config)

    return {
        "base_url": str(config.get("base_url") or ""),
        "api_key": str(config.get("api_key") or ""),
    }
```

Before writing this, confirm the synchronous session helper's name:

```bash
grep -n "SessionLocal" backend/app/db/session.py backend/app/services/llm_trace.py | head -5
```

`llm_trace.py` already uses `with SessionLocal() as db:` synchronously, so the same pattern
is correct inside a node handler.

- [ ] **Step 4: Write the handler**

Create `backend/app/services/node_execution/nodes/decision_node.py`:

```python
from __future__ import annotations

import json
import uuid
from typing import Any

from app.services.decision_models import (
    DecisionProviderError,
    DecisionRequestError,
    build_decision_body,
    call_decision_model,
    load_decision_credential,
)
from app.services.llm_trace import LLMTraceContext
from app.services.node_execution.base import NodeExecutionContext


def _resolve(executor: Any, template: object, inputs: dict, node_id: str) -> Any:
    """Resolve one configuration value, keeping a lone expression's own type."""
    if not isinstance(template, str) or "$" not in template:
        return template
    if executor._is_single_dollar_expression(template.strip()):
        return executor.resolve_expression(template.strip(), inputs, node_id, preserve_type=True)
    return executor._resolve_template(template, inputs, node_id)


def _resolve_questions(
    executor: Any, questions: list, inputs: dict, node_id: str
) -> list[dict]:
    resolved: list[dict] = []
    for question in questions or []:
        if not isinstance(question, dict):
            resolved.append(question)
            continue
        row = dict(question)
        for key in ("instructions", "criteriaTrue", "criteriaFalse"):
            if key in row:
                row[key] = _resolve(executor, row.get(key), inputs, node_id)
        options = row.get("options")
        if isinstance(options, list):
            row["options"] = [
                {
                    "key": option.get("key"),
                    "description": _resolve(
                        executor, option.get("description"), inputs, node_id
                    ),
                }
                if isinstance(option, dict)
                else option
                for option in options
            ]
        levels = row.get("levels")
        if isinstance(levels, list):
            row["levels"] = [_resolve(executor, level, inputs, node_id) for level in levels]
        resolved.append(row)
    return resolved


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the decision node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    credential_id = str(node_data.get("credentialId") or "").strip()
    if not credential_id:
        raise ValueError("Decision node requires a decision credential")

    timeout = float(node_data.get("requestTimeoutSeconds") or 60)

    try:
        if bool(node_data.get("customBodyEnabled")):
            raw_body = str(node_data.get("customBody") or "").strip()
            if not raw_body:
                raise DecisionRequestError("Custom request body is empty")
            resolved_body = self._resolve_template(raw_body, inputs, node_id)
            try:
                body = json.loads(resolved_body)
            except (json.JSONDecodeError, ValueError) as exc:
                raise DecisionRequestError(
                    f"Custom request body is not valid JSON: {exc}"
                ) from exc
            if not isinstance(body, dict):
                raise DecisionRequestError("Custom request body must be a JSON object")
        else:
            body = build_decision_body(
                model=str(node_data.get("model") or ""),
                state=_resolve(self, node_data.get("state"), inputs, node_id),
                questions=_resolve_questions(
                    self, node_data.get("questions") or [], inputs, node_id
                ),
            )

        credential = load_decision_credential(credential_id)
    except DecisionRequestError as exc:
        raise ValueError(str(exc)) from exc

    user_id = getattr(self, "user_id", None)
    trace_context = (
        LLMTraceContext(
            user_id=user_id,
            credential_id=uuid.UUID(credential_id),
            workflow_id=getattr(self, "workflow_id", None),
            node_id=node_id,
            node_label=ctx.node_label,
            source="workflow",
        )
        if user_id
        else None
    )

    try:
        return call_decision_model(
            base_url=credential["base_url"],
            api_key=credential["api_key"],
            body=body,
            timeout=timeout,
            trace_context=trace_context,
        )
    except DecisionProviderError as exc:
        raise ValueError(str(exc)) from exc
```

Confirm the executor's attribute names before relying on them:

```bash
grep -n "self.user_id\|self.workflow_id" backend/app/services/workflow_executor.py | head -5
```

If they differ, adjust the `getattr` calls to the real names.

- [ ] **Step 5: Register the handler**

In `backend/app/services/node_execution/registry.py`, inside `_HANDLER_MODULES`, after the
`"dataTable": "data_table_node",` line:

```python
    "decision": "decision_node",
```

- [ ] **Step 6: Declare cluster placement**

In `backend/app/services/cluster/node_placement.py`, in `NODE_PLACEMENT`, next to the other
`_ANY` entries:

```python
    "decision": _ANY,  # one outbound HTTP call, no local state
```

- [ ] **Step 7: Add the placement test**

In `backend/tests/test_cluster_node_placement.py`, inside `NodePlacementTests`, after
`test_code_node_runs_anywhere`:

```python
    def test_decision_node_runs_anywhere(self) -> None:
        self.assertEqual(node_placement({"type": "decision", "data": {}}), Placement.ANYWHERE)
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_decision_node.py tests/test_cluster_node_placement.py -v
```

Expected: all pass. The placement suite's registry-coverage test is the guard that would
have failed had Step 6 been skipped.

- [ ] **Step 9: Format, lint and commit**

```bash
cd backend && uv run ruff format app/services/ tests/ && uv run ruff check app/services/ tests/
git add backend/app/services/decision_models.py backend/app/services/node_execution/ backend/app/services/cluster/node_placement.py backend/tests/test_decision_node.py backend/tests/test_cluster_node_placement.py
git commit -m "feat(decision): add the decision node handler

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Question generation endpoint

**Files:**
- Create: `backend/app/api/decisions.py`
- Modify: `backend/app/main.py` (router registration)
- Modify: `backend/app/models/schemas.py` (request/response models)
- Test: `backend/tests/test_decision_question_generation.py`

- [ ] **Step 1: Read the pattern you are copying**

```bash
sed -n '1275,1350p' backend/app/api/data_tables.py
```

The new endpoint follows this exact shape: resolve the credential, reject non-LLM types,
decrypt, build a trace context, call `execute_llm(..., content_only=True)`, extract JSON,
normalise, 422 when nothing usable comes back.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_decision_question_generation.py`:

```python
"""AI-assisted decision question drafting."""

import unittest

from app.api.decisions import extract_questions_payload, normalize_generated_questions


class ExtractQuestionsPayloadTests(unittest.TestCase):
    def test_plain_json_object(self) -> None:
        payload = extract_questions_payload('{"questions": []}')
        self.assertEqual(payload, {"questions": []})

    def test_fenced_json_block(self) -> None:
        payload = extract_questions_payload('```json\n{"questions": []}\n```')
        self.assertEqual(payload, {"questions": []})

    def test_prose_around_the_object(self) -> None:
        payload = extract_questions_payload('Sure!\n{"questions": [], "state": "x"}\nDone.')
        self.assertEqual(payload, {"questions": [], "state": "x"})

    def test_unparseable_text_returns_none(self) -> None:
        self.assertIsNone(extract_questions_payload("I could not do that."))


class NormalizeGeneratedQuestionsTests(unittest.TestCase):
    def test_noul_question(self) -> None:
        rows = normalize_generated_questions(
            [
                {
                    "id": "Is Urgent!",
                    "type": "noul",
                    "instructions": "Urgent?",
                    "criteria": {"true": "yes side", "false": "no side"},
                }
            ],
            set(),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "is_urgent")
        self.assertEqual(rows[0]["criteriaTrue"], "yes side")
        self.assertEqual(rows[0]["criteriaFalse"], "no side")

    def test_choice_question_becomes_options(self) -> None:
        rows = normalize_generated_questions(
            [
                {
                    "id": "department",
                    "type": "choice",
                    "instructions": "Which team?",
                    "criteria": {"billing": "Payments", "technical": "Bugs"},
                }
            ],
            set(),
        )
        self.assertEqual(
            rows[0]["options"],
            [
                {"key": "billing", "description": "Payments"},
                {"key": "technical", "description": "Bugs"},
            ],
        )

    def test_score_question_becomes_levels(self) -> None:
        rows = normalize_generated_questions(
            [
                {
                    "id": "frustration",
                    "type": "score",
                    "instructions": "How frustrated?",
                    "criteria": ["Calm", "Angry"],
                }
            ],
            set(),
        )
        self.assertEqual(rows[0]["levels"], ["Calm", "Angry"])

    def test_unknown_type_is_dropped(self) -> None:
        rows = normalize_generated_questions(
            [{"id": "q", "type": "nuol", "instructions": "?"}], set()
        )
        self.assertEqual(rows, [])

    def test_question_without_instructions_is_dropped(self) -> None:
        rows = normalize_generated_questions([{"id": "q", "type": "noul"}], set())
        self.assertEqual(rows, [])

    def test_an_id_colliding_with_an_existing_one_is_suffixed(self) -> None:
        rows = normalize_generated_questions(
            [{"id": "urgent", "type": "noul", "instructions": "?"}], {"urgent"}
        )
        self.assertEqual(rows[0]["id"], "urgent_2")

    def test_duplicate_ids_within_one_batch_are_suffixed(self) -> None:
        rows = normalize_generated_questions(
            [
                {"id": "q", "type": "noul", "instructions": "A?"},
                {"id": "q", "type": "noul", "instructions": "B?"},
            ],
            set(),
        )
        self.assertEqual([row["id"] for row in rows], ["q", "q_2"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd backend && uv run pytest tests/test_decision_question_generation.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.decisions'`.

- [ ] **Step 4: Add the Pydantic models**

In `backend/app/models/schemas.py`, near the data-table suggestion models:

```python
class DecisionQuestionSuggestion(BaseModel):
    """One drafted decision question, in the shape the node panel stores."""

    id: str
    type: str
    instructions: str
    criteriaTrue: str | None = None
    criteriaFalse: str | None = None
    options: list[dict[str, str]] | None = None
    levels: list[str] | None = None


class DecisionQuestionsGenerateRequest(BaseModel):
    prompt: str
    credential_id: uuid.UUID
    model: str
    existing_question_ids: list[str] = []
    state_sample: str | None = None


class DecisionQuestionsSuggestionResponse(BaseModel):
    state: str | None = None
    questions: list[DecisionQuestionSuggestion]
```

- [ ] **Step 5: Write the router**

Create `backend/app/api/decisions.py`:

```python
"""AI-assisted drafting of decision model questions."""

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.models.schemas import (
    CredentialType,
    DecisionQuestionsGenerateRequest,
    DecisionQuestionsSuggestionResponse,
)
from app.services.decision_models import QUESTION_TYPES
from app.services.encryption import decrypt_config
from app.services.llm_provider import is_reasoning_model
from app.services.llm_service import execute_llm
from app.services.llm_trace import LLMTraceContext

router = APIRouter()

_SYSTEM_PROMPT = """You design questions for a decision model.

A decision model reads a `state` and answers typed questions about it. It does not
generate prose. There are exactly three question types:

- "noul": whether a condition holds. Returns the probability of yes.
- "choice": picks one option from a set you define. Returns the option and a distribution.
- "score": rates the state along an ordered rubric you define, two to ten levels.

Rules you must follow:
- Each question id is used only by code and is NEVER shown to the model, so the whole
  meaning must live in "instructions". Never write an instruction that depends on the id.
- Ask one narrow, coherent judgment per question. Split independent dimensions.
- For "choice", include an option that covers "none of these" whenever nothing may fit.
- "score" levels must describe concrete situations and stand on their own.
- Criteria describe what each answer means, not how to answer.

Respond with JSON only, no prose, in exactly this shape:

{
  "state": "a template describing what the model should read, may use $input.text",
  "questions": [
    {"id": "snake_case_id", "type": "noul", "instructions": "...",
     "criteria": {"true": "...", "false": "..."}},
    {"id": "...", "type": "choice", "instructions": "...",
     "criteria": {"option_key": "what this option means"}},
    {"id": "...", "type": "score", "instructions": "...",
     "criteria": ["lowest level", "middle level", "highest level"]}
  ]
}
"""


def extract_questions_payload(content: str) -> dict | None:
    """Pull the JSON object out of a model response that may be fenced or padded."""
    text = str(content or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    return parsed if isinstance(parsed, dict) else None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return slug or "question"


def normalize_generated_questions(
    raw_questions: Any, existing_ids: set[str]
) -> list[dict[str, Any]]:
    """Turn model output into panel rows, dropping anything unusable."""
    if not isinstance(raw_questions, list):
        return []
    taken = set(existing_ids)
    rows: list[dict[str, Any]] = []
    for raw in raw_questions:
        if not isinstance(raw, dict):
            continue
        question_type = str(raw.get("type") or "").strip()
        if question_type not in QUESTION_TYPES:
            continue
        instructions = str(raw.get("instructions") or "").strip()
        if not instructions:
            continue

        question_id = _slug(raw.get("id"))
        candidate = question_id
        suffix = 2
        while candidate in taken:
            candidate = f"{question_id}_{suffix}"
            suffix += 1
        taken.add(candidate)

        row: dict[str, Any] = {
            "id": candidate,
            "type": question_type,
            "instructions": instructions,
        }
        criteria = raw.get("criteria")
        if question_type == "noul" and isinstance(criteria, dict):
            row["criteriaTrue"] = str(criteria.get("true") or "").strip()
            row["criteriaFalse"] = str(criteria.get("false") or "").strip()
        elif question_type == "choice":
            if not isinstance(criteria, dict) or not criteria:
                continue
            row["options"] = [
                {"key": _slug(key), "description": str(value or "").strip()}
                for key, value in criteria.items()
            ]
        elif question_type == "score":
            levels = [str(level).strip() for level in criteria or [] if str(level).strip()]
            if len(levels) < 2:
                continue
            row["levels"] = levels
        rows.append(row)
    return rows


@router.post("/generate-questions", response_model=DecisionQuestionsSuggestionResponse)
async def generate_decision_questions(
    request: DecisionQuestionsGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DecisionQuestionsSuggestionResponse:
    """Draft decision questions from a plain-language intent."""
    # Imported lazily to avoid a circular import, matching data_tables.py.
    from app.api.ai_assistant import get_credential_for_user

    credential = await get_credential_for_user(request.credential_id, current_user, db)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="LLM credential not found"
        )
    if credential.type not in (
        CredentialType.openai,
        CredentialType.google,
        CredentialType.custom,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    config = decrypt_config(credential.encrypted_config)
    raw_base_url = config.get("base_url")

    user_message = f"Intent: {request.prompt.strip()}"
    if request.state_sample:
        user_message += f"\n\nExample state the node will receive:\n{request.state_sample}"
    if request.existing_question_ids:
        user_message += (
            "\n\nThese question ids already exist and must not be reused: "
            + ", ".join(request.existing_question_ids)
        )

    result = await execute_llm(
        credential_type=credential.type.value,
        api_key=str(config.get("api_key") or ""),
        base_url=str(raw_base_url) if raw_base_url else None,
        model=request.model,
        system_instruction=_SYSTEM_PROMPT,
        user_message=user_message,
        temperature=None if is_reasoning_model(request.model) else 0.2,
        extra_body={"disable_reasoning": True},
        trace_context=LLMTraceContext(
            user_id=current_user.id,
            credential_id=credential.id,
            source="decision_ai",
            node_label="AI Decision Questions",
        ),
        content_only=True,
    )

    payload = extract_questions_payload(str(result.get("text") or ""))
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not parse decision questions from the model response",
        )

    questions = normalize_generated_questions(
        payload.get("questions"), set(request.existing_question_ids)
    )
    if not questions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The model did not return any usable decision questions",
        )

    state = str(payload.get("state") or "").strip() or None
    return DecisionQuestionsSuggestionResponse(state=state, questions=questions)
```

- [ ] **Step 6: Register the router**

In `backend/app/main.py`, find how `data_tables` is included and add the same for
`decisions`:

```bash
grep -n "data_tables" backend/app/main.py
```

Then add, next to it:

```python
app.include_router(decisions.router, prefix="/api/decisions", tags=["decisions"])
```

and add `decisions` to the `from app.api import (...)` list.

- [ ] **Step 7: Run the tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_decision_question_generation.py -v
```

Expected: 11 passed.

- [ ] **Step 8: Verify the route is registered**

```bash
cd backend && uv run python -c "
from app.main import app
print([r.path for r in app.routes if 'decisions' in r.path])
"
```

Expected: `['/api/decisions/generate-questions']`

- [ ] **Step 9: Format, lint and commit**

```bash
cd backend && uv run ruff format app/ tests/ && uv run ruff check app/ tests/
git add backend/app/api/decisions.py backend/app/main.py backend/app/models/schemas.py backend/tests/test_decision_question_generation.py
git commit -m "feat(decision): draft decision questions from a plain-language intent

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: DSL prompt

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py`

Without this the AI Assistant cannot build a workflow that contains the node.

- [ ] **Step 1: Read the neighbouring node's section**

```bash
grep -n "maxToolIterations" -B 30 backend/app/services/workflow_dsl_prompt.py | head -45
```

Match the formatting of the surrounding node entries exactly.

- [ ] **Step 2: Add the decision node section**

Insert a section in the same style as its neighbours:

```
### decision
Ask a decision model (TypeSafe Jev and compatible endpoints) typed questions about a state.
It returns probabilities, not text. Fields:
  - `credentialId`: a `decision` credential (required)
  - `model`: model name, e.g. `jev-latest` (required)
  - `state`: what the model should read; expression-capable, default `$input.text`.
    A field holding one expression keeps its type, so `$input` sends an object.
  - `questions`: ordered array. Each entry:
      - `id`: snake_case key; the answer comes back under the same key. Never sent to
        the model, so the meaning must be complete in `instructions`.
      - `type`: `noul` | `choice` | `score`
      - `instructions`: the judgment to make; expression-capable
      - noul only: `criteriaTrue`, `criteriaFalse` — what yes and no mean (optional)
      - choice only: `options`: [{ `key`, `description` }] — at least one
      - score only: `levels`: ordered string array — at least two
  - `customBodyEnabled` / `customBody`: send a hand-written JSON body instead of the
    form, for endpoints with a different contract. Expression-capable.
  - `requestTimeoutSeconds`: default 60
Output is the provider response verbatim, so downstream nodes read
`$decisionLabel.answers.<id>.noul`, `.choice`, or `.score`.
```

- [ ] **Step 3: Verify the prompt still builds**

```bash
cd backend && uv run python -c "
from app.services.workflow_dsl_prompt import *
import app.services.workflow_dsl_prompt as m
src = [v for v in vars(m).values() if isinstance(v, str) and 'decision' in v]
print('decision documented:', bool(src))
"
```

Expected: `decision documented: True`

- [ ] **Step 4: Run the assistant prompt test**

```bash
cd backend && uv run pytest tests/test_build_assistant_prompt_node_templates.py -v
```

Expected: PASS. If it asserts a node count, update the expected number.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py backend/tests/
git commit -m "docs(dsl): document the decision node for the AI assistant

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: Frontend types and node definition

**Files:**
- Modify: `frontend/src/types/workflow.ts:194` (NodeType union) and `WorkflowNodeData`
- Modify: `frontend/src/types/node.ts` (NODE_DEFINITIONS)
- Modify: `frontend/src/components/Canvas/readonlyPreviewFields.ts`
- Modify: `frontend/src/types/credential.ts`
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Add the node type to the union**

In `frontend/src/types/workflow.ts`, in the `NodeType` union next to `| "rag"`:

```ts
  | "decision"
```

- [ ] **Step 2: Add the data fields**

In the same file, in `WorkflowNodeData`, next to `maxToolIterations?: number;`:

```ts
  /** Decision node: ordered question rows, serialised to a map at execution time. */
  questions?: DecisionQuestion[];
  customBodyEnabled?: boolean;
  customBody?: string;
  state?: string;
```

and above the interface:

```ts
export interface DecisionQuestionOption {
  key: string;
  description: string;
}

export interface DecisionQuestion {
  id: string;
  type: "noul" | "choice" | "score";
  instructions: string;
  /** noul */
  criteriaTrue?: string;
  /** noul */
  criteriaFalse?: string;
  /** choice */
  options?: DecisionQuestionOption[];
  /** score */
  levels?: string[];
}
```

Before adding `state`, check it is not already taken:

```bash
grep -n "  state?" frontend/src/types/workflow.ts
```

If it is used by another node with a different type, name the decision field
`decisionState` instead and use that name consistently everywhere below.

- [ ] **Step 3: Add the node definition**

In `frontend/src/types/node.ts`, in `NODE_DEFINITIONS`, after the `rag` entry:

```ts
  decision: {
    type: "decision",
    label: "Decision",
    description: "Ask a decision model typed questions and get probabilities back",
    color: "node-decision",
    icon: "Scale",
    inputs: 1,
    outputs: 1,
    defaultData: {
      label: "decision",
      credentialId: "",
      model: "",
      state: "$input.text",
      questions: [],
      customBodyEnabled: false,
      customBody: "",
      requestTimeoutSeconds: 60,
    },
  },
```

- [ ] **Step 4: Add the colour token**

Find how an existing node colour is defined and add `node-decision` alongside:

```bash
grep -rn "node-rag\|node-llm" frontend/src/assets frontend/tailwind.config.* frontend/src/style.css 2>/dev/null | head -5
```

Add a `node-decision` entry in the same place, using a hue not already taken.

- [ ] **Step 5: Add preview labels**

In `frontend/src/components/Canvas/readonlyPreviewFields.ts`, next to `maxToolIterations`:

```ts
  state: "State",
  questions: "Questions",
  customBody: "Request Body",
```

- [ ] **Step 6: Add the credential type label**

In `frontend/src/types/credential.ts`, add `decision` to the credential type union and add
to `CREDENTIAL_TYPE_LABELS`:

```ts
  decision: "Decision Model",
```

- [ ] **Step 7: Add the API client methods**

In `frontend/src/services/api.ts`, next to `listLLM`:

```ts
  listDecision: async (): Promise<CredentialListItem[]> => {
    const { data } = await client.get<CredentialListItem[]>("/credentials/decision");
    return data;
  },
```

and a new `decisionsApi`:

```ts
export const decisionsApi = {
  generateQuestions: async (payload: {
    prompt: string;
    credential_id: string;
    model: string;
    existing_question_ids?: string[];
    state_sample?: string;
  }): Promise<DecisionQuestionsSuggestion> => {
    const { data } = await client.post<DecisionQuestionsSuggestion>(
      "/decisions/generate-questions",
      payload,
    );
    return data;
  },
};
```

Match the exact client/axios idiom used by the neighbouring API objects in that file — read
`credentialsApi.listLLM` first and copy its shape.

Declare its response type in `frontend/src/types/workflow.ts`, next to `DecisionQuestion`:

```ts
export interface DecisionQuestionsSuggestion {
  state: string | null;
  questions: DecisionQuestion[];
}
```

- [ ] **Step 8: Typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: no errors. A missing `decision` case in an exhaustive `switch` over `NodeType`
will surface here — fix each one the compiler names.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/types frontend/src/services/api.ts frontend/src/components/Canvas/readonlyPreviewFields.ts
git commit -m "feat(decision): add frontend types and the node definition

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: Question rows editor

**Files:**
- Create: `frontend/src/components/Panels/propertiesPanel/nodes/DecisionQuestionsEditor.vue`

- [ ] **Step 1: Read a comparable editor**

```bash
sed -n '1,80p' frontend/src/components/Panels/propertiesPanel/nodes/RagNodeProperties.vue
```

Copy its import order (Vue → external → internal types → internal code), its
`<script setup lang="ts">` style, its explicit return types, and its use of
`ExpressionInput` for expression-capable fields.

- [ ] **Step 2: Write the component**

Create `frontend/src/components/Panels/propertiesPanel/nodes/DecisionQuestionsEditor.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";
import { ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-vue-next";

import type { DecisionQuestion, DecisionQuestionOption } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";

const props = defineProps<{
  questions: DecisionQuestion[];
  expanded: Record<string, boolean>;
}>();

const emit = defineEmits<{
  update: [questions: DecisionQuestion[]];
  toggle: [index: number];
}>();

const TYPE_OPTIONS = [
  { value: "noul", label: "Noul — does this hold?" },
  { value: "choice", label: "Choice — pick one" },
  { value: "score", label: "Score — rate on a scale" },
];

const rows = computed((): DecisionQuestion[] => props.questions ?? []);

function emitWith(mutate: (draft: DecisionQuestion[]) => void): void {
  const draft = rows.value.map((row) => ({ ...row }));
  mutate(draft);
  emit("update", draft);
}

function addQuestion(): void {
  emitWith((draft) => {
    draft.push({ id: `question_${draft.length + 1}`, type: "noul", instructions: "" });
  });
}

function removeQuestion(index: number): void {
  emitWith((draft) => {
    draft.splice(index, 1);
  });
}

function setField(index: number, key: keyof DecisionQuestion, value: unknown): void {
  emitWith((draft) => {
    (draft[index] as Record<string, unknown>)[key] = value;
  });
}

function setType(index: number, type: string): void {
  emitWith((draft) => {
    const row = draft[index];
    row.type = type as DecisionQuestion["type"];
    if (row.type === "choice" && !row.options?.length) {
      row.options = [{ key: "option_1", description: "" }];
    }
    if (row.type === "score" && (row.levels?.length ?? 0) < 2) {
      row.levels = ["", ""];
    }
  });
}

function setOption(index: number, optionIndex: number, patch: Partial<DecisionQuestionOption>): void {
  emitWith((draft) => {
    const options = [...(draft[index].options ?? [])];
    options[optionIndex] = { ...options[optionIndex], ...patch };
    draft[index].options = options;
  });
}

function addOption(index: number): void {
  emitWith((draft) => {
    const options = [...(draft[index].options ?? [])];
    options.push({ key: `option_${options.length + 1}`, description: "" });
    draft[index].options = options;
  });
}

function removeOption(index: number, optionIndex: number): void {
  emitWith((draft) => {
    const options = [...(draft[index].options ?? [])];
    options.splice(optionIndex, 1);
    draft[index].options = options;
  });
}

function setLevel(index: number, levelIndex: number, value: string): void {
  emitWith((draft) => {
    const levels = [...(draft[index].levels ?? [])];
    levels[levelIndex] = value;
    draft[index].levels = levels;
  });
}

function addLevel(index: number): void {
  emitWith((draft) => {
    draft[index].levels = [...(draft[index].levels ?? []), ""];
  });
}

function removeLevel(index: number, levelIndex: number): void {
  emitWith((draft) => {
    const levels = [...(draft[index].levels ?? [])];
    levels.splice(levelIndex, 1);
    draft[index].levels = levels;
  });
}

function duplicateIds(): Set<string> {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const row of rows.value) {
    const id = (row.id ?? "").trim();
    if (!id) continue;
    if (seen.has(id)) duplicates.add(id);
    seen.add(id);
  }
  return duplicates;
}

const duplicates = computed((): Set<string> => duplicateIds());
</script>

<template>
  <div class="space-y-2">
    <div class="flex items-center justify-between">
      <Label>Questions</Label>
      <Button
        variant="outline"
        size="sm"
        class="gap-1"
        @click="addQuestion"
      >
        <Plus class="h-3 w-3" /> Add
      </Button>
    </div>

    <p
      v-if="rows.length === 0"
      class="text-xs text-muted-foreground"
    >
      Add at least one question. The model answers each one about the state above.
    </p>

    <div
      v-for="(row, index) in rows"
      :key="index"
      class="rounded border border-input p-2 space-y-2"
    >
      <div class="flex items-center gap-2">
        <button
          type="button"
          class="text-muted-foreground"
          @click="emit('toggle', index)"
        >
          <ChevronDown
            v-if="expanded[String(index)]"
            class="h-4 w-4"
          />
          <ChevronRight
            v-else
            class="h-4 w-4"
          />
        </button>
        <Input
          :model-value="row.id"
          placeholder="question_id"
          class="flex-1"
          @update:model-value="setField(index, 'id', $event)"
        />
        <Select
          :model-value="row.type"
          :options="TYPE_OPTIONS"
          class="w-44"
          @update:model-value="setType(index, String($event))"
        />
        <Button
          variant="ghost"
          size="sm"
          @click="removeQuestion(index)"
        >
          <Trash2 class="h-3 w-3" />
        </Button>
      </div>

      <p
        v-if="duplicates.has((row.id ?? '').trim())"
        class="text-xs text-destructive"
      >
        Duplicate question id. Each id must be unique — answers come back keyed by it.
      </p>

      <template v-if="expanded[String(index)]">
        <div class="space-y-1">
          <Label class="text-xs">Instructions</Label>
          <slot
            name="instructions"
            :index="index"
            :row="row"
          />
        </div>

        <template v-if="row.type === 'noul'">
          <div class="space-y-1">
            <Label class="text-xs">Yes means</Label>
            <slot
              name="criteria-true"
              :index="index"
              :row="row"
            />
          </div>
          <div class="space-y-1">
            <Label class="text-xs">No means</Label>
            <slot
              name="criteria-false"
              :index="index"
              :row="row"
            />
          </div>
        </template>

        <template v-else-if="row.type === 'choice'">
          <div class="space-y-1">
            <div class="flex items-center justify-between">
              <Label class="text-xs">Options</Label>
              <Button
                variant="outline"
                size="sm"
                class="gap-1"
                @click="addOption(index)"
              >
                <Plus class="h-3 w-3" /> Option
              </Button>
            </div>
            <div
              v-for="(option, optionIndex) in row.options ?? []"
              :key="optionIndex"
              class="flex items-center gap-2"
            >
              <Input
                :model-value="option.key"
                placeholder="option_key"
                class="w-40"
                @update:model-value="setOption(index, optionIndex, { key: String($event) })"
              />
              <div class="flex-1">
                <slot
                  name="option-description"
                  :index="index"
                  :option-index="optionIndex"
                  :option="option"
                />
              </div>
              <Button
                variant="ghost"
                size="sm"
                @click="removeOption(index, optionIndex)"
              >
                <Trash2 class="h-3 w-3" />
              </Button>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="space-y-1">
            <div class="flex items-center justify-between">
              <Label class="text-xs">Levels (lowest first)</Label>
              <Button
                variant="outline"
                size="sm"
                class="gap-1"
                @click="addLevel(index)"
              >
                <Plus class="h-3 w-3" /> Level
              </Button>
            </div>
            <div
              v-for="(level, levelIndex) in row.levels ?? []"
              :key="levelIndex"
              class="flex items-center gap-2"
            >
              <span class="w-6 text-xs text-muted-foreground">{{ levelIndex }}</span>
              <Input
                :model-value="level"
                placeholder="What this level looks like"
                class="flex-1"
                @update:model-value="setLevel(index, levelIndex, String($event))"
              />
              <Button
                variant="ghost"
                size="sm"
                @click="removeLevel(index, levelIndex)"
              >
                <Trash2 class="h-3 w-3" />
              </Button>
            </div>
          </div>
        </template>
      </template>
    </div>
  </div>
</template>
```

The expression-capable fields come in through slots so the parent owns the
`ExpressionInput` refs the expression dialog needs for `1/n` navigation.

- [ ] **Step 3: Typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: no errors. If `Select`, `Input`, `Label` or `Button` live at different paths,
fix the imports to match `RagNodeProperties.vue`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Panels/propertiesPanel/nodes/DecisionQuestionsEditor.vue
git commit -m "feat(decision): add the question rows editor

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 10: Decision node properties panel

**Files:**
- Create: `frontend/src/components/Panels/propertiesPanel/nodes/DecisionNodeProperties.vue`
- Modify: `frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue`
- Modify: `frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts`

- [ ] **Step 1: Add controller state**

In `usePropertiesPanelController.ts`, next to `llmCredentials`:

```ts
  const decisionCredentials = ref<CredentialListItem[]>([]);
```

Load it where `llmCredentials.value = await credentialsApi.listLLM();` is loaded (around
line 1001), guarding the same way:

```ts
          decisionCredentials.value = await credentialsApi.listDecision();
```

Add the options computed and the expression-field count:

```ts
  const decisionCredentialOptions = computed(() =>
    decisionCredentials.value.map((c) => ({ value: c.id, label: c.name })),
  );

  /**
   * Expression slots in decision mode: the custom body alone when it is on, otherwise
   * State followed by each question's instructions and every criteria box, in row order.
   */
  const decisionExpressionFieldCount = computed((): number => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "decision") {
      return 1;
    }
    if (n.data.customBodyEnabled) {
      return 1;
    }
    let count = 1;
    for (const question of n.data.questions ?? []) {
      count += 1;
      if (question.type === "noul") {
        count += 2;
      } else if (question.type === "choice") {
        count += question.options?.length ?? 0;
      } else {
        count += question.levels?.length ?? 0;
      }
    }
    return count;
  });
```

Return `decisionCredentials`, `decisionCredentialOptions` and
`decisionExpressionFieldCount` from the composable alongside `outputTypeOptions`.

- [ ] **Step 2: Write the panel component**

Create `frontend/src/components/Panels/propertiesPanel/nodes/DecisionNodeProperties.vue`:

```vue
<script setup lang="ts">
import { computed, ref } from "vue";
import { Sparkles } from "lucide-vue-next";

import type { DecisionQuestion } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import DecisionAIQuestionsDialog from "@/components/Decision/DecisionAIQuestionsDialog.vue";
import DecisionQuestionsEditor from "./DecisionQuestionsEditor.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelContext";

const {
  selectedNode,
  updateNodeData,
  workflowStore,
  decisionCredentialOptions,
  decisionExpressionFieldCount,
} = usePropertiesPanelContext();

const expanded = ref<Record<string, boolean>>({ "0": true });
const aiDialogOpen = ref(false);

const questions = computed((): DecisionQuestion[] => selectedNode.value?.data.questions ?? []);
const customBodyEnabled = computed((): boolean => !!selectedNode.value?.data.customBodyEnabled);

function toggleRow(index: number): void {
  expanded.value = { ...expanded.value, [String(index)]: !expanded.value[String(index)] };
}

function updateQuestions(next: DecisionQuestion[]): void {
  updateNodeData("questions", next);
}

function updateInstructions(index: number, value: string): void {
  const next = questions.value.map((row, i) => (i === index ? { ...row, instructions: value } : row));
  updateNodeData("questions", next);
}

function updateCriteria(index: number, key: "criteriaTrue" | "criteriaFalse", value: string): void {
  const next = questions.value.map((row, i) => (i === index ? { ...row, [key]: value } : row));
  updateNodeData("questions", next);
}

function updateOptionDescription(index: number, optionIndex: number, value: string): void {
  const next = questions.value.map((row, i) => {
    if (i !== index) return row;
    const options = [...(row.options ?? [])];
    options[optionIndex] = { ...options[optionIndex], description: value };
    return { ...row, options };
  });
  updateNodeData("questions", next);
}

function applyGenerated(payload: { state: string | null; questions: DecisionQuestion[] }): void {
  if (payload.state) {
    updateNodeData("state", payload.state);
  }
  updateNodeData("questions", [...questions.value, ...payload.questions]);
  aiDialogOpen.value = false;
}

function toggleCustomBody(enabled: boolean): void {
  updateNodeData("customBodyEnabled", enabled);
  if (enabled && !selectedNode.value?.data.customBody) {
    updateNodeData(
      "customBody",
      JSON.stringify(
        {
          model: selectedNode.value?.data.model || "jev-latest",
          state: selectedNode.value?.data.state || "$input.text",
          questions: {},
        },
        null,
        2,
      ),
    );
  }
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="decisionCredentialOptions"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <p class="text-xs text-muted-foreground">
        A Decision Model credential. Decision models answer typed questions; they do not
        generate text.
      </p>
    </div>

    <div class="space-y-2">
      <Label>Model</Label>
      <Input
        :model-value="selectedNode.data.model || ''"
        placeholder="jev-latest"
        @update:model-value="updateNodeData('model', $event)"
      />
    </div>

    <template v-if="!customBodyEnabled">
      <div class="space-y-2">
        <Label>State</Label>
        <ExpressionInput
          :model-value="selectedNode.data.state || ''"
          placeholder="$input.text"
          :rows="4"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          expandable
          navigation-enabled
          :navigation-index="0"
          :navigation-total="decisionExpressionFieldCount"
          dialog-key-label="State"
          field-key="state"
          @update:model-value="updateNodeData('state', $event)"
        />
        <p class="text-xs text-muted-foreground">
          What the model should read. A field holding one expression keeps its type, so
          <code>$input</code> sends the object rather than its text.
        </p>
      </div>

      <div class="flex items-center justify-end">
        <Button
          variant="outline"
          size="sm"
          class="gap-1"
          @click="aiDialogOpen = true"
        >
          <Sparkles class="h-3 w-3" /> Generate with AI
        </Button>
      </div>

      <DecisionQuestionsEditor
        :questions="questions"
        :expanded="expanded"
        @update="updateQuestions"
        @toggle="toggleRow"
      >
        <template #instructions="{ index, row }">
          <ExpressionInput
            :model-value="row.instructions || ''"
            placeholder="Does this convey urgency?"
            :rows="2"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            expandable
            @update:model-value="updateInstructions(index, String($event))"
          />
        </template>
        <template #criteria-true="{ index, row }">
          <ExpressionInput
            :model-value="row.criteriaTrue || ''"
            placeholder="Explicitly time-sensitive"
            :rows="2"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            expandable
            @update:model-value="updateCriteria(index, 'criteriaTrue', String($event))"
          />
        </template>
        <template #criteria-false="{ index, row }">
          <ExpressionInput
            :model-value="row.criteriaFalse || ''"
            placeholder="No urgency expressed"
            :rows="2"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            expandable
            @update:model-value="updateCriteria(index, 'criteriaFalse', String($event))"
          />
        </template>
        <template #option-description="{ index, optionIndex, option }">
          <ExpressionInput
            :model-value="option.description || ''"
            placeholder="What this option means"
            :rows="1"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            expandable
            @update:model-value="updateOptionDescription(index, optionIndex, String($event))"
          />
        </template>
      </DecisionQuestionsEditor>
    </template>

    <div class="space-y-2 pt-2 border-t">
      <div class="flex items-center gap-2">
        <input
          id="decision-custom-body"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="customBodyEnabled"
          @change="toggleCustomBody(($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="decision-custom-body"
          class="text-sm font-normal"
        >
          Custom request body
        </Label>
      </div>
      <p class="text-xs text-muted-foreground">
        Send a hand-written JSON body instead of the form above. Use this for an endpoint
        whose contract differs from the one the form builds.
      </p>
    </div>

    <div
      v-if="customBodyEnabled"
      class="space-y-2"
    >
      <ExpressionInput
        :model-value="selectedNode.data.customBody || ''"
        :rows="12"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        expandable
        navigation-enabled
        :navigation-index="0"
        :navigation-total="1"
        dialog-key-label="Request Body"
        field-key="customBody"
        @update:model-value="updateNodeData('customBody', $event)"
      />
    </div>

    <div class="space-y-2 pt-2 border-t">
      <Label>Request Timeout (seconds)</Label>
      <Input
        type="number"
        :model-value="String(selectedNode.data.requestTimeoutSeconds ?? 60)"
        min="1"
        max="3600"
        placeholder="60"
        @update:model-value="updateNodeData('requestTimeoutSeconds', parseInt($event, 10) || 60)"
      />
    </div>

    <DecisionAIQuestionsDialog
      v-if="aiDialogOpen"
      :existing-question-ids="questions.map((q) => q.id)"
      :state-sample="selectedNode.data.state || ''"
      @applied="applyGenerated"
      @close="aiDialogOpen = false"
    />
  </template>
</template>
```

Before writing this, check how sibling node panels obtain `selectedNode`, `updateNodeData`
and `workflowStore` — some use a context composable, some use props:

```bash
sed -n '1,30p' frontend/src/components/Panels/propertiesPanel/nodes/RagNodeProperties.vue
```

Use whichever mechanism that file uses; the import line above is a placeholder for it.
`SearchableSelect` is imported but unused if you keep a free-text model field — remove the
import rather than leaving it, since `noUnusedLocals` is on.

- [ ] **Step 3: Mount the component**

In `frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue`, add the
import next to the others:

```ts
import DecisionNodeProperties from "./DecisionNodeProperties.vue";
```

and the branch next to the `rag` one:

```vue
  <DecisionNodeProperties v-else-if="selectedNode?.type === 'decision'" />
```

- [ ] **Step 4: Typecheck and lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Panels/propertiesPanel/
git commit -m "feat(decision): add the decision node properties panel

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 11: AI question generation dialog

**Files:**
- Create: `frontend/src/components/Decision/DecisionAIQuestionsDialog.vue`

- [ ] **Step 1: Read the dialog you are copying**

```bash
sed -n '1,120p' frontend/src/components/DataTable/DataTableAISchemaDialog.vue
sed -n '240,330p' frontend/src/components/DataTable/DataTableAISchemaDialog.vue
```

Reuse its `phase: "input" | "review"` flow, its Escape handling, its credential/model
selection and its error surface.

- [ ] **Step 2: Write the component**

Create `frontend/src/components/Decision/DecisionAIQuestionsDialog.vue`:

```vue
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { Loader2, Sparkles } from "lucide-vue-next";

import type { DecisionQuestion } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { useChatModelSelection } from "@/composables/useChatModelSelection";
import { decisionsApi } from "@/services/api";

const props = defineProps<{
  existingQuestionIds: string[];
  stateSample: string;
}>();

const emit = defineEmits<{
  applied: [payload: { state: string | null; questions: DecisionQuestion[] }];
  close: [];
}>();

const {
  credentialOptions,
  modelOptions,
  selectedCredentialId,
  selectedModel,
  modelPlaceholder,
  bootstrap,
  selectCredential,
} = useChatModelSelection();

const phase = ref<"input" | "review">("input");
const prompt = ref("");
const generating = ref(false);
const error = ref("");
const draftState = ref<string | null>(null);
const draftQuestions = ref<DecisionQuestion[]>([]);

function handleEscape(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.stopPropagation();
    emit("close");
  }
}

onMounted(() => {
  window.addEventListener("keydown", handleEscape, true);
  void bootstrap();
});
onBeforeUnmount(() => window.removeEventListener("keydown", handleEscape, true));

async function generate(): Promise<void> {
  if (!prompt.value.trim() || !selectedCredentialId.value || !selectedModel.value) return;
  generating.value = true;
  error.value = "";
  try {
    const result = await decisionsApi.generateQuestions({
      prompt: prompt.value.trim(),
      credential_id: selectedCredentialId.value,
      model: selectedModel.value,
      existing_question_ids: props.existingQuestionIds,
      state_sample: props.stateSample || undefined,
    });
    draftState.value = result.state ?? null;
    draftQuestions.value = result.questions;
    phase.value = "review";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Could not generate questions";
  } finally {
    generating.value = false;
  }
}

function apply(): void {
  emit("applied", { state: draftState.value, questions: draftQuestions.value });
}

function describe(question: DecisionQuestion): string {
  if (question.type === "choice") {
    return (question.options ?? []).map((option) => option.key).join(", ");
  }
  if (question.type === "score") {
    return (question.levels ?? []).join(" → ");
  }
  return `${question.criteriaTrue || "yes"} / ${question.criteriaFalse || "no"}`;
}
</script>

<template>
  <Dialog @close="emit('close')">
    <div class="space-y-4 p-4">
      <div class="flex items-center gap-2">
        <Sparkles class="h-4 w-4 text-primary" />
        <h2 class="text-sm font-medium">
          Generate decision questions
        </h2>
      </div>

      <template v-if="phase === 'input'">
        <div class="space-y-2">
          <Label>What should the model judge?</Label>
          <Textarea
            v-model="prompt"
            :rows="5"
            placeholder="Triage an incoming support ticket: how urgent it is, which team owns it, and how frustrated the customer sounds."
          />
        </div>
        <div class="grid grid-cols-2 gap-2">
          <SearchableSelect
            :model-value="selectedCredentialId"
            :options="credentialOptions"
            placeholder="Select credential..."
            @update:model-value="selectCredential(String($event))"
          />
          <SearchableSelect
            v-model="selectedModel"
            :options="modelOptions"
            :placeholder="modelPlaceholder"
          />
        </div>
        <p class="text-xs text-muted-foreground">
          An LLM drafts the questions. The decision model then answers them at run time.
        </p>
      </template>

      <template v-else>
        <div
          v-if="draftState"
          class="space-y-1"
        >
          <Label class="text-xs">Suggested state</Label>
          <p class="rounded bg-muted p-2 text-xs">
            {{ draftState }}
          </p>
        </div>
        <div class="space-y-2">
          <Label class="text-xs">Questions</Label>
          <div
            v-for="question in draftQuestions"
            :key="question.id"
            class="rounded border border-input p-2 text-xs space-y-1"
          >
            <div class="flex items-center gap-2">
              <span class="font-medium">{{ question.id }}</span>
              <span class="rounded bg-muted px-1">{{ question.type }}</span>
            </div>
            <p>{{ question.instructions }}</p>
            <p class="text-muted-foreground">
              {{ describe(question) }}
            </p>
          </div>
        </div>
      </template>

      <p
        v-if="error"
        class="text-xs text-destructive"
      >
        {{ error }}
      </p>

      <div class="flex justify-end gap-2">
        <Button
          variant="outline"
          @click="emit('close')"
        >
          Cancel
        </Button>
        <Button
          v-if="phase === 'input'"
          :disabled="generating || !prompt.trim() || !selectedCredentialId || !selectedModel"
          @click="generate"
        >
          <Loader2
            v-if="generating"
            class="mr-1 h-3 w-3 animate-spin"
          />
          Generate
        </Button>
        <template v-else>
          <Button
            variant="outline"
            @click="phase = 'input'"
          >
            Back
          </Button>
          <Button @click="apply">
            Add {{ draftQuestions.length }} question(s)
          </Button>
        </template>
      </div>
    </div>
  </Dialog>
</template>
```

Check `useChatModelSelection`'s actual exported names before relying on them:

```bash
grep -n "return {" -A 20 frontend/src/composables/useChatModelSelection.ts
```

Adjust the destructuring to match; do not invent names.

- [ ] **Step 3: Typecheck and lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Decision/
git commit -m "feat(decision): add the AI question generation dialog

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 12: Credential dialog form

**Files:**
- Modify: `frontend/src/components/Credentials/CredentialDialog.vue`

- [ ] **Step 1: Add the type option**

Near line 252, next to the `rag` entry:

```ts
  { value: "decision", label: CREDENTIAL_TYPE_LABELS.decision },
```

- [ ] **Step 2: Add the refs**

Next to the other type-specific refs:

```ts
const decisionBaseUrl = ref("https://api.typesafe.ai");
const decisionApiKey = ref("");
```

- [ ] **Step 3: Populate them when editing**

In the block that reads `credential.public_fields` (around line 272), add:

```ts
  if (credential?.type === "decision") {
    decisionBaseUrl.value = String(credential.public_fields?.base_url ?? "https://api.typesafe.ai");
    decisionApiKey.value = "";
  }
```

- [ ] **Step 4: Add validation**

In the `canSave` computed (around line 635), next to the `rag` branch:

```ts
  } else if (type.value === "decision") {
    return !!name.value.trim() && !!decisionBaseUrl.value.trim();
```

- [ ] **Step 5: Add the payload**

In the payload builder (around line 884), next to the `rag` branch:

```ts
  } else if (type.value === "decision") {
    config = {
      base_url: decisionBaseUrl.value.trim(),
      api_key: decisionApiKey.value.trim(),
    };
```

- [ ] **Step 6: Add the form fields**

Next to the `v-if="type === 'rag'"` block (around line 2912):

```vue
      <template v-if="type === 'decision'">
        <div class="space-y-2">
          <Label for="cred-decision-base-url">Base URL</Label>
          <Input
            id="cred-decision-base-url"
            v-model="decisionBaseUrl"
            placeholder="https://api.typesafe.ai"
          />
          <p class="text-xs text-muted-foreground">
            The decision model endpoint. Heym appends <code>/v1/systemone</code>.
          </p>
        </div>
        <div class="space-y-2">
          <Label for="cred-decision-api-key">API Key (optional)</Label>
          <Input
            id="cred-decision-api-key"
            v-model="decisionApiKey"
            type="password"
            placeholder="Leave blank for an endpoint that needs no key"
          />
        </div>
      </template>
```

- [ ] **Step 7: Include it in the "has a secret" branch**

Line 1662 lists the types whose dialog behaves a certain way — read that condition and add
`type.value === "decision"` if and only if the surrounding logic applies (it gates whether
a blank secret field means "keep the stored value"). Read the condition before editing:

```bash
sed -n '1655,1670p' frontend/src/components/Credentials/CredentialDialog.vue
```

- [ ] **Step 8: Typecheck, lint and commit**

```bash
cd frontend && bun run typecheck && bun run lint
git add frontend/src/components/Credentials/CredentialDialog.vue
git commit -m "feat(credentials): add the decision credential form

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 13: Traces source filter

**Files:**
- Modify: `frontend/src/components/Traces/TracesPanel.vue:44` and `:352`

- [ ] **Step 1: Add the label**

In `TRACE_SOURCE_LABELS`, next to `data_table_ai`:

```ts
  decision_ai: "Decision Questions",
```

- [ ] **Step 2: Add the filter option**

In the source options array around line 352, next to the `data_table_ai` entry:

```ts
  { value: "decision_ai", label: TRACE_SOURCE_LABELS.decision_ai },
```

- [ ] **Step 3: Verify**

```bash
cd frontend && bun run typecheck
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Traces/TracesPanel.vue
git commit -m "feat(traces): surface decision question generation as a filterable source

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 14: Agent max tool iterations input

**Files:**
- Modify: `frontend/src/components/Panels/propertiesPanel/nodes/AgentNodeProperties.vue:474-487`

The field already exists everywhere else — defaults, types, DSL prompt, executor, canvas
preview labels. Only the input is missing.

- [ ] **Step 1: Add the input**

Immediately after the Tool Timeout block (which ends at line 487 with `</div>`), add:

```vue
    <div class="space-y-2 pt-2 border-t">
      <Label>Max Tool Iterations</Label>
      <Input
        type="number"
        :model-value="String(selectedNode.data.maxToolIterations ?? 30)"
        min="1"
        placeholder="30"
        @update:model-value="updateNodeData('maxToolIterations', parseInt($event, 10) || 30)"
      />
      <p class="text-xs text-muted-foreground">
        How many tool-call rounds the agent may take before it must answer
      </p>
    </div>
```

No `max` attribute. The executor applies no ceiling —
`int(node_data.get("maxToolIterations") or 30)` at `workflow_executor.py:4854` — so the UI
must not invent one.

- [ ] **Step 2: Verify the field is inside the same `v-if` as Tool Timeout**

```bash
sed -n '465,505p' frontend/src/components/Panels/propertiesPanel/nodes/AgentNodeProperties.vue
```

Tool Timeout sits inside a conditional block (tools present). Max Tool Iterations applies
to any agent with tools, sub-agents, MCP connections or skills, so place it in the same
block as Tool Timeout — a loop cap is meaningless without something to loop over.

- [ ] **Step 3: Typecheck and lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Panels/propertiesPanel/nodes/AgentNodeProperties.vue
git commit -m "feat(agent): expose max tool iterations in the node panel

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 15: Documentation

**Files:**
- Create: `frontend/src/docs/content/nodes/decision-node.md`
- Modify: `frontend/src/docs/manifest.ts`
- Modify: `frontend/src/docs/content/reference/features.md`
- Modify: `frontend/src/docs/content/reference/node-types.md`
- Modify: `frontend/src/docs/content/reference/integrations.md`
- Modify: `frontend/src/docs/content/reference/credentials.md`
- Modify: `frontend/src/docs/content/reference/credentials-sharing.md`

- [ ] **Step 1: Invoke the documentation skill**

This repo requires it for medium/large features:

```
Skill: heym-documentation
```

Follow whatever it specifies; the steps below are the content it needs.

- [ ] **Step 2: Write the node page**

Create `frontend/src/docs/content/nodes/decision-node.md` covering: what a decision model
is and that it does not generate text; the three question types with one example each;
the State field and its type preservation; the Questions editor; the Custom request body
escape hatch; what the output looks like and how to read it with expressions; the
`decision` credential; that cost stays empty in Traces unless a pricing override is added;
and a worked example that routes a `switch` node on `$decision.answers.department.choice`.

- [ ] **Step 3: Register it in the manifest**

In `frontend/src/docs/manifest.ts`, in the nodes category next to `{ slug: "rag-node", ... }`:

```ts
      { slug: "decision-node", title: "Decision" },
```

- [ ] **Step 4: Update the reference docs**

In `frontend/src/docs/content/reference/features.md`:
- Add a `#### [Decision](../nodes/decision-node.md)` section describing the node.
- Add it to the AI-nodes enumeration in the node-types summary paragraph (line 427).
- Add "Decision Model" to the credential types sentence (line 656).

In `reference/node-types.md`, add an entry under `## AI Nodes`.

In `reference/integrations.md`, `reference/credentials.md` and
`reference/credentials-sharing.md`, add the `decision` credential with its `base_url` and
optional `api_key` fields.

- [ ] **Step 5: Verify the docs build**

```bash
cd frontend && bun run build
```

Expected: build succeeds. A manifest slug with no matching file fails here.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/docs/
git commit -m "docs: document the decision node and credential

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 16: Release tour

**Files:**
- Modify: `frontend/src/features/release-tour/releaseRegistry.ts`
- Create: `frontend/src/features/release-tour/components/visuals/DecisionNodeTourVisual.vue`
- Modify: `frontend/src/features/release-tour/tourVisuals.ts`

- [ ] **Step 1: Add the release entry**

In `frontend/src/features/release-tour/releaseRegistry.ts`, as the **first** element of
`RELEASE_REGISTRY` (newest first), above the `2026.12` entry:

```ts
  {
    releaseId: "2026.13",
    publishedAt: new Date("2026-09-21T00:00:00Z"),
    headline: "Ask a model for a decision, not an essay",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: false,
      sectionOrder: ["decision-node"],
    },
    sections: [
      {
        id: "decision-node",
        title: "Get a typed answer instead of a paragraph",
        publishedAt: new Date("2026-09-21T10:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "The new **Decision** node asks a decision model typed questions about whatever the run has produced so far. You give it a **state** — a ticket, a diff, a form submission — and a list of questions, and it answers each one with a probability rather than a paragraph you then have to parse.",
          },
          {
            type: "prose",
            markdown:
              "Questions come in three shapes. **Noul** asks whether a condition holds and returns how likely a yes is. **Choice** picks one option from a set you define and shows the full distribution. **Score** rates the state along levels you write, and can land between them. Every answer carries its own numbers, so a Switch node can branch on the answer and a Condition node can gate on how confident it was.",
          },
          {
            type: "prose",
            markdown:
              "Write the questions yourself, or describe what you want judged and let **Generate with AI** draft them. If your endpoint speaks a different contract, turn on **Custom request body** and send the JSON you need. Connect it with a Decision Model credential pointing at a hosted or self-hosted endpoint.",
          },
        ],
        tour: {
          description:
            "Ask a model typed questions about the run's state and branch on the answer instead of parsing prose.",
          useCases: [
            "Route a ticket to the right team and branch on how confident the call was",
            "Score how risky a change looks before a step that cannot be undone",
            "Draft the questions from a plain sentence with Generate with AI",
          ],
          tourVisual: "decision-node",
          docTarget: {
            categoryId: "nodes",
            slug: "decision-node",
            title: "Decision",
          },
        },
      },
    ],
  },
```

`tourEnabled` stays `false` until the release commit. The registry still renders release
notes while it is off; the flag only gates the automatic popup.

- [ ] **Step 2: Build the visual**

Create `frontend/src/features/release-tour/components/visuals/DecisionNodeTourVisual.vue`.
Read an existing one first and match its conventions:

```bash
cat frontend/src/features/release-tour/components/visuals/ResponsesApiTourVisual.vue
```

Rules: Tailwind semantic tokens only, mock UI never live UI, no production API calls, no
host-page state. Animate with CSS transitions, Vue `<Transition>`, and `useCycleStep` for
looping demo states. No motion library.

Show a small mock panel with three question rows cycling through their answers: a noul
filling toward 0.95, a choice bar chart resolving to one option, and a score marker sliding
between levels.

- [ ] **Step 3: Register the visual**

In `frontend/src/features/release-tour/tourVisuals.ts`, add the import in alphabetical
position and the map entry:

```ts
import DecisionNodeTourVisual from "@/features/release-tour/components/visuals/DecisionNodeTourVisual.vue";
```

```ts
  "decision-node": DecisionNodeTourVisual,
```

- [ ] **Step 4: Run the registry guard**

```bash
cd frontend && bun run test -- releaseTourMapper
```

Expected: PASS. This test fails when a `tourVisual` key has no registered component or a
section is missing from `sectionOrder`.

- [ ] **Step 5: Typecheck and commit**

```bash
cd frontend && bun run typecheck
git add frontend/src/features/release-tour/
git commit -m "feat(release-tour): announce the decision node

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 17: Connection test for the decision credential

**Files:**
- Modify: `backend/app/api/credentials.py:925-1000` (the allow-list and the per-type branch)
- Modify: `frontend/src/components/Credentials/CredentialDialog.vue` (enable the button)
- Test: `backend/tests/test_decision_credentials.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_decision_credentials.py`:

```python
import unittest.mock as mock

from app.api.credentials import _test_decision_endpoint


class DecisionCredentialConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_successful_probe_reports_success(self) -> None:
        with mock.patch(
            "app.api.credentials.call_decision_model",
            return_value={"answers": {"probe": {"type": "noul", "noul": 0.5}}},
        ):
            result = await _test_decision_endpoint(
                {"base_url": "https://api.typesafe.ai", "api_key": "sk-test"}, model="jev-latest"
            )
        self.assertTrue(result.success)

    async def test_a_rejected_key_reports_the_reason(self) -> None:
        from app.services.decision_models import DecisionProviderError

        with mock.patch(
            "app.api.credentials.call_decision_model",
            side_effect=DecisionProviderError("Decision model rejected the API key"),
        ):
            result = await _test_decision_endpoint(
                {"base_url": "https://api.typesafe.ai", "api_key": "bad"}, model="jev-latest"
            )
        self.assertFalse(result.success)
        self.assertIn("API key", result.message)

    async def test_the_probe_sends_exactly_one_question(self) -> None:
        with mock.patch(
            "app.api.credentials.call_decision_model", return_value={"answers": {}}
        ) as call:
            await _test_decision_endpoint(
                {"base_url": "https://api.typesafe.ai", "api_key": "sk-test"}, model="jev-latest"
            )
        body = call.call_args.kwargs["body"]
        self.assertEqual(len(body["questions"]), 1)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && uv run pytest tests/test_decision_credentials.py -k Connection -v
```

Expected: FAIL with `ImportError: cannot import name '_test_decision_endpoint'`.

- [ ] **Step 3: Add the probe helper**

In `backend/app/api/credentials.py`, next to `_test_rag_embedding_endpoint`:

```python
async def _test_decision_endpoint(config: dict, model: str) -> CredentialTestResponse:
    """Send the smallest possible evaluation to prove the endpoint and key work."""
    import anyio

    from app.services.decision_models import (
        DecisionProviderError,
        DecisionRequestError,
        call_decision_model,
    )

    body = {
        "model": (model or "").strip() or "jev-latest",
        "state": "Connection test from Heym.",
        "questions": {
            "probe": {"type": "noul", "instructions": "Is this a connection test?"}
        },
    }
    try:
        await anyio.to_thread.run_sync(
            lambda: call_decision_model(
                base_url=str(config.get("base_url") or ""),
                api_key=str(config.get("api_key") or ""),
                body=body,
                timeout=15.0,
                trace_context=None,
            )
        )
    except (DecisionProviderError, DecisionRequestError) as exc:
        return CredentialTestResponse(success=False, message=str(exc))
    except Exception as exc:  # noqa: BLE001 - the button reports whatever went wrong
        return CredentialTestResponse(success=False, message=f"Connection failed: {exc}")
    return CredentialTestResponse(success=True, message="Decision endpoint reachable")
```

Add `call_decision_model` to the module's imports so the test can patch
`app.api.credentials.call_decision_model`. Check `CredentialTestResponse`'s real field
names first:

```bash
grep -n "class CredentialTestResponse" -A 6 backend/app/models/schemas.py
```

Use its actual fields; adjust the test's assertions only if the field names differ.

- [ ] **Step 4: Wire it into the test endpoint**

In `test_credential_connection`, add `CredentialType.decision` to the allow-list set at
line 929, add the stored-config merge next to the `rag` branch:

```python
        elif test_data.type == CredentialType.decision:
            config = {**stored_config, **{k: v for k, v in config.items() if v not in (None, "")}}
```

and dispatch before the generic `validate_credential_config` call, mirroring how `rag` does:

```python
    if test_data.type == CredentialType.decision:
        validate_credential_config(test_data.type, config)
        return await _test_decision_endpoint(config, str(test_data.config.get("model") or ""))
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_decision_credentials.py -v
```

Expected: 9 passed.

- [ ] **Step 6: Enable the button in the dialog**

In `frontend/src/components/Credentials/CredentialDialog.vue`, find the condition that
decides whether the Test Connection button renders and add `decision` to it:

```bash
grep -n "Test Connection\|canTestConnection\|testSupported" frontend/src/components/Credentials/CredentialDialog.vue | head -5
```

Include the model name in the test payload so the probe uses the same model the node will.

- [ ] **Step 7: Format, lint and commit**

```bash
cd backend && uv run ruff format app/api/credentials.py tests/test_decision_credentials.py && uv run ruff check app/api/credentials.py tests/test_decision_credentials.py
cd ../frontend && bun run typecheck && bun run lint
cd .. && git add backend/app/api/credentials.py backend/tests/test_decision_credentials.py frontend/src/components/Credentials/CredentialDialog.vue
git commit -m "feat(credentials): test a decision credential from the dialog

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 18: Full verification

- [ ] **Step 1: Run the backend suite**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh
```

Expected: ruff format applies cleanly, ruff check passes, frontend lint and typecheck pass,
and the backend suite is green. Fix anything it reports and re-run until clean.

- [ ] **Step 2: Run the frontend unit tests**

```bash
cd frontend && bun run test
```

Expected: PASS. `./check.sh` does not include these, but CI does.

- [ ] **Step 3: Commit any formatting-only diffs**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && git status --short
git add -A && git commit -m "style: apply ruff format after the decision node work

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

Skip this step if the tree is clean.

- [ ] **Step 4: Manual smoke test**

```bash
./run.sh
```

Then, in the browser:

1. Credentials tab → New → Decision Model → base URL + key → Save.
2. Editor → drag a Decision node onto the canvas → connect an Input node to it.
3. Select it → pick the credential → model `jev-latest` → leave State as `$input.text`.
4. Click **Generate with AI**, describe a triage task, review, Apply.
5. Double-click the node and confirm the expression dialog walks `1/n` through State,
   instructions and criteria.
6. Run the workflow and confirm the output contains `answers` with one entry per question.
7. Traces tab → filter source **Decision Questions** → confirm the generation call is there;
   clear the filter and confirm the run's `decision.systemone` trace is there too.
8. Agent node → confirm **Max Tool Iterations** appears next to Tool Timeout, accepts 500,
   and shows no upper-bound validation.

- [ ] **Step 5: Confirm nothing was pushed**

```bash
git status -sb | head -1
```

Expected: a line showing local commits ahead of origin. **Do not push.** Leave the branch
ahead until the user asks.

---

## Self-review notes

Checked against the spec:

- Node identity, data model, placement — Tasks 5, 8.
- Panel, question editor, custom body, `1/n` expression fields — Tasks 9, 10.
- Body construction, state typing, validation — Task 3.
- SSRF guard, headers, timeout, error mapping, trace, pass-through — Task 4.
- `decision` credential with migration, validation, masking, listing, form — Tasks 1, 2, 12.
- Question generation endpoint and dialog, `decision_ai` trace source — Tasks 6, 11, 13.
- DSL prompt — Task 7.
- Docs — Task 15. Release tour — Task 16.
- Agent `maxToolIterations` with no upper bound — Task 14.
- Backend tests — Tasks 2, 3, 4, 5, 6. No frontend UI tests, per repo preference.

- Test Connection for the decision credential — Task 17. It is last because the credential
  test endpoint has a closed allow-list and a per-type merge branch, so it depends on the
  provider module from Task 4 but nothing depends on it.
