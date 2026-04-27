# Execute

The **Execute** node calls another workflow (sub-workflow) and passes input to it. Use it for reusable logic, not for data transformation—use [Set](./set-node.md) for that.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.outputs.output.result`, `$nodeLabel.status`, `$nodeLabel.workflow_id` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `executeWorkflowId` | UUID | ID of the workflow to execute |
| `executeInput` | expression | Single input (for workflows with one input field) |
| `executeInputMappings` | array | `{ key, value }` for multiple inputs. `key` = target workflow's input field name. |
| `executeDoNotWait` | boolean | When `true`, dispatches the sub-workflow in the background without waiting. Output: `{ "status": "dispatched", "workflow_id": "..." }`. Default: `false`. |

## Response Format

```json
{
  "workflow_id": "uuid",
  "status": "success",
  "outputs": {
    "output": { "result": "the output value" }
  },
  "execution_time_ms": 1297.63
}
```

## Do Not Wait

When `executeDoNotWait: true`, the node dispatches the sub-workflow to a background thread and immediately returns:

```json
{
  "status": "dispatched",
  "workflow_id": "uuid"
}
```

The parent workflow continues to the next node without waiting. The sub-workflow's execution record is written to the trace asynchronously when it completes. Use this when the sub-workflow result is not needed downstream.

## Single Input

```json
{
  "type": "execute",
  "data": {
    "label": "callWorkflow",
    "executeWorkflowId": "workflow-uuid",
    "executeInput": "$userInput.body.text"
  }
}
```

## Multiple Inputs

When the target workflow has multiple input fields, use `executeInputMappings`:
```json
{
  "type": "execute",
  "data": {
    "label": "callWorkflow",
    "executeWorkflowId": "workflow-uuid",
    "executeInputMappings": [
      {"key": "text", "value": "$userInput.body.prompt"},
      {"key": "imageUrl", "value": "$userInput.body.image"}
    ]
  }
}
```

The `key` must match the target workflow's [Input](./input-node.md) `inputFields` keys.

## Related

- [Canvas Features](../reference/canvas-features.md) – Extract to Sub-Workflow to create Execute nodes from selected nodes
- [Node Types](../reference/node-types.md) – Overview of all node types
- [Input Node](./input-node.md) – Target workflow's input fields
- [Set Node](./set-node.md) – Data transformation (not workflow calls)
