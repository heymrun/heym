# Model Router credential design

Date: 2026-09-22
Status: approved, not yet implemented

## Summary

Add a `model_router` credential that picks the model for a request instead of holding a
key for one. The user configures a **decision model credential** to do the picking, a
list of **model options** (each an existing `openai` / `google` / `custom` credential plus
a model id), and free text per option saying when that option should win.

At runtime the decision model receives the request's system instruction, the current
message and the attached tool names, and answers a single `choice` question. Heym binds
the winning option's credential and model for that provider call.

The router is a credential, not a node and not a node setting, so it appears wherever an
LLM credential can be chosen today: the `llm` and `agent` nodes, Chat, AI Defaults, Evals,
Dashboards, the expression builder, Data Tables, Playwright generation, the board mapper
and agent memory. Every one of those surfaces reads the same `GET /credentials/llm`
endpoint and the same `GET /credentials/{id}/models` endpoint, so one change reaches all
of them and any surface added later.

Traces, the canvas Execution Log and the Execution Span View show both halves of the
decision: `Auto Model / GPT-5` rather than `GPT-5` alone.

## Why a credential and not a node setting

The alternative shape was an "Auto model" toggle on the `llm` and `agent` nodes. It was
rejected:

- It reaches two node types. The request says this must work "anywhere we send a request
  to an AI model", which today is roughly ten call sites and grows.
- A toggle needs somewhere to store the decision model, the option list and the criteria.
  That is credential-shaped data, and putting it on a node means re-entering it per node.
- Credentials already have sharing, team sharing, an owner, an edit dialog and a listing
  panel. A router needs all of those.

## Non-goals

- No new node type. Nothing is added to `node_placement.py` and no node page is written.
- No routing for image output, batch mode, guardrail checks, embeddings or the decision
  node itself. These reject a router credential with a clear message.
- No routing for the Responses API. See "Responses API" below.
- No per-option overrides of `temperature`, `reasoning_effort` or `max_tokens`. An option
  selects a credential and a model, nothing else.
- No cost-based or latency-based automatic routing. The decision model decides, using the
  criteria the user typed.
- No nested routers. An option may not point at another `model_router` credential.

## Credential shape

Type key `model_router`, added to `CredentialType` in `backend/app/db/models.py` and to
`CredentialType` in `frontend/src/types/credential.ts`.

The config holds **no secret of its own** — only references:

```jsonc
{
  "decision_credential_id": "<decision credential uuid>",
  "decision_model": "jev-latest",
  "routing_instructions": "Pick the cheapest model that can answer correctly.",
  "options": [
    {
      "id": "opt_1",
      "label": "Fast",
      "credential_id": "<openai|google|custom credential uuid>",
      "model": "gpt-4o-mini",
      "criteria": "Short factual questions. No code, no long documents.",
      "is_default": true
    },
    {
      "id": "opt_2",
      "label": "Deep reasoning",
      "credential_id": "<uuid>",
      "model": "gpt-5",
      "criteria": "Multi-step reasoning, code generation, long context."
    }
  ],
  "timeout_seconds": 10
}
```

`option.id` is a stable internal key for the UI's list rendering. `option.label` is what
travels to the decision model as the `choice` key, so it is validated non-empty and
unique. `criteria` is the description under that key.

### Not part of the secret-merge path

`merge_credential_config_for_update` exists so a dialog that leaves a secret input blank
does not wipe the stored secret. A router config contains no secret, so it is **not**
added to that function: an update replaces the config wholesale. Adding it there would be
actively wrong, because a removed option would be merged back in.

### Masking and public fields

- `masked_value` is `null`. There is nothing to mask.
- `public_fields` returns `{"decision_model": "<model>", "option_count": "<n>"}` so the
  credentials list can show what the router does without reading the config.
- Referenced credential ids are returned to the owner and to anyone the router is shared
  with, because the dialog has to render the selection. They are ids, not keys.
- The full config is read back through a dedicated `GET /credentials/{id}/model-router`
  endpoint. `CredentialResponse` deliberately carries no `config`, and `public_fields` is
  a `dict[str, str | None]` meant for summaries rather than a JSON blob, so neither can
  round-trip a router into the edit dialog. Returning this config in full is safe for the
  same reason there is nothing to mask: it holds ids and criteria, never a key.

### Validation on create and update

Rejected with `400` when:

- `decision_credential_id` is missing, is not accessible to the owner, or is not a
  `decision` credential.
- Fewer than two options. A router with one option is a plain credential.
- Any option's `credential_id` is missing, not accessible to the owner, or not one of
  `openai`, `google`, `custom`. A `model_router` id here is rejected by the same check and
  is called out in the error message, because that is the mistake a user will actually
  make.
- Any option's `model` is blank.
- Any option's `label` is blank, or two options share a label.
- More than one option has `is_default: true`.

`is_default` is optional. Without it, a routing failure errors the node rather than
guessing.

## Sharing

Sharing a router credential transitively grants **use** of every model credential it
references. The recipient can run requests that spend the owner's keys; they cannot read
those keys, and the option credentials do not appear in their own credential list.

This is the same trust model as sharing an `openai` credential directly, and it is the
reason the router is useful for a team at all. It is stated in the credential dialog, on
the share screen and in `credentials-sharing.md` rather than left implicit.

At run time the referenced credentials are loaded without re-checking the *runner's*
access, deliberately. The alternative — dropping options the runner cannot reach — would
make the same workflow route differently for different people, which is worse than a
documented grant.

## Runtime

New module `backend/app/services/model_router.py` holds config parsing, validation, the
decision-state builder and the `ModelRouter` runtime class. It is the only place that
knows the router's shape, the way `decision_models.py` is the only place that knows the
System One wire format.

### Where routing happens

`LLMService.__init__` gains an optional `router: ModelRouter | None`.

Today `execute()` and `execute_with_tools()` call `self._get_client()` once, before the
tool loop, and hold `client`, `provider` and `model` as closure variables for the life of
the call. That is replaced by `_resolve_turn(state) -> TurnBinding`, called before each
provider request:

- **No router** — returns the static binding built from `self.credential_type`,
  `self.api_key` and `self.base_url`. Identical behaviour to today.
- **Router** — asks the decision model, then builds the winning option's client.

`_context_limit = get_context_limit(model, client)` currently sits above the tool loop and
must move inside it, since the model can change between turns.

Routing at this level means every caller of `execute_llm` / `execute_llm_with_tools` gets
it. Each of those call sites gains two lines: build the router from the loaded credential,
pass it through. The "credential has no API key" guard each site carries must tolerate a
router, which has none.

### The decision request

One `choice` question, matching the contract `build_decision_body` already enforces:

```jsonc
{
  "model": "jev-latest",
  "state": {
    "system": "<system instruction, truncated>",
    "message": "<current message, truncated>",
    "tools": ["search_web", "read_file"]
  },
  "questions": {
    "route": {
      "type": "choice",
      "instructions": "<routing_instructions, or a built-in default>",
      "criteria": { "Fast": "Short factual questions...", "Deep reasoning": "..." }
    }
  }
}
```

The answer arrives as `answers.route.choice`, a label from `criteria`.

`state.message` is the user message on the first turn of a tool loop and the most recent
tool result on later turns, which is what makes per-turn routing meaningful. `state.tools`
is names only, never schemas.

Truncation limits are module constants (`ROUTER_STATE_SYSTEM_CHARS = 2000`,
`ROUTER_STATE_MESSAGE_CHARS = 4000`), not environment settings.

### Per-call routing and reuse

The router is consulted before every provider call. To keep a twenty-turn agent run from
making twenty decision calls, the built state is hashed (SHA-256 over its canonical JSON,
plus a fingerprint of the option list) and compared with the previous turn's hash. An
unchanged hash reuses the previous decision and sends nothing. A changed hash — which is
what happens when a tool returns something new — routes again.

The cache lives on the `LLMService` instance, so it is scoped to one run and never leaks
between workflows or users.

### Failure

Any of: the decision endpoint erroring, timing out, returning a malformed body, or
returning a label that is not in the option list.

- With an `is_default` option: bind it, record `fallback: true` and the reason in the
  node's routing metadata, and continue. The failed decision call has already written its
  own trace row.
- Without one: raise, so the node fails and the node's own retry settings apply.

### Rejected combinations

Each raises a clear error naming the router credential:

| Combination | Reason |
| --- | --- |
| Responses API | See below |
| Batch mode | The Batch API submits one job against one model |
| Image output (`execute_image_generation` / `execute_image_edit`) | Image models are not interchangeable with chat models on criteria text |
| Guardrail credential slot | The guardrail check is a fixed classification call, not a user request |
| Decision node credential slot | Already restricted to `decision` credentials |

## Tracing

### Schema

Two nullable columns on `llm_traces`:

- `router_credential_id` — UUID FK to `credentials`, `ON DELETE SET NULL`.
- `router_label` — `String(255)`, the router's name denormalised at write time so a
  deleted router still renders in history.

**`llm_traces.model` and `llm_traces.credential_id` keep holding the real model and the
real credential.** `resolve_costs_for_user` prices off `model`, and `/traces/stats` groups
by `model` and filters by `credential_id`. Writing the router into either would make
per-model cost and per-credential attribution wrong.

`LLMTraceContext` gains `router_credential_id` and `router_label`. Because the context is
a frozen dataclass built once per node, each turn rebinds it with `dataclasses.replace`
to carry the actual credential. `trace_ids` must be passed through as **the same list
object**, or `_attach_latest_trace_id` and `_latest_trace_id` stop seeing appended ids and
every "Open trace" link in the execution log goes dead.

The decision call writes its own trace row already (`provider="decision"`,
`request_type="decision.systemone"`). It gains `router_credential_id` too, so the routing
decision and the routed request group together in the Traces tab.

### Traces tab

`TracesPanel.vue` has one `modelLabel(trace)` helper and one Model row in the detail pane.
Both become `router_label ? "${router_label} / ${model}" : model`. The search box already
matches on `model`; `router_label` is added to that filter.

### Node metadata

The executor packs routing into `NodeResult.metadata`, which is already persisted to
`node_results` and already reaches the frontend as `NodeResult.metadata`:

```jsonc
{
  "modelRouting": {
    "routerLabel": "Auto Model",
    "routerCredentialId": "<uuid>",
    "calls": [
      { "model": "gpt-4o-mini", "option": "Fast", "credentialName": "OpenAI prod",
        "fallback": false, "error": null }
    ]
  }
}
```

No prompt text and no key material goes in here. The prompt reaches the LLM trace row, the
same as every other request.

### Execution Log

The node row in `DebugPanel.vue` gains a chip beside the node label reading
`Auto Model / GPT-4o Mini`. When a run used more than one distinct model, the chip shows
the last one plus `+N`.

### Execution Span View

`SpanItem` gains `modelRouting`, carried through `executionTimeline.ts` from the node
result. `ExecutionSpanDetails.vue` gains a Model cell in its existing stats grid showing
`Router / model`, and below it, when more than one model was used, the per-turn list.

## Responses API

`GET /credentials/{id}/models` currently rejects any type outside
`openai | google | custom`. For a router it returns one synthetic row:

```jsonc
[{ "id": "auto", "name": "Auto", "is_reasoning": false,
   "supports_batch": false, "batch_support_reason": "Batch mode is not available for Model Router credentials.",
   "supports_responses": false, "responses_support_reason": "Auto Model does not support the Responses API.",
   "context_window": null }]
```

`useResponsesApiCapability` already returns unavailable when
`selectedModel.supports_responses === false`, and the batch toggle already keys off
`supports_batch`. So selecting a router disables both toggles with a correct reason and no
new branch.

The reverse direction is the part that needs new code: when `responsesApiEnabled` is
already on, router entries in the credential dropdown are rendered `disabled` with a title
explaining why. This mirrors how batch and Responses already disable each other.

A backend guard rejects `router` plus `use_responses_api` regardless of UI, because Chat
and other surfaces can set the flag without going through the node panel.

## UI

`CredentialDialog.vue` is 3942 lines. The router does not grow it further: the type list
gains `model_router`, and the fields live in two new components.

- `frontend/src/components/Credentials/modelRouter/ModelRouterFields.vue` — decision
  credential picker, decision model, routing instructions, the sharing notice.
- `frontend/src/components/Credentials/modelRouter/ModelRouterOptionsEditor.vue` — the
  option rows. Same pattern as `DecisionQuestionsEditor.vue`.

The dialog widens (`sm:max-w-*`) while this type is selected, because an option row holds
a credential picker, a model picker, a label and a criteria textarea.

Flow: pick the decision model credential and its model, write the routing instructions,
then add options. Each option row: credential → model (loaded from
`/credentials/{id}/models` for that credential) → label → criteria → optional "use when
routing fails" radio.

The dialog's Test Connection reuses the decision credential's existing `/credentials/test`
path against the selected decision model, so a misconfigured endpoint is caught before the
router is saved. No router branch is added to that endpoint.

## Files

### Backend

| File | Change |
| --- | --- |
| `app/services/model_router.py` | New. Config model, validation, state builder, `ModelRouter`. |
| `app/services/llm_service.py` | `router` param; `_resolve_turn`; per-turn binding in `execute` and `execute_with_tools`; rejections in batch and image paths. |
| `app/services/llm_trace.py` | Router fields on `LLMTraceContext`, persisted by `record_llm_trace`. |
| `app/db/models.py` | `CredentialType.model_router`; two `LLMTrace` columns. |
| `app/api/credentials.py` | Enum handling, validation, `public_fields`, masked value, `/llm` inclusion, synthetic `/models`, `GET /{id}/model-router`. |
| `app/api/traces.py` | Return and filter on the new columns. |
| `app/models/schemas.py` | Router fields on the trace response models. |
| `app/services/workflow_executor.py` | Build the router from the loaded credential in the `llm` and `agent` paths; pack `metadata.modelRouting`. |
| ~8 other `execute_llm` call sites | Build and pass the router; tolerate a keyless credential. |
| `app/services/workflow_dsl_prompt.py` | Tell the assistant Auto Model exists. |
| `alembic/versions/124_add_model_router_cred_type.py` | `ALTER TYPE credential_type ADD VALUE`. |
| `alembic/versions/125_llm_trace_router_columns.py` | The two trace columns. |

### Frontend

| File | Change |
| --- | --- |
| `components/Credentials/modelRouter/ModelRouterFields.vue` | New. |
| `components/Credentials/modelRouter/ModelRouterOptionsEditor.vue` | New. |
| `components/Credentials/CredentialDialog.vue` | Type entry, child components, conditional width. |
| `types/credential.ts` | `model_router` type, label, router trace fields. |
| `components/Traces/TracesPanel.vue` | `Router / Model` in the list and the detail pane. |
| `components/Panels/DebugPanel.vue` | Routing chip on the node row. |
| `components/Panels/executionTimeline.ts` | `modelRouting` on `SpanItem`. |
| `components/Panels/ExecutionSpanDetails.vue` | Model cell and per-turn list. |
| `components/Panels/propertiesPanel/nodes/LlmNodeProperties.vue` | Disable router entries while Responses API is on. |
| `components/Panels/propertiesPanel/nodes/AgentNodeProperties.vue` | Same. |

## Testing

Backend, under `backend/tests/`:

- `test_model_router.py` — config validation (each rejection above), decision-state
  building and truncation, `choice` criteria mapping, label → option resolution, default
  fallback, unknown label, nested-router rejection, state-hash reuse.
- `test_model_router_credentials.py` — create, update replacing the config wholesale,
  inclusion in `/credentials/llm`, the synthetic `/models` row, the test endpoint,
  validation errors.
- `test_model_router_llm_service.py` — routing per turn inside the tool loop, trace rows
  carrying the real credential plus `router_label`, `trace_ids` continuity across
  `dataclasses.replace`, and the Responses / batch / image rejections.
- `test_advisory_model_router_sharing.py` — the transitive grant is deliberate and
  bounded: option credential keys appear in no API response, no node output, no
  `node_results` row and no routing metadata; a router that references a credential the
  owner cannot access is rejected at write time.

Frontend: pure-logic Vitest only, per the standing preference against component and UI
tests in this repo. `useResponsesApiCapability.test.ts` is extended, and the router option
validation helper gets its own spec. No Playwright spec in this change, a deliberate
departure from the AGENTS.md E2E guidance, decided during design.

## Documentation and release tour

Docs: `frontend/src/docs/content/reference/credentials.md`, `credentials-sharing.md`
(the transitive grant), `integrations.md`, and `reference/features.md`. No node page and
no `node-types.md` entry, because no node type is added.

Release tour: a new `2026.14` entry in `releaseRegistry.ts` with a `model-router` section,
listed in that release's `sectionOrder`, a `ModelRouterTourVisual.vue` under
`components/visuals/` registered in `tourVisuals.ts`. `tourEnabled: false` until the
release commit. `releaseTourMapper.test.ts` stays passing. `frontend/e2e/support.ts`
derives its seeded versioned id from `buildReleaseTours` over the registry, so it needs no
manual realignment; confirm that is still true rather than assuming it.

## Open risks

- **Latency.** Every routed request adds a decision round trip. The state-hash reuse keeps
  a tool loop to one decision per genuinely new state, but a chat turn always pays it. The
  decision model is small and the call is bounded by `timeout_seconds`, defaulting to 10.
- **Criteria quality.** Routing is only as good as the free text the user writes. The
  dialog seeds `routing_instructions` with a usable default and the docs show a worked
  example.
- **Per-turn model changes.** An agent can start a turn on one model and finish on
  another. Conversation history is provider-neutral in `llm_transport.py`, so the handoff
  is sound, but reasoning-effort and structured-output support differ between models. The
  criteria text is where a user keeps incompatible models apart, and the Execution Span
  View shows exactly which turn ran where.
