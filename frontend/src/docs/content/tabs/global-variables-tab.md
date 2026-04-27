# Variables Tab

The **Variables** tab manages the **Global Variable Store** – persistent key-value data shared across all your workflows.

<video src="/features/showcase/globalvariables.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/globalvariables.webm">▶ Watch Variables demo</a></p>

## Overview

- Create, edit, and delete global variables
- Variables are user-scoped and persist across workflow executions
- Reference in expressions via `$global.variableName`

## Creating a Variable

1. Click **New Variable**
2. Enter a **name** (used in expressions)
3. Set the **value** (string, number, boolean, array, or object)
4. Choose **value type** (Auto, String, Number, Boolean, Array, Object)

## Editing and Deleting

- **Edit** – Click the edit icon on a variable row
- **Delete** – Click the trash icon; workflows using it will need a replacement
- **Bulk delete** – Select multiple variables and use **Delete selected**

## Using in Workflows

Reference variables in any expression:

```
$global.apiKey
$global.settings.baseUrl
```

You can also set global variables from a [Variable node](../nodes/variable-node.md) by enabling **Store in Global Variable Store**.

## Related

- [Global Variables](../reference/global-variables.md) – Reference guide
- [Variable Node](../nodes/variable-node.md) – Set variables with `isGlobal`
- [Expression DSL](../reference/expression-dsl.md) – `$global` syntax
- [Chat Tab](./chat-tab.md) – Chat can access global variables
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces
