# Why Heym

Heym is an **AI-native automation platform**. While n8n, Zapier, and Make.com started as trigger-action workflow tools and later layered in AI capabilities, Heym is built from the ground up around LLMs, agents, and intelligent automation. AI is not a node you bolt on—it is the core execution model.

## AI-Native vs AI as an Add-On

| Capability | Heym | n8n | Zapier | Make.com |
|---|---|---|---|---|
| Built-in LLM node | ✓ | ✓ | ✓ | ✓ |
| LLM Batch API + status branches | ✓ | limited¹¹ | –¹¹ | limited¹¹ |
| Built-in Agent node (tool calling) | ✓ | ✓ | ✓ | ✓ |
| Multi-agent orchestration | ✓ | ✓ | limited | limited |
| Built-in RAG / vector store | ✓ | ✓ | limited¹ | plugin² |
| WebSocket read / write | ✓ | limited¹² | –¹³ | –¹⁴ |
| Natural language workflow builder | ✓ | limited³ | ✓ | ✓ |
| MCP (Model Context Protocol) | ✓ | ✓ | ✓ | ✓ |
| Skills system for agents | ✓ | – | – | – |
| LLM trace inspection | ✓ | limited⁴ | – | ✓ |
| Built-in evals for AI workflows | ✓ | ✓ | – | – |
| Human-in-the-Loop (HITL) | ✓ | ✓⁵ | limited⁶ | limited⁷ |
| LLM guardrails | ✓ | ✓⁸ | ✓⁸ | limited⁸ |
| Automatic context compression | ✓ | – | – | – |
| Parallel DAG execution | ✓ | limited⁹ | – | – |
| Self-hostable, source available | ✓ Commons Clause + MIT | ✓ fair-code¹⁰ | – | – |
| Expression DSL for dynamic data | ✓ | ✓ | limited | ✓ |

> **Footnotes:** ¹ Zapier Knowledge Sources — no exposed vector store or embedding control. ² Make.com has Pinecone/Qdrant modules but no native RAG node. ³ n8n AI Workflow Builder is cloud-only beta with credit caps. ⁴ n8n shows intermediate steps; full tracing requires third-party tools. ⁵ n8n supports AI tool-call approvals through chat, email, and collaboration channels, but it doesn't snapshot and resume the whole execution the way Heym does. ⁶ Zapier Human in the Loop supports approvals and data collection inside Zaps, but it isn't a public-review, snapshot-resume checkpoint system. ⁷ Make.com offers Human in the Loop as an Enterprise app with review requests and adjusted/approved/canceled outcomes, but it remains plan-limited and less agent-native. ⁸ n8n ships a dedicated Guardrails node, Zapier ships AI Guardrails across its AI products, and Make.com documents agent rules plus review flows but not a comparable standalone guardrails feature, so Make is marked limited. ⁹ n8n executes sequentially by default; parallelism requires sub-workflow workarounds. ¹⁰ Sustainable Use License — free to self-host for internal use, commercial redistribution restricted. ¹¹ As of April 22, 2026, n8n's official docs describe HTTP batching and loop/wait patterns rather than a native LLM batch-status branch, Zapier's official ChatGPT app docs list no triggers and only a generic API Request beta, and Make's official OpenAI integration page exposes batch actions like create/watch completed but not a first-class status-branching LLM node, so n8n/Make are marked limited and Zapier is marked unavailable for this specific workflow pattern. ¹² n8n's official docs cover HTTP Webhook and HTTP Request nodes plus Code/custom/community extensibility, but I couldn't find a first-party WebSocket trigger/send node, so n8n is marked limited. ¹³ Zapier's official docs cover inbound webhooks and outbound webhook/API requests over HTTP only, not native WebSocket trigger or send steps. ¹⁴ Make's official docs cover Webhooks modules and HTTP(S) request modules, but I couldn't find a native WebSocket trigger or send module.

## Built-In LLM and Agent Nodes

All major platforms now have LLM and agent nodes, but Heym's [Agent Node](../nodes/agent-node.md) goes further with a tightly integrated tool-calling loop, inline Python tools, MCP connections, and a portable skills system—all designed for production AI workflows.

Heym's plain [LLM node](../nodes/llm-node.md) also goes beyond a single prompt-response step. For supported OpenAI and OpenAI-compatible endpoints, it can switch into **Batch API mode** so one node submits an array of prompts in a lower-cost provider-native batch request. The canvas then exposes a dedicated `batchStatus` branch that fires as the batch moves through states such as `pending`, `processing`, and `completed`.

That means the LLM node can do two things at once:

- Run the main batch request and return the final per-item outputs on the normal branch
- Fire notification or logging logic on every meaningful batch status update without turning the flow into a custom polling loop

Other tools can approximate parts of this with generic HTTP modules or polling patterns, but Heym makes it a first-class LLM workflow primitive with provider/model capability checks in the node UI.

The **Agent Node** is the core differentiator:

- **Tool calling** – The agent iterates over tool calls in a loop until it produces a final answer
- **Python tools** – Define custom tools inline with full Python; the agent calls them at runtime
- **MCP connections** – Connect to any [Model Context Protocol](https://modelcontextprotocol.io/) server (stdio or SSE) and the agent gets all its tools automatically
- **Skills** – Drop a `.zip` or `.md` file onto an agent to extend its system context and add Python tooling
- **Sub-workflow calls** – The agent can invoke other Heym workflows as tools, composing complex behavior without custom code

See [Agent Node](../nodes/agent-node.md) and [Agent Architecture](../reference/agent-architecture.md) for the full reference.

## Multi-Agent Orchestration

Heym supports an **orchestrator pattern** with first-class visual primitives that other platforms lack:

- One agent acts as the **orchestrator** (`isOrchestrator: true`) and is given a `call_sub_agent` tool
- It delegates tasks to named **sub-agents** on the same canvas
- Sub-agents can themselves call other agents or sub-workflows (max depth: 5)
- **Parallel execution**: When the orchestrator calls multiple sub-agents in one turn, they run in parallel for faster results

This enables architectures like a planning agent that routes work to a researcher, a coder, and a summarizer—all wired visually, without custom orchestration code.

See [Agent Architecture](../reference/agent-architecture.md) for execution details.

## Built-In RAG Pipeline

Heym includes a [Qdrant RAG Node](../nodes/rag-node.md) and a managed [Vectorstores](../tabs/vectorstores-tab.md) tab. You can:

- Insert documents into a vector store directly from a workflow node
- Perform semantic search and feed results into an LLM or Agent node
- Reference results with expressions like `$ragNode.results.map("item.payload.content").join("\n\n")`

n8n now offers vector store nodes, and Zapier has abstracted Knowledge Sources, but they require more assembly. In Heym, RAG is two nodes with full control over embeddings and retrieval.

## AI Assistant: Build Workflows with Natural Language

The [AI Assistant](../reference/ai-assistant.md) is a chat panel inside the workflow editor. Describe what you want—"create a workflow that takes user input, searches my knowledge base, and replies using GPT-4o"—and the assistant generates nodes and edges that are instantly applied to the canvas.

- Uses your own LLM credential (any supported model)
- Supports **voice input** for hands-free workflow design
- Auto-applies valid workflow JSON from the AI response to the canvas
- Streams responses in real time

Zapier Copilot and Make Maia now offer natural-language workflow generation, but they operate as separate steps before the canvas. Heym's assistant works directly inside the editor, streaming nodes onto the canvas in real time with voice support.

## MCP (Model Context Protocol) Integration

Heym has native [MCP](../tabs/mcp-tab.md) support on both sides:

- **As a client**: Agent nodes connect to external MCP servers (Filesystem, Browserbase, custom tools) via stdio or SSE and consume their tools automatically
- **As a server**: Each workflow with an Agent node can expose its tools as an MCP server, reachable at `/api/mcp/sse`—letting Claude Desktop, Cursor, or other MCP clients call your Heym workflows directly

n8n, Zapier, and Make.com have all added MCP support. Heym differentiates by exposing every workflow as an MCP server endpoint out of the box, and by allowing agents to consume multiple MCP servers simultaneously with zero configuration.

## Skills System

Skills are portable capability bundles—a `SKILL.md` instruction file plus optional Python scripts—that can be dropped onto any Agent node.

- The skill's instructions are prepended to the agent's system prompt
- Python files in the skill become callable tools
- Skills are reusable across workflows and shareable as `.zip` archives

This is analogous to giving your agent a job description and a toolbox in one drop.

## Human-in-the-Loop (HITL)

Heym has a built-in [Human-in-the-Loop](../reference/human-in-the-loop.md) system that lets agents pause execution, request human review, and resume from exactly where they left off.

- **Agent checkpoints** – Enable `hitlEnabled` on any Agent node to give it a `request_human_review` tool. The agent decides when a decision needs human oversight and calls the tool with a summary and draft.
- **Public review URLs** – Each review request generates a secure one-time link at `/review/{token}` (168-hour TTL). Reviewers can **accept**, **edit & continue**, or **refuse**—no login required.
- **Execution snapshots** – The workflow freezes its full state (conversation history, variables, tool results) so it resumes exactly where it paused after the reviewer responds.
- **Notification branch** – An optional `review` output handle lets you wire a notification flow (Slack, email, webhook) that fires when a review is requested.
- **MCP tool approval policies** – Written HITL guidelines are interpreted into approval scopes (`always` / `once` / `never`) so the agent can auto-approve low-risk tools and escalate high-risk ones.
- **Multiple checkpoints** – A single agent run can pause for review multiple times; each checkpoint is independent.

n8n supports AI tool-call approvals across chat, email, and collaboration channels, but it is centered on reviewing tool invocations rather than pausing with a full execution snapshot. Zapier's Human in the Loop handles approvals and data collection inside Zaps, while Make.com's Human in the Loop app adds structured review requests on Enterprise plans. Heym differentiates with public review URLs, edit-and-continue, notification branching, and snapshot-based resume from the same agent checkpoint.

See [Human-in-the-Loop](../reference/human-in-the-loop.md) for the full reference.

## LLM Guardrails

Heym has built-in [Guardrails](../reference/guardrails.md) on both [LLM](../nodes/llm-node.md) and [Agent](../nodes/agent-node.md) nodes, so you can block unsafe content before a model response reaches downstream steps.

- **Node-level safety toggle** – Enable guardrails directly on the node that generates or processes user-facing content
- **Broad policy coverage** – Block violence, hate speech, sexual content, NSFW/profanity, harassment, illegal activity, personal-data requests, and prompt injection attempts
- **Multilingual detection** – Apply the same safety rules across Turkish, English, Arabic, Spanish, and other languages
- **Workflow-native fallback** – When a message is blocked, the node throws a typed workflow error that you can route through an [Error Handler](../nodes/error-handler-node.md)

n8n now ships a dedicated Guardrails node, and Zapier now ships AI Guardrails across its AI surfaces. Make.com documents agent rules and review flows, but its currently published first-party docs don't show a comparable standalone guardrails feature, so we mark it as limited. Heym's differentiator is that safety policy lives directly inside the LLM and Agent configuration and plugs straight into workflow branching and error handling.

## LLM Traces

The [Traces Tab](../tabs/traces-tab.md) provides full observability for every LLM call:

- Request and response payloads
- Per-call timing: `llm_ms`, `tools_ms`, `mcp_list_ms`
- Tool call names, arguments, and results
- Skills passed to the model

Make.com now offers a Reasoning Panel for agent steps. n8n shows intermediate steps but full tracing requires third-party tools like Langfuse. Zapier has no trace visibility. Heym's trace system is purpose-built for debugging agentic behavior with full request/response payloads and per-call timing.

## Built-In Evals

The [Evals Tab](../tabs/evals-tab.md) lets you define test suites and run them against any workflow:

- Create test cases with inputs and expected outputs
- Run the whole suite with one click
- Review pass/fail, actual vs expected, and run history
- Control temperature and reasoning effort per run

n8n added evaluations in v1.95.1 with dataset-based testing and custom metrics. Zapier and Make.com still have no eval support. Heym makes eval-driven development a first-class workflow with one-click test suites, pass/fail review, and per-run temperature/reasoning control.

## Parallel DAG Execution

Heym's workflow executor uses a directed acyclic graph (DAG) scheduler. Independent nodes run in parallel automatically—no configuration needed.

- Nodes at the same dependency level are dispatched concurrently to a thread pool (`max_workers=8`)
- As soon as any node finishes, its downstream nodes are scheduled
- The [Merge Node](../nodes/merge-node.md) combines parallel branch results
- Multiple workflow runs execute concurrently; each run is fully isolated

Make.com and Zapier run steps sequentially. n8n executes sequentially by default and requires sub-workflow workarounds for parallelism. In Heym, parallelism is the default behavior determined by the graph structure.

See [Parallel Execution](../reference/parallel-execution.md).

## Portal: Publish Workflows as Chat UIs

The [Portal](../reference/portal.md) feature turns any workflow into a public-facing chat interface at `/chat/{slug}`:

- Optional authentication with per-user credentials
- Streaming execution (real-time node progress)
- File upload support
- Multi-turn conversation history

This enables teams to ship internal tools, customer-facing chatbots, and AI-powered forms without any frontend code—just a workflow and a URL.

## Expression DSL

Heym's [Expression DSL](../reference/expression-dsl.md) provides a clean, powerful syntax for referencing upstream node data:

- `$input.text` – Input node data
- `$nodeName.field` – Any upstream node's output field
- `$global.variableName` – Persistent global variables
- Array helpers: `.first()`, `.map("field")`, `.join("\n")`

Expressions work in every string field—prompts, HTTP headers, conditions, set values—making dynamic data flow natural. Make.com now has a capable function library, and n8n uses JavaScript-based expressions. Zapier's in-line formulas remain more limited. Heym's DSL strikes a balance between power and readability without requiring full JavaScript knowledge.

## Self-Hosted, You Own Your Data

Like n8n, Heym is self-hostable. Unlike Zapier and Make.com, your automation data, credentials, and LLM calls never touch a third-party SaaS platform. For AI workloads that process sensitive documents, customer data, or proprietary knowledge bases, this is a hard requirement.

Heym is licensed under the **Commons Clause + MIT License**. The source code is source-available—you can use, modify, and self-host it freely. The Commons Clause restricts selling the software as a competing commercial product. For commercial use, enterprise deployments, or professional support, contact [enterprise@heym.run](mailto:enterprise@heym.run).

## Related

- [Introduction](./introduction.md) – Platform overview
- [Quick Start](./quick-start.md) – Build your first workflow
- [Agent Node](../nodes/agent-node.md) – LLM node with tool calling, MCP, and skills
- [Agent Architecture](../reference/agent-architecture.md) – Sub-agents, orchestrator, and tool dispatch
- [Qdrant RAG Node](../nodes/rag-node.md) – Vector search and document insertion
- [AI Assistant](../reference/ai-assistant.md) – Natural language workflow builder
- [Human-in-the-Loop](../reference/human-in-the-loop.md) – Agent checkpoints with public review URLs
- [Guardrails](../reference/guardrails.md) – Block unsafe prompts before they reach your models
- [Traces Tab](../tabs/traces-tab.md) – LLM call observability
- [Evals Tab](../tabs/evals-tab.md) – Test suites for AI workflows
- [Portal](../reference/portal.md) – Publish workflows as public chat UIs
- [Parallel Execution](../reference/parallel-execution.md) – DAG-based concurrent execution
- [MCP Tab](../tabs/mcp-tab.md) – MCP server and client configuration
