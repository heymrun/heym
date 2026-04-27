# Agent Architecture

The [Agent Node](../nodes/agent-node.md) supports sub-agents, sub-workflows, an orchestrator pattern, skills, MCP connections, tool calling, optional [persistent memory](./agent-persistent-memory.md) (per canvas node, with optional sharing to other agents), and optional [human review](./human-in-the-loop.md). This page describes the architecture.

## Sub-Agents

Sub-agents are agent nodes that an orchestrator can call via the `call_sub_agent` tool.

- **Orchestrator**: `isOrchestrator: true`, `subAgentLabels: ["researchAgent", "summarizerAgent"]`
- **Sub-agents**: Must use `$input.text` in their User Message so they receive the orchestrator's prompt
- **Tool**: `call_sub_agent` with `sub_agent_label` (enum) and `prompt`
- **Depth limit**: Max 5 nested sub-agent calls

### Execution Flow

1. Orchestrator decides to call a sub-agent
2. `_execute_sub_agent_tool` finds the target agent by label
3. Builds `synthetic_inputs = {"input": {"text": prompt}}`
4. Runs `_execute_agent_node` for the sub-agent
5. Result is returned to the orchestrator

### Parallel Sub-Agent Execution

When the orchestrator returns multiple `call_sub_agent` tool calls in a single turn, they are executed **in parallel**. For example, if the user asks about "Paris" and the orchestrator calls both `distanceAgent` and `foodAgent`, both run concurrently instead of sequentially.

- **Benefit**: Total time is roughly the slowest sub-agent, not the sum of all.
- **Hint**: Encourage the orchestrator to call multiple sub-agents in one turn when the task requires it.

## Sub-Workflows

When `subWorkflowIds` is configured, the agent can call other workflows via the `call_sub_workflow` tool.

- **Config**: `subWorkflowIds: ["workflow-uuid-1", "workflow-uuid-2"]`
- **Tool**: `call_sub_workflow` with `workflow_id` (enum) and `inputs` (object)
- **Depth limit**: Max 5 nested sub-workflow calls

### Execution Flow

1. Agent decides to call a sub-workflow
2. `_execute_sub_workflow_tool` fetches the workflow from `workflow_cache`
3. Builds `enriched_inputs = {"headers": {}, "query": {}, "body": inputs}`
4. Runs `WorkflowExecutor.execute()` for the sub-workflow
5. Result is returned to the agent

Sub-workflows cannot pause for HITL in v1. If a nested sub-workflow tries to enter a pending review state, the execution fails instead of suspending inside the nested call.

## Human-in-the-Loop

When `hitlEnabled` is set on an agent, the agent receives a `request_human_review` tool that it can call at specific approval checkpoints.

1. The system prompt and node HITL guidelines tell the agent which actions require approval
2. When the agent reaches one of those steps, it calls `request_human_review`
3. Heym stores a workflow execution snapshot and creates a public review request
4. The node result is marked `pending` with a review URL
5. The agent's `review` output handle is scheduled immediately so notification branches can run with the pending payload
6. Main execution scheduling stops until the reviewer responds
7. On `accept`, `edit`, or `refuse`, the executor is rebuilt from the stored snapshot
8. The paused agent continues with the approved review context, or exits immediately on `refuse`
9. Downstream nodes continue after the resumed agent finishes, without rerunning the `review` branch
10. If a later action also requires approval, the agent can create another HITL checkpoint in the same run

The reviewer-facing summary is generated from the review request itself, so the node field can stay focused on approval policy and timing.

This lets agent workflows wait for external approval while preserving conversation history, completed node outputs, loop state, and other runtime context.

## Orchestrator Tool Executor

The custom tool executor routes:

- **Sub-agent calls** (`_source == "sub_agent"`) → `_execute_sub_agent_tool`
- **Sub-workflow calls** (`_source == "sub_workflow"`) → `_execute_sub_workflow_tool`
- **Human review** (`_source == "hitl"`) → creates a pending HITL checkpoint
- **Other tools** → `_unified_tool_executor` (Python, MCP, skill tools)

It is used when HITL is enabled, when `isOrchestrator` with `subAgentLabels` is set, or when `subWorkflowIds` is configured.

## Skills

Skills extend the agent's system context and can add Python tools.

- **Shape**: `AgentSkill` = `{ id, name, content, files?, timeoutSeconds? }`
- **Content**: Prepended to the system instruction (joined with `---`)
- **Python tools**: For each skill with `.py` files, a `skill_{skill_name}` tool is added
- **Execution**: `skill_python_executor.py` runs scripts with `uv run python` in a temp dir; args as JSON on stdin, result as JSON on stdout

Skills can be added by dropping a `.zip` or `.md` file onto the Skills area in the [Agent Node](../nodes/agent-node.md) config.

## MCP Client

The MCP (Model Context Protocol) client connects to external tool servers.

- **Transports**: `stdio` (command + args) or `sse` (url + headers)
- **List tools**: `list_mcp_tools` → `ClientSession.list_tools()` → converted to OpenAI function format with `_source: "mcp"`
- **Execute**: `execute_mcp_tool` → `ClientSession.call_tool()` → result via `_extract_tool_result`

Configure MCP connections in the [MCP Tab](../tabs/mcp-tab.md) or on the agent node's `mcpConnections`.

## Tool Calling

The LLM service runs an `execute_with_tools` loop:

1. **Context compression check** — before each iteration, estimate token usage and compress if needed (see below)
2. Call the model with `tools` and `tool_choice: "auto"`
3. If `tool_calls` exist: for each call, run `tool_executor(tool_def, name, args, timeout)`
4. Append tool result to messages, repeat
5. Stop when no more tool calls or `max_tool_iterations` reached

### Tool Dispatch

`_unified_tool_executor` routes by `_source`:

| Source | Handler |
|--------|---------|
| `mcp` | `execute_mcp_tool` |
| `skill` | `execute_skill_python` |
| (default) | `execute_tool` (Python code tools) |

Tools use OpenAI function-calling format: `name`, `description`, `parameters` (JSON schema).

## Context Compression

To prevent context overflow on long-running agents, Heym automatically compresses the accumulated `messages` list before each tool iteration.

### Algorithm

1. **Estimate tokens**: `total_chars / 4` across all messages (fast, no tokenizer needed)
2. **Threshold check**: if `estimated_tokens < context_limit × 0.80`, skip compression
3. **Context limit**: try `client.models.retrieve(model).context_window`; fall back to a built-in table (`gpt-4o` → 128K, `claude-3-5-sonnet` → 200K, `gemini-2.0-flash` → 1M, etc.); default 128K
4. **Anchor preservation**: always keep
   - First `system` message (agent identity and instructions)
   - First `user` message (original task)
   - Last `user` message (most recent instruction)
5. **Summarize middle**: everything between first and last user message is serialized and sent to the same model with a summarization prompt
6. **Rebuild**: `[system, first_user, assistant(summary), last_user]`

Compression is skipped if there are fewer than 2 distinct user messages (no middle to summarize) or if the LLM summarization call fails (safe fallback: return original messages).

### Observability

Each compression event is recorded as:
- A `_context_compression` entry in `tool_calls_collected` → visible in Execution History run detail
- An `on_tool_call` event with `phase: "compression"` → rendered in the Debug panel as `Context compressed (N messages → summary)`
- A `context.compression` LLM trace entry → visible in the Traces tab with before/after token estimates

## Related

- [Why Heym](../getting-started/why-heym.md) – Multi-agent orchestration and AI-native features
- [Agent Node](../nodes/agent-node.md) – Configuration and parameters
- [Agent Persistent Memory](./agent-persistent-memory.md) – Knowledge graph per agent node and peer sharing
- [Human-in-the-Loop](./human-in-the-loop.md) – Review links, pending payloads, and resume behavior
- [Node Types](./node-types.md) – Agent and related nodes
- [Parallel Execution](./parallel-execution.md) – DAG-based and sub-agent parallel execution
- [MCP Tab](../tabs/mcp-tab.md) – Configure MCP connections
- [Expression DSL](./expression-dsl.md) – `$input.text` for sub-agents
