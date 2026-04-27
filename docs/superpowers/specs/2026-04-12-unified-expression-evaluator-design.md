# Unified Expression Evaluator — Design Spec

**Date:** 2026-04-12  
**Status:** Approved  
**Scope:** Frontend + Backend + DSL + Docs  

---

## 1. Background & Problem Statement

Heym's `ExpressionInput.vue` component currently operates in two distinct modes controlled by a `evaluationMode?: "template" | "expression"` prop:

- **Expression mode** (default): single `$expr` → typed value. Used for Condition, Variable, Set, Output schema values. Badge: blue "Expression Mode".
- **Template mode**: prose with embedded `$ref` substitutions → always a string. Used for LLM prompts, Output messages, Slack/Email bodies. Badge: amber "Text(String) Mode".

### Root problems

1. **Hidden configuration**: The mode is only a Vue prop on `ExpressionInput`. It is never saved to workflow JSON. Users have no way to know which mode a field uses without inspecting the source code.
2. **Frontend–Backend duplication**: `resolveTemplatePreview`, `resolveExpressionPreview`, arithmetic tokenizer, and ternary parser in `ExpressionInput.vue` are manual re-implementations of backend logic in `workflow_executor.py`. Any backend change must be manually mirrored in the frontend.
3. **Unexpected behaviour**: The two preview implementations can silently diverge from the backend, making the dialog output misleading.
4. **Confusion**: Users encounter two differently-coloured badges and two behavioural models in the same dialog with no in-product explanation of when each applies.
5. **Dialog is too small**: The current expand dialog does not give enough visual space for complex expressions.
6. **No field identity in header**: The dialog header always says "Edit Expression" — users lose track of which field they are editing.

---

## 2. Goal

Merge both modes into a single, unified `ExpressionInput` that:

- Removes the `evaluationMode` prop distinction from the frontend.
- Delegates all evaluation to the backend via a new API endpoint.
- Adds a **Run** button that uses pinned data / last execution context.
- Shows `"Evaluate — {fieldName}"` in the dialog header.
- Is displayed as a **80 vw × 80 vh** centered modal.
- Preserves type semantics: if the entire field value is a single `$expr`, arrays/objects come back as their native types; prose templates always produce strings.
- Keeps all existing DSL syntax rules unchanged.
- Is fully covered by backend unit tests.

---

## 3. Architecture

```
[ExpressionInput.vue — unified, no evaluationMode]
        |
        | user clicks Run (Ctrl/Cmd+R)
        ↓
POST /api/expressions/evaluate
  body: { expression, workflow_id, current_node_id, field_name }
        |
        ↓
ExpressionEvaluatorService.evaluate(...)
        |
        ├─ _is_single_dollar_expression()?
        │     YES → resolve_expression(preserve_type=True)
        │     NO  → evaluate_message_template()
        |
        ↓
{ result, result_type, preserved_type, error }
        |
        ↓
[Dialog Output section — backend result rendered]
[ExpressionOutputPathPicker — works on backend result]
```

### What is removed

| Component | Removed |
|---|---|
| `ExpressionInput.vue` | `resolveTemplatePreview()`, `resolveExpressionPreview()`, arithmetic tokenizer, ternary parser, `evaluationMode` prop |
| `PropertiesPanel.vue` | All `evaluation-mode="template"` and `evaluation-mode="expression"` attributes |
| `JsonInputPanel.vue` | `evaluationMode` prop pass-through |

### What is kept

| Component | Kept | Reason |
|---|---|---|
| `findDollarExpressions()` | ✅ | Powers autocomplete, not evaluation |
| `ExpressionOutputPathPicker` | ✅ | UI feature, works on any result object |
| Nested `$` warning | ✅ | Syntax hint, no backend round-trip needed |
| `expressionPathPicker.ts` helpers | ✅ | Used by path picker UX |

---

## 4. Backend Changes

### 4.1 New API endpoint

```
POST /api/expressions/evaluate
Auth: required (get_current_user)
```

**Request schema (`ExpressionEvaluateRequest`):**

```python
class NodeResultItem(BaseModel):
    node_id: str
    label: str
    output: Any  # the node's last execution output (any JSON-serialisable value)

class ExpressionEvaluateRequest(BaseModel):
    expression: str
    workflow_id: UUID
    current_node_id: str
    field_name: str | None = None
    node_results: list[NodeResultItem] = []  # last-run outputs from canvas
```

**Response schema (`ExpressionEvaluateResponse`):**

```python
class ExpressionEvaluateResponse(BaseModel):
    result: Any               # the evaluated value
    result_type: str          # "string" | "number" | "boolean" | "array" | "object" | "null"
    preserved_type: bool      # True when single $ expression and type was not serialised to JSON string
    error: str | None         # None on success, error message on failure
```

**Evaluation logic (`ExpressionEvaluatorService`):**

```python
def evaluate(self, expression: str, context: dict) -> ExpressionEvaluateResponse:
    if _is_single_dollar_expression(expression):
        result = executor.resolve_expression(expression, context, preserve_type=True)
        preserved_type = True
    else:
        result = executor.evaluate_message_template(expression, context)
        preserved_type = False
    return ExpressionEvaluateResponse(
        result=result,
        result_type=_classify_type(result),
        preserved_type=preserved_type,
        error=None,
    )
```

### 4.2 Context construction for the endpoint

The frontend already holds last-run node outputs in its `nodeResults` store (displayed as badges on canvas nodes after a workflow run). These are sent in the request body alongside the expression.

Priority order for building evaluation context (highest → lowest):

1. **Pinned data** — `node.pinned_data` on each workflow node. Set explicitly by the user via the canvas Pin action. Takes precedence because it reflects intentional test data.
2. **Last-run canvas outputs** — `node_results` array from the request body. Populated after the user runs the workflow on the canvas. The frontend sends `{ node_id, label, output }` for every node that has a result in the store.
3. **Empty / null** — if neither source covers an upstream node label, expressions referencing it resolve to `null`. The user sees a tooltip: `"Pin node data or run the workflow first"`.

Merge rule: for each upstream node label, pinned data wins; canvas output fills the rest. Both are injected as `label → value` into `_build_context`.

> The endpoint instantiates a lightweight `WorkflowExecutor` in read-only mode — no execution, only `_build_context` + evaluators. It does **not** re-run any node.

### 4.3 Security

- `simpleeval` already sandboxes evaluation; no change to security model.
- Input length limit: `expression` ≤ 10 000 characters.
- Endpoint is behind existing JWT auth middleware.

### 4.4 New file: `backend/app/services/expression_evaluator.py`

Extracts shared evaluation helpers out of `workflow_executor.py` into a dedicated service:
- `_is_single_dollar_expression(expr: str) -> bool`
- `_classify_type(value: Any) -> str`
- `ExpressionEvaluatorService.evaluate()`

`workflow_executor.py` imports from this service (no behavioural change to existing execution paths).

---

## 5. Frontend Changes

### 5.1 `ExpressionInput.vue`

- Remove `evaluationMode` prop (keep as deprecated optional — logs a Vue `warn()` but has no effect — until the next minor release, then delete entirely).
- Remove all frontend preview computation functions.
- Dialog output section becomes: **empty until Run is pressed**, then shows backend result.
- Run button: top-right of output section. `Ctrl/Cmd+R` shortcut.
- On click: sends `{ expression, workflow_id, current_node_id, field_name, node_results }` to the backend. `node_results` is built from the `nodeResults` prop already available on `ExpressionInput` (populated by the workflow store after each canvas run).
- Disabled state: when neither pinned data nor canvas run outputs exist for any upstream node → tooltip: `"Pin node data or run the workflow first"`.
- When canvas `nodeResults` are present (user has run the workflow), Run is always enabled.
- Loading state: spinner, button disabled.
- Error state: red output box with the `error` field from response.

### 5.2 Dialog layout

| Property | Current | New |
|---|---|---|
| Width | Full-screen overlay via `Teleport` | `w-[80vw]` centered modal |
| Height | Full-screen | `h-[80vh]` |
| Header | `"Edit Expression"` (static) | `"Evaluate — {dialogKeyLabel}"` |
| Badge | Blue/Amber mode badge | Removed |
| Output trigger | Every keystroke | Run button / `Ctrl+R` |

### 5.3 `PropertiesPanel.vue`

Remove all `evaluation-mode` attribute occurrences (~40 instances). Script to audit:

```bash
rg 'evaluation-mode' frontend/src/components/Panels/PropertiesPanel.vue
```

### 5.4 `JsonInputPanel.vue`

Remove `evaluationMode` prop forwarding. No change to `inputMode` (`raw` | `selective`).

---

## 6. DSL & AI Builder Changes

### 6.1 `workflow_dsl_prompt.py` — `WORKFLOW_DSL_SYSTEM_PROMPT`

- Remove any mention of "template mode" vs "expression mode" distinction.
- Add clarification: *"All string fields use unified expression syntax. If the entire value is a single `$expr`, the value preserves its native type (arrays stay arrays). If the value contains prose + `$refs`, the result is always a string."*
- Existing `$` placement rules remain unchanged.

### 6.2 `ai_assistant.py`

No change needed — the AI generates plain strings; the unified backend evaluator handles semantics.

---

## 7. Documentation Changes

Use `heym-documentation` skill for all doc updates.

| File | Change |
|---|---|
| `expression-evaluation-dialog.md` | Rewrite: remove mode distinction, document Run button, new header format, new dialog size |
| `expression-dsl.md` | Add type preservation behaviour section; update any mode references |
| `ai-assistant.md` | Remove mention of template vs expression field distinction |
| `features.md` | Update expression dialog entry |
| `nodes/*.md` files that reference expression/template mode | Update field descriptions |

---

## 8. Test Plan

**Approach: backend unit tests only.** No integration tests. All DB/HTTP dependencies are mocked via `AsyncMock` / `unittest.mock.patch`. Tests follow existing `unittest.TestCase` / `unittest.IsolatedAsyncioTestCase` conventions.

### 8.1 New: `backend/tests/test_expression_evaluator_service.py`

Core service logic, pure unit tests (no network, no DB).

```
TestIsSingleDollarExpression (TestCase)
  test_plain_dollar_ref                    # "$input.text" → True
  test_dollar_ref_with_method              # "$llm.text.upper()" → True
  test_dollar_ref_with_bracket             # "$node.headers['x-api-key']" → True
  test_template_with_prefix_text           # "Hello $input.name" → False
  test_template_with_suffix_text           # "$input.name suffix" → False
  test_template_with_two_refs              # "$a.x and $b.y" → False
  test_literal_no_dollar                   # "just text" → False
  test_empty_string                        # "" → False

TestClassifyType (TestCase)
  test_string                              # "hello" → "string"
  test_integer                             # 42 → "number"
  test_float                              # 3.14 → "number"
  test_boolean_true                        # True → "boolean"
  test_boolean_false                       # False → "boolean"
  test_list                                # [1, 2] → "array"
  test_dict                                # {"a": 1} → "object"
  test_none                                # None → "null"

TestBuildEvalContext (TestCase)
  test_pinned_data_takes_precedence_over_canvas_output
  test_canvas_output_fills_when_no_pinned_data
  test_label_from_canvas_result_injected_correctly
  test_missing_node_resolves_to_null
  test_multiple_nodes_all_injected

TestExpressionEvaluatorServiceEvaluate (TestCase)
  test_single_expr_string_result
  test_single_expr_array_preserved               # array stays list, not JSON string
  test_single_expr_object_preserved              # dict stays dict, not JSON string
  test_single_expr_boolean_preserved
  test_single_expr_number_preserved
  test_template_string_concatenation             # "Hello $name" → "Hello John"
  test_template_with_two_refs                    # "$a and $b" → "foo and bar"
  test_arithmetic_expression                     # "$count + 1" single expr
  test_ternary_expression                        # "$x > 0 ? 'pos' : 'neg'"
  test_nested_object_dot_access                  # "$node.body.field"
  test_bracket_key_access                        # "$node.headers['x-api-key']"
  test_array_method_filter                       # "$items.filter('item > 2')"
  test_array_method_map                          # "$items.map('item.name')"
  test_string_method_upper                       # "$text.upper()"
  test_string_method_replace                     # "$text.replace('a','b')"
  test_date_now_available_in_context             # "$now" resolves without error
  test_uuid_available_in_context                 # "$UUID" produces non-empty string
  test_global_vars_available_in_context          # "$global.key" resolves
  test_credentials_available_in_context          # "$credentials.Token" resolves
  test_invalid_expression_returns_error_field    # bad syntax → error not None, result None
  test_expression_with_undefined_label_returns_null  # "$unknown.x" → null result, no crash
  test_preserve_type_false_serialises_array      # when preserve_type forced False → JSON string
  test_range_function                            # "$range(1,5)" → [1,2,3,4]
  test_array_function                            # "$array(1,2,3)" → [1,2,3]
  test_dict_function                             # "$dict(name='Ali')" → {"name": "Ali"}

TestExpressionEvaluatorServiceEdgeCases (TestCase)
  test_empty_expression_returns_empty_string
  test_expression_over_length_limit_raises
  test_literal_string_no_dollar_returned_as_is   # "just text" → "just text"
  test_null_literal_expression                   # "$null" or "null" → None result
  test_bool_literal_true                         # "true" → True (or string?)
  test_multiline_template_with_newlines
  test_expression_with_unicode_content
```

### 8.2 New: `backend/tests/test_expression_evaluator_api.py`

FastAPI route unit tests. DB and auth are mocked.

```
TestExpressionEvaluateEndpoint (IsolatedAsyncioTestCase)
  test_auth_required_returns_401
  test_valid_request_returns_200
  test_pinned_data_injected_from_workflow_nodes
  test_canvas_node_results_injected_from_request_body
  test_pinned_data_wins_over_canvas_result_for_same_label
  test_workflow_not_found_returns_404
  test_expression_too_long_returns_422
  test_invalid_expression_returns_200_with_error_field   # not 500
  test_result_type_array_in_response
  test_result_type_object_in_response
  test_result_type_string_in_response
  test_result_type_null_in_response
  test_preserved_type_true_for_single_expr
  test_preserved_type_false_for_template
```

### 8.3 Extend: `backend/tests/test_output_message_template_resolve.py`

- Add cases verifying `_is_single_dollar_expression` behaviour is consistent with the new service (no divergence after extraction).

---

## 9. Migration Pre-Conditions

The following must be complete before any implementation starts:

1. **Pinned data API confirmed**: verify that `node.pinned_data` is accessible via workflow query and the evaluator endpoint can read it without executing the workflow.
2. **PropertiesPanel audit**: run `rg 'evaluation-mode'` and produce exact line count — confirms migration scope.
3. **TDD first**: write all tests in §8 before writing service/endpoint code.
4. **DSL prompt regression**: after prompt update, run AI-generated workflow sample through the executor and confirm no breakage.
5. **Backward compatibility window**: deprecated `evaluationMode` prop logs a Vue warning but does not break existing workflows for one release.

---

## 10. Out of Scope

- Changing the workflow JSON schema (no `evaluationMode` field will be added to saved data).
- Real-time keystroke evaluation (Run is explicit; avoids excessive API calls).
- Changing `$` syntax rules.
- Frontend tests (per AGENTS.md convention).

---

## 11. Success Criteria

- [ ] `rg 'evaluationMode\|evaluation-mode' frontend/src` returns zero results (excluding deprecated fallback).
- [ ] `rg 'resolveTemplatePreview\|resolveExpressionPreview' frontend/src` returns zero results.
- [ ] All tests in §8 pass.
- [ ] Dialog shows `"Evaluate — fieldName"` header.
- [ ] Run button returns correct typed result for array expressions.
- [ ] `./check.sh` passes (lint + typecheck + all backend tests).
- [ ] All documentation updated via `heym-documentation` skill.
