# Input

The **Input** node is the entry point for workflows that receive data from the user or API caller. It supports single or multiple input fields and exposes request metadata (headers, query params).

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.body.fieldKey`, `$nodeLabel.headers`, `$nodeLabel.query` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `value` | string | Default value for single text input (optional) |
| `inputFields` | array | Input field definitions. Each: `{ key, defaultValue? }` |

### Input Fields

| Field | Type | Description |
|-------|------|-------------|
| `key` | string | Field key (e.g. `text`, `imageUrl`, `base64`) |
| `defaultValue` | string | Default if not provided (optional) |

## Accessing Input Data

**Body fields** (always use `$nodeLabel.body.fieldKey`):

- `$userInput.body.text` – text field
- `$userInput.body.imageUrl` – image URL
- `$userInput.body.userId` – with default if configured
- `$userInput.body.event.user.id` – nested JSON from Generic webhook mode

**Request metadata** (when executed via API):

- `$userInput.headers` – all headers (keys lowercase)
- `$userInput.headers.authorization` – specific header
- `$userInput.query` – query parameters
- `$userInput.query.param1` – specific query param

## Run Panel File Input

In the editor **Run** tab (Defined webhook mode), each input field supports drag-and-drop and an inline attachment control (bottom-right of the field):

- **Text files** (`.txt`, `.md`, `.json`, `.csv`, and any other file that reads as UTF-8 text, such as `notes` or `todo.list`) are read as plain text, up to 500 KB.
- **Images** (JPEG, PNG, GIF, WebP) are stored as a `data:` URL (base64) in the field value — use field keys such as `imageUrl` or `base64` when downstream nodes expect image data.
- **PDF** files are converted to extracted text (max 5 MB file, 100k characters of content).

One file per field. You can still edit the textarea after a file is loaded. Generic webhook mode (raw JSON body) does not show per-field file controls.

## Input Fields vs Generic Webhooks

`inputFields` still describe expected inputs for defined-mode editor forms, sub-workflow mapping, and other metadata-driven surfaces.

When a workflow uses **Generic** webhook body mode, the incoming HTTP body is not reshaped from `inputFields`. Instead, the raw JSON payload is passed through to `$nodeLabel.body`, and the Input node field add/remove controls are hidden in the node panel.

## Examples

**Single input (default):**

```json
{
  "type": "textInput",
  "data": {
    "label": "userInput",
    "inputFields": [{ "key": "text" }]
  }
}
```

**Multiple inputs:**

```json
{
  "type": "textInput",
  "data": {
    "label": "userInput",
    "inputFields": [
      { "key": "text" },
      { "key": "imageUrl" },
      { "key": "userId", "defaultValue": "anonymous" }
    ]
  }
}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Triggers](../reference/triggers.md) – Entry points (Input, Cron, RabbitMQ)
- [Expression DSL](../reference/expression-dsl.md) – Referencing `$nodeLabel.body`, `$nodeLabel.query`
- [Portal](../reference/portal.md) – Expose workflows as chat UIs
- [Webhooks](../reference/webhooks.md) – HTTP trigger for workflows
