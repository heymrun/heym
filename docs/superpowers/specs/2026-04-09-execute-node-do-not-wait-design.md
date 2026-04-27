# Execute Workflow Node — "Do Not Wait" Option

**Date:** 2026-04-09  
**Status:** Approved

---

## Summary

Add a `executeDoNotWait` boolean option to the Execute Workflow node. When enabled, the node dispatches the sub-workflow in the background and immediately returns `{ "status": "dispatched", "workflow_id": "<uuid>" }` without blocking the parent workflow's execution.

This option does NOT apply to agent nodes or tool calls inside agents — only to `node_type === "execute"`.

---

## Architecture

### New Field

`executeDoNotWait: boolean` (default: `false`) stored in node data.

### Backend — `workflow_executor.py`

In `_execute_node_logic()`, the `elif node_type == "execute":` branch is updated:

**When `executeDoNotWait` is `false` (default):**  
Behavior is identical to today — sub-executor runs synchronously and the parent waits.

**When `executeDoNotWait` is `true`:**

1. Input mappings are resolved the same way as today.
2. A `WorkflowExecutor` sub-executor is created with the same parameters as today (depth tracking, cancel_event, credentials, etc.).
3. `_SHARED_EXECUTOR.submit(sub_executor.execute, ...)` dispatches the sub-workflow to the existing thread pool without blocking.
4. A `done_callback` is attached to the future. When the background thread finishes (success or error), the callback:
   - Constructs a `SubWorkflowExecution` dataclass with the result or error details.
   - Appends it to `self.sub_workflow_executions` under the existing thread lock.
5. The execute node immediately returns:
   ```json
   { "status": "dispatched", "workflow_id": "<uuid>" }
   ```
6. The parent workflow continues to downstream nodes with this output.

**Constraints preserved:**
- HITL is still not supported inside sub-workflows (enforcement is inside the sub-executor itself, unchanged).
- Sub-workflow invocation depth tracking still applies.
- Cancel event is passed through (sub-workflow can still be cancelled).
- Agent nodes and their tool calls are completely unaffected.

### Frontend — `PropertiesPanel.vue`

A toggle is added in the Execute node configuration section:

```
[ ] Do not wait
    Alt workflow sonucunu beklemeden bir sonraki adıma geç
```

- Visible only when `node_type === "execute"`.
- Binds to `nodeData.executeDoNotWait` (boolean).
- Default: `false`.
- No visual badge or indicator on the node canvas (kept simple).

### TypeScript — `workflow.ts`

`NodeData` interface gets one new optional field:

```typescript
executeDoNotWait?: boolean;
```

### Documentation — `execute-node.md`

Add `executeDoNotWait` to the parameter table:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `executeDoNotWait` | boolean | No (default: false) | When true, dispatches the sub-workflow in the background and moves to the next node immediately. Output will be `{ "status": "dispatched", "workflow_id": "..." }`. |

---

## Output

| Mode | Output |
|------|--------|
| `executeDoNotWait: false` (default) | `{ "workflow_id": "...", "status": "success\|error", "outputs": {...}, "execution_time_ms": 1234 }` |
| `executeDoNotWait: true` | `{ "status": "dispatched", "workflow_id": "..." }` |

---

## Error Handling

- Background sub-workflow errors do **not** affect the parent workflow.
- Errors are captured in the `done_callback` and written to `sub_workflow_executions` with `status: "error"` and error details.
- These appear in trace/execution records visible to the user.

---

## Testing

Two test cases in `backend/tests/`:

1. **Regression:** `executeDoNotWait: false` (or absent) — sub-workflow result is returned synchronously, existing behavior unchanged.
2. **Fire-and-forget:** `executeDoNotWait: true` — node returns `{ "status": "dispatched", "workflow_id": "..." }` immediately; after the background thread completes, `sub_workflow_executions` contains the execution record.
