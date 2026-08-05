# Extra Body passthrough for LLM and Agent nodes

Date: 2026-07-31

## Problem

Some providers accept non-standard request parameters that the OpenAI-compatible SDK
does not model, for example `{"thinking": {"type": "disabled"}}` or
`{"disable_reasoning": true}`. Heym already supports these internally through the
`extra_body` argument on `LLMService.execute`, but workflow authors have no way to set
them from the canvas. Today the only way is to edit backend code.

## Goal

Let a workflow author attach an arbitrary JSON object to every LLM API call made by an
`llm` or `agent` node, configured from the properties panel, disabled by default.

## Node data

Two new fields on both the `llm` and the `agent` node:

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `extraBodyEnabled` | boolean | `false` | Master switch. When false nothing is sent. |
| `extraBody` | string | `""` | Raw JSON text. Expression capable. |

The pair mirrors the existing `jsonOutputEnabled` / `jsonOutputSchema` convention so the
panel, the readonly canvas preview, and the DSL all stay consistent.

## Backend

### Shared resolution helper

`WorkflowExecutor.resolve_extra_body(node_data, inputs, node_id) -> dict | None`

1. Return `None` when `extraBodyEnabled` is falsy or `extraBody` is blank. Nothing is
   sent, which keeps the feature off by default.
2. Run `_resolve_template` over the raw text so `$node.field` references resolve.
3. `json.loads` the result.
4. Reject anything that is not a JSON object.

Failures raise `ValueError`, so the node fails with a clear message instead of silently
dropping the configuration:

- `Invalid extra body JSON: <parser message>`
- `Extra body must be a JSON object, got list`

The helper lives on `WorkflowExecutor` next to the other expression helpers because both
node handlers need it and because it depends on `_resolve_template`, `inputs`, and
`node_id`.

### Service layer

- `LLMService.execute` already accepts `extra_body`. No change.
- `LLMService.execute_with_tools` gains `extra_body` and applies it to every completion
  call in the tool loop, including follow-up turns after a tool result.
- `LLMService.execute_batch` gains `extra_body`. Batch JSONL entries carry the raw request
  body, so the keys merge into the top level of each per-item `body` dict rather than
  nesting under an `extra_body` key.
- The module level wrappers `execute_llm_with_tools` and `execute_llm_batch` forward the
  new argument. `execute_llm` already forwards it.

### Call sites that receive extra body

- `llm` node primary completion.
- `llm` node fallback model attempt, using the same value.
- `llm` node batch mode requests.
- `agent` node tool loop, every iteration.
- `agent` node non tool completion path.

### Call sites that deliberately do not

- Image generation and image edit. The images endpoint interprets body parameters
  differently and a chat-shaped payload would break the request.
- Guardrail sub calls. Those run against a separate moderation model chosen by a separate
  credential, so parameters aimed at the main model do not apply.

## Frontend

- `types/workflow.ts` gains `extraBodyEnabled?: boolean` and `extraBody?: string`.
- `types/node.ts` and the node creation defaults in `WorkflowCanvas.vue` seed
  `extraBodyEnabled: false` and `extraBody: ""` for both node types.
- `LlmNodeProperties.vue` and `AgentNodeProperties.vue` render a checkbox, and while it is
  checked, an `ExpressionInput` in monospace with a `Braces` format button in the top
  right corner of the field header. The button reformats the JSON, and turns red reading
  `Invalid` when the text does not parse.
- `usePropertiesPanelController.ts` gains `formatExtraBody`, an `extraBodyFormatError`
  ref, and the input refs. `llmExpressionFieldCount` and `agentExpressionFieldCount` grow
  by one while `extraBodyEnabled` is true so the field joins the `1/n` expression
  navigation, and the focus and navigate index maps route to it.
- `readonlyPreviewFields.ts` lists `extraBodyEnabled` as a boolean preview field and
  labels `extraBody` as `Extra Body`.

## DSL

The `llm` and `agent` sections of `workflow_dsl_prompt.py` document both fields and state
that the default is off, and that the generator must omit them entirely unless the user
explicitly asks for provider specific request parameters.

## Docs

`frontend/src/docs/content/nodes/llm-node.md` and `agent-node.md` gain an Extra Body
section covering the toggle, the JSON object requirement, expression support, and the
call sites that are excluded.

## Testing

Backend pytest coverage:

- Helper returns `None` when the toggle is off, when the text is blank, and when the key
  is absent entirely.
- Helper parses a valid object.
- Helper resolves `$` expressions before parsing.
- Helper raises on malformed JSON and on a JSON array or scalar.
- `llm` node handler passes the resolved value into `_execute_llm_node`.
- `_execute_llm_node` forwards it to the primary attempt and to the fallback attempt.
- Batch mode forwards it and the keys land in the per item body.
- `execute_with_tools` places it in the completion kwargs.
- `agent` node forwards it to `execute_llm_with_tools`.
- Default off: a node without the fields produces no `extra_body` argument.

Manual verification on a local instance: an `llm` node with `{"max_tokens": 16}` in the
extra body produces a visibly truncated response compared with the toggle disabled.

## Known limitation

Expression resolution is textual substitution into a JSON string, matching the existing
`githubWorkflowInputs` field. `{"max_tokens": $prev.limit}` works, but a resolved value
containing a double quote or a newline produces invalid JSON and fails the node. Building
JSON aware escaping is out of scope; the docs call this out instead.
