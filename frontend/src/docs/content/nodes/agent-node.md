# Agent Node

The **AI Agent** node is an LLM node with tool calling. It can run Python tools, call connected canvas nodes as tools, connect to MCP servers, use skills, optionally act as an orchestrator that delegates to other agent nodes, call other workflows as tools, and pause for [human review](../reference/human-in-the-loop.md).

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1, plus optional `review` when HITL is enabled |
| Output | `$nodeLabel.text`, `$nodeLabel.fieldName` (when JSON output enabled), or a pending HITL payload while waiting for review |

## Core Parameters

### Credential & Model

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | LLM credential (API key) from Settings |
| `model` | string | Model name (e.g. `gpt-4o`, `gemini-2.5-flash-lite`) |
| `fallbackCredentialId` | UUID (optional) | Fallback credential when primary fails |
| `fallbackModel` | string (optional) | Fallback model when primary fails |

Add credentials in the [Credentials](../tabs/credentials-tab.md) tab. The model list is loaded from the selected credential. If the primary credential or model returns an error, the node automatically retries with the fallback credential and model before failing.

### Prompts

| Parameter | Type | Description |
|-----------|------|-------------|
| `systemInstruction` | string | System prompt for the AI. Supports [expressions](../reference/expression-dsl.md). |
| `userMessage` | string | User message/prompt. Default: `$input.text` |
| `jsonOutputEnabled` | boolean | Structured JSON output |
| `jsonOutputSchema` | string | JSON Schema for structured output |

Use `$input.text`, `$nodeName.field`, and other [Expression DSL](../reference/expression-dsl.md) syntax.

### Reasoning models (o1, o3)

| Parameter | Type | Description |
|-----------|------|-------------|
| `temperature` | number | 0.0–2.0 (default: 0.7), for standard models |
| `reasoningEffort` | `"low"` \| `"medium"` \| `"high"` | Reasoning depth for reasoning models |

When using a reasoning model (e.g. o1, o3), the UI shows **Reasoning Effort** instead of Temperature. For standard models, **Temperature** controls creativity.

**JSON output example:** When you need structured data from the agent (e.g. classification, extraction), enable JSON output and provide a schema. The agent returns JSON matching the schema; access fields by name on the node output:

```json
{
  "jsonOutputEnabled": true,
  "jsonOutputSchema": "{ \"type\": \"object\", \"properties\": { \"status\": { \"type\": \"string\", \"enum\": [\"APPROPRIATE\", \"INAPPROPRIATE\"] }, \"reason\": { \"type\": \"string\" } }, \"required\": [\"status\", \"reason\"] }"
}
```

Downstream nodes can use `$agentLabel.status`, `$agentLabel.reason`, etc. Same behavior as the [LLM node](../nodes/llm-node.md) JSON output.

## Human Review (HITL)

Use HITL when an agent may need approval at specific moments before important actions.

| Parameter | Type | Description |
|-----------|------|-------------|
| `hitlEnabled` | boolean | Adds human-review checkpoints to the agent |
| `hitlSummary` | string | Approval guidelines that tell the agent when human review is needed |

When HITL is enabled, the agent receives a `request_human_review` tool. Use the system prompt and
this guidelines field to explain which tool calls, sub-agents, sub-workflows, MCP actions, skills,
or side effects require approval. The agent can call that tool only when needed, including multiple
times in one run.

The reviewer-facing summary on the public page is generated from the agent's review request at
runtime. If the agent does not provide a summary explicitly, Heym derives one from the Markdown
review body.

For MCP tools, Heym asks the model to interpret your written HITL instructions as one of three
scopes: `always`, `once`, or `never`. That means freeform wording such as "for each call", "only
one time", or "never ask" is normalized before runtime gating is applied.

Each HITL checkpoint creates a one-time public review link at `/review/{token}`. A reviewer can:

- **Accept** the original Markdown review text
- **Edit & Continue** with modified Markdown
- **Refuse** and continue with `text: ""`

When HITL is enabled, the node also exposes a `review` output handle on the canvas. Connect that branch to Slack, email, or other notification nodes if you want to broadcast the review URL and summary as soon as the run pauses.

The execution moves to `pending` until a reviewer responds. The review text is a single Markdown body, and the pending payload also includes shareable link text for external handoff. Nodes on the `review` branch run immediately when the pause is created; the normal output path continues only after approval. After approval, Heym resumes from the stored execution snapshot and the agent continues with the approved context. If a later step also needs approval, the agent can create another HITL checkpoint. See [Human-in-the-Loop](../reference/human-in-the-loop.md) for payload shape, review URL behavior, and resume semantics.

HITL is available for text-mode agent output only. In v1 it cannot be combined with `jsonOutputEnabled`.


## Orchestrator Mode

When enabled, the agent can delegate tasks to other agent nodes in the workflow. If **Orchestrator mode is disabled**, the agent **cannot create agent→agent connections** in the canvas.

| Parameter | Type | Description |
|-----------|------|-------------|
| `isOrchestrator` | boolean | When `true`, agent gets a `call_sub_agent` tool |
| `subAgentLabels` | string[] | Labels of agent nodes this orchestrator can call |

**Sub-agents** must use `$input.text` in their User Message so they receive the orchestrator's prompt.

When the orchestrator calls multiple sub-agents in a single turn, they execute in parallel. See [Agent Architecture](../reference/agent-architecture.md) for details.

## Sub-Workflows

When configured, the agent receives a `call_sub_workflow` tool to execute other workflows.

| Parameter | Type | Description |
|-----------|------|-------------|
| `subWorkflowIds` | string[] | IDs of workflows this agent can call as tools |

Select workflows in the Sub-Workflows section of the agent config. The agent will call them with `workflow_id` and `inputs` (object matching the target workflow's input fields). Max depth: 5 nested sub-workflow calls.

## Canvas Node Tools

You can connect a supported workflow node to an agent's **tools** handle so the agent can call that node at runtime. This turns existing canvas actions and transforms into callable tools without writing Python.

Use canvas node tools when you want the agent to decide when to run a configured node, while still keeping credentials, static fields, and workflow-specific settings in the node UI.

### Agent-provided fields

Fields on a connected tool node can be marked with the bot icon. Marked fields become required tool parameters that the agent must provide when it calls the node. Unmarked fields stay fixed and are read from the node configuration.

For example:

- Connect a Slack node to an agent as a tool
- Keep the credential fixed in the Slack node
- Mark `message` as agent-provided
- The agent receives a Slack tool where it supplies only the message at runtime

If the node is not connected to an agent as a tool, the bot icon is hidden and the node behaves like a normal workflow step.

### Runtime behavior

When the agent calls a canvas node tool, Heym temporarily merges the agent-provided arguments into that node's data, executes the node, returns the node output to the agent, then restores the original node configuration. Tool nodes do not run as regular workflow steps through normal scheduling; they run only when the agent calls them.

Canvas node tools are useful with integration nodes such as Slack, Telegram, HTTP, Send Email, and data-shaping nodes such as [Set](./set-node.md) and [JSON output mapper](./json-output-mapper-node.md). Trigger nodes and control-flow nodes are not intended to be used as agent tools.

## Python Tools

Define custom tools the agent can call. Each tool has:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Tool name (e.g. `count_characters`) |
| `description` | string | Description for the LLM |
| `parameters` | JSON Schema | OpenAI function-calling schema (object format) |
| `code` | string | Python function code |

**Parameters** must be a JSON object, not a string:

```json
{
  "type": "object",
  "properties": {
    "text": { "type": "string", "description": "Text to count" }
  },
  "required": ["text"]
}
```

**Example tool:**

```python
def count_characters(text: str) -> int:
    return len(text)
```

> **Sandbox.** Python tools run as untrusted code in a hardened, isolated Docker container by default (no network, no Docker socket, read-only filesystem, non-root). Imports are limited to an allowlist of safe standard-library modules. See [Security → Python Tool Sandbox](../reference/security.md#python-tool-sandbox) for configuration (`HEYM_PYTHON_TOOL_SANDBOX`).

| Parameter | Type | Description |
|-----------|------|-------------|
| `toolTimeoutSeconds` | number | Max seconds per tool execution (default: 30) |
| `requestTimeoutSeconds` | number | Max seconds to wait for each model response before timing out (default: 60). Raise it for slow or self-hosted providers (LiteLLM, vLLM, local models) and long multi-step runs. |

## MCP Connections

Connect to [Model Context Protocol](https://modelcontextprotocol.io/) servers to expose their tools to the agent.

| Parameter | Type | Description |
|-----------|------|-------------|
| `transport` | `"stdio"` \| `"sse"` \| `"streamable_http"` | Connection type |
| `timeoutSeconds` | number | Timeout for this connection (default: 30) |
| `label` | string | Optional display name |

**stdio** (local process):

| Field | Description |
|-------|-------------|
| `command` | Command to run (e.g. `npx`) |
| `args` | JSON array (e.g. `["-y", "@modelcontextprotocol/server-filesystem", "--path", "/tmp"]`) |
| `env` | JSON object of environment variables injected into the process (e.g. `{"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..."}`) |

Most API-keyed stdio servers authenticate via environment variables rather than command arguments. Set `env` per-connection so each agent node can use a different credential without touching the host environment.

`env` values support [Expression DSL](../reference/expression-dsl.md), so you can pass workflow inputs as credentials instead of hardcoding secrets:

```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "$userInput.pat" }
}
```

The expression `$userInput.pat` is resolved at runtime against the workflow's input data before the MCP process starts. This lets you accept tokens from a trigger or input node rather than embedding them in the workflow definition.

Example — GitHub MCP with hardcoded token:

```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxxxxxxxxxxx" }
}
```

Example — GitHub MCP with dynamic token from workflow input:

```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "$userInput.pat" }
}
```

Example — GitHub MCP with a Heym GitHub credential:

```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "$credentials.MyGitHubToken" }
}
```

The built-in GitHub credential currently targets PAT-based auth. If you need organization access, use a PAT with the required org/repository permissions.

Example — Slack MCP:

```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-slack"],
  "env": { "SLACK_BOT_TOKEN": "xoxb-...", "SLACK_TEAM_ID": "T0123456" }
}
```

**SSE** (remote server):

| Field | Description |
|-------|-------------|
| `url` | SSE endpoint URL. Supports expressions (e.g. `$userInput.serverUrl`). |
| `headers` | JSON object for auth/custom headers. Values support expressions. |

**Streamable HTTP** (remote server):

| Field | Description |
|-------|-------------|
| `url` | MCP endpoint URL (e.g. `https://example.com/mcp`). Supports expressions. |
| `headers` | JSON object for auth/custom headers. Values support expressions. |

## Skills

Skills are SKILL.md instructions plus optional Python files. They extend the agent's system context and can add Python tools.

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | string | Skill name |
| `content` | string | SKILL.md content (instructions) |
| `timeoutSeconds` | number | Timeout for skill Python execution (default: 30) |
| `files` | array | Optional `{ path, content }` entries (e.g. `.py` scripts) |

Skills can be added by dropping a `.zip` or `.md` file onto the Skills area.
Use the download button on a skill card to export that skill as a `.zip` archive for backup or reuse in another workflow.

Each skill card has four actions on the row below the title:

| Button | Description |
|--------|-------------|
| **Edit with AI** | Open Skill Builder to revise the skill from a chat prompt |
| **Download** | Export the skill as a `.zip` archive |
| **Remove** | Delete the skill from this agent node |
| **History** | Open skill history derived from [Edit History](../reference/edit-history.md) |

### Skill history

Skill history is **not** stored separately. It is derived from workflow Edit History snapshots: each saved workflow version includes the full agent node `skills` array.

From the History dialog you can:

- **Preview** a past snapshot (SKILL.md and file list)
- **Edit** — load a snapshot into the skill editor without reverting the whole workflow
- **AI Fine-tune** — open Skill Builder with that snapshot as the starting point
- **Revert** — restore only this skill from a past version (other nodes stay as they are)

History follows the same 7-day retention as workflow Edit History. Saving the workflow after skill edits creates new history entries.

The Skills section also includes **AI Build**:

- Click **AI Build** to create a new skill from a chat prompt
- Click the sparkle button on an existing skill to revise it with AI
- The modal streams assistant text while showing live `SKILL.md` and `.py` file previews
- **Download ZIP** exports the current preview without adding it to the node
- **Save & Add** saves the generated files back through the same ZIP parsing flow used by manual uploads

When editing with AI, Heym only sends text `.md` and `.py` skill files to the builder. Binary files are not included; if a skill needs images or other binary inputs, pass them as workflow inputs instead of embedding them inside Python source.

## Guardrails

Enable **Guardrails** in the node properties to block unsafe user messages before the agent runs. See [Guardrails](../reference/guardrails.md) for the full reference.

## Persistent memory (graph)

Optional **per-agent-node** knowledge graph stored in the database. When enabled, Heym appends a Markdown summary of remembered entities and relationships to the **system instruction** before each run (only if the graph is non-empty). After a **successful** agent completion, a background job extracts new durable facts from the conversation and merges them into the graph.

| Parameter | Type | Description |
|-----------|------|-------------|
| `persistentMemoryEnabled` | boolean | Enable load + background extraction for this canvas node |

**Sub-agents** keep their **own** graph (keyed by their node id), separate from the orchestrator.

Use the pink **brain** control on the node (when memory is on or the model row is shown) to open the graph editor and optional **memory sharing** (other workflows/agents). Full behavior, REST paths, and JSON export details: [Agent Persistent Memory](../reference/agent-persistent-memory.md).

## Context Compression

When an agent runs many tool iterations with large results (web scraping, document reads, sub-workflow outputs), the accumulated message history can approach the model's context window limit. Heym automatically compresses the conversation history mid-run to prevent context overflow.

**How it works:**

1. Before each tool iteration, Heym estimates the current token count (~4 characters per token).
2. If the estimate exceeds **80%** of the model's context window, compression is triggered.
3. The message history is split into preserved and compressed sections:
   - **Preserved**: system prompt, first user message, most recent user message
   - **Compressed**: everything in between (assistant reasoning turns, tool calls, tool results)
4. The middle section is summarized using the **same model and credential** — no extra configuration needed.
5. The compressed summary replaces the middle as a single assistant message.

**Observability:**

Compression events appear as `Context compressed (N messages → summary)` entries in:
- The **Debug panel** tool call list during live execution
- The **Execution history** run detail view
- The **Traces tab** as a `context.compression` trace entry

Compression is automatic and always active for Agent nodes. It does **not** apply to LLM nodes, the Chat tab, or AI Assistant sessions.

## Related

- [Why Heym](../getting-started/why-heym.md) – AI-native features vs n8n, Zapier, Make.com
- [Agent Persistent Memory](../reference/agent-persistent-memory.md) – Knowledge graph per agent node, optional sharing, API, editor
- [Agent Architecture](../reference/agent-architecture.md) – Sub-agents, orchestrator, skills, MCP, tool calling
- [Human-in-the-Loop](../reference/human-in-the-loop.md) – Public review pages, pending executions, approve/edit/refuse flow
- [Guardrails](../reference/guardrails.md) – Block unsafe content categories
- [Node Types](../reference/node-types.md) – Overview of all node types
- [AI Assistant](../reference/ai-assistant.md) – Chat UI for building workflows with natural language (distinct from the Agent node)
- [Expression DSL](../reference/expression-dsl.md) – Referencing data in prompts
- [Workflow Structure](../reference/workflow-structure.md) – Nodes, edges, and DSL format
- [Quick Start](../getting-started/quick-start.md) – Basic workflow with LLM and expressions
- [Credentials Tab](../tabs/credentials-tab.md) – Add API keys for the agent
- [MCP Tab](../tabs/mcp-tab.md) – Configure MCP for workflow tools
