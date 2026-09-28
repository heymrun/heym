# AI Assistant

The **AI Assistant** is a chat panel that opens from the Debug panel and starts at the bottom-right of the editor. Drag the header to move it, and drag an edge or a corner to change its width or height. It will not shrink below 360×480 pixels. The position and size are remembered in this browser. **Reset position and size** in the header puts the panel back at the bottom-right. Use natural language to create or modify workflows—describe what you want, and the AI generates nodes and edges that are applied to the canvas.

For documentation questions outside the editor, use [Chat with Heym](./chat-with-heym.md). That surface is optimized for page-aware product help instead of workflow generation.

## Opening the Panel

1. Open a workflow in the editor
2. Locate the **Debug panel** at the bottom (execution results area)
3. Click the **AI** button (Sparkles icon) in the panel toolbar
4. The AI Assistant panel opens at the bottom-right. Drag its header to move it, or drag an edge or a corner to change its width and height.

Press `Ctrl + I` / `Cmd + I` anywhere in the editor to open or close the panel — the shortcut works even while a text input is focused. See [Keyboard Shortcuts](./keyboard-shortcuts.md).

## Closing the Panel

Click the **X** button, press `Ctrl + I` / `Cmd + I`, or toggle the **AI** button in the Debug panel toolbar. The header drags the panel; it does not close it.

## Configuration

Before sending messages, select:

| Setting | Description |
|---------|-------------|
| **Credential** | LLM credential (API key) from [Credentials](../tabs/credentials-tab.md) |
| **Model** | Model name (e.g. `gpt-4o`, `gemini-2.5-flash`) |

Add credentials in the [Credentials Tab](../tabs/credentials-tab.md). The model list loads from the selected credential.

## Agent Mode vs Ask Mode

The panel has two modes, toggled with the **Agent / Ask** chip in the panel header.

| Mode | Default | Behaviour |
|------|---------|-----------|
| **Agent** | ✓ | Builds and modifies the canvas. The AI generates a workflow JSON block that is automatically applied to the canvas when the response is complete. |
| **Ask** | | Answers questions only. The canvas is never touched. Use this to ask about your workflow, Heym features, or get advice without triggering a canvas update. |

Switch modes at any time. Changing the mode does not clear the conversation.

In Agent mode, the **YOLO mode** box under the message field makes the assistant run and fix what it builds. See [YOLO Mode](#yolo-mode).

## Using the Chat

- Type your request in the input (e.g. "Create a workflow that takes user input and sends it to an LLM")
- Press **Enter** to send (Shift+Enter for newline)
- The AI streams its response. In **Agent** mode, if the response includes a workflow in a \`\`\`json code block, it is automatically parsed and applied to the canvas. In **Ask** mode the canvas is never modified.
- Use **Clear** to reset the conversation
- Hover a message and click its copy icon to copy the text it shows, including any workflow JSON
- Drag the line above the message box to make the box taller. The input area can grow to 60% of the panel, and it returns to its default height when the page reloads

## Workflow Auto-Apply

When the AI response contains a valid workflow JSON block (with `nodes` and optionally `edges`) in a \`\`\`json code block, Heym:

1. Parses the JSON from the response
2. Replaces the current canvas with the new nodes and edges
3. Tidies up node layout
4. Marks the workflow as unsaved

If parsing fails, a **Retry** button appears to regenerate the response.

## YOLO Mode

**YOLO mode** lets the assistant test what it builds. Check the **YOLO mode** box under the message field, then send your request. The box appears in Agent mode only. It is off by default and resets to off when the page reloads. Hover the info icon next to it for a short summary.

With YOLO mode on, the assistant does not stop after it applies a workflow:

1. It applies the workflow to the canvas.
2. Before the first run it asks for test inputs. The card lists the workflow's input fields, filled with values the assistant suggests. Edit them and press **Run**. Later runs reuse these values. The card only comes back when the input fields change or the assistant needs different test data.
3. It runs the workflow on the canvas exactly like the **Run** button: unsaved changes are saved first, nodes light up, and the run appears in the Debug panel and [Execution History](./execution-history.md).
4. It reads the result. If the run did what you asked, it finishes with **Verified** and a short summary. If not, it fixes the workflow and runs it again.

It makes at most **5 runs** per message. Press **Stop** at any time to end the loop and stop a run in progress.

Each reply shows its steps as they happen:
- `Applying changes to canvas`;
- `Running workflow · attempt 2/5`, with an `Executing <node>` row for each node;
- the final verdict.

After each run a short line such as *Attempt 1 result sent · error in 1.2s* shows that the result went back to the assistant.

### Running your other workflows

In YOLO mode the assistant can also run your other workflows when it needs their result. For example, it can check what a workflow returns before calling it from an [Execute](../nodes/execute-node.md) node. These runs show as `Running workflow "<name>"...` steps and are recorded in Execution History with the trigger source `ai_assistant`. The workflow being edited is always tested on the canvas.

### When it stops early

| Situation | What happens |
|---|---|
| The assistant needs a decision, information, a credential or a data table | It asks with the usual question card. Answering continues the loop. |
| The run waits for a [human review](./human-in-the-loop.md) | The loop stops. Approve the review, then send a message. |
| The workflow waits for a file upload | The loop stops. YOLO mode cannot test upload-triggered runs. |
| A newer version of the workflow was saved elsewhere | The loop stops. Resolve the save conflict, then send a message. |

> **Runs are real.** Emails, messages and API calls in the workflow are actually sent on every attempt, and DataTable nodes write real rows. Every run saves the workflow, so earlier versions stay in [Edit History](./edit-history.md).

## Voice Input

On supported browsers, a **Voice** button enables speech-to-text. Click to start recording, click again to stop. The transcribed text is sent to the AI for grammar fixing before you send.

## Agent Node vs AI Assistant

| | Agent Node | AI Assistant |
|---|------------|---------------|
| **Purpose** | LLM node inside a workflow; runs during execution | Chat UI to build workflows with natural language |
| **Location** | Canvas node | Debug panel → floating panel |
| **When** | At runtime | While editing |

See [Agent Node](../nodes/agent-node.md) for the workflow node that executes LLM calls with tools and MCP.

## How It Works (AI Builder DSL)

The AI Assistant is powered by a **workflow DSL** (domain-specific language) that describes nodes, edges, and expressions. When you send a message:

1. Your message plus [User Rules](./user-settings.md) and the current workflow (if any) are sent to the backend.
2. The backend builds a **system prompt** that includes:
   - The full workflow DSL (node types, expression syntax, rules, examples)
   - Your User Rules appended as "User Custom Rules"
   - The current workflow JSON when you are editing an existing workflow
   - The list of available workflows if you use the Execute node
   - The names, types and ids of your own credentials (never their values)
   - The names, ids, descriptions and columns of the data tables you can use (never their rows)
3. The model returns a single workflow JSON block (with `nodes` and `edges`). The frontend parses it and applies it to the canvas.

### Credentials

When a workflow needs a credential, the assistant asks before building it. If you have credentials of a fitting type it lists them together with **Create a new credential**; if you have none it asks whether to create one. Every question also lets you continue without a credential.

Choosing to create one opens the credential form in the panel, preset to the right type and a suggested name. The values go straight to Heym; the assistant only learns the name and type. OAuth credentials (Google Sheets, Google Drive, BigQuery, Linear, Notion) connect in a popup, and a link to the authorization page appears in case the popup is blocked. Once the credential is saved, the card shows its name and the create button turns off; press **Submit answers** and the assistant puts the new credential on the node.

You can also ask for a credential on its own ("create a GitHub credential") or ask to change one you own ("update my sheet credential", "reconnect my Google Sheets"). The assistant answers with the same card: creating opens an empty form, updating opens the form on that credential with its secrets masked.

The assistant prefers a dedicated node. When no node covers an operation, such as adding a tab to a Google Sheet, it uses an HTTP request and writes the header line for the chosen credential. See [HTTP › Authenticating with Credentials](../nodes/http-node.md#authenticating-with-credentials).

Clarification questions that the workflow can do without say **Optional** in their input and can be skipped.

The DSL enforces camelCase labels, unified expression rules, and node-specific fields. If a field value is a single `$expr`, the backend preserves the native type; if the value mixes prose with `$refs`, the result is a string. The one-`$` rule still applies: no `$` inside parentheses. [Settings](./user-settings.md) User Rules are injected into this system prompt so your preferences apply to every AI-generated workflow.

If the current workflow contains Agent skills, the AI Assistant includes only each skill's `SKILL.md` in that workflow context. Attached `.py` files and binary skill assets are stripped before the request so the builder stays within model context limits even when skills contain large implementations.

### Data tables

When a workflow saves, stores or looks up records and you have not named another store, the assistant uses a [DataTable](../nodes/datatable-node.md) node. If you name one of your tables and it has the columns the workflow needs, the assistant uses it. Otherwise it asks which table to use. The card lists the tables that fit, each with its description and column types, plus **Create a new table** with a proposed name and columns. Tables shared with you are offered too; one you can only read is offered only for reading.

Pick the new table and press **Submit answers**: the card creates the table, and the assistant puts its id on the node and uses its exact column names. You can also ask for a table on its own, for example "create a table for my leads".

The assistant sees table names, descriptions and columns, never rows. It never changes the columns of an existing table: if a table lacks a column the workflow needs, it names the column and offers a new table instead. Add columns in the [DataTable tab](../tabs/datatable-tab.md).

## Related

- [Why Heym](../getting-started/why-heym.md) – Natural language workflow building vs other platforms
- [Quick Start](../getting-started/quick-start.md) – Build your first workflow
- [Settings](./user-settings.md) – User Rules injected into AI Assistant system prompt
- [Chat with Heym](./chat-with-heym.md) – Page-aware assistant inside the documentation area
- [Core Concepts](../getting-started/core-concepts.md) – Workflows, nodes, and execution flow
- [Agent Node](../nodes/agent-node.md) – LLM node with tools and MCP
- [Credentials Tab](../tabs/credentials-tab.md) – Add API keys for the AI Assistant
- [Workflow Structure](./workflow-structure.md) – JSON format for workflows
