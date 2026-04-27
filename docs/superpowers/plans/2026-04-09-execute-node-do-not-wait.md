# Execute Workflow Node — Do Not Wait Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `executeDoNotWait` boolean option to the Execute Workflow node so the parent workflow can dispatch a sub-workflow in the background and immediately move to the next step.

**Architecture:** When `executeDoNotWait: true`, the execute node submits the sub-executor to `_SHARED_EXECUTOR` (already used for parallel node execution), attaches a `done_callback` that writes `SubWorkflowExecution` to `self.sub_workflow_executions` under the existing lock, and immediately returns `{ "status": "dispatched", "workflow_id": "..." }`. The synchronous path is unchanged. Agent nodes and tool calls are unaffected.

**Tech Stack:** Python 3.11 + `concurrent.futures.ThreadPoolExecutor` (already imported as `_SHARED_EXECUTOR`), Vue 3 + TypeScript (strict), Ruff formatter.

---

## File Map

| Action | Path |
|--------|------|
| Create | `backend/tests/test_execute_node_do_not_wait.py` |
| Modify | `backend/app/services/workflow_executor.py` (lines 4677–4769) |
| Modify | `frontend/src/types/workflow.ts` (line 285, after `executeInputMappings`) |
| Modify | `frontend/src/components/Panels/PropertiesPanel.vue` (after line 4204) |
| Modify | `frontend/src/docs/content/nodes/execute-node.md` |

---

## Task 1: Write failing backend tests

**Files:**
- Create: `backend/tests/test_execute_node_do_not_wait.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for Execute Workflow node executeDoNotWait option."""
import time
import uuid
import unittest

from app.services.workflow_executor import WorkflowExecutor, SubWorkflowExecution


TARGET_WF_ID = "11111111-1111-1111-1111-111111111111"

_TARGET_NODES = [
    {"id": "t1", "type": "textInput", "data": {"label": "input", "inputFields": [{"key": "text"}]}},
    {"id": "t2", "type": "output", "data": {"label": "output"}},
]
_TARGET_EDGES = [{"id": "te1", "source": "t1", "target": "t2"}]
_WORKFLOW_CACHE = {
    TARGET_WF_ID: {
        "nodes": _TARGET_NODES,
        "edges": _TARGET_EDGES,
        "name": "Target",
    }
}


def _make_parent_nodes(do_not_wait: bool) -> list[dict]:
    execute_data: dict = {
        "label": "callWorkflow",
        "executeWorkflowId": TARGET_WF_ID,
        "executeInput": "$userInput.body.text",
    }
    if do_not_wait:
        execute_data["executeDoNotWait"] = True
    return [
        {"id": "n1", "type": "textInput", "data": {"label": "userInput", "inputFields": [{"key": "text"}]}},
        {"id": "n2", "type": "execute", "data": execute_data},
        {"id": "n3", "type": "output", "data": {"label": "output"}},
    ]


_PARENT_EDGES = [
    {"id": "e1", "source": "n1", "target": "n2"},
    {"id": "e2", "source": "n2", "target": "n3"},
]

_INITIAL_INPUTS = {"headers": {}, "query": {}, "body": {"text": "hello"}}


class ExecuteNodeDoNotWaitTests(unittest.TestCase):
    """Covers both synchronous (regression) and fire-and-forget modes."""

    def test_wait_mode_returns_sub_result(self) -> None:
        """executeDoNotWait absent: returns sub-workflow result synchronously."""
        executor = WorkflowExecutor(
            nodes=_make_parent_nodes(do_not_wait=False),
            edges=_PARENT_EDGES,
            workflow_cache=dict(_WORKFLOW_CACHE),
        )
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs=_INITIAL_INPUTS,
        )
        self.assertEqual(result.status, "success")
        execute_result = next(
            (nr for nr in result.node_results if nr.node_type == "execute"), None
        )
        self.assertIsNotNone(execute_result)
        self.assertIn("outputs", execute_result.output)
        self.assertEqual(execute_result.output.get("workflow_id"), TARGET_WF_ID)
        # sub_workflow_executions must contain 1 record
        self.assertEqual(len(result.sub_workflow_executions), 1)
        self.assertEqual(result.sub_workflow_executions[0].workflow_id, TARGET_WF_ID)

    def test_do_not_wait_returns_dispatched(self) -> None:
        """executeDoNotWait: true → node output is dispatched status, not sub-result."""
        executor = WorkflowExecutor(
            nodes=_make_parent_nodes(do_not_wait=True),
            edges=_PARENT_EDGES,
            workflow_cache=dict(_WORKFLOW_CACHE),
        )
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs=_INITIAL_INPUTS,
        )
        self.assertEqual(result.status, "success")
        execute_result = next(
            (nr for nr in result.node_results if nr.node_type == "execute"), None
        )
        self.assertIsNotNone(execute_result)
        self.assertEqual(execute_result.output.get("status"), "dispatched")
        self.assertEqual(execute_result.output.get("workflow_id"), TARGET_WF_ID)
        # outputs key must NOT be present (we didn't wait for sub-result)
        self.assertNotIn("outputs", execute_result.output)

    def test_do_not_wait_background_records_trace(self) -> None:
        """Background sub-workflow appends SubWorkflowExecution to executor after completion."""
        executor = WorkflowExecutor(
            nodes=_make_parent_nodes(do_not_wait=True),
            edges=_PARENT_EDGES,
            workflow_cache=dict(_WORKFLOW_CACHE),
        )
        executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs=_INITIAL_INPUTS,
        )
        # Give background thread time to finish (sub-workflow is trivial, 0.5 s is generous)
        time.sleep(0.5)
        with executor.lock:
            bg_execs = list(executor.sub_workflow_executions)
        self.assertEqual(len(bg_execs), 1)
        self.assertEqual(bg_execs[0].workflow_id, TARGET_WF_ID)
        self.assertEqual(bg_execs[0].status, "success")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_execute_node_do_not_wait.py -v
```

Expected: `test_wait_mode_returns_sub_result` PASSES (existing behavior works), `test_do_not_wait_returns_dispatched` and `test_do_not_wait_background_records_trace` FAIL because `executeDoNotWait` is not yet implemented.

---

## Task 2: Backend implementation — add `executeDoNotWait` to executor

**Files:**
- Modify: `backend/app/services/workflow_executor.py` (lines 4677–4769)

- [ ] **Step 1: Read the current execute node branch**

Open `backend/app/services/workflow_executor.py` at line 4677 and confirm the branch starts with:

```python
elif node_type == "execute":
    execute_workflow_id = node_data.get("executeWorkflowId", "")
    execute_input_mappings = node_data.get("executeInputMappings", [])
    execute_input_template = node_data.get("executeInput", "")
```

- [ ] **Step 2: Add `execute_do_not_wait` read after line 4680**

After the line `execute_input_template = node_data.get("executeInput", "")` (line 4680), add:

```python
                execute_do_not_wait = bool(node_data.get("executeDoNotWait", False))
```

- [ ] **Step 3: Replace the synchronous sub-workflow execution block (lines 4721–4769) with the branching implementation**

Find this exact block (lines 4721–4769):

```python
                if execute_workflow_id and execute_workflow_id in self.workflow_cache:
                    target_workflow = self.workflow_cache[execute_workflow_id]
                    merged_global = dict(self.global_variables_context)
                    merged_global.update(self.vars)
                    sub_executor = WorkflowExecutor(
                        nodes=target_workflow["nodes"],
                        edges=target_workflow["edges"],
                        workflow_cache=self.workflow_cache,
                        test_mode=False,
                        credentials_context=self.credentials_context,
                        global_variables_context=merged_global,
                        workflow_id=uuid.UUID(execute_workflow_id),
                        trace_user_id=self.trace_user_id,
                        sub_workflow_invocation_depth=self._sub_workflow_invocation_depth + 1,
                        cancel_event=self.cancel_event,
                    )
                    enriched_execute_inputs = {
                        "headers": {},
                        "query": {},
                        "body": execute_inputs,
                    }
                    sub_result = sub_executor.execute(
                        workflow_id=uuid.UUID(execute_workflow_id),
                        initial_inputs=enriched_execute_inputs,
                    )
                    if sub_result.status == "pending":
                        raise ValueError("HITL is not supported inside Execute node sub-workflows.")

                    sub_exec = SubWorkflowExecution(
                        workflow_id=execute_workflow_id,
                        inputs=execute_inputs,
                        outputs=sub_result.outputs,
                        status=sub_result.status,
                        execution_time_ms=sub_result.execution_time_ms,
                        node_results=sub_result.node_results,
                        workflow_name=target_workflow.get("name", ""),
                    )
                    with self.lock:
                        self.sub_workflow_executions.append(sub_exec)
                        self.sub_workflow_executions.extend(sub_executor.sub_workflow_executions)

                    output = {
                        "workflow_id": execute_workflow_id,
                        "status": sub_result.status,
                        "outputs": sub_result.outputs,
                        "execution_time_ms": sub_result.execution_time_ms,
                    }
                else:
                    output = execute_inputs
```

Replace with:

```python
                if execute_workflow_id and execute_workflow_id in self.workflow_cache:
                    target_workflow = self.workflow_cache[execute_workflow_id]
                    merged_global = dict(self.global_variables_context)
                    merged_global.update(self.vars)
                    sub_executor = WorkflowExecutor(
                        nodes=target_workflow["nodes"],
                        edges=target_workflow["edges"],
                        workflow_cache=self.workflow_cache,
                        test_mode=False,
                        credentials_context=self.credentials_context,
                        global_variables_context=merged_global,
                        workflow_id=uuid.UUID(execute_workflow_id),
                        trace_user_id=self.trace_user_id,
                        sub_workflow_invocation_depth=self._sub_workflow_invocation_depth + 1,
                        cancel_event=self.cancel_event,
                    )
                    enriched_execute_inputs = {
                        "headers": {},
                        "query": {},
                        "body": execute_inputs,
                    }

                    if execute_do_not_wait:
                        _wf_id = execute_workflow_id
                        _wf_name = target_workflow.get("name", "")
                        _inputs_snapshot = dict(execute_inputs)
                        _self = self

                        def _bg_done(future) -> None:  # noqa: ANN001
                            try:
                                sub_res = future.result()
                                sub_exec = SubWorkflowExecution(
                                    workflow_id=_wf_id,
                                    inputs=_inputs_snapshot,
                                    outputs=sub_res.outputs,
                                    status=sub_res.status,
                                    execution_time_ms=sub_res.execution_time_ms,
                                    node_results=sub_res.node_results,
                                    workflow_name=_wf_name,
                                )
                            except Exception:
                                sub_exec = SubWorkflowExecution(
                                    workflow_id=_wf_id,
                                    inputs=_inputs_snapshot,
                                    outputs={},
                                    status="error",
                                    execution_time_ms=0.0,
                                    node_results=[],
                                    workflow_name=_wf_name,
                                )
                            with _self.lock:
                                _self.sub_workflow_executions.append(sub_exec)

                        bg_future = _SHARED_EXECUTOR.submit(
                            sub_executor.execute,
                            workflow_id=uuid.UUID(execute_workflow_id),
                            initial_inputs=enriched_execute_inputs,
                        )
                        bg_future.add_done_callback(_bg_done)
                        output = {"status": "dispatched", "workflow_id": execute_workflow_id}
                    else:
                        sub_result = sub_executor.execute(
                            workflow_id=uuid.UUID(execute_workflow_id),
                            initial_inputs=enriched_execute_inputs,
                        )
                        if sub_result.status == "pending":
                            raise ValueError("HITL is not supported inside Execute node sub-workflows.")

                        sub_exec = SubWorkflowExecution(
                            workflow_id=execute_workflow_id,
                            inputs=execute_inputs,
                            outputs=sub_result.outputs,
                            status=sub_result.status,
                            execution_time_ms=sub_result.execution_time_ms,
                            node_results=sub_result.node_results,
                            workflow_name=target_workflow.get("name", ""),
                        )
                        with self.lock:
                            self.sub_workflow_executions.append(sub_exec)
                            self.sub_workflow_executions.extend(sub_executor.sub_workflow_executions)

                        output = {
                            "workflow_id": execute_workflow_id,
                            "status": sub_result.status,
                            "outputs": sub_result.outputs,
                            "execution_time_ms": sub_result.execution_time_ms,
                        }
                else:
                    output = execute_inputs
```

- [ ] **Step 4: Run ruff format and check**

```bash
cd backend && uv run ruff format app/services/workflow_executor.py && uv run ruff check app/services/workflow_executor.py
```

Expected: no errors.

- [ ] **Step 5: Run tests — all three must pass**

```bash
cd backend && uv run pytest tests/test_execute_node_do_not_wait.py -v
```

Expected output:
```
PASSED tests/test_execute_node_do_not_wait.py::ExecuteNodeDoNotWaitTests::test_wait_mode_returns_sub_result
PASSED tests/test_execute_node_do_not_wait.py::ExecuteNodeDoNotWaitTests::test_do_not_wait_returns_dispatched
PASSED tests/test_execute_node_do_not_wait.py::ExecuteNodeDoNotWaitTests::test_do_not_wait_background_records_trace
```

- [ ] **Step 6: Run full backend test suite**

```bash
cd backend && ./run_tests.sh
```

Expected: all suites pass.

- [ ] **Step 7: Commit**

```bash
git add backend/tests/test_execute_node_do_not_wait.py backend/app/services/workflow_executor.py
git commit -m "feat: add executeDoNotWait option to Execute Workflow node (backend)"
```

---

## Task 3: Frontend TypeScript type

**Files:**
- Modify: `frontend/src/types/workflow.ts` (after line 285, `executeInputMappings?: ExecuteInputMapping[];`)

- [ ] **Step 1: Add `executeDoNotWait` to `NodeData`**

In `frontend/src/types/workflow.ts`, find the line:

```typescript
  executeInputMappings?: ExecuteInputMapping[];
```

Add immediately after:

```typescript
  executeDoNotWait?: boolean;
```

- [ ] **Step 2: Run TypeScript check**

```bash
cd frontend && bun run typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/workflow.ts
git commit -m "feat: add executeDoNotWait field to NodeData type"
```

---

## Task 4: Frontend UI toggle

**Files:**
- Modify: `frontend/src/components/Panels/PropertiesPanel.vue` (after the execute template, around line 4204)

- [ ] **Step 1: Add the checkbox toggle inside the execute template**

In `PropertiesPanel.vue`, find the closing `</template>` of the execute section (line 4205, immediately after the `v-if="!selectedNode.data.executeWorkflowId"` block):

```html
          </template>

          <template v-if="selectedNode.type === 'http'">
```

Insert **before** that `<template v-if="selectedNode.type === 'http'">` line, still inside the execute template:

```html
            <div class="flex items-center gap-2 pt-1">
              <input
                id="execute-do-not-wait"
                type="checkbox"
                class="h-4 w-4 rounded border-input bg-background"
                :checked="!!selectedNode.data.executeDoNotWait"
                @change="updateNodeData('executeDoNotWait', ($event.target as HTMLInputElement).checked)"
              >
              <Label
                for="execute-do-not-wait"
                class="text-sm font-normal"
              >
                Do not wait
              </Label>
            </div>
```

- [ ] **Step 2: Run lint and typecheck**

```bash
cd frontend && bun run lint && bun run typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Panels/PropertiesPanel.vue
git commit -m "feat: add Do not wait toggle to Execute node properties panel"
```

---

## Task 5: Update documentation

**Files:**
- Modify: `frontend/src/docs/content/nodes/execute-node.md`

- [ ] **Step 1: Add `executeDoNotWait` to the Parameters table**

Find the Parameters table:

```markdown
| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `executeWorkflowId` | UUID | ID of the workflow to execute |
| `executeInput` | expression | Single input (for workflows with one input field) |
| `executeInputMappings` | array | `{ key, value }` for multiple inputs. `key` = target workflow's input field name. |
```

Replace with:

```markdown
| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `executeWorkflowId` | UUID | ID of the workflow to execute |
| `executeInput` | expression | Single input (for workflows with one input field) |
| `executeInputMappings` | array | `{ key, value }` for multiple inputs. `key` = target workflow's input field name. |
| `executeDoNotWait` | boolean | When `true`, dispatches the sub-workflow in the background without waiting. Output: `{ "status": "dispatched", "workflow_id": "..." }`. Default: `false`. |
```

- [ ] **Step 2: Add a Do Not Wait section after the Response Format section**

After the existing `## Response Format` section (after the closing ` ``` ` of the JSON block), add:

```markdown
## Do Not Wait

When `executeDoNotWait: true`, the node dispatches the sub-workflow to a background thread and immediately returns:

```json
{
  "status": "dispatched",
  "workflow_id": "uuid"
}
```

The parent workflow continues to the next node without waiting. The sub-workflow's execution record is written to the execution trace asynchronously when it completes. Use this when the sub-workflow result is not needed downstream.
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/docs/content/nodes/execute-node.md
git commit -m "docs: add executeDoNotWait option to execute-node documentation"
```

---

## Final Verification

- [ ] **Run full backend test suite**

```bash
cd backend && ./run_tests.sh
```

- [ ] **Run frontend lint + typecheck**

```bash
cd frontend && rm -rf dist && bun run lint && bun run typecheck
```

- [ ] **Run ruff on backend**

```bash
cd backend && uv run ruff check . && uv run ruff format --check .
```
