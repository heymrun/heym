# Decision node design

Date: 2026-09-21
Status: approved, not yet implemented

## Summary

Add a `decision` node that calls a **decision model** (also marketed as a "System One"
model) and returns its typed judgments to the workflow. The first supported provider is
TypeSafe's Jev, but nothing in the design is Jev-specific: the request body is editable,
so any endpoint that speaks a similar contract can be targeted.

A decision model takes a `state` (what is going on) plus a map of typed `questions`, and
returns one answer per question with probabilities. It does not generate text.

## Why a separate node and not an LLM output type

The first shape considered was `outputType: "decision"` on the existing `llm` node, next
to `text` and `image`. It was rejected because a decision model is not an LLM in the sense
the rest of the codebase means:

- The protocol differs. The endpoint is `/v1/systemone`, not `/v1/chat/completions`.
  There is no `messages` array, no system prompt, no `temperature`, no streaming, no tool
  calling, and no `/v1/models` listing to populate a model dropdown from.
- The output differs. Answers are typed values with probability distributions, not text.
- The billing shape differs. Input is billed, output is free, because an answer is a few
  tokens.
- The training goal differs. These models are trained for calibrated decisions rather than
  for generation.

Folding it into `llm` would have meant hiding roughly half of the node's panel, splitting
the credential dropdown in two, and giving `credentialId` two incompatible meanings. A
separate node removes all of that.

## Non-goals

- No change to the `llm` node. `outputType` stays `text | image`.
- No decision integration on the `agent` node, and no decision agent tool. The only agent
  change in this work is exposing `maxToolIterations` in the panel (see below).
- No response normalisation. Whatever the provider returns becomes the node output
  verbatim; the workflow author consumes it with expressions.
- No seeded pricing row for Jev (see Traces and cost).

## Node identity

| Property | Value |
| --- | --- |
| Type key | `decision` |
| Label | Decision |
| Family | AI Nodes |
| Icon | `Scale` (lucide) |
| Colour token | `node-decision` |
| Inputs / outputs | 1 / 1 |
| Cluster placement | `ANYWHERE` |

`ANYWHERE` is correct: the node is a plain outbound HTTP call. It does not touch
`FILE_STORAGE_DIR`, leaves nothing on local disk, depends on nothing installed per
instance, and does not need a fixed outbound IP.

## Node data

```ts
{
  label: "decision",
  credentialId: "",          // a `decision` credential
  model: "",                 // e.g. "jev-latest"
  state: "$input.text",      // expression
  questions: [],             // DecisionQuestion[]
  customBodyEnabled: false,
  customBody: "",            // JSON, expression
  requestTimeoutSeconds: 60,
}

interface DecisionQuestion {
  id: string;
  type: "noul" | "choice" | "score";
  instructions: string;
  criteriaTrue?: string;                              // noul
  criteriaFalse?: string;                             // noul
  options?: { key: string; description: string }[];   // choice
  levels?: string[];                                  // score
}
```

Two shape decisions worth recording:

**`questions` is an ordered array, not a map**, even though it is sent as a map. While the
user types an `id` the field is briefly empty, two rows can transiently share an id, and a
map would not preserve row order in the editor. The array is converted to a map at
execution time; an empty or duplicated `id` is an execution error.

**`DecisionQuestion` is a flat record, not a discriminated union.** Switching `type` from
`choice` to `score` must not discard the `instructions` already typed. A union would
require rebuilding the object on every type change.

## Properties panel

New files under `frontend/src/components/Panels/propertiesPanel/nodes/`:

- `DecisionNodeProperties.vue` — Label, Credential, Model, State, Questions, Custom
  request body toggle, Request Timeout.
- `DecisionQuestionsEditor.vue` — the repeatable question rows. Split out because
  `PropertiesPanel.vue` must stay a thin shell and node forms should not grow unbounded.

Each row is a collapsible block: `id`, a `type` dropdown, `instructions`, and a
type-dependent criteria editor — true/false text for `noul`, key + description pairs for
`choice`, an ordered list of levels for `score`.

When **Custom request body** is enabled, the State field and the questions editor are
hidden and replaced by a single JSON editor pre-filled from the form. The body already
contains `model`, `state` and `questions`, so showing both would raise the question of
which one wins.

### Expression fields and `1/n` navigation

With a custom body: one expression field (the body).

Otherwise: State, plus each question's `instructions`, plus each criteria box. A two
question setup (one `noul`, one `choice` with two options) therefore navigates `1/6`
through `6/6`. All of them are registered in the expression dialog metadata, so
double-clicking the node walks them one by one and AI autofill can populate them.

## Backend execution

Two modules:

- `backend/app/services/decision_models.py` — body construction, the HTTP call, error
  mapping, trace writing. Provider knowledge starts and ends here.
- `backend/app/services/node_execution/nodes/decision_node.py` — expression resolution and
  delegation. Retry, tracing, cancellation and `NodeResult` packaging stay in the executor,
  per the WorkflowExecutor modularity policy.

Registered as `"decision": "decision_node"` in `node_execution/registry.py`.

### Body construction

```
customBodyEnabled = false:
  state       -> resolved expression (see below)
  questions[] -> map keyed by id, row order preserved
  body = {"model": model, "state": <resolved>, "questions": {...}}

customBodyEnabled = true:
  customBody  -> expressions resolved -> JSON parsed -> sent verbatim
```

Criteria are built per type: `noul` produces `{"true": ..., "false": ...}` and is omitted
entirely when both sides are blank, since the API treats it as optional; `choice` produces
`{key: description}`; `score` produces an ordered array.

Validation errors (surfaced as execution errors): empty `id`, duplicate `id`, a `choice`
with no options, a `score` with fewer than two levels, malformed custom-body JSON.

### State typing

The API accepts `state` as `string | object | array`. A field holding a single expression
is resolved with `preserve_type=True`, so a chat log or a record object is sent as
structured data rather than being flattened into a string. A template with an embedded
expression (`"Ticket: $input.text"`) resolves to a string. This mirrors the branch already
used in `output_node.py`.

### HTTP and SSRF

`base_url` comes from user-supplied credential config, which makes it an SSRF surface. The
call goes through the existing guard, exactly as `create_guarded_openai_client` does:

```python
guard_http_url(base_url, subject="decision model endpoint")
client = build_guarded_http_client(timeout=..., limits=..., follow_redirects=True)
```

Public-IP check plus dial-time pinning, fail-closed. A raw `httpx.Client` must not be used
here. Outbound headers go through `merge_outbound_headers` so the Heym User-Agent is
preserved. `Authorization: Bearer <api_key>` is added only when an API key is set, because
self-hosted reproductions run without one. Timeout comes from `requestTimeoutSeconds`.

The OpenCode session header rule does not apply: it is scoped to requests whose credential
base URL is an `opencode.ai` host, and a decision provider is not OpenCode.

### Error mapping

| Upstream | Behaviour |
| --- | --- |
| 401 | "Invalid API key for the decision credential" |
| 422 | The provider's field-level message is carried into the node error |
| 429, 529 | Error message names the condition as transient (rate limited / provider overloaded) |
| Connection error / timeout | Ordinary node error |

The handler does not implement its own backoff. The executor has no notion of a "retryable"
error — retry is a per-node toggle (`retryEnabled`, `retryMaxAttempts`, `retryWaitSeconds`
at `workflow_executor.py:7095`) that applies to every exception alike. So 429 and 529 raise
an ordinary node error whose message says the condition is transient, and a node that wants
to survive it turns its own retry on. Duplicating backoff inside the handler is out of
bounds.

### Response

The provider response becomes the node output unchanged. With Jev this makes
`$decision.answers.department.choice`, `$decision.answers.urgency.noul` and
`$decision.usage.input_tokens` work naturally. With a custom contract, the author navigates
whatever their server returns.

## Traces and cost

Reuses the existing `LLMTrace` table. No new table.

```python
LLMTraceContext(user_id, credential_id, workflow_id, node_id, node_label, source="workflow")
record_llm_trace(ctx, request_type="decision.systemone",
                 request=body, response=resp, model=..., provider="decision",
                 prompt_tokens=usage.input_tokens,
                 completion_tokens=usage.output_tokens,
                 elapsed_ms=...)
```

`request_type` already carries values such as `chat.completions`, `images.generate` and
`guardrail_classification`; `decision.systemone` joins that family and keeps decision calls
distinguishable in the Traces tab.

**Cost is deliberately left unresolved.** `llm_pricing` is synced from Helicone, which does
not carry decision models. A seeded `startsWith` row would match correctly today and would
quietly become wrong at the vendor's first price change. An unpriced model already renders
as empty in Traces, and a user who wants a figure can add their own `LLMPricingOverride`
from the UI. The docs will say this in one sentence.

No `audit()` calls: the node runs on whichever instance claimed the run, and audit logging
is restricted to routers.

## Credential

A new `decision` credential type, because `GET /credentials/llm` returns only
`openai | google | custom` and `custom` is assumed OpenAI-compatible everywhere — its model
dropdown calls `/v1/models`, which a decision endpoint does not expose.

Config: `base_url` (required — `https://api.typesafe.ai`, or a self-hosted address) and
`api_key` (optional).

Surfaces touched:

- `backend/app/models/schemas.py` — enum value plus `CredentialConfigDecision`.
- `backend/app/db/models.py` — enum value.
- One Alembic migration: `ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'decision'`.
  There are eight precedents, most recently `105_add_rag_credential_type.py`. The file is
  numbered against the actual Alembic head at implementation time; 122 is the highest
  numbered revision today.
- `backend/app/api/credentials.py` — the create/update/mask/test/list branches, plus a new
  `GET /credentials/decision`.
- `frontend/src/components/Credentials/CredentialDialog.vue` — type option, form fields,
  validation, payload construction, and `CREDENTIAL_TYPE_LABELS`.

**Test Connection** is supported: a minimal `/v1/systemone` call with a single `noul`
question. It costs a handful of tokens and confirms at setup time that the key works.

## AI generation (Sparkle)

`DecisionAIQuestionsDialog.vue`, following two existing patterns:
`DataTableAISchemaDialog.vue` for the two-phase flow (`phase: "input" | "review"` — write
the intent, review what was generated, then apply) and `AlertAiPrompt.vue` for
`useChatModelSelection()` and for returning a clarification request when the prompt is too
vague to draft from.

The dialog produces a suggested `state` template plus question rows. With Custom request
body enabled, it produces the full body instead.

Endpoint: `POST /api/decisions/generate-questions` in a new `backend/app/api/decisions.py`.
Request: `prompt`, `credential_id`, `model`, optional `existing_questions`, optional
`state_sample`. The credential here is an **LLM** credential — the generator is an LLM, not
the decision model. A decision model answers questions; it does not write them.

The implementation mirrors `data_tables.generate_data_table_schema`:
`get_credential_for_user` → `execute_llm(..., content_only=True)` → JSON extraction →
normalisation → 422 when nothing usable comes back.

The system prompt teaches the contract: when each primitive applies (`noul` for whether a
condition holds, `choice` for one of a defined set, `score` for a degree along an ordered
dimension), that question ids are for code and are never sent to the model so the meaning
must be complete inside `instructions`, and that a `choice` needs a no-match option when
nothing may fit.

Trace source: `decision_ai`, node label `AI Decision Questions`. Because it is a new source,
`TRACE_SOURCE_LABELS` and the source filter list in `TracesPanel.vue` must both be updated —
otherwise the traces appear in the table but cannot be filtered for.

## DSL, expressions, autofill

- `workflow_dsl_prompt.py` gains a `decision` node section: fields, defaults, which fields
  accept expressions, and the schema of the three question types. Without it the AI
  Assistant cannot build a workflow containing the node.
- Expression dialog metadata registers State, every `instructions`, and every criteria box,
  so `1/n` navigation and AI autofill cover the whole node.
- `readonlyPreviewFields.ts` gains labels for the new fields.

## Docs

- New `frontend/src/docs/content/nodes/decision-node.md`, registered in
  `frontend/src/docs/manifest.ts`.
- `reference/features.md`: a per-node section and an entry in the AI Nodes sentence of the
  node-types summary.
- `reference/node-types.md`: AI Nodes.
- `reference/integrations.md`, `reference/credentials.md`, `reference/credentials-sharing.md`
  for the new credential type.

The node page states plainly that these models do not generate text, and that cost stays
empty in Traces unless the user adds a pricing override.

## Release tour

`2026.12` shipped on 2026-09-20 with `tourEnabled: true`, so this work opens a new entry:
`releaseId: "2026.13"`, `publishedAt` 2026-09-21, `tourEnabled: false` until the release
commit.

One section, `decision-node`, listed in `sectionOrder`, with an animated mock under
`components/visuals/` registered in `tourVisuals.ts` under the same `tourVisual` key.

The agent `maxToolIterations` input ships **without** a tour section, by decision: it
exposes a field that already existed in the DSL and the canvas default rather than
introducing new behaviour, and announcing it would be noise next to the node.

An unregistered key falls back silently to the neutral visual, which
`releaseTourMapper.test.ts` guards. While `tourEnabled` stays `false`, the seeded release id
in `frontend/e2e/support.ts` does not need to change.

## Agent: expose `maxToolIterations`

`maxToolIterations` already exists in the node defaults, in `WorkflowNodeData`, in the DSL
prompt, in `readonlyPreviewFields.ts` as "Max Iterations", and is read by the executor at
`workflow_executor.py:4854`. It has no input in `AgentNodeProperties.vue`, so today it can
only be set through the DSL or the canvas default.

Add a number input next to Tool Timeout, `min="1"`, **no upper bound**, default 30,
following the same block pattern as `requestTimeoutSeconds`. The engine applies no ceiling —
`int(node_data.get("maxToolIterations") or 30)` — and the `max(1, ...)` at line 5071 is a
HITL-resume floor, not a cap. A `max` attribute in the UI would invent a limit the engine
does not have.

## Testing

Backend (required):

- `backend/tests/test_decision_node.py` — form-to-body conversion for all three question
  types; rejection of empty and duplicate ids; type preservation for a single-expression
  `state`; custom body overriding the form; malformed JSON rejection; 401/422/429/529
  mapped to messages that name the cause; a private `base_url` rejected by the SSRF guard;
  a trace written as `decision.systemone` with the right token counts; the response passed
  through untouched.
- `backend/tests/test_decision_question_generation.py` — the generation endpoint: a
  non-LLM credential rejected, an unparseable model response returning 422, normalised
  question output.
- `backend/tests/test_cluster_node_placement.py` — `decision` resolves to `ANYWHERE`. The
  suite already fails the build when a registered node type has no placement entry.

Frontend: no new UI tests, per the standing preference for this repo; verification is lint,
typecheck, and manual use. `releaseTourMapper.test.ts` is a registry guard rather than a UI
test and must stay green. Playwright coverage is available on request but is not planned.

## File touch list

Backend:

```
app/services/decision_models.py                         (new)
app/services/node_execution/nodes/decision_node.py      (new)
app/services/node_execution/registry.py
app/services/cluster/node_placement.py
app/services/workflow_dsl_prompt.py
app/api/decisions.py                                    (new)
app/api/credentials.py
app/main.py                                             (router registration)
app/models/schemas.py
app/db/models.py
alembic/versions/123_add_decision_credential_type.py    (new)
tests/test_decision_node.py                             (new)
tests/test_decision_question_generation.py              (new)
tests/test_cluster_node_placement.py
```

Frontend:

```
src/types/node.ts
src/types/workflow.ts
src/types/credential.ts
src/components/Panels/propertiesPanel/nodes/DecisionNodeProperties.vue   (new)
src/components/Panels/propertiesPanel/nodes/DecisionQuestionsEditor.vue  (new)
src/components/Panels/propertiesPanel/PropertiesPanel.vue                (wiring only)
src/components/Panels/propertiesPanel/usePropertiesPanelController.ts
src/components/Panels/propertiesPanel/nodes/AgentNodeProperties.vue
src/components/Decision/DecisionAIQuestionsDialog.vue                    (new)
src/components/Canvas/readonlyPreviewFields.ts
src/components/Canvas/WorkflowCanvas.vue
src/components/Credentials/CredentialDialog.vue
src/components/Traces/TracesPanel.vue
src/services/api.ts
src/docs/content/nodes/decision-node.md                                  (new)
src/docs/manifest.ts
src/docs/content/reference/features.md
src/docs/content/reference/node-types.md
src/docs/content/reference/integrations.md
src/docs/content/reference/credentials.md
src/docs/content/reference/credentials-sharing.md
src/features/release-tour/releaseRegistry.ts
src/features/release-tour/components/visuals/DecisionNodeTourVisual.vue  (new)
src/features/release-tour/tourVisuals.ts
```

## Assumptions

- Nothing is pushed. Work stays local.
