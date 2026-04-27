# Sticky Note

The **Sticky Note** node adds markdown notes to the canvas. It is not executed—use it for documentation, instructions, or workflow notes.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 0 |
| Output | N/A (not executed) |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `note` | string | Markdown content. Double-click to edit on canvas. |

## Example

```json
{
  "type": "sticky",
  "data": {
    "label": "workflowNotes",
    "note": "## Workflow Notes\n\nThis workflow processes user input and returns a summary."
  }
}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Workflow Organization](../reference/workflow-organization.md) – Organize workflows
