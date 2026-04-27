# AI Assistant

The **AI Assistant** is a chat panel that opens from the Debug panel and appears fixed at the bottom-right of the editor. Use natural language to create or modify workflows—describe what you want, and the AI generates nodes and edges that are applied to the canvas.

For documentation questions outside the editor, use [Chat with Docs](./chat-with-docs.md). That surface is optimized for page-aware product help instead of workflow generation.

## Opening the Panel

1. Open a workflow in the editor
2. Locate the **Debug panel** at the bottom (execution results area)
3. Click the **AI** button (Sparkles icon) in the panel toolbar
4. The AI Assistant panel opens at the bottom-right

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

## Using the Chat

- Type your request in the input (e.g. "Create a workflow that takes user input and sends it to an LLM")
- Press **Enter** to send (Shift+Enter for newline)
- The AI streams its response. In **Agent** mode, if the response includes a workflow in a \`\`\`json code block, it is automatically parsed and applied to the canvas. In **Ask** mode the canvas is never modified.
- Use **Clear** to reset the conversation

## Workflow Auto-Apply

When the AI response contains a valid workflow JSON block (with `nodes` and optionally `edges`) in a \`\`\`json code block, Heym:

1. Parses the JSON from the response
2. Replaces the current canvas with the new nodes and edges
3. Tidies up node layout
4. Marks the workflow as unsaved

If parsing fails, a **Retry** button appears to regenerate the response.

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
3. The model returns a single workflow JSON block (with `nodes` and `edges`). The frontend parses it and applies it to the canvas.

The DSL enforces camelCase labels, unified expression rules, and node-specific fields. If a field value is a single `$expr`, the backend preserves the native type; if the value mixes prose with `$refs`, the result is a string. The one-`$` rule still applies: no `$` inside parentheses. [User Settings](./user-settings.md) User Rules are injected into this system prompt so your preferences apply to every AI-generated workflow.

If the current workflow contains Agent skills, the AI Assistant includes only each skill's `SKILL.md` in that workflow context. Attached `.py` files and binary skill assets are stripped before the request so the builder stays within model context limits even when skills contain large implementations.

## Related

- [Why Heym](../getting-started/why-heym.md) – Natural language workflow building vs other platforms
- [Quick Start](../getting-started/quick-start.md) – Build your first workflow
- [User Settings](./user-settings.md) – User Rules injected into AI Assistant system prompt
- [Chat with Docs](./chat-with-docs.md) – Page-aware assistant inside the documentation area
- [Core Concepts](../getting-started/core-concepts.md) – Workflows, nodes, and execution flow
- [Agent Node](../nodes/agent-node.md) – LLM node with tools and MCP
- [Credentials Tab](../tabs/credentials-tab.md) – Add API keys for the AI Assistant
- [Workflow Structure](./workflow-structure.md) – JSON format for workflows
