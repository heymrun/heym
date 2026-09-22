# Model Router Credential Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **NO COMMITS.** The repository owner has asked that this work stay as an uncommitted local diff. Do not run `git commit`, `git branch`, `git stash` or `git push` at any point. Every task ends with a verification step instead of a commit step. If a skill instructs you to commit, that instruction is overridden here.

**Goal:** Add a `model_router` credential that uses a decision model to pick which model serves each request, and show both the router and the model it chose in Traces, the Execution Log and the Execution Span View.

**Architecture:** The router is a credential, not a node setting. `GET /credentials/llm` returns it alongside `openai`/`google`/`custom`, and `GET /credentials/{id}/models` returns one synthetic `auto` model for it, so every existing LLM picker gets it without per-surface code. Routing itself happens inside `LLMService`: a new `_resolve_turn()` replaces the single `_get_client()` call that today binds a client before the tool loop, so each provider request can bind a different credential and model.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 async + Alembic + pytest; Vue 3 `<script setup>` + TypeScript strict + Vitest.

**Spec:** `docs/superpowers/specs/2026-09-22-model-router-credential-design.md`

---

## Conventions for every task

Backend tests run from `backend/`:

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_x.py -v
```

`HEYM_OTEL_ENABLED=false` is required: a local `.env` with OTel on and no collector makes pytest hang forever.

Frontend checks run from `frontend/`:

```bash
cd frontend && bun run lint && bun run typecheck && bun run test
```

Python style: type hints everywhere including returns, docstrings on public functions, Ruff format (line length 100, double quotes). TypeScript: strict, explicit return types, `interface` over `type` for objects, `const` over `let`.

---

## File Structure

### Backend — new files

| File | Responsibility |
| --- | --- |
| `backend/app/services/model_router.py` | The only module that knows the router config shape. Config parsing and validation, decision-state building, the `ModelRouter` runtime class, option credential loading. |
| `backend/alembic/versions/124_add_model_router_cred_type.py` | `ALTER TYPE credential_type ADD VALUE 'model_router'`. |
| `backend/alembic/versions/125_llm_trace_router_columns.py` | `llm_traces.router_credential_id`, `llm_traces.router_label`. |
| `backend/tests/test_model_router.py` | Config validation, state building, routing, fallback, caching. |
| `backend/tests/test_model_router_credentials.py` | Credentials API surface. |
| `backend/tests/test_model_router_llm_service.py` | Per-turn routing, tracing, rejections. |
| `backend/tests/test_advisory_model_router_sharing.py` | Secret boundary of the transitive grant. |

### Backend — modified files

| File | Change |
| --- | --- |
| `backend/app/db/models.py` | `CredentialType.model_router`; two `LLMTrace` columns. |
| `backend/app/services/llm_trace.py` | Router fields on `LLMTraceContext`; persist them. |
| `backend/app/services/llm_service.py` | `TurnBinding`, `_resolve_turn`, per-turn binding, rejections, `router` params. |
| `backend/app/api/credentials.py` | Validation, `public_fields`, masked value, `/llm`, `/models`, `/test`. |
| `backend/app/api/traces.py` | Return and search the new columns. |
| `backend/app/models/schemas.py` | Router fields on trace response models. |
| `backend/app/services/workflow_executor.py` | Build the router in the `llm` and `agent` paths; pack `metadata.model_routing`. |
| `backend/app/services/workflow_dsl_prompt.py` | One paragraph telling the assistant Auto Model exists. |

### Frontend — new files

| File | Responsibility |
| --- | --- |
| `frontend/src/components/Credentials/modelRouter/ModelRouterFields.vue` | Decision credential, decision model, routing instructions, sharing notice. |
| `frontend/src/components/Credentials/modelRouter/ModelRouterOptionsEditor.vue` | The option rows. |
| `frontend/src/components/Credentials/modelRouter/modelRouterConfig.ts` | Pure config shape + client-side validation, shared by the two components. |
| `frontend/src/components/Credentials/modelRouter/modelRouterConfig.test.ts` | Vitest for the above. |
| `frontend/src/features/release-tour/components/visuals/ModelRouterTourVisual.vue` | Animated mock for the tour. |

### Frontend — modified files

| File | Change |
| --- | --- |
| `frontend/src/types/credential.ts` | `model_router` type, label, description, trace router fields. |
| `frontend/src/components/ui/Select.vue` | Optional per-option `disabled`. |
| `frontend/src/components/Credentials/CredentialDialog.vue` | Type entry, child components, conditional width, save/reset wiring. |
| `frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts` | Disable router options when the Responses API is on. |
| `frontend/src/components/Panels/propertiesPanel/useResponsesApiCapability.ts` | Router-specific message. |
| `frontend/src/components/Traces/TracesPanel.vue` | `Router / Model` in list and detail. |
| `frontend/src/components/Panels/DebugPanel.vue` | Routing chip on the node row. |
| `frontend/src/components/Panels/executionTimeline.ts` | `modelRouting` on `SpanItem`. |
| `frontend/src/components/Panels/ExecutionSpanDetails.vue` | Model cell and per-turn list. |
| `frontend/src/lib/executionLog.ts` | Read routing off node metadata. |
| `frontend/src/features/release-tour/releaseRegistry.ts` | `2026.14` entry. |
| `frontend/src/features/release-tour/tourVisuals.ts` | Register the visual. |
| `frontend/e2e/support.ts` | Realign the seeded tour id. |

---

# Phase 1 — Credential type and config

## Task 1: Add the `model_router` credential type

**Files:**
- Modify: `backend/app/db/models.py:64`
- Create: `backend/alembic/versions/124_add_model_router_cred_type.py`
- Test: `backend/tests/test_alembic_migrations.py`

- [ ] **Step 1: Add the enum member**

In `backend/app/db/models.py`, directly after the `decision = "decision"` line inside `class CredentialType(str, PyEnum)`:

```python
    decision = "decision"
    model_router = "model_router"
```

- [ ] **Step 2: Write the migration**

Create `backend/alembic/versions/124_add_model_router_cred_type.py`:

```python
"""add model router credential type

Revision ID: 124_add_model_router_cred
Revises: 123_add_decision_cred_type
Create Date: 2026-09-22 00:00:00.000000

Note: alembic_version.version_num is varchar(32), so the revision id must stay
within 32 characters.

"""

from typing import Sequence, Union

from alembic import op

revision: str = "124_add_model_router_cred"
down_revision: Union[str, None] = "123_add_decision_cred_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'model_router'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
```

- [ ] **Step 3: Run the migration chain test**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_alembic_migrations.py -v
```

Expected: PASS. This test walks the revision chain, so a wrong `down_revision` or a revision id over 32 characters fails here. `"124_add_model_router_cred"` is 25 characters.

- [ ] **Step 4: Apply the migration to the dev database**

```bash
cd backend && uv run alembic upgrade head
```

Expected: `Running upgrade 123_add_decision_cred_type -> 124_add_model_router_cred`.

- [ ] **Step 5: Verify**

```bash
cd backend && uv run ruff format . && uv run ruff check app/db/models.py alembic/versions/124_add_model_router_cred_type.py
```

Expected: no errors.

---

## Task 2: Router config parsing and validation

This is pure logic with no I/O. Write the tests first.

**Files:**
- Create: `backend/app/services/model_router.py`
- Test: `backend/tests/test_model_router.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_model_router.py`:

```python
import unittest

from app.services.model_router import (
    ModelRouterConfigError,
    RouterConfig,
    RouterOption,
    parse_router_config,
)


def _valid_config() -> dict:
    return {
        "decision_credential_id": "11111111-1111-1111-1111-111111111111",
        "decision_model": "jev-latest",
        "routing_instructions": "Pick the cheapest model that can answer correctly.",
        "options": [
            {
                "id": "opt_1",
                "label": "Fast",
                "credential_id": "22222222-2222-2222-2222-222222222222",
                "model": "gpt-4o-mini",
                "criteria": "Short factual questions.",
                "is_default": True,
            },
            {
                "id": "opt_2",
                "label": "Deep reasoning",
                "credential_id": "33333333-3333-3333-3333-333333333333",
                "model": "gpt-5",
                "criteria": "Multi-step reasoning and code.",
            },
        ],
        "timeout_seconds": 10,
    }


class TestParseRouterConfig(unittest.TestCase):
    def test_parses_a_valid_config(self) -> None:
        config = parse_router_config(_valid_config())
        self.assertIsInstance(config, RouterConfig)
        self.assertEqual(config.decision_model, "jev-latest")
        self.assertEqual(len(config.options), 2)
        self.assertIsInstance(config.options[0], RouterOption)
        self.assertEqual(config.options[0].label, "Fast")
        self.assertTrue(config.options[0].is_default)
        self.assertFalse(config.options[1].is_default)
        self.assertEqual(config.timeout_seconds, 10.0)

    def test_default_option_is_exposed(self) -> None:
        config = parse_router_config(_valid_config())
        self.assertIsNotNone(config.default_option)
        self.assertEqual(config.default_option.label, "Fast")

    def test_default_option_is_none_when_unmarked(self) -> None:
        raw = _valid_config()
        raw["options"][0].pop("is_default")
        self.assertIsNone(parse_router_config(raw).default_option)

    def test_option_lookup_by_label_is_exact_then_case_insensitive(self) -> None:
        config = parse_router_config(_valid_config())
        self.assertEqual(config.option_by_label("Deep reasoning").model, "gpt-5")
        self.assertEqual(config.option_by_label("deep REASONING").model, "gpt-5")
        self.assertIsNone(config.option_by_label("Nonexistent"))

    def test_timeout_defaults_to_ten_seconds(self) -> None:
        raw = _valid_config()
        raw.pop("timeout_seconds")
        self.assertEqual(parse_router_config(raw).timeout_seconds, 10.0)

    def test_missing_decision_credential_is_rejected(self) -> None:
        raw = _valid_config()
        raw["decision_credential_id"] = "  "
        with self.assertRaises(ModelRouterConfigError) as ctx:
            parse_router_config(raw)
        self.assertIn("decision model credential", str(ctx.exception))

    def test_missing_decision_model_is_rejected(self) -> None:
        raw = _valid_config()
        raw["decision_model"] = ""
        with self.assertRaises(ModelRouterConfigError):
            parse_router_config(raw)

    def test_fewer_than_two_options_is_rejected(self) -> None:
        raw = _valid_config()
        raw["options"] = raw["options"][:1]
        with self.assertRaises(ModelRouterConfigError) as ctx:
            parse_router_config(raw)
        self.assertIn("at least two", str(ctx.exception))

    def test_blank_option_label_is_rejected(self) -> None:
        raw = _valid_config()
        raw["options"][1]["label"] = ""
        with self.assertRaises(ModelRouterConfigError) as ctx:
            parse_router_config(raw)
        self.assertIn("name", str(ctx.exception))

    def test_duplicate_option_labels_are_rejected(self) -> None:
        raw = _valid_config()
        raw["options"][1]["label"] = "fast"
        with self.assertRaises(ModelRouterConfigError) as ctx:
            parse_router_config(raw)
        self.assertIn("same name", str(ctx.exception))

    def test_blank_option_model_is_rejected(self) -> None:
        raw = _valid_config()
        raw["options"][0]["model"] = "   "
        with self.assertRaises(ModelRouterConfigError):
            parse_router_config(raw)

    def test_blank_option_credential_is_rejected(self) -> None:
        raw = _valid_config()
        raw["options"][0]["credential_id"] = ""
        with self.assertRaises(ModelRouterConfigError):
            parse_router_config(raw)

    def test_two_defaults_are_rejected(self) -> None:
        raw = _valid_config()
        raw["options"][1]["is_default"] = True
        with self.assertRaises(ModelRouterConfigError) as ctx:
            parse_router_config(raw)
        self.assertIn("one option", str(ctx.exception))

    def test_malformed_option_row_is_rejected(self) -> None:
        raw = _valid_config()
        raw["options"][1] = "not a dict"
        with self.assertRaises(ModelRouterConfigError):
            parse_router_config(raw)

    def test_missing_option_id_is_generated(self) -> None:
        raw = _valid_config()
        raw["options"][0].pop("id")
        config = parse_router_config(raw)
        self.assertTrue(config.options[0].id)
        self.assertNotEqual(config.options[0].id, config.options[1].id)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router.py -v
```

Expected: collection error, `ModuleNotFoundError: No module named 'app.services.model_router'`.

- [ ] **Step 3: Write the module**

Create `backend/app/services/model_router.py`:

```python
"""Model Router credentials: config shape, routing decisions, option binding.

A model router does not hold a key of its own. It holds a decision model
credential, a list of options (each an existing LLM credential plus a model id)
and free text per option saying when that option should win. At request time the
decision model answers one `choice` question and the winning option's credential
is bound for that provider call.

Everything that knows the router's config shape lives here, the way
`decision_models.py` is the only module that knows the System One wire format.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

# The routing state is sent to the decision model on every new turn, so it is
# truncated rather than unbounded. Platform limits are constants, not settings.
ROUTER_STATE_SYSTEM_CHARS = 2000
ROUTER_STATE_MESSAGE_CHARS = 4000
ROUTER_STATE_MAX_TOOLS = 40
DEFAULT_ROUTER_TIMEOUT_SECONDS = 10.0
ROUTING_QUESTION_ID = "route"

DEFAULT_ROUTING_INSTRUCTIONS = (
    "Choose the model best suited to this request. Read each option's criteria and "
    "pick the one whose criteria the request matches. When several fit, prefer the "
    "cheaper option."
)


class ModelRouterConfigError(ValueError):
    """Raised when a router credential's configuration cannot be used."""


class ModelRouterError(RuntimeError):
    """Raised when routing fails and there is no default option to fall back to."""


def _text(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class RouterOption:
    """One routable target: an LLM credential, a model on it, and when to use it."""

    id: str
    label: str
    credential_id: str
    model: str
    criteria: str
    is_default: bool = False


@dataclass(frozen=True)
class RouterConfig:
    """A parsed, validated router credential config."""

    decision_credential_id: str
    decision_model: str
    routing_instructions: str
    options: tuple[RouterOption, ...]
    timeout_seconds: float

    @property
    def default_option(self) -> RouterOption | None:
        """The option to use when the decision model cannot be consulted."""
        for option in self.options:
            if option.is_default:
                return option
        return None

    def option_by_label(self, label: str) -> RouterOption | None:
        """Resolve a label the decision model returned back to an option."""
        wanted = _text(label)
        if not wanted:
            return None
        for option in self.options:
            if option.label == wanted:
                return option
        lowered = wanted.lower()
        for option in self.options:
            if option.label.lower() == lowered:
                return option
        return None

    def fingerprint(self) -> str:
        """Stable digest of the routable surface, for decision reuse across turns."""
        payload = [
            [option.label, option.criteria, option.credential_id, option.model]
            for option in self.options
        ]
        payload.append([self.decision_model, self.routing_instructions])
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()


def _parse_option(raw: object, index: int) -> RouterOption:
    if not isinstance(raw, dict):
        raise ModelRouterConfigError(f"Model option {index + 1} is malformed")
    label = _text(raw.get("label"))
    if not label:
        raise ModelRouterConfigError(f"Model option {index + 1} needs a name")
    credential_id = _text(raw.get("credential_id"))
    if not credential_id:
        raise ModelRouterConfigError(f"Model option '{label}' needs a credential")
    model = _text(raw.get("model"))
    if not model:
        raise ModelRouterConfigError(f"Model option '{label}' needs a model")
    return RouterOption(
        id=_text(raw.get("id")) or f"opt_{index + 1}",
        label=label,
        credential_id=credential_id,
        model=model,
        criteria=_text(raw.get("criteria")),
        is_default=bool(raw.get("is_default")),
    )


def parse_router_config(config: dict) -> RouterConfig:
    """Validate a router credential's stored config and return it typed.

    Raises ModelRouterConfigError with a message meant for the user.
    """
    decision_credential_id = _text(config.get("decision_credential_id"))
    if not decision_credential_id:
        raise ModelRouterConfigError("Model Router needs a decision model credential")
    decision_model = _text(config.get("decision_model"))
    if not decision_model:
        raise ModelRouterConfigError("Model Router needs a decision model")

    raw_options = config.get("options")
    if not isinstance(raw_options, list):
        raise ModelRouterConfigError("Model Router options are malformed")
    options = tuple(_parse_option(raw, index) for index, raw in enumerate(raw_options))
    if len(options) < 2:
        raise ModelRouterConfigError(
            "Model Router needs at least two model options; with one there is nothing to route"
        )

    seen: set[str] = set()
    for option in options:
        lowered = option.label.lower()
        if lowered in seen:
            raise ModelRouterConfigError(
                f"Two model options share the same name '{option.label}'; "
                "names are what the decision model picks between"
            )
        seen.add(lowered)

    if sum(1 for option in options if option.is_default) > 1:
        raise ModelRouterConfigError(
            "Only one option can be the fallback used when routing fails"
        )

    raw_timeout = config.get("timeout_seconds")
    try:
        timeout_seconds = float(raw_timeout) if raw_timeout else DEFAULT_ROUTER_TIMEOUT_SECONDS
    except (TypeError, ValueError) as exc:
        raise ModelRouterConfigError("Model Router timeout must be a number") from exc
    if timeout_seconds <= 0:
        raise ModelRouterConfigError("Model Router timeout must be greater than zero")

    return RouterConfig(
        decision_credential_id=decision_credential_id,
        decision_model=decision_model,
        routing_instructions=_text(config.get("routing_instructions"))
        or DEFAULT_ROUTING_INSTRUCTIONS,
        options=options,
        timeout_seconds=timeout_seconds,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router.py -v
```

Expected: 15 passed.

- [ ] **Step 5: Verify formatting**

```bash
cd backend && uv run ruff format . && uv run ruff check app/services/model_router.py tests/test_model_router.py
```

Expected: no errors.

---

## Task 3: Routing state and the decision request

**Files:**
- Modify: `backend/app/services/model_router.py`
- Test: `backend/tests/test_model_router.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_model_router.py`, above the `if __name__` block, and add `build_routing_body`, `build_routing_state`, `read_route_answer` to the import list at the top of the file:

```python
class TestRoutingState(unittest.TestCase):
    def test_state_carries_system_message_and_tools(self) -> None:
        state = build_routing_state(
            system_instruction="You are a code reviewer.",
            message="Review this diff.",
            tool_names=["read_file", "search"],
        )
        self.assertEqual(state["system"], "You are a code reviewer.")
        self.assertEqual(state["message"], "Review this diff.")
        self.assertEqual(state["tools"], ["read_file", "search"])

    def test_absent_parts_are_omitted_rather_than_sent_empty(self) -> None:
        state = build_routing_state(system_instruction=None, message="Hi", tool_names=[])
        self.assertNotIn("system", state)
        self.assertNotIn("tools", state)
        self.assertEqual(state["message"], "Hi")

    def test_long_values_are_truncated_with_a_marker(self) -> None:
        state = build_routing_state(
            system_instruction="s" * (ROUTER_STATE_SYSTEM_CHARS + 500),
            message="m" * (ROUTER_STATE_MESSAGE_CHARS + 500),
            tool_names=[f"tool_{i}" for i in range(ROUTER_STATE_MAX_TOOLS + 10)],
        )
        self.assertTrue(state["system"].endswith("…[truncated]"))
        self.assertLessEqual(len(state["system"]), ROUTER_STATE_SYSTEM_CHARS + 20)
        self.assertTrue(state["message"].endswith("…[truncated]"))
        self.assertEqual(len(state["tools"]), ROUTER_STATE_MAX_TOOLS)

    def test_state_hash_is_stable_and_input_sensitive(self) -> None:
        first = build_routing_state(system_instruction="a", message="b", tool_names=["t"])
        same = build_routing_state(system_instruction="a", message="b", tool_names=["t"])
        other = build_routing_state(system_instruction="a", message="c", tool_names=["t"])
        self.assertEqual(state_hash(first), state_hash(same))
        self.assertNotEqual(state_hash(first), state_hash(other))


class TestRoutingBody(unittest.TestCase):
    def test_body_is_one_choice_question_keyed_by_option_label(self) -> None:
        config = parse_router_config(_valid_config())
        body = build_routing_body(config, {"message": "hello"})
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(body["state"], {"message": "hello"})
        question = body["questions"]["route"]
        self.assertEqual(question["type"], "choice")
        self.assertEqual(
            question["instructions"], "Pick the cheapest model that can answer correctly."
        )
        self.assertEqual(
            question["criteria"],
            {
                "Fast": "Short factual questions.",
                "Deep reasoning": "Multi-step reasoning and code.",
            },
        )

    def test_an_option_without_criteria_still_reaches_the_question(self) -> None:
        raw = _valid_config()
        raw["options"][1]["criteria"] = ""
        body = build_routing_body(parse_router_config(raw), {"message": "x"})
        self.assertIsNone(body["questions"]["route"]["criteria"]["Deep reasoning"])


class TestReadRouteAnswer(unittest.TestCase):
    def test_reads_the_choice(self) -> None:
        payload = {"answers": {"route": {"type": "choice", "choice": "Deep reasoning"}}}
        self.assertEqual(read_route_answer(payload), "Deep reasoning")

    def test_missing_answer_returns_none(self) -> None:
        self.assertIsNone(read_route_answer({"answers": {}}))
        self.assertIsNone(read_route_answer({}))
        self.assertIsNone(read_route_answer({"answers": {"route": {"type": "choice"}}}))
        self.assertIsNone(read_route_answer({"answers": {"route": "not a dict"}}))
```

Update the import at the top of the file to:

```python
from app.services.model_router import (
    ROUTER_STATE_MAX_TOOLS,
    ROUTER_STATE_MESSAGE_CHARS,
    ROUTER_STATE_SYSTEM_CHARS,
    ModelRouterConfigError,
    RouterConfig,
    RouterOption,
    build_routing_body,
    build_routing_state,
    parse_router_config,
    read_route_answer,
    state_hash,
)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router.py -v
```

Expected: `ImportError: cannot import name 'build_routing_state'`.

- [ ] **Step 3: Implement**

Append to `backend/app/services/model_router.py`:

```python
def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…[truncated]"


def build_routing_state(
    *,
    system_instruction: str | None,
    message: str | None,
    tool_names: list[str] | None,
) -> dict[str, object]:
    """Describe the request to the decision model, bounded in size.

    Only what a routing decision needs travels: the system instruction, the current
    message and the names of the attached tools. Tool schemas never go, and neither
    does conversation history.
    """
    state: dict[str, object] = {}
    system = _text(system_instruction)
    if system:
        state["system"] = _truncate(system, ROUTER_STATE_SYSTEM_CHARS)
    body = _text(message)
    if body:
        state["message"] = _truncate(body, ROUTER_STATE_MESSAGE_CHARS)
    names = [_text(name) for name in (tool_names or []) if _text(name)]
    if names:
        state["tools"] = names[:ROUTER_STATE_MAX_TOOLS]
    return state


def state_hash(state: dict[str, object]) -> str:
    """Digest of a routing state, used to reuse a decision across identical turns."""
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def build_routing_body(config: RouterConfig, state: dict[str, object]) -> dict[str, object]:
    """Build the decision model request that picks one option.

    The option labels become the `choice` keys, which is why they are validated
    non-empty and unique: they are the vocabulary the decision model answers in.
    """
    criteria: dict[str, str | None] = {
        option.label: (option.criteria or None) for option in config.options
    }
    return {
        "model": config.decision_model,
        "state": state,
        "questions": {
            ROUTING_QUESTION_ID: {
                "type": "choice",
                "instructions": config.routing_instructions,
                "criteria": criteria,
            }
        },
    }


def read_route_answer(payload: object) -> str | None:
    """Pull the chosen option label out of a decision model response."""
    if not isinstance(payload, dict):
        return None
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        return None
    answer = answers.get(ROUTING_QUESTION_ID)
    if not isinstance(answer, dict):
        return None
    return _text(answer.get("choice")) or None
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router.py -v
```

Expected: 24 passed.

- [ ] **Step 5: Verify**

```bash
cd backend && uv run ruff format . && uv run ruff check app/services/model_router.py tests/test_model_router.py
```

Expected: no errors.

---

## Task 4: The `ModelRouter` runtime class

`ModelRouter.route()` calls the decision model, resolves the label, falls back on failure and reuses a decision when the state has not changed.

**Files:**
- Modify: `backend/app/services/model_router.py`
- Test: `backend/tests/test_model_router.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_model_router.py`:

```python
class TestModelRouterRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.config = parse_router_config(_valid_config())

    def _router(self, **kwargs: object) -> "ModelRouter":
        return ModelRouter(
            credential_id="99999999-9999-9999-9999-999999999999",
            label="Auto Model",
            config=self.config,
            **kwargs,
        )

    def test_routes_to_the_chosen_option(self) -> None:
        calls: list[dict] = []

        def fake_call(**kwargs: object) -> dict:
            calls.append(dict(kwargs))
            return {"answers": {"route": {"type": "choice", "choice": "Deep reasoning"}}}

        router = self._router()
        with mock.patch.object(model_router, "call_decision_model", side_effect=fake_call), \
             mock.patch.object(
                 model_router,
                 "load_decision_credential",
                 return_value={"base_url": "https://api.typesafe.ai", "api_key": "k"},
             ):
            decision = router.route(
                system_instruction="sys", message="deep question", tool_names=None
            )

        self.assertEqual(decision.option.label, "Deep reasoning")
        self.assertEqual(decision.option.model, "gpt-5")
        self.assertFalse(decision.fallback)
        self.assertIsNone(decision.error)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["timeout"], 10.0)

    def test_identical_state_reuses_the_decision_without_a_second_call(self) -> None:
        payload = {"answers": {"route": {"type": "choice", "choice": "Fast"}}}
        router = self._router()
        with mock.patch.object(
            model_router, "call_decision_model", return_value=payload
        ) as called, mock.patch.object(
            model_router,
            "load_decision_credential",
            return_value={"base_url": "https://api.typesafe.ai", "api_key": "k"},
        ):
            first = router.route(system_instruction="s", message="m", tool_names=None)
            second = router.route(system_instruction="s", message="m", tool_names=None)
            third = router.route(system_instruction="s", message="changed", tool_names=None)

        self.assertEqual(first.option.label, "Fast")
        self.assertEqual(second.option.label, "Fast")
        self.assertEqual(third.option.label, "Fast")
        self.assertEqual(called.call_count, 2)

    def test_provider_failure_falls_back_to_the_default_option(self) -> None:
        router = self._router()
        with mock.patch.object(
            model_router,
            "call_decision_model",
            side_effect=DecisionProviderError("Decision model returned 500"),
        ), mock.patch.object(
            model_router,
            "load_decision_credential",
            return_value={"base_url": "https://api.typesafe.ai", "api_key": "k"},
        ):
            decision = router.route(system_instruction=None, message="m", tool_names=None)

        self.assertEqual(decision.option.label, "Fast")
        self.assertTrue(decision.fallback)
        self.assertIn("500", decision.error)

    def test_unknown_label_falls_back_to_the_default_option(self) -> None:
        payload = {"answers": {"route": {"type": "choice", "choice": "Nonexistent"}}}
        router = self._router()
        with mock.patch.object(
            model_router, "call_decision_model", return_value=payload
        ), mock.patch.object(
            model_router,
            "load_decision_credential",
            return_value={"base_url": "https://api.typesafe.ai", "api_key": "k"},
        ):
            decision = router.route(system_instruction=None, message="m", tool_names=None)

        self.assertEqual(decision.option.label, "Fast")
        self.assertTrue(decision.fallback)
        self.assertIn("Nonexistent", decision.error)

    def test_failure_without_a_default_option_raises(self) -> None:
        raw = _valid_config()
        raw["options"][0].pop("is_default")
        router = ModelRouter(
            credential_id="99999999-9999-9999-9999-999999999999",
            label="Auto Model",
            config=parse_router_config(raw),
        )
        with mock.patch.object(
            model_router,
            "call_decision_model",
            side_effect=DecisionProviderError("boom"),
        ), mock.patch.object(
            model_router,
            "load_decision_credential",
            return_value={"base_url": "https://api.typesafe.ai", "api_key": "k"},
        ):
            with self.assertRaises(ModelRouterError) as ctx:
                router.route(system_instruction=None, message="m", tool_names=None)
        self.assertIn("boom", str(ctx.exception))

    def test_a_fallback_decision_is_not_cached(self) -> None:
        payload = {"answers": {"route": {"type": "choice", "choice": "Fast"}}}
        router = self._router()
        with mock.patch.object(
            model_router,
            "call_decision_model",
            side_effect=[DecisionProviderError("boom"), payload],
        ) as called, mock.patch.object(
            model_router,
            "load_decision_credential",
            return_value={"base_url": "https://api.typesafe.ai", "api_key": "k"},
        ):
            first = router.route(system_instruction=None, message="m", tool_names=None)
            second = router.route(system_instruction=None, message="m", tool_names=None)

        self.assertTrue(first.fallback)
        self.assertFalse(second.fallback)
        self.assertEqual(called.call_count, 2)
```

Add these imports at the top of the test file:

```python
from unittest import mock

from app.services import model_router
from app.services.decision_models import DecisionProviderError
from app.services.model_router import ModelRouter, ModelRouterError
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router.py -v
```

Expected: `ImportError: cannot import name 'ModelRouter'`.

- [ ] **Step 3: Implement**

Append to `backend/app/services/model_router.py`:

```python
@dataclass(frozen=True)
class RouteDecision:
    """The option bound for one provider call, and how it was reached."""

    option: RouterOption
    fallback: bool = False
    error: str | None = None


class ModelRouter:
    """Runtime side of a router credential: ask the decision model, bind an option."""

    def __init__(
        self,
        *,
        credential_id: str,
        label: str,
        config: RouterConfig,
        trace_context: object | None = None,
    ) -> None:
        self.credential_id = credential_id
        self.label = label
        self.config = config
        self.trace_context = trace_context
        self._cached_key: str | None = None
        self._cached_decision: RouteDecision | None = None

    def route(
        self,
        *,
        system_instruction: str | None,
        message: str | None,
        tool_names: list[str] | None,
    ) -> RouteDecision:
        """Pick the option for this request.

        The decision is reused when the routing state is byte-for-byte what it was on
        the previous call, so an agent tool loop only pays for a decision when the
        conversation has actually moved. A fallback decision is never cached: the next
        turn gets a fresh chance to reach the decision model.
        """
        state = build_routing_state(
            system_instruction=system_instruction,
            message=message,
            tool_names=tool_names,
        )
        key = f"{self.config.fingerprint()}:{state_hash(state)}"
        if self._cached_key == key and self._cached_decision is not None:
            return self._cached_decision

        decision = self._decide(state)
        if not decision.fallback:
            self._cached_key = key
            self._cached_decision = decision
        return decision

    def _decide(self, state: dict[str, object]) -> RouteDecision:
        try:
            credential = load_decision_credential(self.config.decision_credential_id)
            payload = call_decision_model(
                base_url=credential["base_url"],
                api_key=credential["api_key"],
                body=build_routing_body(self.config, state),
                timeout=self.config.timeout_seconds,
                trace_context=self.trace_context,
            )
        except (DecisionProviderError, DecisionRequestError, OSError) as exc:
            return self._fallback(str(exc))

        label = read_route_answer(payload)
        if label is None:
            return self._fallback("Decision model returned no routing answer")
        option = self.config.option_by_label(label)
        if option is None:
            return self._fallback(f"Decision model chose '{label}', which is not a model option")
        return RouteDecision(option=option)

    def _fallback(self, reason: str) -> RouteDecision:
        default = self.config.default_option
        if default is None:
            raise ModelRouterError(
                f"Model Router could not pick a model and has no fallback option: {reason}"
            )
        return RouteDecision(option=default, fallback=True, error=reason)
```

Add these imports to the top of the module, beneath the existing ones:

```python
from app.services.decision_models import (
    DecisionProviderError,
    DecisionRequestError,
    call_decision_model,
    load_decision_credential,
)
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router.py -v
```

Expected: 30 passed.

- [ ] **Step 5: Verify**

```bash
cd backend && uv run ruff format . && uv run ruff check app/services/model_router.py tests/test_model_router.py
```

Expected: no errors.

---

## Task 5: Loading the option's credential

**Files:**
- Modify: `backend/app/services/model_router.py`
- Test: `backend/tests/test_model_router.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_model_router.py`:

```python
class TestLoadOptionCredential(unittest.TestCase):
    def _credential(self, cred_type: object, name: str = "OpenAI prod") -> mock.Mock:
        credential = mock.Mock()
        credential.type = cred_type
        credential.name = name
        credential.encrypted_config = "encrypted"
        return credential

    def test_returns_type_key_and_base_url(self) -> None:
        from app.db.models import CredentialType

        credential = self._credential(CredentialType.openai)
        session = mock.MagicMock()
        session.__enter__.return_value.get.return_value = credential

        with mock.patch.object(model_router, "SessionLocal", return_value=session), \
             mock.patch.object(
                 model_router, "decrypt_config", return_value={"api_key": "sk-x", "base_url": None}
             ):
            bound = load_option_credential(
                RouterOption(
                    id="opt_1",
                    label="Fast",
                    credential_id="22222222-2222-2222-2222-222222222222",
                    model="gpt-4o-mini",
                    criteria="",
                )
            )

        self.assertEqual(bound.credential_type, "openai")
        self.assertEqual(bound.api_key, "sk-x")
        self.assertIsNone(bound.base_url)
        self.assertEqual(bound.credential_name, "OpenAI prod")

    def test_missing_credential_is_reported_with_the_option_name(self) -> None:
        session = mock.MagicMock()
        session.__enter__.return_value.get.return_value = None
        with mock.patch.object(model_router, "SessionLocal", return_value=session):
            with self.assertRaises(ModelRouterError) as ctx:
                load_option_credential(
                    RouterOption(
                        id="opt_1",
                        label="Fast",
                        credential_id="22222222-2222-2222-2222-222222222222",
                        model="gpt-4o-mini",
                        criteria="",
                    )
                )
        self.assertIn("Fast", str(ctx.exception))

    def test_a_router_option_pointing_at_another_router_is_refused(self) -> None:
        from app.db.models import CredentialType

        credential = self._credential(CredentialType.model_router, name="Other router")
        session = mock.MagicMock()
        session.__enter__.return_value.get.return_value = credential
        with mock.patch.object(model_router, "SessionLocal", return_value=session), \
             mock.patch.object(model_router, "decrypt_config", return_value={}):
            with self.assertRaises(ModelRouterError) as ctx:
                load_option_credential(
                    RouterOption(
                        id="opt_1",
                        label="Fast",
                        credential_id="22222222-2222-2222-2222-222222222222",
                        model="gpt-4o-mini",
                        criteria="",
                    )
                )
        self.assertIn("another Model Router", str(ctx.exception))

    def test_a_bad_uuid_is_reported(self) -> None:
        with self.assertRaises(ModelRouterError):
            load_option_credential(
                RouterOption(
                    id="opt_1",
                    label="Fast",
                    credential_id="not-a-uuid",
                    model="gpt-4o-mini",
                    criteria="",
                )
            )
```

Add `BoundOption` and `load_option_credential` to the `app.services.model_router` import list.

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router.py::TestLoadOptionCredential -v
```

Expected: `ImportError: cannot import name 'load_option_credential'`.

- [ ] **Step 3: Implement**

Append to `backend/app/services/model_router.py`:

```python
@dataclass(frozen=True)
class BoundOption:
    """An option resolved into the values `LLMService` needs to build a client."""

    option: RouterOption
    credential_type: str
    api_key: str
    base_url: str | None
    credential_name: str
    credential_uuid: uuid.UUID


ROUTABLE_CREDENTIAL_TYPES = ("openai", "google", "custom")


def load_option_credential(option: RouterOption) -> BoundOption:
    """Read and decrypt the credential behind one routable option.

    Access is not re-checked against the running user: using a router credential is
    itself the grant, exactly as using a shared OpenAI credential is. The check that
    the router's owner could reach this credential happens when the router is saved.
    """
    try:
        credential_uuid = uuid.UUID(str(option.credential_id))
    except ValueError as exc:
        raise ModelRouterError(
            f"Model option '{option.label}' has an invalid credential id"
        ) from exc

    with SessionLocal() as db:
        credential = db.get(Credential, credential_uuid)
        if credential is None:
            raise ModelRouterError(
                f"Model option '{option.label}' points at a credential that no longer exists"
            )
        credential_type = credential.type.value
        credential_name = credential.name
        config = decrypt_config(credential.encrypted_config)

    if credential_type == CredentialType.model_router.value:
        raise ModelRouterError(
            f"Model option '{option.label}' points at another Model Router, which is not allowed"
        )
    if credential_type not in ROUTABLE_CREDENTIAL_TYPES:
        raise ModelRouterError(
            f"Model option '{option.label}' points at a {credential_type} credential, "
            "which cannot serve model requests"
        )

    api_key = _text(config.get("api_key"))
    if not api_key:
        raise ModelRouterError(f"Model option '{option.label}' has a credential with no API key")

    return BoundOption(
        option=option,
        credential_type=credential_type,
        api_key=api_key,
        base_url=_text(config.get("base_url")) or None,
        credential_name=credential_name,
        credential_uuid=credential_uuid,
    )
```

Add to the module's imports:

```python
import uuid

from app.db.models import Credential, CredentialType
from app.db.session import SessionLocal
from app.services.encryption import decrypt_config
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router.py -v
```

Expected: 34 passed.

- [ ] **Step 5: Verify**

```bash
cd backend && uv run ruff format . && uv run ruff check app/services/model_router.py tests/test_model_router.py
```

Expected: no errors.

---

# Phase 2 — Credentials API surface

## Task 6: Validation, masking and public fields

**Files:**
- Modify: `backend/app/api/credentials.py` (four call sites)
- Test: `backend/tests/test_model_router_credentials.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_model_router_credentials.py`:

```python
import unittest
import uuid
from unittest import mock

from fastapi import HTTPException

from app.api.credentials import (
    _build_public_fields,
    _compute_masked_value,
    merge_credential_config_for_update,
    validate_credential_config,
)
from app.db.models import CredentialType


def _config() -> dict:
    return {
        "decision_credential_id": str(uuid.uuid4()),
        "decision_model": "jev-latest",
        "routing_instructions": "Pick the cheapest model that works.",
        "options": [
            {
                "id": "opt_1",
                "label": "Fast",
                "credential_id": str(uuid.uuid4()),
                "model": "gpt-4o-mini",
                "criteria": "Short questions.",
                "is_default": True,
            },
            {
                "id": "opt_2",
                "label": "Deep",
                "credential_id": str(uuid.uuid4()),
                "model": "gpt-5",
                "criteria": "Hard questions.",
            },
        ],
    }


class TestRouterConfigValidation(unittest.TestCase):
    def test_a_valid_config_passes_shape_validation(self) -> None:
        validate_credential_config(CredentialType.model_router, _config())

    def test_a_shape_error_becomes_a_400(self) -> None:
        raw = _config()
        raw["options"] = raw["options"][:1]
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.model_router, raw)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("at least two", ctx.exception.detail)


class TestRouterMaskingAndPublicFields(unittest.TestCase):
    def test_masked_value_is_none_because_there_is_no_secret(self) -> None:
        self.assertIsNone(_compute_masked_value(CredentialType.model_router, _config()))

    def test_public_fields_summarise_the_router(self) -> None:
        fields = _build_public_fields(CredentialType.model_router, _config())
        self.assertEqual(fields["decision_model"], "jev-latest")
        self.assertEqual(fields["option_count"], "2")

    def test_public_fields_never_leak_a_referenced_key(self) -> None:
        raw = _config()
        raw["options"][0]["api_key"] = "sk-should-not-be-here"
        fields = _build_public_fields(CredentialType.model_router, raw)
        self.assertNotIn("sk-should-not-be-here", str(fields))


class TestRouterUpdateMerge(unittest.TestCase):
    def test_update_replaces_the_config_wholesale(self) -> None:
        existing = _config()
        incoming = _config()
        incoming["options"] = incoming["options"][:2]
        incoming["options"].pop()
        merged = merge_credential_config_for_update(
            CredentialType.model_router, existing, incoming
        )
        self.assertEqual(merged, incoming)
        self.assertEqual(len(merged["options"]), 1)


if __name__ == "__main__":
    unittest.main()
```

Note the last test: a removed option must stay removed. If `model_router` were ever added to the secret-merge path, that test fails, which is exactly the regression it guards.

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_credentials.py -v
```

Expected: `TestRouterConfigValidation` fails because no branch exists yet; the masking test returns something other than `None`.

- [ ] **Step 3: Add the validation branch**

In `backend/app/api/credentials.py`, inside `validate_credential_config`, directly after the `elif credential_type == CredentialType.decision:` block that ends with the `base_url must start with http://` check, add:

```python
    elif credential_type == CredentialType.model_router:
        from app.services.model_router import ModelRouterConfigError, parse_router_config

        try:
            parse_router_config(config)
        except ModelRouterConfigError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
```

- [ ] **Step 4: Add the masked value branch**

In `_compute_masked_value`, after the `elif credential_type == CredentialType.decision:` block, add:

```python
    elif credential_type == CredentialType.model_router:
        # A router holds references, never a key of its own, so there is nothing to mask.
        return None
```

- [ ] **Step 5: Add the public fields branch**

In `_build_public_fields`, after `if credential_type == CredentialType.decision:`, add:

```python
    if credential_type == CredentialType.model_router:
        options = config.get("options")
        option_count = len(options) if isinstance(options, list) else 0
        return {
            "decision_model": str(config.get("decision_model", "") or "").strip() or None,
            "option_count": str(option_count),
        }
```

- [ ] **Step 6: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_credentials.py -v
```

Expected: 6 passed.

- [ ] **Step 7: Verify**

```bash
cd backend && uv run ruff format . && uv run ruff check app/api/credentials.py tests/test_model_router_credentials.py
```

Expected: no errors.

---

## Task 7: Validate referenced credentials at write time

The shape check in Task 6 does not touch the database. This task adds the access check: every credential the router points at must be reachable by the router's owner, and be the right type.

**Files:**
- Modify: `backend/app/api/credentials.py` (`create_credential`, `update_credential`)
- Test: `backend/tests/test_model_router_credentials.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_model_router_credentials.py`:

```python
class TestRouterReferenceValidation(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.owner = mock.Mock()
        self.owner.id = uuid.uuid4()
        self.config = _config()

    def _credential(self, cred_type: CredentialType) -> mock.Mock:
        credential = mock.Mock()
        credential.type = cred_type
        credential.name = "ref"
        return credential

    async def _run(self, lookups: dict) -> None:
        from app.api import credentials as credentials_api

        async def fake_lookup(db: object, credential_id: uuid.UUID, user: object) -> object:
            return lookups.get(str(credential_id))

        with mock.patch.object(
            credentials_api, "_get_accessible_credential", side_effect=fake_lookup
        ):
            await credentials_api.validate_model_router_references(
                mock.AsyncMock(), self.config, self.owner
            )

    async def test_passes_when_every_reference_resolves(self) -> None:
        lookups = {
            self.config["decision_credential_id"]: self._credential(CredentialType.decision),
            self.config["options"][0]["credential_id"]: self._credential(CredentialType.openai),
            self.config["options"][1]["credential_id"]: self._credential(CredentialType.google),
        }
        await self._run(lookups)

    async def test_unreachable_decision_credential_is_a_400(self) -> None:
        lookups = {
            self.config["options"][0]["credential_id"]: self._credential(CredentialType.openai),
            self.config["options"][1]["credential_id"]: self._credential(CredentialType.openai),
        }
        with self.assertRaises(HTTPException) as ctx:
            await self._run(lookups)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("decision model credential", ctx.exception.detail)

    async def test_wrong_decision_credential_type_is_a_400(self) -> None:
        lookups = {
            self.config["decision_credential_id"]: self._credential(CredentialType.openai),
            self.config["options"][0]["credential_id"]: self._credential(CredentialType.openai),
            self.config["options"][1]["credential_id"]: self._credential(CredentialType.openai),
        }
        with self.assertRaises(HTTPException) as ctx:
            await self._run(lookups)
        self.assertIn("decision model credential", ctx.exception.detail)

    async def test_unreachable_option_credential_is_a_400_naming_the_option(self) -> None:
        lookups = {
            self.config["decision_credential_id"]: self._credential(CredentialType.decision),
            self.config["options"][0]["credential_id"]: self._credential(CredentialType.openai),
        }
        with self.assertRaises(HTTPException) as ctx:
            await self._run(lookups)
        self.assertIn("Deep", ctx.exception.detail)

    async def test_an_option_pointing_at_another_router_is_a_400(self) -> None:
        lookups = {
            self.config["decision_credential_id"]: self._credential(CredentialType.decision),
            self.config["options"][0]["credential_id"]: self._credential(CredentialType.openai),
            self.config["options"][1]["credential_id"]: self._credential(
                CredentialType.model_router
            ),
        }
        with self.assertRaises(HTTPException) as ctx:
            await self._run(lookups)
        self.assertIn("another Model Router", ctx.exception.detail)

    async def test_an_option_pointing_at_a_slack_credential_is_a_400(self) -> None:
        lookups = {
            self.config["decision_credential_id"]: self._credential(CredentialType.decision),
            self.config["options"][0]["credential_id"]: self._credential(CredentialType.openai),
            self.config["options"][1]["credential_id"]: self._credential(CredentialType.slack),
        }
        with self.assertRaises(HTTPException) as ctx:
            await self._run(lookups)
        self.assertIn("Deep", ctx.exception.detail)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_credentials.py::TestRouterReferenceValidation -v
```

Expected: `AttributeError: module 'app.api.credentials' has no attribute 'validate_model_router_references'`.

- [ ] **Step 3: Implement the helper**

In `backend/app/api/credentials.py`, add above `@router.post("", response_model=CredentialResponse, ...)`:

```python
ROUTER_OPTION_CREDENTIAL_TYPES = (
    CredentialType.openai,
    CredentialType.google,
    CredentialType.custom,
)


async def validate_model_router_references(
    db: AsyncSession,
    config: dict,
    owner: User,
) -> None:
    """Reject a router whose owner cannot reach what it points at.

    This is the only access check in the router's life. At run time the referenced
    credentials are loaded without re-checking the caller, because using a router is
    itself the grant. Doing the check here keeps that grant to credentials the owner
    genuinely held when they built the router.
    """
    from app.services.model_router import ModelRouterConfigError, parse_router_config

    try:
        router_config = parse_router_config(config)
    except ModelRouterConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    try:
        decision_uuid = uuid.UUID(router_config.decision_credential_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Model Router needs a valid decision model credential",
        ) from exc

    decision_credential = await _get_accessible_credential(db, decision_uuid, owner)
    if decision_credential is None or decision_credential.type != CredentialType.decision:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Model Router needs a decision model credential you can access",
        )

    for option in router_config.options:
        try:
            option_uuid = uuid.UUID(option.credential_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model option '{option.label}' has an invalid credential",
            ) from exc

        option_credential = await _get_accessible_credential(db, option_uuid, owner)
        if option_credential is not None and option_credential.type == CredentialType.model_router:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Model option '{option.label}' points at another Model Router, "
                    "which is not allowed"
                ),
            )
        if (
            option_credential is None
            or option_credential.type not in ROUTER_OPTION_CREDENTIAL_TYPES
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Model option '{option.label}' needs an OpenAI, Google or Custom "
                    "credential you can access"
                ),
            )
```

- [ ] **Step 4: Call it from create and update**

In `create_credential`, immediately after the existing `validate_credential_config(...)` call, add:

```python
    if credential_data.type == CredentialType.model_router:
        await validate_model_router_references(db, credential_data.config, current_user)
```

In `update_credential`, after the config has been merged and validated, add the same two lines using the merged config and the credential's owner:

```python
    if credential.type == CredentialType.model_router:
        await validate_model_router_references(db, merged_config, current_user)
```

Read the surrounding code first and use whatever the merged-config variable is actually named there; do not introduce a new name.

- [ ] **Step 5: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_credentials.py -v
```

Expected: 12 passed.

- [ ] **Step 6: Verify**

```bash
cd backend && uv run ruff format . && uv run ruff check app/api/credentials.py tests/test_model_router_credentials.py
```

Expected: no errors.

---

## Task 8: Expose the router to every LLM picker

**Files:**
- Modify: `backend/app/api/credentials.py:837-846` (`list_llm_credentials`), `:1495` (`get_credential_models`)
- Test: `backend/tests/test_model_router_credentials.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_model_router_credentials.py`:

```python
class TestRouterSyntheticModel(unittest.TestCase):
    def test_auto_model_row_rejects_batch_and_responses(self) -> None:
        from app.api.credentials import build_model_router_models

        models = build_model_router_models()
        self.assertEqual(len(models), 1)
        auto = models[0]
        self.assertEqual(auto.id, "auto")
        self.assertEqual(auto.name, "Auto")
        self.assertFalse(auto.is_reasoning)
        self.assertFalse(auto.supports_batch)
        self.assertFalse(auto.supports_responses)
        self.assertIn("Responses API", auto.responses_support_reason)
        self.assertIn("Batch", auto.batch_support_reason)
        self.assertIsNone(auto.context_window)


class TestRouterInLlmList(unittest.TestCase):
    def test_llm_listing_includes_the_router_type(self) -> None:
        import inspect

        from app.api import credentials as credentials_api

        source = inspect.getsource(credentials_api.list_llm_credentials)
        self.assertIn("CredentialType.model_router", source)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_credentials.py::TestRouterSyntheticModel tests/test_model_router_credentials.py::TestRouterInLlmList -v
```

Expected: `ImportError: cannot import name 'build_model_router_models'` and the listing assertion fails.

- [ ] **Step 3: Add the router to the LLM listing**

Replace the body of `list_llm_credentials` in `backend/app/api/credentials.py`:

```python
@router.get("/llm", response_model=list[CredentialListResponse])
async def list_llm_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CredentialListResponse]:
    """Every credential that can serve a model request, routers included.

    Routers appear here on purpose: each surface that offers a model picker reads
    this one endpoint, so listing the router here is what makes Auto Model reachable
    from the nodes, Chat, AI Defaults, Evals and everywhere added later.
    """
    return await _list_credentials_of_types(
        db,
        current_user,
        [
            CredentialType.openai,
            CredentialType.google,
            CredentialType.custom,
            CredentialType.model_router,
        ],
    )
```

- [ ] **Step 4: Add the synthetic model**

Above `@router.get("/{credential_id}/models", ...)` in the same file:

```python
MODEL_ROUTER_AUTO_MODEL_ID = "auto"
MODEL_ROUTER_BATCH_MESSAGE = (
    "Batch mode is not available for Model Router credentials: a batch job runs "
    "against one fixed model."
)
MODEL_ROUTER_RESPONSES_MESSAGE = (
    "Auto Model does not support the Responses API. Pick a specific credential and "
    "model to use it."
)


def build_model_router_models() -> list[LLMModel]:
    """The one pseudo-model a router offers; the real model is chosen per request."""
    return [
        LLMModel(
            id=MODEL_ROUTER_AUTO_MODEL_ID,
            name="Auto",
            is_reasoning=False,
            supports_batch=False,
            batch_support_reason=MODEL_ROUTER_BATCH_MESSAGE,
            supports_responses=False,
            responses_support_reason=MODEL_ROUTER_RESPONSES_MESSAGE,
            context_window=None,
        )
    ]
```

Then inside `get_credential_models`, replace the type guard so routers short-circuit before the provider fetch:

```python
    if credential.type == CredentialType.model_router:
        return build_model_router_models()

    if credential.type not in (CredentialType.openai, CredentialType.google, CredentialType.custom):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This credential type does not support model listing",
        )
```

- [ ] **Step 5: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_credentials.py -v
```

Expected: 14 passed.

- [ ] **Step 6: Verify nothing else regressed in credentials**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_decision_credentials.py tests/test_advisory_shared_credential_test_override.py -v
cd backend && uv run ruff format . && uv run ruff check app/api/credentials.py
```

Expected: all pass, no lint errors.

---

## Task 8b: Read the router config back for editing

`CredentialResponse` deliberately has no `config` field, so the dialog cannot round-trip
a stored router from the existing detail endpoint, and `public_fields` is a
`dict[str, str | None]` meant for summaries rather than a JSON blob. A router config holds
no secret, so it gets its own typed read endpoint.

**Files:**
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/api/credentials.py`
- Test: `backend/tests/test_model_router_credentials.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_model_router_credentials.py`:

```python
class TestRouterConfigReadSchema(unittest.TestCase):
    def test_response_model_mirrors_the_stored_config(self) -> None:
        from app.models.schemas import ModelRouterConfigResponse

        raw = _config()
        response = ModelRouterConfigResponse(**raw)
        self.assertEqual(response.decision_model, "jev-latest")
        self.assertEqual(len(response.options), 2)
        self.assertEqual(response.options[0].label, "Fast")
        self.assertTrue(response.options[0].is_default)
        self.assertFalse(response.options[1].is_default)

    def test_the_response_model_has_no_key_field_to_fill(self) -> None:
        from app.models.schemas import ModelRouterConfigResponse, ModelRouterOptionResponse

        self.assertNotIn("api_key", ModelRouterConfigResponse.model_fields)
        self.assertNotIn("api_key", ModelRouterOptionResponse.model_fields)

    def test_endpoint_exists_and_is_owner_scoped(self) -> None:
        import inspect

        from app.api import credentials as credentials_api

        source = inspect.getsource(credentials_api.get_model_router_config)
        self.assertIn("_get_accessible_credential", source)
        self.assertIn("CredentialType.model_router", source)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_credentials.py::TestRouterConfigReadSchema -v
```

Expected: `ImportError: cannot import name 'ModelRouterConfigResponse'`.

- [ ] **Step 3: Add the response models**

In `backend/app/models/schemas.py`, next to the other credential models:

```python
class ModelRouterOptionResponse(BaseModel):
    id: str
    label: str
    credential_id: str
    model: str
    criteria: str = ""
    is_default: bool = False


class ModelRouterConfigResponse(BaseModel):
    """A router's stored config, returned so the dialog can edit it.

    Safe to return in full: a router references credentials by id and holds no key of
    its own, which is why there is no masked variant of this model.
    """

    decision_credential_id: str
    decision_model: str
    routing_instructions: str = ""
    options: list[ModelRouterOptionResponse] = Field(default_factory=list)
    timeout_seconds: float | None = None
```

- [ ] **Step 4: Add the endpoint**

In `backend/app/api/credentials.py`, beside the other `/{credential_id}/...` routes and
**above** the bare `@router.get("/{credential_id}")` so the path matches:

```python
@router.get("/{credential_id}/model-router", response_model=ModelRouterConfigResponse)
async def get_model_router_config(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModelRouterConfigResponse:
    """Return a router's config so the credential dialog can edit it.

    Returned in full because it contains no secret: only the ids of credentials the
    caller already has access to through this router, plus the routing criteria.
    """
    credential = await _get_accessible_credential(db, credential_id, current_user)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )
    if credential.type != CredentialType.model_router:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This credential is not a Model Router",
        )
    return ModelRouterConfigResponse(**decrypt_config(credential.encrypted_config))
```

Import the two models alongside the other schema imports at the top of the file.

- [ ] **Step 5: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_credentials.py -v
```

Expected: 17 passed.

- [ ] **Step 6: Verify**

```bash
cd backend && uv run ruff format . && uv run ruff check app/api/credentials.py app/models/schemas.py
```

Expected: no errors. Confirm the new route is declared before `@router.get("/{credential_id}")`, or FastAPI matches the bare route first and `"model-router"` is parsed as a UUID.

---

# Phase 3 — Trace plumbing

## Task 9: Router columns on `llm_traces`

**Files:**
- Modify: `backend/app/db/models.py:700-713`
- Create: `backend/alembic/versions/125_llm_trace_router_columns.py`
- Modify: `backend/app/services/llm_trace.py`
- Test: `backend/tests/test_model_router_llm_service.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_model_router_llm_service.py`:

```python
import unittest
import uuid
from dataclasses import replace
from unittest import mock

from app.services.llm_trace import LLMTraceContext


class TestTraceContextRouterFields(unittest.TestCase):
    def _context(self) -> LLMTraceContext:
        return LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            node_id="node-1",
            node_label="Agent",
            source="workflow",
            session_id="session-1",
        )

    def test_router_fields_default_to_none(self) -> None:
        context = self._context()
        self.assertIsNone(context.router_credential_id)
        self.assertIsNone(context.router_label)

    def test_replace_rebinds_the_credential_and_keeps_the_same_trace_id_list(self) -> None:
        context = self._context()
        router_id = uuid.uuid4()
        actual_credential = uuid.uuid4()

        rebound = replace(
            context,
            credential_id=actual_credential,
            router_credential_id=router_id,
            router_label="Auto Model",
        )

        self.assertEqual(rebound.credential_id, actual_credential)
        self.assertEqual(rebound.router_credential_id, router_id)
        self.assertEqual(rebound.router_label, "Auto Model")
        # The executor reads trace ids off the context it built, so the list must be
        # the very same object, not a copy. A fresh LLMTraceContext(...) here would
        # silently break every "Open trace" link in the execution log.
        self.assertIs(rebound.trace_ids, context.trace_ids)
        rebound.trace_ids.append(uuid.uuid4())
        self.assertEqual(len(context.trace_ids), 1)

    def test_record_llm_trace_persists_the_router_columns(self) -> None:
        from app.services import llm_trace

        context = replace(
            self._context(),
            router_credential_id=uuid.uuid4(),
            router_label="Auto Model",
        )
        captured: list[object] = []
        session = mock.MagicMock()
        session.__enter__.return_value.add.side_effect = captured.append

        with mock.patch.object(llm_trace, "SessionLocal", return_value=session):
            llm_trace.record_llm_trace(
                context,
                request_type="chat.completions",
                request={"model": "gpt-5"},
                response={"text": "hi"},
                model="gpt-5",
                provider="OpenAI",
            )

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].router_credential_id, context.router_credential_id)
        self.assertEqual(captured[0].router_label, "Auto Model")
        self.assertEqual(captured[0].model, "gpt-5")
        self.assertEqual(captured[0].credential_id, context.credential_id)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py -v
```

Expected: `TypeError: LLMTraceContext.__init__() got an unexpected keyword argument 'router_credential_id'`.

- [ ] **Step 3: Add the columns**

In `backend/app/db/models.py`, inside `class LLMTrace`, directly after the `credential_id` column:

```python
    # The router that chose the model, when one did. `credential_id` and `model` keep
    # holding what actually served the request, because pricing and the per-model and
    # per-credential stats read those two columns.
    router_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credentials.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    router_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
```

Because `LLMTrace` now has two foreign keys to `credentials`, the existing relationship needs an explicit join condition. Change it to:

```python
    credential: Mapped["Credential | None"] = relationship(
        "Credential", foreign_keys=[credential_id]
    )
```

- [ ] **Step 4: Write the migration**

Create `backend/alembic/versions/125_llm_trace_router_columns.py`:

```python
"""add router columns to llm_traces

Revision ID: 125_llm_trace_router_cols
Revises: 124_add_model_router_cred
Create Date: 2026-09-22 00:00:00.000000

Note: alembic_version.version_num is varchar(32), so the revision id must stay
within 32 characters.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "125_llm_trace_router_cols"
down_revision: Union[str, None] = "124_add_model_router_cred"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_traces",
        sa.Column("router_credential_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column("llm_traces", sa.Column("router_label", sa.String(length=255), nullable=True))
    op.create_index(
        "ix_llm_traces_router_credential_id", "llm_traces", ["router_credential_id"]
    )
    op.create_foreign_key(
        "fk_llm_traces_router_credential_id",
        "llm_traces",
        "credentials",
        ["router_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_llm_traces_router_credential_id", "llm_traces", type_="foreignkey")
    op.drop_index("ix_llm_traces_router_credential_id", table_name="llm_traces")
    op.drop_column("llm_traces", "router_label")
    op.drop_column("llm_traces", "router_credential_id")
```

- [ ] **Step 5: Extend `LLMTraceContext` and `record_llm_trace`**

In `backend/app/services/llm_trace.py`, add two fields to `LLMTraceContext` directly below `session_id`:

```python
    # Set when a Model Router chose the model. `credential_id` above stays the
    # credential that actually served the request.
    router_credential_id: uuid.UUID | None = None
    router_label: str | None = None
```

Note that `trace_ids` must remain the last field, so add these above it.

Then in `record_llm_trace`, pass them into the `LLMTrace(...)` constructor:

```python
                credential_id=context.credential_id,
                router_credential_id=context.router_credential_id,
                router_label=context.router_label,
```

- [ ] **Step 6: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py tests/test_alembic_migrations.py -v
cd backend && uv run alembic upgrade head
```

Expected: tests pass; `Running upgrade 124_add_model_router_cred -> 125_llm_trace_router_cols`.

- [ ] **Step 7: Verify nothing that reads traces broke**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "trace" -v
cd backend && uv run ruff format . && uv run ruff check app/db/models.py app/services/llm_trace.py
```

Expected: all pass, no lint errors.

---

# Phase 4 — Routing inside `LLMService`

## Task 10: `TurnBinding` and `_resolve_turn`

**Files:**
- Modify: `backend/app/services/llm_service.py:524-600`
- Test: `backend/tests/test_model_router_llm_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_model_router_llm_service.py`:

```python
class TestResolveTurn(unittest.TestCase):
    def _service(self, **kwargs: object) -> object:
        from app.db.models import CredentialType
        from app.services.llm_service import LLMService

        defaults = {
            "credential_type": CredentialType.openai,
            "api_key": "sk-static",
            "base_url": None,
        }
        defaults.update(kwargs)
        return LLMService(**defaults)

    def test_without_a_router_the_binding_is_the_static_credential(self) -> None:
        service = self._service()
        with mock.patch.object(
            service, "_get_client", return_value=(mock.sentinel.client, "OpenAI")
        ):
            binding = service._resolve_turn(
                model="gpt-4o", system_instruction="s", message="m", tool_names=None
            )
        self.assertIs(binding.client, mock.sentinel.client)
        self.assertEqual(binding.provider, "OpenAI")
        self.assertEqual(binding.model, "gpt-4o")
        self.assertIsNone(binding.router_label)
        self.assertFalse(binding.fallback)

    def test_with_a_router_the_binding_comes_from_the_chosen_option(self) -> None:
        from app.db.models import CredentialType
        from app.services import llm_service as llm_service_module
        from app.services.model_router import BoundOption, RouteDecision, RouterOption

        option = RouterOption(
            id="opt_2",
            label="Deep",
            credential_id=str(uuid.uuid4()),
            model="gpt-5",
            criteria="hard",
        )
        bound = BoundOption(
            option=option,
            credential_type="openai",
            api_key="sk-routed",
            base_url=None,
            credential_name="OpenAI prod",
            credential_uuid=uuid.uuid4(),
        )
        router = mock.Mock()
        router.label = "Auto Model"
        router.credential_id = str(uuid.uuid4())
        router.route.return_value = RouteDecision(option=option)

        service = self._service(
            credential_type=CredentialType.model_router, api_key="", router=router
        )
        with mock.patch.object(
            llm_service_module, "load_option_credential", return_value=bound
        ), mock.patch.object(
            llm_service_module, "create_openai_client", return_value=mock.sentinel.routed
        ):
            binding = service._resolve_turn(
                model="auto", system_instruction="s", message="m", tool_names=["search"]
            )

        router.route.assert_called_once_with(
            system_instruction="s", message="m", tool_names=["search"]
        )
        self.assertEqual(binding.model, "gpt-5")
        self.assertEqual(binding.provider, "OpenAI")
        self.assertEqual(binding.router_label, "Auto Model")
        self.assertEqual(binding.option_label, "Deep")
        self.assertEqual(binding.credential_name, "OpenAI prod")
        self.assertEqual(binding.credential_id, bound.credential_uuid)

    def test_each_resolved_turn_is_recorded_for_the_executor(self) -> None:
        from app.db.models import CredentialType
        from app.services import llm_service as llm_service_module
        from app.services.model_router import BoundOption, RouteDecision, RouterOption

        option = RouterOption(
            id="opt_1",
            label="Fast",
            credential_id=str(uuid.uuid4()),
            model="gpt-4o-mini",
            criteria="easy",
        )
        bound = BoundOption(
            option=option,
            credential_type="openai",
            api_key="sk",
            base_url=None,
            credential_name="OpenAI prod",
            credential_uuid=uuid.uuid4(),
        )
        router = mock.Mock()
        router.label = "Auto Model"
        router.credential_id = str(uuid.uuid4())
        router.route.return_value = RouteDecision(
            option=option, fallback=True, error="Decision model timed out"
        )

        service = self._service(
            credential_type=CredentialType.model_router, api_key="", router=router
        )
        with mock.patch.object(
            llm_service_module, "load_option_credential", return_value=bound
        ), mock.patch.object(
            llm_service_module, "create_openai_client", return_value=mock.sentinel.routed
        ):
            service._resolve_turn(
                model="auto", system_instruction=None, message="a", tool_names=None
            )
            service._resolve_turn(
                model="auto", system_instruction=None, message="b", tool_names=None
            )

        summary = service.model_routing_summary()
        self.assertEqual(summary["routerLabel"], "Auto Model")
        self.assertEqual(len(summary["calls"]), 2)
        self.assertEqual(summary["calls"][0]["model"], "gpt-4o-mini")
        self.assertEqual(summary["calls"][0]["option"], "Fast")
        self.assertTrue(summary["calls"][0]["fallback"])
        self.assertEqual(summary["calls"][0]["error"], "Decision model timed out")

    def test_no_router_means_no_routing_summary(self) -> None:
        self.assertIsNone(self._service().model_routing_summary())

    def test_a_router_with_the_responses_api_is_refused(self) -> None:
        from app.db.models import CredentialType

        with self.assertRaises(ValueError) as ctx:
            self._service(
                credential_type=CredentialType.model_router,
                api_key="",
                router=mock.Mock(),
                use_responses_api=True,
            )
        self.assertIn("Responses API", str(ctx.exception))
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py::TestResolveTurn -v
```

Expected: `TypeError: LLMService.__init__() got an unexpected keyword argument 'router'`.

- [ ] **Step 3: Add the imports and the binding type**

At the top of `backend/app/services/llm_service.py`, alongside the other `app.services` imports:

```python
from app.services.model_router import (
    ModelRouter,
    load_option_credential,
)
```

Above `class LLMService:`, add:

```python
@dataclass(frozen=True)
class TurnBinding:
    """The client, provider and model serving one provider request.

    Without a router this is the credential the caller passed and never changes.
    With a router it is re-derived before every request, which is what lets an agent
    tool loop move between models mid-run.
    """

    client: OpenAI
    provider: str
    model: str
    credential_id: uuid.UUID | None = None
    credential_name: str | None = None
    router_credential_id: uuid.UUID | None = None
    router_label: str | None = None
    option_label: str | None = None
    fallback: bool = False
    routing_error: str | None = None
```

`dataclass` is already imported in this module for `HumanReviewPause`; if it is not, add `from dataclasses import dataclass`.

- [ ] **Step 4: Accept the router and refuse the Responses API**

Replace `LLMService.__init__` with:

```python
    def __init__(
        self,
        credential_type: CredentialType,
        api_key: str,
        base_url: str | None = None,
        trace_context: LLMTraceContext | None = None,
        request_timeout: float = LLM_REQUEST_TIMEOUT,
        use_responses_api: bool = False,
        router: ModelRouter | None = None,
    ) -> None:
        if router is not None and use_responses_api:
            raise ValueError(
                "Auto Model does not support the Responses API. Turn the Responses API "
                "off, or pick a specific credential and model."
            )
        self.credential_type = credential_type
        self.api_key = api_key
        self.base_url = base_url
        self.trace_context = trace_context
        self.session_id = (trace_context.session_id if trace_context else None) or str(uuid.uuid4())
        self.request_timeout = request_timeout
        self.use_responses_api = use_responses_api
        self.router = router
        self._routed_calls: list[dict[str, Any]] = []
```

- [ ] **Step 5: Add `_resolve_turn` and the summary**

Directly after `_get_client`, add:

```python
    def _client_for(
        self, credential_type: str, api_key: str, base_url: str | None
    ) -> tuple[OpenAI, str]:
        """Build a provider client for an arbitrary credential, not just self's."""
        if credential_type == CredentialType.google.value:
            return create_openai_client(
                api_key=api_key,
                base_url=GOOGLE_OPENAI_BASE_URL,
                timeout=self.request_timeout,
            ), "Google"

        if credential_type == CredentialType.custom.value:
            if not base_url:
                raise ValueError("Base URL is required for custom provider")
            base = base_url.rstrip("/")
            if not base.endswith("/v1"):
                base = base + "/v1"
            return create_guarded_openai_client(
                api_key=api_key,
                base_url=base,
                subject="Custom LLM credential base URL",
                session_id=self.session_id,
                timeout=self.request_timeout,
            ), "Custom"

        if base_url:
            return create_guarded_openai_client(
                api_key=api_key,
                base_url=base_url,
                subject="LLM credential base URL",
                session_id=self.session_id,
                timeout=self.request_timeout,
            ), "OpenAI"
        return create_openai_client(
            api_key=api_key, timeout=self.request_timeout, session_id=self.session_id
        ), "OpenAI"

    def _resolve_turn(
        self,
        *,
        model: str,
        system_instruction: str | None,
        message: str | None,
        tool_names: list[str] | None,
    ) -> TurnBinding:
        """Bind the client, provider and model for the next provider request.

        With no router this is the static credential and the caller's model, which is
        the behaviour every existing caller already gets. With a router the decision
        model picks an option first; identical states reuse the previous decision, so
        a tool loop only pays for a decision when the conversation has moved.
        """
        if self.router is None:
            client, provider = self._get_client()
            return TurnBinding(
                client=client,
                provider=provider,
                model=model,
                credential_id=self.trace_context.credential_id if self.trace_context else None,
            )

        decision = self.router.route(
            system_instruction=system_instruction,
            message=message,
            tool_names=tool_names,
        )
        bound = load_option_credential(decision.option)
        client, provider = self._client_for(
            bound.credential_type, bound.api_key, bound.base_url
        )
        try:
            router_uuid: uuid.UUID | None = uuid.UUID(str(self.router.credential_id))
        except ValueError:
            router_uuid = None

        binding = TurnBinding(
            client=client,
            provider=provider,
            model=bound.option.model,
            credential_id=bound.credential_uuid,
            credential_name=bound.credential_name,
            router_credential_id=router_uuid,
            router_label=self.router.label,
            option_label=decision.option.label,
            fallback=decision.fallback,
            routing_error=decision.error,
        )
        self._routed_calls.append(
            {
                "model": binding.model,
                "option": binding.option_label,
                "credentialName": binding.credential_name,
                "fallback": binding.fallback,
                "error": binding.routing_error,
            }
        )
        return binding

    def model_routing_summary(self) -> dict[str, Any] | None:
        """What the executor writes into node metadata, or None when no router ran."""
        if self.router is None or not self._routed_calls:
            return None
        return {
            "routerLabel": self.router.label,
            "routerCredentialId": str(self.router.credential_id),
            "calls": copy.deepcopy(self._routed_calls),
        }
```

`GOOGLE_OPENAI_BASE_URL`, `create_openai_client` and `create_guarded_openai_client` are already imported in this module; confirm before adding anything.

- [ ] **Step 6: Route trace rows to the right credential**

Replace `_record_trace` so it takes the binding:

```python
    def _record_trace(
        self,
        request_type: str,
        provider: str,
        model: str | None,
        request: dict[str, Any],
        response: dict[str, Any] | None,
        error: str | None,
        elapsed_ms: float | None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        binding: TurnBinding | None = None,
    ) -> None:
        if not self.trace_context:
            return
        context = self.trace_context
        if binding is not None and binding.router_label is not None:
            # `replace` keeps `trace_ids` as the same list object, which the executor
            # reads back to link the node to its trace. Constructing a fresh
            # LLMTraceContext here would give it a new list and break that link.
            context = replace(
                context,
                credential_id=binding.credential_id or context.credential_id,
                router_credential_id=binding.router_credential_id,
                router_label=binding.router_label,
            )
        record_llm_trace(
            context=context,
            request_type=request_type,
            request=request,
            response=response,
            model=model,
            provider=provider,
            error=error,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            elapsed_ms=elapsed_ms,
        )
```

Add `from dataclasses import replace` to the module imports.

- [ ] **Step 7: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py -v
```

Expected: 9 passed.

- [ ] **Step 8: Verify**

```bash
cd backend && uv run ruff format . && uv run ruff check app/services/llm_service.py
```

Expected: no errors.

---

## Task 11: Route the single-shot `execute()` path

**Files:**
- Modify: `backend/app/services/llm_service.py:613-733`
- Test: `backend/tests/test_model_router_llm_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_model_router_llm_service.py`:

```python
class TestExecuteRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_execute_uses_the_routed_model_in_result_and_trace(self) -> None:
        from app.db.models import CredentialType
        from app.services import llm_service as llm_service_module
        from app.services.llm_service import LLMService, TurnBinding

        service = LLMService(
            credential_type=CredentialType.model_router,
            api_key="",
            router=mock.Mock(),
        )
        binding = TurnBinding(
            client=mock.Mock(),
            provider="OpenAI",
            model="gpt-5",
            credential_id=uuid.uuid4(),
            credential_name="OpenAI prod",
            router_credential_id=uuid.uuid4(),
            router_label="Auto Model",
            option_label="Deep",
        )
        turn = mock.Mock()
        turn.text = "routed answer"
        turn.prompt_tokens = 3
        turn.completion_tokens = 4
        turn.total_tokens = 7
        turn.raw_items = [mock.Mock()]

        recorded: list[dict] = []

        with mock.patch.object(service, "_resolve_turn", return_value=binding) as resolve, \
             mock.patch.object(
                 service, "_record_trace", side_effect=lambda **kw: recorded.append(kw)
             ), \
             mock.patch.object(
                 llm_service_module.asyncio, "to_thread", new=mock.AsyncMock(return_value=turn)
             ):
            result = await service.execute(
                model="auto",
                system_instruction="You are helpful.",
                user_message="Explain this diff.",
            )

        resolve.assert_called_once()
        self.assertEqual(resolve.call_args.kwargs["system_instruction"], "You are helpful.")
        self.assertEqual(resolve.call_args.kwargs["message"], "Explain this diff.")
        self.assertEqual(result["model"], "gpt-5")
        self.assertEqual(recorded[-1]["model"], "gpt-5")
        self.assertIs(recorded[-1]["binding"], binding)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py::TestExecuteRoutes -v
```

Expected: FAIL — `result["model"]` is `"auto"`, and `_record_trace` receives no `binding`.

- [ ] **Step 3: Rewire `execute()`**

In `LLMService.execute`, replace the first two lines of the body:

```python
        client, provider = self._get_client()
        transport = self._get_transport()
```

with:

```python
        binding = self._resolve_turn(
            model=model,
            system_instruction=system_instruction,
            message=user_message,
            tool_names=None,
        )
        client, provider, model = binding.client, binding.provider, binding.model
        transport = self._get_transport()
```

Then, in the same method, add `binding=binding` to both `self._record_trace(...)` calls (the failure one inside the retry loop and the success one at the end). Leave every other line as it is: rebinding `model` at the top means the `result["model"]` value, the `_log_request` call and the trace all pick up the routed model with no further edits.

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Verify the unrouted path still behaves**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "llm" -v
cd backend && uv run ruff format . && uv run ruff check app/services/llm_service.py
```

Expected: all pass, no lint errors.

---

## Task 12: Route every turn of the tool loop

**Files:**
- Modify: `backend/app/services/llm_service.py:978-1280`
- Test: `backend/tests/test_model_router_llm_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_model_router_llm_service.py`:

```python
class TestExecuteWithToolsRoutesEachTurn(unittest.IsolatedAsyncioTestCase):
    async def test_two_turns_can_land_on_two_models(self) -> None:
        from app.db.models import CredentialType
        from app.services import llm_service as llm_service_module
        from app.services.llm_service import LLMService, TurnBinding

        service = LLMService(
            credential_type=CredentialType.model_router,
            api_key="",
            router=mock.Mock(),
        )

        def _binding(model: str) -> TurnBinding:
            return TurnBinding(
                client=mock.Mock(),
                provider="OpenAI",
                model=model,
                credential_id=uuid.uuid4(),
                credential_name="OpenAI prod",
                router_credential_id=uuid.uuid4(),
                router_label="Auto Model",
                option_label=model,
            )

        first_turn = mock.Mock()
        first_turn.text = None
        first_turn.prompt_tokens = 1
        first_turn.completion_tokens = 1
        first_turn.total_tokens = 2
        first_turn.raw_items = [mock.Mock()]
        first_turn.tool_calls = [
            {"id": "call_1", "name": "search", "arguments": {"q": "x"}}
        ]

        second_turn = mock.Mock()
        second_turn.text = "final"
        second_turn.prompt_tokens = 1
        second_turn.completion_tokens = 1
        second_turn.total_tokens = 2
        second_turn.raw_items = [mock.Mock()]
        second_turn.tool_calls = []

        with mock.patch.object(
            service,
            "_resolve_turn",
            side_effect=[_binding("gpt-4o-mini"), _binding("gpt-5")],
        ) as resolve, mock.patch.object(service, "_record_trace"), mock.patch.object(
            llm_service_module.asyncio,
            "to_thread",
            new=mock.AsyncMock(side_effect=[first_turn, second_turn]),
        ):
            result = await service.execute_with_tools(
                model="auto",
                system_instruction="sys",
                user_message="go",
                tools=[{"name": "search", "description": "", "parameters": {}}],
                tool_executor=lambda *args: "tool output",
                max_tool_iterations=4,
            )

        self.assertEqual(resolve.call_count, 2)
        # Turn one routes on the user message; turn two routes on the tool result.
        self.assertEqual(resolve.call_args_list[0].kwargs["message"], "go")
        self.assertIn("tool output", str(resolve.call_args_list[1].kwargs["message"]))
        self.assertEqual(resolve.call_args_list[0].kwargs["tool_names"], ["search"])
        self.assertEqual(result["model"], "gpt-5")
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py::TestExecuteWithToolsRoutesEachTurn -v
```

Expected: `resolve.call_count` is 0, because `execute_with_tools` still calls `_get_client()` once.

- [ ] **Step 3: Rewire the loop**

In `execute_with_tools`:

1. Delete the `client, provider = self._get_client()` line at the top of the body. Keep `transport = self._get_transport()`.

2. After `tools_by_name = {t["name"]: t for t in tools}`, add the two pieces of loop state:

```python
        tool_names = [t["name"] for t in tools]
        # The first turn routes on the user's message; later turns route on what the
        # last tool returned, which is what makes per-turn routing mean anything.
        routing_message: str | None = user_message
        binding: TurnBinding | None = None
        provider = ""
        _context_limit: int | None = None
```

3. Delete the `_context_limit = get_context_limit(model, client)` line that currently sits above the loop, and keep the `from app.services.context_compressor import get_context_limit` import where it is.

4. Inside the loop, immediately before the `opts = RequestOpts(` block that precedes `transport.create`, insert:

```python
            binding = self._resolve_turn(
                model=model,
                system_instruction=system_instruction,
                message=routing_message,
                tool_names=tool_names,
            )
            client, provider, turn_model = binding.client, binding.provider, binding.model
            _context_limit = get_context_limit(turn_model, client)
```

5. Inside the loop, replace every `model=model` passed to `transport.create`, to `_record_trace`, and into any `result` dict with `turn_model`. Replace `model` in the `logger.info` retry message too. The `model` parameter itself stays untouched, because it is what `_resolve_turn` is asked to fall back to when there is no router.

6. Add `binding=binding` to every `self._record_trace(...)` call inside `execute_with_tools`, including the `context.compression` one.

7. Feed later turns with what the last turn's tools returned. Do **not** hook into the
   `slot_results` machinery: it is intricate, and every finished tool already lands in
   `tool_calls_collected`. Track a cursor over that list instead.

   Add next to the other loop state from step 3.2:

```python
        routed_tool_cursor = len(tool_calls_collected)
```

   and, immediately before the `binding = self._resolve_turn(` call added in step 3.4:

```python
            # Turn one routes on the user's message; later turns route on what the last
            # turn's tools returned, which is what makes per-turn routing mean anything.
            new_tool_entries = tool_calls_collected[routed_tool_cursor:]
            if new_tool_entries:
                routing_message = _routing_message_from_tool_results(new_tool_entries)
                routed_tool_cursor = len(tool_calls_collected)
```

   Add this helper above `class LLMService`:

```python
def _routing_message_from_tool_results(tool_entries: list[dict[str, Any]]) -> str:
    """Condense a turn's tool output into the text the router reads next.

    Only the text matters for a routing decision, and `build_routing_state` truncates
    it again, so this stays a cheap join rather than a full serialisation.
    """
    parts: list[str] = []
    for entry in tool_entries or []:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("result") or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)[:ROUTER_STATE_MESSAGE_CHARS]
```

   and import `ROUTER_STATE_MESSAGE_CHARS` from `app.services.model_router`. Starting the
   cursor at the current length rather than zero matters on a resumed agent: the entries
   restored from `initial_tool_calls` describe a turn that already ran, so they must not
   be replayed as this turn's routing input.

8. In `_build_error_result`, replace `"model": model` with `"model": binding.model if binding is not None else model`.

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Verify the agent path did not regress**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "agent or tool" -v
cd backend && uv run ruff format . && uv run ruff check app/services/llm_service.py
```

Expected: all pass, no lint errors. If any agent test fails on a missing `provider` or `client`, re-check step 3.2 — those names must be defined before the loop for the compression branch that runs before the first `_resolve_turn`.

---

## Task 13: Refuse batch and image, and pass the router through

**Files:**
- Modify: `backend/app/services/llm_service.py` (`execute_batch`, `execute_image_generation`, `execute_image_edit`, `execute_llm`, `execute_llm_with_tools`, `execute_llm_batch`)
- Test: `backend/tests/test_model_router_llm_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_model_router_llm_service.py`:

```python
class TestRouterRejections(unittest.IsolatedAsyncioTestCase):
    def _router_service(self) -> object:
        from app.db.models import CredentialType
        from app.services.llm_service import LLMService

        return LLMService(
            credential_type=CredentialType.model_router, api_key="", router=mock.Mock()
        )

    async def test_batch_is_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self._router_service().execute_batch(
                model="auto",
                system_instruction=None,
                user_messages=["a", "b"],
            )
        self.assertIn("Batch", str(ctx.exception))

    async def test_image_generation_is_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self._router_service().execute_image_generation(
                model="auto", prompt="a cat"
            )
        self.assertIn("image", str(ctx.exception).lower())

    async def test_image_edit_is_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self._router_service().execute_image_edit(
                model="auto", prompt="a cat", image_input="data:image/png;base64,AAA"
            )
        self.assertIn("image", str(ctx.exception).lower())


class TestRouterPassesThroughModuleFunctions(unittest.IsolatedAsyncioTestCase):
    async def test_execute_llm_forwards_the_router(self) -> None:
        from app.services import llm_service as llm_service_module

        router = mock.Mock()
        captured: dict = {}

        class FakeService:
            def __init__(self, *args: object, **kwargs: object) -> None:
                captured.update(kwargs)

            async def execute(self, **kwargs: object) -> dict:
                return {"text": "ok", "model": "gpt-5"}

        with mock.patch.object(llm_service_module, "LLMService", FakeService):
            await llm_service_module.execute_llm(
                credential_type="model_router",
                api_key="",
                base_url=None,
                model="auto",
                system_instruction=None,
                user_message="hi",
                router=router,
            )

        self.assertIs(captured["router"], router)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py::TestRouterRejections tests/test_model_router_llm_service.py::TestRouterPassesThroughModuleFunctions -v
```

Expected: `TypeError: execute_llm() got an unexpected keyword argument 'router'`, and the rejections do not raise.

- [ ] **Step 3: Add the guards**

At the very top of `LLMService.execute_batch`:

```python
        if self.router is not None:
            raise ValueError(
                "Batch mode is not available for Model Router credentials: a batch job "
                "runs against one fixed model. Pick a specific credential and model."
            )
```

At the top of both `execute_image_generation` and `execute_image_edit`:

```python
        if self.router is not None:
            raise ValueError(
                "Model Router credentials cannot generate or edit images. Pick a "
                "specific credential and image model."
            )
```

- [ ] **Step 4: Thread the router through the module functions**

Add `router: ModelRouter | None = None` as the last parameter of `execute_llm`, `execute_llm_with_tools` and `execute_llm_batch`, and pass `router=router` into the `LLMService(...)` construction in each. `execute_llm_batch` keeps the parameter so a caller does not have to special-case it; the guard inside `execute_batch` produces the error.

- [ ] **Step 5: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py -v
```

Expected: 15 passed.

- [ ] **Step 6: Verify**

```bash
cd backend && uv run ruff format . && uv run ruff check app/services/llm_service.py
```

Expected: no errors.

---

# Phase 5 — Executor and the other call sites

## Task 14: A one-line router builder for callers

**Files:**
- Modify: `backend/app/services/model_router.py`
- Test: `backend/tests/test_model_router.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_model_router.py`:

```python
class TestBuildRouterForCredential(unittest.TestCase):
    def test_returns_none_for_a_plain_llm_credential(self) -> None:
        self.assertIsNone(
            build_router_for_credential(
                credential_id="x",
                credential_name="OpenAI prod",
                credential_type="openai",
                config={"api_key": "sk"},
            )
        )

    def test_builds_a_router_labelled_with_the_credential_name(self) -> None:
        router = build_router_for_credential(
            credential_id="99999999-9999-9999-9999-999999999999",
            credential_name="Auto Model",
            credential_type="model_router",
            config=_valid_config(),
        )
        self.assertIsInstance(router, ModelRouter)
        self.assertEqual(router.label, "Auto Model")
        self.assertEqual(len(router.config.options), 2)

    def test_a_broken_config_raises_a_router_error(self) -> None:
        raw = _valid_config()
        raw["options"] = []
        with self.assertRaises(ModelRouterConfigError):
            build_router_for_credential(
                credential_id="99999999-9999-9999-9999-999999999999",
                credential_name="Auto Model",
                credential_type="model_router",
                config=raw,
            )
```

Add `build_router_for_credential` to the import list.

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router.py::TestBuildRouterForCredential -v
```

Expected: `ImportError: cannot import name 'build_router_for_credential'`.

- [ ] **Step 3: Implement**

Append to `backend/app/services/model_router.py`:

```python
def build_router_for_credential(
    *,
    credential_id: str,
    credential_name: str,
    credential_type: str,
    config: dict,
    trace_context: object | None = None,
) -> ModelRouter | None:
    """Return a router for a router credential, or None for anything else.

    Every caller that loads an LLM credential goes through this, so adding a new
    model-request surface means one call here rather than a new branch per surface.
    """
    if credential_type != CredentialType.model_router.value:
        return None
    return ModelRouter(
        credential_id=credential_id,
        label=credential_name,
        config=parse_router_config(config),
        trace_context=trace_context,
    )
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router.py -v
```

Expected: 37 passed.

- [ ] **Step 5: Verify**

```bash
cd backend && uv run ruff format . && uv run ruff check app/services/model_router.py
```

Expected: no errors.

---

## Task 15: Wire the `llm` node path

**Files:**
- Modify: `backend/app/services/workflow_executor.py:3363-3661` (`_execute_llm_node`), `:324-329` (`NodeTraceableExecutionError`), `:7288-7300` (node metadata)
- Modify: `backend/app/services/node_execution/nodes/llm_node.py`
- Test: `backend/tests/test_model_router_llm_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_model_router_llm_service.py`:

```python
class TestExecutorLlmNodeRouting(unittest.TestCase):
    def test_routing_summary_reaches_node_metadata(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        output = {
            "text": "answer",
            "model": "gpt-5",
            "_model_routing": {
                "routerLabel": "Auto Model",
                "routerCredentialId": str(uuid.uuid4()),
                "calls": [
                    {
                        "model": "gpt-5",
                        "option": "Deep",
                        "credentialName": "OpenAI prod",
                        "fallback": False,
                        "error": None,
                    }
                ],
            },
        }
        metadata: dict = {}
        routing = WorkflowExecutor._pop_model_routing(output)
        if routing:
            metadata["model_routing"] = routing

        self.assertNotIn("_model_routing", output)
        self.assertEqual(metadata["model_routing"]["routerLabel"], "Auto Model")
        self.assertEqual(metadata["model_routing"]["calls"][0]["model"], "gpt-5")

    def test_pop_ignores_a_non_dict(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        self.assertIsNone(WorkflowExecutor._pop_model_routing({"_model_routing": "nope"}))
        self.assertIsNone(WorkflowExecutor._pop_model_routing({}))

    def test_traceable_error_carries_routing(self) -> None:
        from app.services.workflow_executor import NodeTraceableExecutionError

        error = NodeTraceableExecutionError(
            "boom", "trace-1", model_routing={"routerLabel": "Auto Model", "calls": []}
        )
        self.assertEqual(error.trace_id, "trace-1")
        self.assertEqual(error.model_routing["routerLabel"], "Auto Model")

    def test_traceable_error_routing_defaults_to_none(self) -> None:
        from app.services.workflow_executor import NodeTraceableExecutionError

        self.assertIsNone(NodeTraceableExecutionError("boom", "trace-1").model_routing)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py::TestExecutorLlmNodeRouting -v
```

Expected: `AttributeError: type object 'WorkflowExecutor' has no attribute '_pop_model_routing'`.

- [ ] **Step 3: Add the error field and the metadata helper**

In `backend/app/services/workflow_executor.py`, replace `NodeTraceableExecutionError`:

```python
class NodeTraceableExecutionError(ValueError):
    """Raised when a node error has a trace entry that should stay linked."""

    def __init__(
        self,
        message: str,
        trace_id: str,
        model_routing: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.trace_id = trace_id
        self.model_routing = model_routing
```

Next to `_pop_internal_trace_id`, add:

```python
    @staticmethod
    def _pop_model_routing(output: dict[str, Any]) -> dict[str, Any] | None:
        """Take the router summary off a node output so it lands in metadata instead."""
        routing = output.pop("_model_routing", None)
        return routing if isinstance(routing, dict) else None
```

- [ ] **Step 4: Write the routing summary into node metadata**

In `_execute_node_logic`, directly after the `trace_id = self._pop_internal_trace_id(output)` block:

```python
            model_routing = self._pop_model_routing(output)
            if model_routing:
                metadata["model_routing"] = model_routing
```

And in the error path where `error_metadata` is built from `last_error`:

```python
        routing = getattr(last_error, "model_routing", None)
        if isinstance(routing, dict):
            error_metadata["model_routing"] = routing
```

- [ ] **Step 5: Build the router in `_execute_llm_node`**

Inside the `for attempt_idx, (cid, mod) in enumerate(attempts):` loop, the credential is loaded into `credential_type`, `api_key` and `base_url`. Replace that block and the guard beneath it with:

```python
            credential_type = None
            credential_name = ""
            api_key = None
            base_url = None
            credential_config: dict = {}
            try:
                with SessionLocal() as db:
                    cred = self._get_accessible_credential(db, cid)
                    if cred:
                        credential_type = cred.type
                        credential_name = cred.name
                        credential_config = decrypt_config(cred.encrypted_config)
                        api_key = credential_config.get("api_key")
                        base_url = credential_config.get("base_url")
            except Exception as e:
                last_error = e
                last_model = mod
                continue

            trace_context = self._build_llm_trace_context(cid, node_id)

            router = None
            if credential_type is not None:
                try:
                    router = build_router_for_credential(
                        credential_id=cid,
                        credential_name=credential_name,
                        credential_type=credential_type.value,
                        config=credential_config,
                        trace_context=trace_context,
                    )
                except ModelRouterConfigError as e:
                    last_error = e
                    last_model = mod
                    continue

            if not api_key and router is None:
                last_error = ValueError("Credential has no API key")
                last_model = mod
                continue
```

The existing `trace_context = self._build_llm_trace_context(cid, node_id)` line further down must be deleted, since it has moved above the router build.

Add to the module imports at the top of `workflow_executor.py`:

```python
from app.services.model_router import ModelRouterConfigError, build_router_for_credential
```

- [ ] **Step 6: Pass the router and collect the summary**

Add `router=router` to the `execute_llm(...)` and `execute_llm_batch(...)` calls inside `_execute_llm_node`. For `execute_image_generation` / `execute_image_edit`, add a guard above the `if output_type == "image":` block instead:

```python
            if output_type == "image" and router is not None:
                last_error = ValueError(
                    "Model Router credentials cannot generate or edit images. "
                    "Pick a specific credential and image model."
                )
                last_model = mod
                continue
```

`execute_llm` already returns the result dict; the routing summary is attached by `LLMService`. Add that attachment at the end of `LLMService.execute` and `LLMService.execute_with_tools`, right before each `return result`:

```python
        routing_summary = self.model_routing_summary()
        if routing_summary:
            result["_model_routing"] = routing_summary
```

Apply it to every `return result` in those two methods, including the early structured-content return and `_build_error_result`.

- [ ] **Step 7: Pass routing through the node handler's error path**

In `backend/app/services/node_execution/nodes/llm_node.py`, the handler pops the trace id before raising. Change the two `NodeTraceableExecutionError` raises so routing survives a failure:

```python
    trace_id = self._pop_internal_trace_id(output)
    model_routing = output.get("_model_routing")
    if output.get("error"):
        if trace_id:
            raise NodeTraceableExecutionError(
                f"LLM error: {output.get('error')}",
                trace_id,
                model_routing=model_routing if isinstance(model_routing, dict) else None,
            )
        raise ValueError(f"LLM error: {output.get('error')}")
```

Do the same for the JSON parse error raise further down.

- [ ] **Step 8: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py -v
```

Expected: 19 passed.

- [ ] **Step 9: Verify the executor did not regress**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "executor or llm_node or workflow" -v
cd backend && uv run ruff format . && uv run ruff check app/services/workflow_executor.py app/services/node_execution/nodes/llm_node.py
```

Expected: all pass, no lint errors.

---

## Task 16: Wire the `agent` node path

**Files:**
- Modify: `backend/app/services/workflow_executor.py:5455-5600` (the agent attempt loop)
- Test: `backend/tests/test_model_router_llm_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_model_router_llm_service.py`:

```python
class TestAgentPathBuildsRouter(unittest.TestCase):
    def test_agent_loop_builds_a_router_and_forwards_it(self) -> None:
        import inspect

        from app.services import workflow_executor

        source = inspect.getsource(workflow_executor.WorkflowExecutor)
        # Both agent entry points must forward the router, or an agent on Auto Model
        # would silently run on a credential with no key.
        self.assertGreaterEqual(source.count("build_router_for_credential"), 2)
        self.assertGreaterEqual(source.count("router=router"), 3)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py::TestAgentPathBuildsRouter -v
```

Expected: FAIL, count is 1.

- [ ] **Step 3: Apply the same edit to the agent loop**

The agent attempt loop has the identical shape as Task 15 step 5: it loads `credential_type`, `api_key`, `base_url`, guards on `api_key`, then builds `trace_context`. Make the same three changes:

1. Capture `credential_name` and the decrypted `credential_config`.
2. Move `trace_context = self._build_llm_trace_context(cid, node_id)` above the router build, then build the router with `build_router_for_credential(...)`, `continue`-ing on `ModelRouterConfigError` into `agent_last_error`.
3. Change the guard to `if not api_key and router is None:`.

Then add `router=router` to both the `execute_llm_with_tools(...)` and `execute_llm(...)` calls in that loop.

The HITL MCP policy classifier (`self._classify_hitl_mcp_policy_with_model`) runs before the main call and takes `credential_type`, `api_key`, `base_url` and `model` directly. It is a fixed classification call, not a user request, so it does not route. Guard it:

```python
            if hitl_enabled and mcp_tool_names and router is None:
```

and leave `effective_hitl_mcp_policy = fallback_hitl_mcp_policy` in place for the router case. Add a one-line comment saying why:

```python
            # A fixed classification call, so it never routes; on Auto Model the
            # configured fallback policy is used instead.
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py -v
```

Expected: 20 passed.

- [ ] **Step 5: Verify**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "agent" -v
cd backend && uv run ruff format . && uv run ruff check app/services/workflow_executor.py
```

Expected: all pass, no lint errors.

---

## Task 17: Wire the remaining model-request surfaces

Eight modules load an LLM credential and call `execute_llm` themselves. Each needs the same two lines so Auto Model works there.

**Files:**
- Modify: `backend/app/api/playwright.py:270,290,474,496`
- Modify: `backend/app/api/data_tables.py:1316`
- Modify: `backend/app/api/decisions.py:185`
- Modify: `backend/app/api/dashboards.py:91`
- Modify: `backend/app/api/expressions.py:299`
- Modify: `backend/app/services/eval_service.py:446,496`
- Modify: `backend/app/services/board_mapper_service.py:81,190`
- Modify: `backend/app/services/agent_memory_service.py:745,755`
- Test: `backend/tests/test_model_router_llm_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_model_router_llm_service.py`:

```python
class TestEverySurfaceForwardsTheRouter(unittest.TestCase):
    MODULES = (
        "app.api.playwright",
        "app.api.data_tables",
        "app.api.decisions",
        "app.api.dashboards",
        "app.api.expressions",
        "app.services.eval_service",
        "app.services.board_mapper_service",
        "app.services.agent_memory_service",
    )

    def test_each_llm_surface_builds_and_forwards_a_router(self) -> None:
        import importlib
        import inspect

        missing: list[str] = []
        for name in self.MODULES:
            source = inspect.getsource(importlib.import_module(name))
            if "build_router_for_credential" not in source or "router=router" not in source:
                missing.append(name)
        self.assertEqual(missing, [], f"surfaces not wired for Auto Model: {missing}")
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py::TestEverySurfaceForwardsTheRouter -v
```

Expected: FAIL listing all eight modules.

- [ ] **Step 3: Apply the same edit in each module**

In each module, find where the credential is decrypted and `execute_llm` is called. The shape is always the same. Read the existing code, then insert directly after the decrypt:

```python
    router = build_router_for_credential(
        credential_id=str(credential.id),
        credential_name=credential.name,
        credential_type=credential.type.value,
        config=config,
        trace_context=trace_context,
    )
```

using whatever the module already names its credential, config and trace context variables — do not rename them. Then add `router=router` to the `execute_llm(...)` call, and relax any "no API key" guard to `if not api_key and router is None:`.

Add the import to each module:

```python
from app.services.model_router import build_router_for_credential
```

In `app/api/decisions.py` the `execute_llm` call generates decision questions with an LLM credential; it routes like any other. The decision node's own `credentialId` is a `decision` credential and is untouched.

For the four call sites in `app/api/playwright.py`, build the router once per request and reuse it across all four calls in that request, so a generation and its repair pass share one routing cache.

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py -v
```

Expected: 21 passed.

- [ ] **Step 5: Verify**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "playwright or data_table or dashboard or expression or eval or board or memory or decision" -v
cd backend && uv run ruff format . && uv run ruff check app/
```

Expected: all pass, no lint errors.

---

## Task 18: Return the router in the traces API

**Files:**
- Modify: `backend/app/models/schemas.py:511-536`
- Modify: `backend/app/api/traces.py:100-165`
- Test: `backend/tests/test_model_router_llm_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_model_router_llm_service.py`:

```python
class TestTraceApiSurface(unittest.TestCase):
    def test_list_item_carries_the_router_columns(self) -> None:
        from app.models.schemas import LLMTraceListItem

        item = LLMTraceListItem(
            id=uuid.uuid4(),
            created_at=__import__("datetime").datetime.now(),
            source="workflow",
            request_type="chat.completions",
            provider="OpenAI",
            model="gpt-5",
            status="success",
            router_credential_id=uuid.uuid4(),
            router_label="Auto Model",
        )
        self.assertEqual(item.router_label, "Auto Model")

    def test_router_fields_default_to_none(self) -> None:
        from app.models.schemas import LLMTraceListItem

        item = LLMTraceListItem(
            id=uuid.uuid4(),
            created_at=__import__("datetime").datetime.now(),
            source="workflow",
            request_type="chat.completions",
            status="success",
        )
        self.assertIsNone(item.router_label)
        self.assertIsNone(item.router_credential_id)

    def test_trace_search_covers_the_router_label(self) -> None:
        import inspect

        from app.api import traces

        source = inspect.getsource(traces)
        self.assertIn("LLMTrace.router_label.ilike(pattern)", source)
        self.assertIn("router_label=trace.router_label", source)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py::TestTraceApiSurface -v
```

Expected: `ValidationError: unexpected keyword argument 'router_label'`.

- [ ] **Step 3: Add the schema fields**

In `backend/app/models/schemas.py`, inside `class LLMTraceListItem`, after `credential_name`:

```python
    # Set when a Model Router chose the model. `model` above is what actually ran.
    router_credential_id: uuid.UUID | None = None
    router_label: str | None = None
```

`LLMTraceDetailResponse` extends `LLMTraceListItem`, so it inherits them.

- [ ] **Step 4: Populate and search them**

In `backend/app/api/traces.py`, in the search filter that currently lists `LLMTrace.model.ilike(pattern)` in the trace list query, add:

```python
                LLMTrace.router_label.ilike(pattern),
```

Do the same in the `_apply_search` filter used by `/stats`.

Then in the `LLMTraceListItem(...)` construction, after `credential_name=credential_name`:

```python
                router_credential_id=trace.router_credential_id,
                router_label=trace.router_label,
```

Add the same two lines wherever the detail endpoint builds its response.

Leave `by_model` grouping alone: it groups on `LLMTrace.model`, which is the real model, and that is deliberate.

- [ ] **Step 5: Run to verify pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_model_router_llm_service.py -v
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "trace" -v
```

Expected: all pass.

- [ ] **Step 6: Verify**

```bash
cd backend && uv run ruff format . && uv run ruff check app/api/traces.py app/models/schemas.py
```

Expected: no errors.

---

## Task 19: Tell the workflow assistant about Auto Model

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py`

- [ ] **Step 1: Add the paragraph**

`workflow_dsl_prompt.py` keeps the node reference inside one triple-quoted
`WORKFLOW_DSL_SYSTEM_PROMPT` string; the decision node added itself as a `### 5b.` section
there (see `git show f924cf4d -- backend/app/services/workflow_dsl_prompt.py`). Follow
that: add a section **inside that string**, directly after the `llm` and `agent` node
documentation. Do not create a new module-level constant.

```markdown
### Auto Model (Model Router credentials)

A `model_router` credential picks the model per request using a decision model, so it
appears in the same credential list as OpenAI, Google and Custom. Its only model id is
`auto`. Set `credentialId` to the router and `model` to `"auto"` when the user asks for
automatic model selection, cost-aware routing, or "pick the best model for the job".

Auto Model cannot be combined with `responsesApiEnabled`, `batchModeEnabled`, or
`outputType: "image"`. If the user wants any of those, use a specific credential and
model instead.
```

- [ ] **Step 2: Verify the prompt still builds**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "dsl or prompt" -v
cd backend && uv run ruff format . && uv run ruff check app/services/workflow_dsl_prompt.py
```

Expected: all pass, no lint errors.

---

# Phase 6 — Frontend

## Task 20: Types, labels and the shared config helper

**Files:**
- Modify: `frontend/src/types/credential.ts`
- Create: `frontend/src/components/Credentials/modelRouter/modelRouterConfig.ts`
- Test: `frontend/src/components/Credentials/modelRouter/modelRouterConfig.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/Credentials/modelRouter/modelRouterConfig.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
  buildModelRouterConfig,
  createEmptyOption,
  emptyModelRouterForm,
  validateModelRouterForm,
  type ModelRouterForm,
} from "./modelRouterConfig";

function validForm(): ModelRouterForm {
  return {
    decisionCredentialId: "dec-1",
    decisionModel: "jev-latest",
    routingInstructions: "Pick the cheapest model that works.",
    options: [
      {
        id: "opt_1",
        label: "Fast",
        credentialId: "cred-1",
        model: "gpt-4o-mini",
        criteria: "Short questions.",
        isDefault: true,
      },
      {
        id: "opt_2",
        label: "Deep",
        credentialId: "cred-2",
        model: "gpt-5",
        criteria: "Hard questions.",
        isDefault: false,
      },
    ],
  };
}

describe("emptyModelRouterForm", () => {
  it("starts with two option rows so the shape is obvious", () => {
    const form = emptyModelRouterForm();
    expect(form.options).toHaveLength(2);
    expect(form.decisionCredentialId).toBe("");
    expect(form.routingInstructions.length).toBeGreaterThan(0);
  });
});

describe("createEmptyOption", () => {
  it("gives every row a distinct id", () => {
    expect(createEmptyOption().id).not.toBe(createEmptyOption().id);
  });
});

describe("validateModelRouterForm", () => {
  it("accepts a complete form", () => {
    expect(validateModelRouterForm(validForm())).toBeNull();
  });

  it("requires a decision credential", () => {
    const form = validForm();
    form.decisionCredentialId = "";
    expect(validateModelRouterForm(form)).toMatch(/decision model credential/i);
  });

  it("requires a decision model", () => {
    const form = validForm();
    form.decisionModel = "  ";
    expect(validateModelRouterForm(form)).toMatch(/decision model/i);
  });

  it("requires at least two options", () => {
    const form = validForm();
    form.options = form.options.slice(0, 1);
    expect(validateModelRouterForm(form)).toMatch(/two/i);
  });

  it("requires a name on every option", () => {
    const form = validForm();
    form.options[1].label = "";
    expect(validateModelRouterForm(form)).toMatch(/name/i);
  });

  it("rejects duplicate option names regardless of case", () => {
    const form = validForm();
    form.options[1].label = "fast";
    expect(validateModelRouterForm(form)).toMatch(/same name/i);
  });

  it("requires a credential and a model on every option", () => {
    const missingCredential = validForm();
    missingCredential.options[0].credentialId = "";
    expect(validateModelRouterForm(missingCredential)).toMatch(/credential/i);

    const missingModel = validForm();
    missingModel.options[1].model = "";
    expect(validateModelRouterForm(missingModel)).toMatch(/model/i);
  });

  it("allows zero defaults but not two", () => {
    const noDefault = validForm();
    noDefault.options[0].isDefault = false;
    expect(validateModelRouterForm(noDefault)).toBeNull();

    const twoDefaults = validForm();
    twoDefaults.options[1].isDefault = true;
    expect(validateModelRouterForm(twoDefaults)).toMatch(/one option/i);
  });
});

describe("buildModelRouterConfig", () => {
  it("emits the snake_case payload the API stores", () => {
    expect(buildModelRouterConfig(validForm())).toEqual({
      decision_credential_id: "dec-1",
      decision_model: "jev-latest",
      routing_instructions: "Pick the cheapest model that works.",
      options: [
        {
          id: "opt_1",
          label: "Fast",
          credential_id: "cred-1",
          model: "gpt-4o-mini",
          criteria: "Short questions.",
          is_default: true,
        },
        {
          id: "opt_2",
          label: "Deep",
          credential_id: "cred-2",
          model: "gpt-5",
          criteria: "Hard questions.",
          is_default: false,
        },
      ],
    });
  });

  it("trims every text field", () => {
    const form = validForm();
    form.decisionModel = "  jev-latest  ";
    form.options[0].label = "  Fast  ";
    const config = buildModelRouterConfig(form);
    expect(config.decision_model).toBe("jev-latest");
    expect(config.options[0].label).toBe("Fast");
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd frontend && bun run test src/components/Credentials/modelRouter/modelRouterConfig.test.ts
```

Expected: `Failed to resolve import "./modelRouterConfig"`.

- [ ] **Step 3: Write the helper**

Create `frontend/src/components/Credentials/modelRouter/modelRouterConfig.ts`:

```ts
export interface ModelRouterOptionForm {
  id: string;
  label: string;
  credentialId: string;
  model: string;
  criteria: string;
  isDefault: boolean;
}

export interface ModelRouterForm {
  decisionCredentialId: string;
  decisionModel: string;
  routingInstructions: string;
  options: ModelRouterOptionForm[];
}

export interface ModelRouterOptionConfig {
  id: string;
  label: string;
  credential_id: string;
  model: string;
  criteria: string;
  is_default: boolean;
}

export interface ModelRouterConfig {
  decision_credential_id: string;
  decision_model: string;
  routing_instructions: string;
  options: ModelRouterOptionConfig[];
}

export const DEFAULT_ROUTING_INSTRUCTIONS =
  "Choose the model best suited to this request. Read each option's criteria and pick the one whose criteria the request matches. When several fit, prefer the cheaper option.";

let optionCounter = 0;

export function createEmptyOption(): ModelRouterOptionForm {
  optionCounter += 1;
  return {
    id: `opt_${Date.now()}_${optionCounter}`,
    label: "",
    credentialId: "",
    model: "",
    criteria: "",
    isDefault: false,
  };
}

export function emptyModelRouterForm(): ModelRouterForm {
  return {
    decisionCredentialId: "",
    decisionModel: "",
    routingInstructions: DEFAULT_ROUTING_INSTRUCTIONS,
    options: [createEmptyOption(), createEmptyOption()],
  };
}

/** Mirrors `parse_router_config` on the backend so the dialog fails before the request. */
export function validateModelRouterForm(form: ModelRouterForm): string | null {
  if (!form.decisionCredentialId.trim()) return "Pick a decision model credential.";
  if (!form.decisionModel.trim()) return "Enter the decision model to use.";
  if (form.options.length < 2) {
    return "Add at least two model options; with one there is nothing to route.";
  }

  const seen = new Set<string>();
  for (const option of form.options) {
    const label = option.label.trim();
    if (!label) return "Every model option needs a name.";
    const lowered = label.toLowerCase();
    if (seen.has(lowered)) {
      return `Two model options share the same name "${label}". Names are what the decision model picks between.`;
    }
    seen.add(lowered);
    if (!option.credentialId.trim()) return `Model option "${label}" needs a credential.`;
    if (!option.model.trim()) return `Model option "${label}" needs a model.`;
  }

  if (form.options.filter((option) => option.isDefault).length > 1) {
    return "Only one option can be the fallback used when routing fails.";
  }
  return null;
}

export function buildModelRouterConfig(form: ModelRouterForm): ModelRouterConfig {
  return {
    decision_credential_id: form.decisionCredentialId.trim(),
    decision_model: form.decisionModel.trim(),
    routing_instructions: form.routingInstructions.trim(),
    options: form.options.map((option) => ({
      id: option.id,
      label: option.label.trim(),
      credential_id: option.credentialId.trim(),
      model: option.model.trim(),
      criteria: option.criteria.trim(),
      is_default: option.isDefault,
    })),
  };
}
```

- [ ] **Step 4: Add the credential type**

In `frontend/src/types/credential.ts`:

1. Add `| "model_router"` to the `CredentialType` union, after `| "decision"`.
2. Add to `CREDENTIAL_TYPE_LABELS`: `model_router: "Model Router (Auto Model)",`
3. Add to `CREDENTIAL_TYPE_DESCRIPTIONS`: `model_router: "Let a decision model pick which of your models serves each request",`
4. Add the router fields to the trace interface used by `TracesPanel.vue` (`LLMTraceListItem` or equivalent):

```ts
  router_credential_id?: string | null;
  router_label?: string | null;
```

- [ ] **Step 5: Run to verify pass**

```bash
cd frontend && bun run test src/components/Credentials/modelRouter/modelRouterConfig.test.ts && bun run typecheck
```

Expected: 12 passed; typecheck clean. If typecheck complains that `CREDENTIAL_TYPE_LABELS` is missing a key, an entry was missed — the record is exhaustive over the union, which is what makes this safe.

---

## Task 21: The options editor

**Files:**
- Create: `frontend/src/components/Credentials/modelRouter/ModelRouterOptionsEditor.vue`

- [ ] **Step 1: Write the component**

Create the file:

```vue
<script setup lang="ts">
import { ref } from "vue";
import { Plus, Trash2 } from "lucide-vue-next";

import type { CredentialListItem, LLMModel } from "@/types/credential";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { credentialsApi } from "@/services/api";
import { createEmptyOption, type ModelRouterOptionForm } from "./modelRouterConfig";

const props = defineProps<{
  options: ModelRouterOptionForm[];
  credentials: CredentialListItem[];
}>();

const emit = defineEmits<{
  "update:options": [value: ModelRouterOptionForm[]];
}>();

const modelsByCredential = ref<Record<string, LLMModel[]>>({});
const loadingFor = ref<Record<string, boolean>>({});

const credentialOptions = computed((): { value: string; label: string }[] => [
  { value: "", label: "Select credential..." },
  ...props.credentials.map((credential) => ({
    value: credential.id,
    label: credential.is_shared
      ? `${credential.name} (${credential.type}) - shared`
      : `${credential.name} (${credential.type})`,
  })),
]);

function modelOptionsFor(credentialId: string): { value: string; label: string }[] {
  const models = modelsByCredential.value[credentialId] ?? [];
  return models.map((model) => ({ value: model.id, label: model.name }));
}

async function loadModels(credentialId: string): Promise<void> {
  if (!credentialId || modelsByCredential.value[credentialId]) return;
  loadingFor.value = { ...loadingFor.value, [credentialId]: true };
  try {
    const models = await credentialsApi.getModels(credentialId);
    modelsByCredential.value = { ...modelsByCredential.value, [credentialId]: models };
  } catch {
    modelsByCredential.value = { ...modelsByCredential.value, [credentialId]: [] };
  } finally {
    loadingFor.value = { ...loadingFor.value, [credentialId]: false };
  }
}

function patch(index: number, changes: Partial<ModelRouterOptionForm>): void {
  const next = props.options.map((option, i) => (i === index ? { ...option, ...changes } : option));
  emit("update:options", next);
}

async function handleCredentialChange(index: number, credentialId: string): Promise<void> {
  patch(index, { credentialId, model: "" });
  await loadModels(credentialId);
}

function handleDefaultChange(index: number, isDefault: boolean): void {
  // Exactly one fallback, so selecting one clears the rest.
  emit(
    "update:options",
    props.options.map((option, i) => ({ ...option, isDefault: isDefault && i === index })),
  );
}

function addOption(): void {
  emit("update:options", [...props.options, createEmptyOption()]);
}

function removeOption(index: number): void {
  emit(
    "update:options",
    props.options.filter((_, i) => i !== index),
  );
}

onMounted(() => {
  props.options.forEach((option) => {
    if (option.credentialId) void loadModels(option.credentialId);
  });
});
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center justify-between">
      <Label>Model options</Label>
      <Button
        type="button"
        variant="outline"
        size="sm"
        data-testid="model-router-add-option"
        @click="addOption"
      >
        <Plus class="mr-1 h-3.5 w-3.5" />
        Add option
      </Button>
    </div>
    <p class="text-xs text-muted-foreground">
      The decision model picks between these by name, so give each one a short, distinct
      name and say plainly when it should win.
    </p>

    <div
      v-for="(option, index) in options"
      :key="option.id"
      class="space-y-3 rounded-xl border border-border/60 p-3"
      :data-testid="`model-router-option-${index}`"
    >
      <div class="flex items-start gap-2">
        <div class="flex-1 space-y-1">
          <Label :for="`router-option-label-${option.id}`">Name</Label>
          <Input
            :id="`router-option-label-${option.id}`"
            :model-value="option.label"
            placeholder="Fast"
            @update:model-value="patch(index, { label: String($event) })"
          />
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          class="mt-6"
          :disabled="options.length <= 2"
          :title="options.length <= 2 ? 'A router needs at least two options' : 'Remove option'"
          :aria-label="`Remove option ${index + 1}`"
          @click="removeOption(index)"
        >
          <Trash2 class="h-3.5 w-3.5" />
        </Button>
      </div>

      <div class="grid gap-3 sm:grid-cols-2">
        <div class="space-y-1">
          <Label>Credential</Label>
          <Select
            :model-value="option.credentialId"
            :options="credentialOptions"
            @update:model-value="handleCredentialChange(index, String($event ?? ''))"
          />
        </div>
        <div class="space-y-1">
          <Label>Model</Label>
          <SearchableSelect
            :model-value="option.model"
            :options="modelOptionsFor(option.credentialId)"
            placeholder="Select model..."
            search-placeholder="Search models..."
            empty-text="No models found."
            :disabled="!option.credentialId || loadingFor[option.credentialId]"
            @update:model-value="patch(index, { model: String($event ?? '') })"
          />
        </div>
      </div>

      <div class="space-y-1">
        <Label :for="`router-option-criteria-${option.id}`">Use this when</Label>
        <Textarea
          :id="`router-option-criteria-${option.id}`"
          :model-value="option.criteria"
          :rows="2"
          placeholder="Short factual questions. No code, no long documents."
          @update:model-value="patch(index, { criteria: String($event) })"
        />
      </div>

      <div class="flex items-center gap-2">
        <input
          :id="`router-option-default-${option.id}`"
          type="radio"
          class="h-4 w-4 border-input"
          :checked="option.isDefault"
          @change="handleDefaultChange(index, ($event.target as HTMLInputElement).checked)"
        >
        <Label
          :for="`router-option-default-${option.id}`"
          class="text-sm font-normal"
        >
          Use this option when routing fails
        </Label>
      </div>
    </div>
  </div>
</template>
```

Add `computed` and `onMounted` to the `vue` import at the top. Confirm the exact export names on `credentialsApi` before using `getModels`; `frontend/src/services/api.ts:1332` shows the LLM listing call, and the models call lives next to it.

- [ ] **Step 2: Verify it compiles**

```bash
cd frontend && bun run lint && bun run typecheck
```

Expected: clean. Fix any import path or API-name mismatch the typechecker reports.

---

## Task 22: The router fields component

**Files:**
- Create: `frontend/src/components/Credentials/modelRouter/ModelRouterFields.vue`

- [ ] **Step 1: Write the component**

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Info } from "lucide-vue-next";

import type { CredentialListItem } from "@/types/credential";

import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { credentialsApi } from "@/services/api";
import ModelRouterOptionsEditor from "./ModelRouterOptionsEditor.vue";
import type { ModelRouterForm, ModelRouterOptionForm } from "./modelRouterConfig";

const props = defineProps<{ form: ModelRouterForm }>();
const emit = defineEmits<{ "update:form": [value: ModelRouterForm] }>();

const decisionCredentials = ref<CredentialListItem[]>([]);
const llmCredentials = ref<CredentialListItem[]>([]);

const decisionOptions = computed((): { value: string; label: string }[] => [
  { value: "", label: "Select decision model credential..." },
  ...decisionCredentials.value.map((credential) => ({
    value: credential.id,
    label: credential.is_shared ? `${credential.name} - shared` : credential.name,
  })),
]);

function patch(changes: Partial<ModelRouterForm>): void {
  emit("update:form", { ...props.form, ...changes });
}

function handleOptionsChange(options: ModelRouterOptionForm[]): void {
  patch({ options });
}

onMounted(async () => {
  const [decision, llm] = await Promise.all([
    credentialsApi.getDecisionCredentials(),
    credentialsApi.getLlmCredentials(),
  ]);
  decisionCredentials.value = decision;
  // A router cannot route to another router.
  llmCredentials.value = llm.filter((credential) => credential.type !== "model_router");
});
</script>

<template>
  <div class="space-y-4">
    <div class="space-y-2">
      <Label for="router-decision-credential">Decision model credential</Label>
      <Select
        id="router-decision-credential"
        :model-value="form.decisionCredentialId"
        :options="decisionOptions"
        @update:model-value="patch({ decisionCredentialId: String($event ?? '') })"
      />
      <p class="text-xs text-muted-foreground">
        The model that reads each request and picks which of your models answers it.
      </p>
    </div>

    <div class="space-y-2">
      <Label for="router-decision-model">Decision model</Label>
      <Input
        id="router-decision-model"
        :model-value="form.decisionModel"
        placeholder="jev-latest"
        @update:model-value="patch({ decisionModel: String($event) })"
      />
    </div>

    <div class="space-y-2">
      <Label for="router-instructions">Routing instructions</Label>
      <Textarea
        id="router-instructions"
        :model-value="form.routingInstructions"
        :rows="3"
        @update:model-value="patch({ routingInstructions: String($event) })"
      />
      <p class="text-xs text-muted-foreground">
        How to weigh the options overall. Each option's own criteria go below.
      </p>
    </div>

    <ModelRouterOptionsEditor
      :options="form.options"
      :credentials="llmCredentials"
      @update:options="handleOptionsChange"
    />

    <div class="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/5 p-3">
      <Info class="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
      <p class="text-xs text-amber-700">
        Sharing this router lets the people you share it with run requests against every
        credential listed above. They cannot read those keys, and the credentials do not
        appear in their own list, but the requests spend them.
      </p>
    </div>
  </div>
</template>
```

Confirm the real method names on `credentialsApi` for the decision and LLM listings before using them; both endpoints already exist (`/credentials/decision`, `/credentials/llm`).

- [ ] **Step 1b: Add Test Connection for the decision half**

The spec calls for the dialog to prove the decision endpoint works before the router is
saved. Reuse the endpoint the decision credential already has, rather than adding a router
branch to `/credentials/test`:

```ts
const testing = ref(false);
const testSuccess = ref<boolean | null>(null);
const testMessage = ref("");

async function testDecisionModel(): Promise<void> {
  if (!props.form.decisionCredentialId || !props.form.decisionModel.trim()) return;
  testing.value = true;
  testSuccess.value = null;
  testMessage.value = "";
  try {
    const result = await credentialsApi.test({
      type: "decision",
      credential_id: props.form.decisionCredentialId,
      config: { model: props.form.decisionModel.trim() },
    });
    testSuccess.value = result.success;
    testMessage.value = result.message;
  } catch (error) {
    testSuccess.value = false;
    testMessage.value = error instanceof Error ? error.message : "Connection test failed";
  } finally {
    testing.value = false;
  }
}
```

Render the button under the decision model input, following the markup
`CredentialDialog.vue` already uses for `decision-test-connection-button`. Note that
`/credentials/test` rejects a config override from a non-owner with a 403; surface that
message as-is rather than hiding the button, so a collaborator sees why.

- [ ] **Step 2: Verify it compiles**

```bash
cd frontend && bun run lint && bun run typecheck
```

Expected: clean.

---

## Task 23: Wire the dialog

**Files:**
- Modify: `frontend/src/components/Credentials/CredentialDialog.vue`

- [ ] **Step 1: Add the state**

Near the other per-type refs (around `decisionBaseUrl` at line 116), add:

```ts
const modelRouterForm = ref<ModelRouterForm>(emptyModelRouterForm());
```

with the imports:

```ts
import ModelRouterFields from "@/components/Credentials/modelRouter/ModelRouterFields.vue";
import {
  buildModelRouterConfig,
  emptyModelRouterForm,
  validateModelRouterForm,
  type ModelRouterForm,
} from "@/components/Credentials/modelRouter/modelRouterConfig";
```

- [ ] **Step 2: Add the type to the picker**

In `credentialTypeOptions`, directly after the `decision` entry:

```ts
  { value: "model_router", label: CREDENTIAL_TYPE_LABELS.model_router },
```

- [ ] **Step 3: Reset and prefill**

Add a loader next to `applyDecisionPublicFields`. The config is not in `public_fields`
and not in the credential detail response, so it comes from the endpoint added in
Task 8b:

```ts
async function applyModelRouterCredential(
  credential: Credential | null | undefined,
): Promise<void> {
  modelRouterForm.value = emptyModelRouterForm();
  if (credential?.type !== "model_router") return;
  try {
    const config = await credentialsApi.getModelRouterConfig(credential.id);
    modelRouterForm.value = {
      decisionCredentialId: config.decision_credential_id,
      decisionModel: config.decision_model,
      routingInstructions: config.routing_instructions || DEFAULT_ROUTING_INSTRUCTIONS,
      options: config.options.map((option) => ({
        id: option.id,
        label: option.label,
        credentialId: option.credential_id,
        model: option.model,
        criteria: option.criteria,
        isDefault: option.is_default,
      })),
    };
  } catch {
    // Leave the blank form up rather than a half-filled one the user might save over.
    modelRouterForm.value = emptyModelRouterForm();
  }
}
```

Call it from wherever the dialog resets per-type state for an existing credential, beside
the `applyDecisionPublicFields(credential)` call. Add `getModelRouterConfig` to
`credentialsApi` in `frontend/src/services/api.ts` next to the LLM listing call at line
1332, typed against a `ModelRouterConfigResponse` interface added to
`frontend/src/types/credential.ts`. Import `DEFAULT_ROUTING_INSTRUCTIONS` from
`modelRouterConfig.ts`.

- [ ] **Step 4: Gate the save button**

In the `canSave` computed, after the `decision` branch:

```ts
  } else if (type.value === "model_router") {
    return validateModelRouterForm(modelRouterForm.value) === null;
```

- [ ] **Step 5: Build the payload**

In the config-building function, after the `decision` branch:

```ts
  } else if (type.value === "model_router") {
    return buildModelRouterConfig(modelRouterForm.value);
```

- [ ] **Step 6: Render the fields and widen the dialog**

In the template, after the `<template v-if="type === 'decision'">` block:

```vue
      <template v-if="type === 'model_router'">
        <ModelRouterFields
          :form="modelRouterForm"
          @update:form="modelRouterForm = $event"
        />
      </template>
```

On the dialog's content element, make the max width conditional:

```vue
      :class="type === 'model_router' ? 'sm:max-w-3xl' : undefined"
```

Read the existing width class first and extend it rather than replacing it.

- [ ] **Step 7: Verify**

```bash
cd frontend && bun run lint && bun run typecheck && bun run test
```

Expected: clean, all tests pass.

- [ ] **Step 8: Check it by hand**

```bash
./run.sh
```

Open `http://localhost:4017`, go to Credentials, add a Model Router credential. Confirm: the dialog widens, the decision credential dropdown lists your decision credentials, adding an option loads that credential's models, and Save is disabled until two complete options exist.

---

## Task 24: Disable Auto Model under the Responses API

**Files:**
- Modify: `frontend/src/components/ui/Select.vue`
- Modify: `frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts:6204-6245`
- Modify: `frontend/src/components/Panels/propertiesPanel/useResponsesApiCapability.ts`
- Test: `frontend/src/components/Panels/propertiesPanel/useResponsesApiCapability.test.ts`

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/Panels/propertiesPanel/useResponsesApiCapability.test.ts`, following the shape of the cases already there:

```ts
  it("reports Auto Model as unsupported with the model's own reason", () => {
    const capability = useResponsesApiCapability({
      credentialType: ref("model_router"),
      batchModeEnabled: ref(false),
      outputType: ref("text"),
      selectedModel: ref({
        id: "auto",
        name: "Auto",
        is_reasoning: false,
        supports_batch: false,
        supports_responses: false,
        responses_support_reason:
          "Auto Model does not support the Responses API. Pick a specific credential and model to use it.",
      }),
    });

    expect(capability.available.value).toBe(false);
    expect(capability.message.value).toMatch(/Auto Model does not support/);
    expect(capability.tone.value).toBe("warning");
  });

  it("explains Auto Model even before a model has loaded", () => {
    const capability = useResponsesApiCapability({
      credentialType: ref("model_router"),
      batchModeEnabled: ref(false),
      outputType: ref("text"),
      selectedModel: ref(null),
    });

    expect(capability.available.value).toBe(false);
    expect(capability.message.value).toMatch(/Auto Model/);
  });
```

- [ ] **Step 2: Run to verify failure**

```bash
cd frontend && bun run test src/components/Panels/propertiesPanel/useResponsesApiCapability.test.ts
```

Expected: the second case fails — with no model loaded the composable currently reports available.

- [ ] **Step 3: Teach the composable about routers**

In `useResponsesApiCapability.ts`, add the constant:

```ts
const MODEL_ROUTER_MESSAGE =
  "Auto Model does not support the Responses API. Pick a specific credential and model to use it.";
```

In `available`, after the `google` check:

```ts
    if (input.credentialType.value === "model_router") return false;
```

In `message`, after the `google` branch:

```ts
    if (input.credentialType.value === "model_router") {
      return input.selectedModel.value?.responses_support_reason ?? MODEL_ROUTER_MESSAGE;
    }
```

- [ ] **Step 4: Let a `Select` option be disabled**

In `frontend/src/components/ui/Select.vue`, add `disabled?: boolean` to the `Option` interface and render it:

```vue
      <option
        v-for="option in options"
        :key="option.value ?? 'undefined'"
        :value="option.value ?? ''"
        :disabled="option.disabled"
        :title="option.title"
      >
        {{ option.label }}
      </option>
```

and add `title?: string` to `Option` as well. Both are optional, so every existing caller is unaffected.

- [ ] **Step 5: Disable routers in the node credential picker**

In `usePropertiesPanelController.ts`, give `buildCredentialOptions` an optional last parameter and use it:

```ts
  function buildCredentialOptions(
    credentials: CredentialListItem[],
    selectedCredentialId: string | undefined,
    placeholderLabel: string,
    sharedFallbackLabel: string,
    disableRouters: boolean = false,
  ): { value: string; label: string; disabled?: boolean; title?: string }[] {
    const options: { value: string; label: string; disabled?: boolean; title?: string }[] = [
      { value: "", label: placeholderLabel },
      ...credentials.map((c) => ({
        value: c.id,
        label: c.is_shared ? `${c.name} (${c.type}) - shared` : `${c.name} (${c.type})`,
        disabled: disableRouters && c.type === "model_router",
        title:
          disableRouters && c.type === "model_router"
            ? "Auto Model cannot be used with the Responses API"
            : undefined,
      })),
    ];
```

leaving the rest of the function unchanged. Then in `credentialOptions`, pass the flag:

```ts
    return buildCredentialOptions(
      llmCredentials.value,
      selectedCredentialId,
      "Select credential...",
      "Credential not available (re-select)",
      Boolean(node?.data.responsesApiEnabled),
    );
```

Apply the same flag to `fallbackCredentialOptions` and `guardrailCredentialOptions`. For guardrails, pass `true` unconditionally: a guardrail check is a fixed classification call and never routes.

- [ ] **Step 6: Run to verify pass**

```bash
cd frontend && bun run test && bun run lint && bun run typecheck
```

Expected: all pass, clean.

---

## Task 25: Show `Router / Model` in Traces

**Files:**
- Modify: `frontend/src/components/Traces/TracesPanel.vue:157-163`, `:1022-1034`

- [ ] **Step 1: Update the list label**

Replace `traceModelListLabel`:

```ts
function traceModelListLabel(trace: LLMTraceListItem): string | null {
  if (trace.model) {
    // Both halves, so a run shows that automatic selection happened and where it went.
    return trace.router_label ? `${trace.router_label} / ${trace.model}` : trace.model;
  }
  if (isMcpWorkflowServerTrace(trace))
    return null;
  return "Unknown model";
}
```

- [ ] **Step 2: Update the detail card**

Replace the Model card's value line:

```vue
            <div class="mt-1 text-sm font-medium">
              {{
                selectedTrace.model
                  ? selectedTrace.router_label
                    ? `${selectedTrace.router_label} / ${selectedTrace.model}`
                    : selectedTrace.model
                  : "Unknown"
              }}
            </div>
```

- [ ] **Step 3: Verify**

```bash
cd frontend && bun run lint && bun run typecheck
```

Expected: clean.

- [ ] **Step 4: Check it by hand**

With `./run.sh` running, execute a workflow whose LLM node uses the router credential, then open the Traces tab. The row and the detail Model card must both read `<router name> / <actual model>`, and the Cost column must price the actual model, not the router.

---

## Task 26: Show routing in the Execution Log and Span View

**Files:**
- Modify: `frontend/src/lib/executionLog.ts`
- Modify: `frontend/src/components/Panels/DebugPanel.vue:2976-2985`
- Modify: `frontend/src/components/Panels/executionTimeline.ts`
- Modify: `frontend/src/components/Panels/ExecutionSpanDetails.vue`
- Test: `frontend/src/components/Panels/executionTimeline.test.ts`

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/Panels/executionTimeline.test.ts`, matching the file's existing style for building a `NodeResult`:

```ts
describe("model routing on spans", () => {
  it("carries the routing summary from node metadata onto the span", () => {
    const results = [
      {
        node_id: "n1",
        node_label: "Agent",
        node_type: "agent",
        status: "success" as const,
        output: { text: "done" },
        execution_time_ms: 120,
        error: null,
        metadata: {
          model_routing: {
            routerLabel: "Auto Model",
            routerCredentialId: "cred-1",
            calls: [
              { model: "gpt-4o-mini", option: "Fast", credentialName: "OpenAI", fallback: false, error: null },
              { model: "gpt-5", option: "Deep", credentialName: "OpenAI", fallback: false, error: null },
            ],
          },
        },
      },
    ];

    const { rows } = buildTimeline(results);
    const span = rows[0].spans[0];
    expect(span.modelRouting?.routerLabel).toBe("Auto Model");
    expect(span.modelRouting?.calls).toHaveLength(2);
  });

  it("leaves modelRouting null when a node did not route", () => {
    const results = [
      {
        node_id: "n1",
        node_label: "LLM",
        node_type: "llm",
        status: "success" as const,
        output: { text: "done" },
        execution_time_ms: 10,
        error: null,
        metadata: {},
      },
    ];
    expect(buildTimeline(results).rows[0].spans[0].modelRouting).toBeNull();
  });
});

describe("formatModelRoutingLabel", () => {
  it("shows router and model for a single model", () => {
    expect(
      formatModelRoutingLabel({
        routerLabel: "Auto Model",
        routerCredentialId: "c",
        calls: [{ model: "gpt-5", option: "Deep", credentialName: "OpenAI", fallback: false, error: null }],
      }),
    ).toBe("Auto Model / gpt-5");
  });

  it("marks extra distinct models with a count", () => {
    expect(
      formatModelRoutingLabel({
        routerLabel: "Auto Model",
        routerCredentialId: "c",
        calls: [
          { model: "gpt-4o-mini", option: "Fast", credentialName: "OpenAI", fallback: false, error: null },
          { model: "gpt-5", option: "Deep", credentialName: "OpenAI", fallback: false, error: null },
          { model: "gpt-5", option: "Deep", credentialName: "OpenAI", fallback: false, error: null },
        ],
      }),
    ).toBe("Auto Model / gpt-5 +1");
  });

  it("returns null with no calls", () => {
    expect(
      formatModelRoutingLabel({ routerLabel: "Auto Model", routerCredentialId: "c", calls: [] }),
    ).toBeNull();
  });
});
```

Import `formatModelRoutingLabel` from `./executionTimeline`.

- [ ] **Step 2: Run to verify failure**

```bash
cd frontend && bun run test src/components/Panels/executionTimeline.test.ts
```

Expected: `formatModelRoutingLabel is not exported`.

- [ ] **Step 3: Add the types and helpers**

In `frontend/src/components/Panels/executionTimeline.ts`, above `SpanItem`:

```ts
export interface ModelRoutingCall {
  model: string;
  option: string | null;
  credentialName: string | null;
  fallback: boolean;
  error: string | null;
}

export interface ModelRoutingSummary {
  routerLabel: string;
  routerCredentialId: string;
  calls: ModelRoutingCall[];
}

/** `Auto Model / gpt-5`, with `+N` when the run moved between models. */
export function formatModelRoutingLabel(routing: ModelRoutingSummary | null): string | null {
  if (!routing || routing.calls.length === 0) return null;
  const last = routing.calls[routing.calls.length - 1].model;
  const distinct = new Set(routing.calls.map((call) => call.model));
  const extra = distinct.size - 1;
  return extra > 0 ? `${routing.routerLabel} / ${last} +${extra}` : `${routing.routerLabel} / ${last}`;
}

export function readSpanModelRouting(result: {
  metadata?: Record<string, unknown>;
}): ModelRoutingSummary | null {
  const raw = result.metadata?.model_routing;
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Partial<ModelRoutingSummary>;
  if (typeof value.routerLabel !== "string" || !Array.isArray(value.calls)) return null;
  return {
    routerLabel: value.routerLabel,
    routerCredentialId: String(value.routerCredentialId ?? ""),
    calls: value.calls as ModelRoutingCall[],
  };
}
```

Add `modelRouting: ModelRoutingSummary | null;` to `SpanItem` and to `RawSpanItem`, and set it from `readSpanModelRouting(result)` wherever the raw span is built from a node result. Follow how `traceId` is threaded through — the same two places.

- [ ] **Step 4: Show it in the Execution Log**

In `DebugPanel.vue`, inside the node-label line, after the `#occurrence` span:

```vue
                <span
                  v-if="modelRoutingLabel(result)"
                  class="ml-2 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-normal text-primary"
                  :title="modelRoutingTitle(result)"
                  data-testid="execution-log-model-routing"
                >
                  {{ modelRoutingLabel(result) }}
                </span>
```

and in the script:

```ts
function modelRoutingLabel(result: DisplayNodeResult): string | null {
  return formatModelRoutingLabel(readSpanModelRouting(result));
}

function modelRoutingTitle(result: DisplayNodeResult): string {
  const routing = readSpanModelRouting(result);
  if (!routing) return "";
  return routing.calls
    .map((call, index) => `${index + 1}. ${call.model}${call.fallback ? " (fallback)" : ""}`)
    .join("\n");
}
```

Import `formatModelRoutingLabel` and `readSpanModelRouting` from `@/components/Panels/executionTimeline` in `DebugPanel.vue`.

- [ ] **Step 5: Show it in the Span View**

In `ExecutionSpanDetails.vue`, add a fourth cell to the existing stats grid:

```vue
      <div v-if="span.modelRouting">
        <span class="text-muted-foreground">Model</span><div
          class="font-medium"
          data-testid="span-model-routing"
        >
          {{ formatModelRoutingLabel(span.modelRouting) }}
        </div>
      </div>
```

and, below the grid, the per-turn list when the run moved:

```vue
    <div
      v-if="span.modelRouting && span.modelRouting.calls.length > 1"
      class="mx-2 mb-2 space-y-0.5 rounded border border-border/40 px-2 py-1.5 text-[10px]"
    >
      <div class="text-muted-foreground">
        Routed per turn
      </div>
      <div
        v-for="(call, index) in span.modelRouting.calls"
        :key="index"
        class="flex items-center gap-2 font-mono"
      >
        <span class="text-muted-foreground">{{ index + 1 }}.</span><span>{{ call.model }}</span><span
          v-if="call.option"
          class="text-muted-foreground"
        >{{ call.option }}</span><span
          v-if="call.fallback"
          class="text-amber-600"
        >fallback</span>
      </div>
    </div>
```

Import `formatModelRoutingLabel` in the script block.

- [ ] **Step 6: Run to verify pass**

```bash
cd frontend && bun run test && bun run lint && bun run typecheck
```

Expected: all pass, clean.

- [ ] **Step 7: Check it by hand**

With `./run.sh` running, run an agent node on the router credential with at least one tool so the loop takes two turns. The Execution Log row must show `Auto Model / <model>`, and clicking the span in the timeline must show the Model cell plus the per-turn list.

---

# Phase 7 — Documentation and the release tour

## Task 27: Documentation

**Files:**
- Modify: `frontend/src/docs/content/reference/credentials.md`
- Modify: `frontend/src/docs/content/reference/credentials-sharing.md`
- Modify: `frontend/src/docs/content/reference/integrations.md`
- Modify: `frontend/src/docs/content/reference/features.md`

No node page and no `node-types.md` entry: this change adds a credential, not a node type.

- [ ] **Step 1: Read what the decision credential did**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && git show f924cf4d -- frontend/src/docs/content/reference/credentials.md frontend/src/docs/content/reference/credentials-sharing.md frontend/src/docs/content/reference/integrations.md frontend/src/docs/content/reference/features.md
```

Match that shape. The docs skill for this repo is `heym-documentation`; invoke it before writing if it is available.

- [ ] **Step 2: Add the credential to `credentials.md`**

Add a `Model Router (Auto Model)` row to the credential table, then a section:

```markdown
### Model Router (Auto Model)

A Model Router holds no key of its own. It holds a **decision model credential**, a list
of **model options** — each an existing OpenAI, Google or Custom credential plus a model
— and, for each option, free text saying when that option should be used.

It appears in every credential picker that offers a model: the LLM and Agent nodes, Chat,
AI Defaults, Evals, Dashboards, the expression builder and Data Tables. Its only model is
**Auto**. Pick it and the decision model reads each request and routes it.

Auto Model cannot be combined with the Responses API, Batch mode, or image output. The
toggles disable themselves when a router is selected, and each says why.

Routing failures fall back to the option you marked **Use this option when routing
fails**. Without one, the node fails rather than guessing.
```

- [ ] **Step 3: Add the sharing paragraph to `credentials-sharing.md`**

```markdown
### Sharing a Model Router

Sharing a Model Router shares everything it routes to. The people you share it with can
run requests against every credential in its option list; those requests spend your keys.
They cannot read the keys, and the credentials do not appear in their own credential list.

This is the same grant as sharing an OpenAI credential directly, and it is what makes a
router useful to a team. If you do not want that, share the individual credentials instead
and let each person pick a model.
```

- [ ] **Step 4: Add to `integrations.md` and `features.md`**

In `integrations.md`, add a Model Router entry next to Decision Model describing what it
connects to. In `features.md`, add a short section and include Model Router wherever
credential types are enumerated.

- [ ] **Step 5: Verify the docs build**

```bash
cd frontend && bun run lint && bun run typecheck && bun run build
```

Expected: clean build. If a doc page is registered anywhere, check `frontend/src/docs/manifest.ts` — for reference pages that already exist, no manifest change is needed.

---

## Task 28: Release tour entry

**Files:**
- Modify: `frontend/src/features/release-tour/releaseRegistry.ts`
- Create: `frontend/src/features/release-tour/components/visuals/ModelRouterTourVisual.vue`
- Modify: `frontend/src/features/release-tour/tourVisuals.ts`
- Test: `frontend/src/features/release-tour/releaseTourMapper.test.ts`

The registry holds four sections today, so adding a fifth needs no eviction.

- [ ] **Step 1: Add the release entry**

At the top of `RELEASE_REGISTRY` in `releaseRegistry.ts`, before the `2026.13` entry:

```ts
  {
    releaseId: "2026.14",
    publishedAt: new Date("2026-09-22T00:00:00Z"),
    headline: "Let a model pick the model",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: false,
      sectionOrder: ["model-router"],
    },
    sections: [
      {
        id: "model-router",
        title: "One credential, the right model every time",
        publishedAt: new Date("2026-09-22T10:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "The new **Model Router** credential does not hold a key. It holds a decision model, a list of your existing OpenAI, Google and Custom credentials, and a sentence for each one saying when it should be used. Pick the router in any model dropdown, choose **Auto**, and the decision model reads each request and sends it to the model you described.",
          },
          {
            type: "prose",
            markdown:
              "It works everywhere a model is chosen: the **LLM** and **Agent** nodes, **Chat**, **AI Defaults**, **Evals**, **Dashboards** and the expression builder. An agent re-routes as its tool loop progresses, so a cheap model can take the early turns and a stronger one can take the turn that actually needs it.",
          },
          {
            type: "prose",
            markdown:
              "Nothing is hidden. **Traces** shows `Auto Model / GPT-5` rather than just the model, costs are still attributed to the model that ran, and the canvas **Execution Log** and **Span View** show which turn went where. Mark one option as the fallback and a decision model outage never stops a run.",
          },
        ],
        tour: {
          description:
            "A credential that picks the model per request, with both the router and the model it chose visible in every trace.",
          useCases: [
            "Send short questions to a cheap model and hard ones to a strong one, automatically",
            "Let an agent start cheap and escalate only on the turn that needs it",
            "See Auto Model / GPT-5 in Traces, the Execution Log and the Span View",
          ],
          tourVisual: "model-router",
          docTarget: {
            categoryId: "reference",
            slug: "credentials",
            title: "Credentials",
          },
        },
      },
    ],
  },
```

`tourEnabled: false` keeps the automatic popup shut while the work is in progress. Flip it to `true` only when the release actually ships.

- [ ] **Step 2: Build the visual**

Create `frontend/src/features/release-tour/components/visuals/ModelRouterTourVisual.vue`. Read `DecisionNodeTourVisual.vue` first and follow it exactly: Tailwind semantic tokens only, no production API calls, no host-page state, animation through CSS transitions, Vue `<Transition>` and `useCycleStep`.

The mock cycles three steps: a request arrives, the router weighs two named options, one lights up, and a `Auto Model / gpt-5` chip appears beneath. Use `useCycleStep` for the cycle, exactly as the neighbouring visuals do.

- [ ] **Step 3: Register it**

In `tourVisuals.ts`:

```ts
import ModelRouterTourVisual from "@/features/release-tour/components/visuals/ModelRouterTourVisual.vue";
```

and add to `TOUR_VISUALS`:

```ts
  "model-router": ModelRouterTourVisual,
```

An unregistered key silently falls back to the neutral visual, which is why the mapper test guards this.

- [ ] **Step 4: Run the registry test**

```bash
cd frontend && bun run test src/features/release-tour/releaseTourMapper.test.ts
```

Expected: PASS. If it fails on a count or on the newest release id, update the expectation in that test to `2026.14` — that is the test doing its job.

- [ ] **Step 5: Confirm the E2E seed still derives itself**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && grep -n "buildReleaseTours" frontend/e2e/support.ts
```

Expected: `support.ts` computes the seeded versioned id from `buildReleaseTours(RELEASE_REGISTRY)` rather than hard-coding one, so no edit is needed. If it turns out to hard-code an id, update it to `2026.14` with the current `TOUR_REVISION` suffix.

- [ ] **Step 6: Verify**

```bash
cd frontend && bun run test && bun run lint && bun run typecheck
```

Expected: all pass, clean.

---

# Phase 8 — Security boundary and final verification

## Task 29: Advisory test for the sharing boundary

**Files:**
- Create: `backend/tests/test_advisory_model_router_sharing.py`

- [ ] **Step 1: Write the test**

```python
"""The Model Router's transitive grant is deliberate, and bounded.

Sharing a router lets the recipient *run* requests against the credentials it points
at. It must never let them *read* those credentials. These tests pin both halves: the
grant works at run time, and no key crosses any response, node output or metadata.
"""

import unittest
import uuid
from unittest import mock

from app.api.credentials import _build_public_fields, _compute_masked_value
from app.db.models import CredentialType

SECRET = "sk-router-option-key-must-never-appear"


def _router_config() -> dict:
    return {
        "decision_credential_id": str(uuid.uuid4()),
        "decision_model": "jev-latest",
        "routing_instructions": "Pick the cheapest model that works.",
        "options": [
            {
                "id": "opt_1",
                "label": "Fast",
                "credential_id": str(uuid.uuid4()),
                "model": "gpt-4o-mini",
                "criteria": "Short questions.",
                "is_default": True,
            },
            {
                "id": "opt_2",
                "label": "Deep",
                "credential_id": str(uuid.uuid4()),
                "model": "gpt-5",
                "criteria": "Hard questions.",
            },
        ],
    }


class TestNoKeyLeavesTheRouter(unittest.TestCase):
    def test_the_stored_config_holds_no_key_to_leak(self) -> None:
        self.assertNotIn("api_key", str(_router_config()))

    def test_public_fields_expose_only_a_summary(self) -> None:
        fields = _build_public_fields(CredentialType.model_router, _router_config())
        self.assertEqual(set(fields), {"decision_model", "option_count"})

    def test_masked_value_is_none_not_a_key(self) -> None:
        self.assertIsNone(_compute_masked_value(CredentialType.model_router, _router_config()))

    def test_routing_summary_names_credentials_but_carries_no_key(self) -> None:
        from app.db.models import CredentialType as CT
        from app.services.llm_service import LLMService
        from app.services import llm_service as llm_service_module
        from app.services.model_router import BoundOption, RouteDecision, RouterOption

        option = RouterOption(
            id="opt_1",
            label="Fast",
            credential_id=str(uuid.uuid4()),
            model="gpt-4o-mini",
            criteria="easy",
        )
        bound = BoundOption(
            option=option,
            credential_type="openai",
            api_key=SECRET,
            base_url=None,
            credential_name="OpenAI prod",
            credential_uuid=uuid.uuid4(),
        )
        router = mock.Mock()
        router.label = "Auto Model"
        router.credential_id = str(uuid.uuid4())
        router.route.return_value = RouteDecision(option=option)

        service = LLMService(credential_type=CT.model_router, api_key="", router=router)
        with mock.patch.object(
            llm_service_module, "load_option_credential", return_value=bound
        ), mock.patch.object(
            llm_service_module, "create_openai_client", return_value=mock.Mock()
        ):
            service._resolve_turn(
                model="auto", system_instruction=None, message="m", tool_names=None
            )

        summary = service.model_routing_summary()
        self.assertEqual(summary["calls"][0]["credentialName"], "OpenAI prod")
        # The summary is written into node metadata and persisted to node_results,
        # so the key must not be reachable anywhere inside it.
        self.assertNotIn(SECRET, str(summary))

    def test_routing_state_carries_no_credential_material(self) -> None:
        from app.services.model_router import build_routing_state

        state = build_routing_state(
            system_instruction="You are helpful.",
            message="What is 2+2?",
            tool_names=["search"],
        )
        self.assertEqual(set(state), {"system", "message", "tools"})


class TestGrantIsCheckedAtWriteTime(unittest.TestCase):
    def test_run_time_loading_does_not_re_check_the_caller(self) -> None:
        import inspect

        from app.services import model_router

        source = inspect.getsource(model_router.load_option_credential)
        # If this ever gains a user check, the design changed and the docs and the
        # sharing notice in the dialog have to change with it.
        self.assertNotIn("user_id", source)
        self.assertIn("Access is not re-checked", source)

    def test_write_time_validation_exists_and_checks_access(self) -> None:
        import inspect

        from app.api import credentials as credentials_api

        source = inspect.getsource(credentials_api.validate_model_router_references)
        self.assertIn("_get_accessible_credential", source)
        self.assertIn("ROUTER_OPTION_CREDENTIAL_TYPES", source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_advisory_model_router_sharing.py -v
```

Expected: 7 passed. If `test_run_time_loading_does_not_re_check_the_caller` fails, either the docstring in `load_option_credential` was reworded or a user check crept in — decide which, and fix the one that is wrong.

- [ ] **Step 3: Verify**

```bash
cd backend && uv run ruff format . && uv run ruff check tests/test_advisory_model_router_sharing.py
```

Expected: no errors.

---

## Task 30: Cluster placement check and full verification

No new node type is added, so `node_placement.py` needs no entry — but the guard test must confirm that, not assume it.

- [ ] **Step 1: Confirm no placement entry is owed**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_cluster_node_placement.py -v
```

Expected: PASS with no change. This test fails when a node registered in `node_execution/registry.py` has no placement entry; the router registers no node, so it stays green.

- [ ] **Step 2: Run the whole backend suite**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./run_tests.sh
```

Expected: all pass. Read any failure rather than re-running: the most likely breakages are the `LLMTrace.credential` relationship (two foreign keys to `credentials` now, so the explicit `foreign_keys=` from Task 9 must be in place) and any test that constructs `LLMService` positionally.

- [ ] **Step 3: Run the full check script**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh
```

Expected: frontend lint and typecheck clean, backend Ruff clean, backend tests pass. `check.sh` applies `ruff format` — leave the resulting diff in the working tree.

- [ ] **Step 4: Run the frontend unit tests**

```bash
cd frontend && bun run test
```

Expected: all pass. These are enforced in CI and are not part of `check.sh`.

- [ ] **Step 5: End-to-end manual check**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && ./run.sh
```

At `http://localhost:4017`:

1. Create a Decision Model credential if there is not one already.
2. Create a Model Router credential with two options on different models. Mark one as the routing-failure fallback.
3. On an LLM node, select the router. Confirm the Model dropdown offers only **Auto**, and that the **Responses API** and **Batch mode** toggles are disabled with their reasons shown.
4. Turn the Responses API on for a different credential, then reopen the credential dropdown: the router entry must be disabled with the tooltip.
5. Run the workflow. The Execution Log row shows `<router name> / <model>`; the Span View shows the Model cell.
6. Open Traces: the row and the detail Model card read `<router name> / <model>`, and Cost prices the model that ran.
7. Break the decision credential's base URL and run again: the run must succeed on the fallback option, and the Span View must mark that turn `fallback`.
8. Remove the fallback marking and repeat: the node must now fail with a message naming the router.

- [ ] **Step 6: Confirm the tree is uncommitted**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && git status --short --branch
```

Expected: `## main...origin/main` with no ahead count, and the changed and untracked files listed. **Do not commit.** The work stays as a local diff.

---

## Known limitations, stated deliberately

- **Batch, image output, guardrail checks and the HITL MCP policy classifier do not route.** Each is a fixed, single-model call; each refuses a router with a message naming why.
- **No Playwright coverage.** Decided during design: the repository owner opted out of E2E for this change. Backend pytest plus the pure-logic Vitest specs plus the manual pass in Task 30 are the verification.
- **Routing metadata on a failed node depends on the error carrying it.** `NodeTraceableExecutionError` carries `model_routing`, so an LLM node that routed and then failed still shows its chip. A node that failed before routing shows none, which is correct.
- **Latency.** Every genuinely new routing state costs one decision round trip, bounded by the router's `timeout_seconds` (10 by default). Identical states within a run reuse the previous decision.
