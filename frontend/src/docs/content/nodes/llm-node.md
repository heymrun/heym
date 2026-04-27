# LLM

The **LLM** node processes text with a language model or generates images. It supports text generation, vision (image input), image generation, structured JSON output, and provider-native **Batch API** execution for supported text models.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1, plus optional `batchStatus` when batch mode is enabled |
| Output | `$nodeLabel.text` (text), `$nodeLabel.image` (image), or batch result fields such as `$nodeLabel.results` |

## Parameters

### Credential & Model

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | LLM credential from [Credentials](../tabs/credentials-tab.md) |
| `model` | string | Model name (e.g. `gpt-4o`, `gemini-2.5-flash-lite`, `nanobanana` for images) |
| `fallbackCredentialId` | UUID (optional) | Fallback credential when primary fails |
| `fallbackModel` | string (optional) | Fallback model when primary fails |

If the primary credential or model returns an error, the node automatically retries with the fallback credential and model before failing.

Heym also checks **batch capability** from the selected credential and model. Batch mode is available for:

- OpenAI credentials
- Custom / OpenAI-compatible credentials whose endpoint exposes the required `/v1/files` and `/v1/batches` APIs

If the selected provider or model does not support batch execution, the Properties panel shows that directly and disables the toggle.

### Prompts (text mode)

| Parameter | Type | Description |
|-----------|------|-------------|
| `systemInstruction` | string | System prompt. Supports [expressions](../reference/expression-dsl.md). |
| `userMessage` | string | User message. Default: `$input.text` |
| `temperature` | number | 0.0–2.0 (default: 0.7) |
| `maxTokens` | number | Max response tokens (optional) |

### Image & Output

| Parameter | Type | Description |
|-----------|------|-------------|
| `outputType` | `"text"` \| `"image"` | Text or image generation |
| `imageInputEnabled` | boolean | Include image with user message (vision) |
| `imageInput` | expression | Base64 data URL or image URL |
| `jsonOutputEnabled` | boolean | Structured JSON output |
| `jsonOutputSchema` | string | JSON Schema for structured output |

### Reasoning models (o1, o3)

| Parameter | Type | Description |
|-----------|------|-------------|
| `isReasoningModel` | boolean | Enable for reasoning models |
| `reasoningEffort` | `"low"` \| `"medium"` \| `"high"` | Reasoning depth |

### Batch Mode

| Parameter | Type | Description |
|-----------|------|-------------|
| `batchModeEnabled` | boolean | Use the provider-native Batch API instead of single-request execution |

Batch mode is available only on the **LLM** node. It does **not** apply to the [Agent Node](./agent-node.md).

When batch mode is enabled:

- `outputType` must stay `text`
- `imageInputEnabled` must stay `false`
- `userMessage` must resolve to an **array**
- each array item must resolve to a string or primitive value

Typical examples:

- `$input.items.map("item.text")`
- `$vars.promptList`

If the expression resolves to a single string instead of an array, the run fails with a validation error before the provider call starts.

## Batch Status Branch

When batch mode is enabled, the LLM node exposes a second output handle: `batchStatus`.

Use that branch for notifications, logging, Slack messages, or side effects while the batch is still running. The branch fires whenever the provider status meaningfully changes, including normalized states such as:

- `pending`
- `processing`
- `completed`
- `failed`

The status branch payload is available as `$input` inside downstream nodes and includes:

- `$input.batchId`
- `$input.batchStatus`
- `$input.status`
- `$input.rawStatus`
- `$input.total`
- `$input.completed`
- `$input.failed`
- `$input.requestCounts.total`
- `$input.requestCounts.completed`
- `$input.requestCounts.failed`
- `$input.provider`
- `$input.model`

Example edge:

```json
{
  "id": "edge-status",
  "source": "batchLlmNode",
  "sourceHandle": "batchStatus",
  "target": "notifyProgress"
}
```

Example status mapper:

```json
{
  "type": "set",
  "data": {
    "label": "notifyProgress",
    "mappings": [
      { "key": "status", "value": "$input.batchStatus" },
      { "key": "completed", "value": "$input.completed" },
      { "key": "total", "value": "$input.total" }
    ]
  }
}
```

## Batch Result Shape

On successful completion, the main LLM output contains:

- `$nodeLabel.text` – concatenated successful texts
- `$nodeLabel.batchId`
- `$nodeLabel.status`
- `$nodeLabel.rawStatus`
- `$nodeLabel.requestCounts`
- `$nodeLabel.total`
- `$nodeLabel.completed`
- `$nodeLabel.failed`
- `$nodeLabel.results` – per-item results in original order
- `$nodeLabel.usage`

Each item in `$nodeLabel.results` includes fields such as:

- `index`
- `customId`
- `status`
- `statusCode`
- `text`
- `error`
- `usage`

When **JSON output** is enabled together with batch mode, Heym parses each successful item separately. Parsed objects are exposed per item and collected on `parsedResults`.

## Image Generation

- **Models:** `nanobanana`, `gemini-2.0-flash-exp`
- **Output:** `$nodeLabel.image` (base64 data URL)
- When using [Input](./input-node.md) for the prompt, use `$userPrompt.body.text` in `userMessage`

## JSON Output

When `jsonOutputEnabled` is true, the LLM returns JSON matching the schema. Access fields via `$nodeLabel.fieldName`.

## Example – Text

```json
{
  "type": "llm",
  "data": {
    "label": "generateResponse",
    "credentialId": "credential-uuid",
    "model": "gpt-4o",
    "systemInstruction": "You are a helpful assistant.",
    "userMessage": "$userInput.body.text"
  }
}
```

## Example – Batch text

```json
{
  "nodes": [
    {
      "id": "var_1",
      "type": "variable",
      "position": { "x": 120, "y": 180 },
      "data": {
        "label": "batchPrompts",
        "variableName": "promptList",
        "variableType": "array",
        "variableValue": "$array(\"Summarize this invoice\", \"Draft a follow-up email\", \"Classify the invoice status\")"
      }
    },
    {
      "id": "llm_1",
      "type": "llm",
      "position": { "x": 420, "y": 180 },
      "data": {
        "label": "batchLlm",
        "credentialId": "credential-uuid",
        "model": "gpt-4o-mini",
        "batchModeEnabled": true,
        "systemInstruction": "Answer each item briefly.",
        "userMessage": "$vars.promptList"
      }
    },
    {
      "id": "set_1",
      "type": "set",
      "position": { "x": 760, "y": 70 },
      "data": {
        "label": "progressUpdate",
        "mappings": [
          { "key": "status", "value": "$input.batchStatus" },
          { "key": "completed", "value": "$input.completed" }
        ]
      }
    },
    {
      "id": "out_1",
      "type": "output",
      "position": { "x": 760, "y": 280 },
      "data": {
        "label": "batchResult",
        "outputKey": "responses"
      }
    }
  ],
  "edges": [
    { "id": "e1", "source": "var_1", "target": "llm_1" },
    { "id": "e2", "source": "llm_1", "sourceHandle": "batchStatus", "target": "set_1" },
    { "id": "e3", "source": "llm_1", "target": "out_1" }
  ]
}
```

## Example – Image generation

```json
{
  "type": "llm",
  "data": {
    "label": "generateImage",
    "credentialId": "credential-uuid",
    "model": "nanobanana",
    "outputType": "image",
    "userMessage": "$userPrompt.body.text"
  }
}
```

## Guardrails

Enable **Guardrails** in the node properties to block unsafe user messages before the LLM call. See [Guardrails](../reference/guardrails.md) for the full reference.

## Related

- [Agent Node](./agent-node.md) – LLM with tool calling
- [Why Heym](../getting-started/why-heym.md) – AI-native features vs n8n, Zapier, Make.com
- [Guardrails](../reference/guardrails.md) – Block unsafe content categories
- [Node Types](../reference/node-types.md) – Overview of all node types
- [Expression DSL](../reference/expression-dsl.md) – Referencing data in prompts
- [Expression Evaluation Dialog](../reference/expression-evaluation-dialog.md) – Expandable editor with live backend preview for prompts
- [Credentials Tab](../tabs/credentials-tab.md) – Add LLM API keys
- [Quick Start](../getting-started/quick-start.md) – Basic LLM workflow
