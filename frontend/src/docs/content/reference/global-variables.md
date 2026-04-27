# Global Variables

The **Global Variable Store** holds persistent, user-scoped key-value data that survives across workflow executions. Use it for API keys, configuration, or shared state that multiple workflows need.

## Local vs Global

| Store | Syntax | Scope | Persistence |
|-------|--------|-------|-------------|
| **Workflow-local** | `$vars.variableName` | Current execution only | In-memory, lost when execution ends |
| **Global** | `$global.variableName` | All workflows for the user | Persisted in database |

## Creating Global Variables

1. **From the Variables tab** – [Variables Tab](../tabs/global-variables-tab.md): Create, edit, and delete variables directly.
2. **From a Variable node** – Enable **Store in Global Variable Store** (`isGlobal: true`) in the node's properties. The variable is written to the store when the workflow runs.

## Using in Expressions

Access global variables with `$global.variableName`:

```
$global.apiKey
$global.settings.baseUrl
$global.userId
```

Use the same methods as workflow-local variables (e.g. `.upper()`, `.length`, `.add()` for arrays).

## Value Types

Supported types: `string`, `number`, `boolean`, `array`, `object`. Choose the type when creating or editing a variable.

## Sharing Global Variables

You can share a global variable with other users or [Teams](./teams.md) so they can use it in their own workflows.

- **Share with user** – Click the share icon next to an owned variable, enter the recipient's email, and click **Share**. The recipient will see the variable in their Global Variables list with a **Shared** badge and a "Shared by &lt;your email&gt;" label.
- **Share with team** – In the share dialog, select a team and click **Add**. All team members gain access.
- **Editable access** – Recipients can view, edit, and reference the shared variable via `$global.variableName` in their workflows. Only the owner can share, unshare, or delete the variable.
- **Name conflicts** – If a recipient already has a variable with the same name, their own variable takes precedence over the shared one.
- **Deshare** – Open the share dialog for the variable and click the **×** button next to the user you want to remove access for.

## Chat Integration

Global variables are available to the [Chat](../tabs/chat-tab.md) assistant. The LLM can reference them when answering questions or generating content.

## Related

- [Variables Tab](../tabs/global-variables-tab.md) – Manage global variables in the UI
- [Variable Node](../nodes/variable-node.md) – Set variables with `isGlobal`
- [Expression DSL](./expression-dsl.md) – `$global` syntax
