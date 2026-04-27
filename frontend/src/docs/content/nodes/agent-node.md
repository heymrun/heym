# Agent Node

The **AI Agent** node is an LLM node with tool calling. It can run Python tools, connect to MCP servers, use skills, optionally act as an orchestrator that delegates to other agent nodes, call other workflows as tools, and pause for [human review](../reference/human-in-the-loop.md).

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

| Parameter | Type | Description |
|-----------|------|-------------|
| `toolTimeoutSeconds` | number | Max seconds per tool execution (default: 30) |

## MCP Connections

Connect to [Model Context Protocol](https://modelcontextprotocol.io/) servers to expose their tools to the agent.

| Parameter | Type | Description |
|-----------|------|-------------|
| `transport` | `"stdio"` \| `"sse"` | Connection type |
| `timeoutSeconds` | number | Timeout for this connection (default: 30) |
| `label` | string | Optional display name |

**stdio** (local process):

| Field | Description |
|-------|-------------|
| `command` | Command to run (e.g. `npx`) |
| `args` | JSON array (e.g. `["-y", "@modelcontextprotocol/server-filesystem", "--path", "/tmp"]`) |

**SSE** (remote server):

| Field | Description |
|-------|-------------|
| `url` | SSE endpoint URL |
| `headers` | JSON object for auth/custom headers |

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
