# Why Heym

Heym is infrastructure for running and governing AI agents in production. One self-hosted runtime covers every stage of the agent lifecycle.

A prototype agent needs a model, a prompt, and a few tools. A production agent also needs triggers and retries, saved state when it pauses for a person, a record of every model and tool call, a cost for every run, tests before a change ships, and clear limits on what it may do on its own. Heym holds all of that in one place, so the system you design on the canvas is the system that runs. Build agentic systems, then run them with confidence.

## One Runtime for the Agent Lifecycle

| Stage | What Heym gives you |
|---|---|
| **Build** | Compose agents and deterministic steps on the canvas, generate them with the [AI Assistant](../reference/ai-assistant.md), or start from [Templates](../tabs/templates-tab.md) and portable skills. |
| **Orchestrate** | Coordinate agents, [sub-agents](../reference/agent-architecture.md), coding agents, RAG, browser automation, and tools with explicit data flow and [parallel execution](../reference/parallel-execution.md). |
| **Run** | Start runs from [webhooks](../reference/webhooks.md), schedules, and event [triggers](../reference/triggers.md), with per-node retries, [error handling](../nodes/error-handler-node.md), and [load distribution](../reference/cluster.md) across instances. |
| **Observe** | Inspect every execution through [history](../reference/execution-history.md), [LLM traces](../tabs/traces-tab.md), per-run USD cost, live runs on the canvas, [analytics](../tabs/analytics-tab.md), [alerts](../tabs/alerts-tab.md), and [OpenTelemetry](../reference/opentelemetry.md) export. |
| **Evaluate** | Test prompts and models against expected outputs in [Evals](../tabs/evals-tab.md), with LLM-as-Judge scoring and side-by-side model comparison. |
| **Control** | Keep humans in control with [review checkpoints](../reference/human-in-the-loop.md) and [guardrails](../reference/guardrails.md), and govern access with encrypted [credentials](../reference/credentials.md), [teams](../reference/teams.md), [single sign-on](../reference/sso.md), and an [audit trail](../reference/audit.md). |
| **Expose** | Serve workflows over REST and [SSE](../reference/sse-streaming.md), as [MCP](../tabs/mcp-tab.md) tools, as [Portal](../reference/portal.md) chat UIs, and as [dashboard](../tabs/dashboard-tab.md) widgets. |

## Build

### AI Assistant: Build Workflows with Natural Language

The [AI Assistant](../reference/ai-assistant.md) is a chat panel inside the workflow editor. Describe what you want, for example "create a workflow that takes user input, searches my knowledge base, and replies using GPT-4o", and the assistant generates nodes and edges that are instantly applied to the canvas.

- Uses your own LLM credential (any supported model)
- Supports **voice input** for hands-free workflow design
- Auto-applies valid workflow JSON from the AI response to the canvas
- Streams responses in real time

The assistant works directly inside the editor and streams nodes onto the canvas in real time, and everything it generates stays editable like nodes you placed by hand.

### Skills System

Skills are portable capability bundles, a `SKILL.md` instruction file plus optional Python scripts, that can be dropped onto any Agent node.

- The skill's instructions are prepended to the agent's system prompt
- Python files in the skill become callable tools
- Skills are reusable across workflows and shareable as `.zip` archives

This is analogous to giving your agent a job description and a toolbox in one drop.

### Workflow Analyzer: Run-Aware Feedback

The [Workflow Analysis](../reference/workflow-analysis.md) panel is a run-aware documentation and feedback tool built into the editor. Click **Analyze**, choose an LLM credential and model, and Heym generates an editable Markdown report for the current workflow.

Unlike a static note, the analyzer first runs the workflow when it can and includes the execution result in the prompt. The report covers improvement areas, the workflow's purpose, and a step-by-step explanation of what the nodes do. When a report already exists, **Reanalyze** streams a separate preview so you can accept the new version or keep the current shared document.

## Orchestrate

### Built-In LLM and Agent Nodes

Heym's [Agent Node](../nodes/agent-node.md) runs a tightly integrated tool-calling loop with inline Python tools, MCP connections, and a portable skills system, all designed for production agents.

Heym's plain [LLM node](../nodes/llm-node.md) also goes beyond a single prompt-response step. For supported OpenAI and OpenAI-compatible endpoints, it can switch into **Batch API mode** so one node submits an array of prompts in a lower-cost provider-native batch request. The canvas then exposes a dedicated `batchStatus` branch that fires as the batch moves through states such as `pending`, `processing`, and `completed`.

That means the LLM node can do two things at once:

- Run the main batch request and return the final per-item outputs on the normal branch
- Fire notification or logging logic on every meaningful batch status update without turning the flow into a custom polling loop

Batch execution is a first-class LLM workflow primitive, with provider and model capability checks in the node UI.

The **Agent Node** is the core of agent orchestration in Heym:

- **Tool calling** – The agent iterates over tool calls in a loop until it produces a final answer
- **Python tools** – Define custom tools inline with full Python; the agent calls them at runtime
- **MCP connections** – Connect to any [Model Context Protocol](https://modelcontextprotocol.io/) server (stdio or SSE) and the agent gets all its tools automatically
- **Skills** – Drop a `.zip` or `.md` file onto an agent to extend its system context and add Python tooling
- **Sub-workflow calls** – The agent can invoke other Heym workflows as tools, composing complex behavior without custom code

See [Agent Node](../nodes/agent-node.md) and [Agent Architecture](../reference/agent-architecture.md) for the full reference.

### Multi-Agent Orchestration

Heym supports an **orchestrator pattern** with first-class visual primitives:

- One agent acts as the **orchestrator** (`isOrchestrator: true`) and is given a `call_sub_agent` tool
- It delegates tasks to named **sub-agents** on the same canvas
- Sub-agents can themselves call other agents or sub-workflows (max depth: 5)
- **Parallel execution**: When the orchestrator calls multiple sub-agents in one turn, they run in parallel for faster results

This enables architectures like a planning agent that routes work to a researcher, a coder, and a summarizer, all wired visually without custom orchestration code.

See [Agent Architecture](../reference/agent-architecture.md) for execution details.

### Coding Agents as Workflow Nodes

Heym ships two nodes that run a real coding agent as a workflow step, not a chat completion:

- **[Codex Node](../nodes/codex-node.md)** – Runs the OpenAI Codex CLI in an isolated Heym workspace against a GitHub repository. Supports **Sign in with ChatGPT** (PKCE OAuth on your Plus/Pro subscription, no per-token API cost) or an access token, clones the repo, lets Codex edit code, and returns `summary`, `diff`, `changedFiles`, and a draft `pullRequestUrl`.
- **[OpenCode Go Node](../nodes/opencode-go-node.md)** – The same repository workflow through the provider-agnostic OpenCode gateway (Kimi, DeepSeek, Qwen, and more), executed in a **hardened throwaway container**: all capabilities dropped, read-only root, pid/memory/CPU limits. The GitHub token stays outside the sandbox: Heym performs every git and GitHub operation host-side, so generated code cannot exfiltrate push credentials.

That means a workflow can triage a bug from a webhook, hand the repo to a coding agent, wait for the draft PR, and post the link to Slack, fully automated, with resource limits configurable per deployment.

### Built-In RAG Pipeline

Heym includes a [RAG / Vector Store Node](../nodes/rag-node.md) and a managed [Vectorstores](../tabs/vectorstores-tab.md) tab. You can:

- Choose your vector backend: **Qdrant** (external server) or **Postgres (pgvector)**, which stores vectors in Heym's own database with no extra service to run
- Insert documents into a vector store directly from a workflow node
- Perform semantic search and feed results into an LLM or Agent node
- Reference results with expressions like `$ragNode.results.map("item.payload.content").join("\n\n")`

In Heym, RAG is two nodes with full control over embeddings and retrieval.

### Browser Automation with Playwright

The [Playwright node](../nodes/playwright-node.md) is first-party browser automation on the canvas.

- **Steps mode** – Compose navigate, click, type, fill, screenshot, extract, and scroll actions visually
- **AI steps with auto-heal** – Describe an action in natural language and an LLM generates the Playwright actions; failed selectors can be healed automatically, and generated steps can be cached to skip future LLM calls
- **Run Code mode** – Switch the node to full Playwright Python for complex flows (disabled by default; runs in Heym's hardened sandbox when enabled)
- **Authenticated sessions** – Restore cookies/`storageState` before running, verify login with a selector check, and fall back to scripted login steps
- **Network capture** – Optionally collect JSON responses, headers, cookies, and browser storage alongside results

Heym treats the browser as a normal node with the same expressions, credentials, and error handling as everything else.

### Expression DSL

Heym's [Expression DSL](../reference/expression-dsl.md) provides a clean, powerful syntax for referencing upstream node data:

- `$input.text` – Input node data
- `$nodeName.field` – Any upstream node's output field
- `$global.variableName` – Persistent global variables
- Array helpers: `.first()`, `.map("field")`, `.join("\n")`

Expressions work in every string field, including prompts, HTTP headers, conditions, and set values, so data moves between steps explicitly. The DSL balances power and readability without requiring full JavaScript knowledge.

## Run

### Triggers, Retries, and Error Paths

A workflow can start from many places. [Input](../nodes/input-node.md) nodes receive HTTP [webhooks](../reference/webhooks.md), [Cron](../nodes/cron-node.md) runs on a schedule, and event [triggers](../reference/triggers.md) start runs from Telegram, Discord, Slack, IMAP inboxes, WebSocket streams, RabbitMQ queues, file uploads, and Heym platform events.

Failures are handled inside the graph. Any node can retry on failure with a set number of attempts and a wait between them, each attempt is recorded in [execution history](../reference/execution-history.md), and an [Error Handler](../nodes/error-handler-node.md) node runs automatically when a node fails, so recovery is part of the workflow itself.

### Parallel DAG Execution

Heym's workflow executor uses a directed acyclic graph (DAG) scheduler. Independent nodes run in parallel automatically, with no configuration needed.

- Nodes at the same dependency level are dispatched concurrently to a thread pool (`max_workers=8`)
- As soon as any node finishes, its downstream nodes are scheduled
- The [Merge Node](../nodes/merge-node.md) combines parallel branch results
- Multiple workflow runs execute concurrently; each run is fully isolated

Parallelism is the default behavior, determined by the graph structure.

See [Parallel Execution](../reference/parallel-execution.md).

### Scale Across Instances

Point a second Heym instance at the same PostgreSQL database and it joins as a worker. Background runs are shared between instances by weights you set, one elected leader keeps schedules, alert evaluation, and crash recovery running through a failover, and every run records the instance that executed it. See [Load Distribution](../reference/cluster.md).

### Agentic Kanban Board

The [Board tab](../tabs/board-tab.md) is a built-in Kanban board where the columns themselves execute workflows. A card is a persistent agentic job that carries context, conversation history, execution state, outputs, and workflow runs.

- **Column workflow chains** – Moving a card into a column triggers that column's workflow chain; an **Agentic Kanban Model** (your credential + model) maps card content into workflow inputs and turns outputs back into readable text
- **Card attachments** – Drop files onto a card; documents are extracted to text and images are passed to vision-capable models before each run
- **Live run canvas** – Open the active run inside a card and watch it execute on the real workflow canvas, node by node
- **Team sharing** – Share boards with users or teams with read/write permissions; chains on shared boards run with the owner's credentials, so collaborators never need their own
- **Failure visibility** – Failed cards surface an error-history indicator, and follow-up runs can pause to await comments

The board is a native surface of the platform: cards, workflows, credentials, and live runs all live in one place.

### Heym Drive: Built-In File Storage

The [Drive tab](../tabs/drive-tab.md) is a file store built into the platform. Files generated by skills and workflows (PDF, DOCX, CSV, images) land there automatically, and board card attachments are stored there too.

- **Share links** – Public or password-protected (Basic Auth) download links with optional expiry and max-download limits
- **Team sharing** – Share files read-only with your teams, and remove all team shares in one action
- **Bulk actions** – Multi-select with shift-click ranges, bundle selections into a single ZIP download, or apply one share/password/delete setting to many files at once
- **Agent access** – Skills can opt in to read Drive files, so an agent can work over documents you or other workflows produced

Generated artifacts get a permanent, shareable home inside the platform.

## Observe

### LLM Traces

The [Traces Tab](../tabs/traces-tab.md) provides full observability for every LLM call:

- Request and response payloads
- Per-call timing: `llm_ms`, `tools_ms`, `mcp_list_ms`
- Tool call names, arguments, and results
- Skills passed to the model

The trace system is purpose-built for debugging agentic behavior, with full request and response payloads and per-call timing.

### LLM Token Cost Tracking

Every LLM call in Heym is automatically costed. The [Traces Tab](../tabs/traces-tab.md) shows per-trace input and output token counts alongside a real-time USD cost derived from a synced pricing table.

- **Per-trace cost** – Input tokens, output tokens, and total USD shown on every trace row
- **Cost analytics** – KPI cards and a per-model cost chart update with the selected time range (1h / 24h / 7d / 30d / All)
- **LLM Cost Table** – A system table in the [DataTable tab](../tabs/datatable-tab.md) is seeded from Helicone every 24 hours; you can override prices or add custom rows for models not yet listed
- **Missing-price warning** – Traces for models without a pricing entry surface an inline warning with a direct link to the cost table

Every execution carries its own USD cost, broken down by model.

### Open Production Runs on a Live Canvas

A production workflow stays inspectable after it starts outside the editor. Open any **Running** entry from either History dialog, or open the active run inside an Agentic Kanban card, and Heym attaches the normal workflow editor to that exact execution.

- Nodes that already finished appear with their results immediately
- The current node and pending downstream nodes keep pulsing as execution advances
- The Debug panel receives the same incremental node results as a canvas-started run
- The final output and execution highlights arrive without polling or starting a duplicate run
- Closing the editor only disconnects the observer; it never cancels the production workflow

The observer uses SSE backed by a cross-worker execution snapshot, so it works for webhook, schedule, chat, MCP, integration, and Board triggers even when another backend worker owns the run.

### OpenTelemetry, Analytics, and Alerts

Heym emits [OpenTelemetry](../reference/opentelemetry.md) spans for every workflow run, node execution, and Agent tool invocation, exported over OTLP/HTTP to Jaeger, Grafana Tempo, Honeycomb, Datadog, or any other compatible backend.

The [Analytics](../tabs/analytics-tab.md) tab tracks run counts, success rate, duration, and trends per workflow. [Alerts](../tabs/alerts-tab.md) watch error counts, run duration, token or USD spend, and execution volume over a time window, then run a notify workflow you choose, so an alert reaches Slack, email, Telegram, or anywhere else a node can.

## Evaluate

### Built-In Evals

The [Evals Tab](../tabs/evals-tab.md) lets you define test suites and run them against your agent workflows:

- Create test cases with inputs and expected outputs, or generate them from the suite prompt
- Run one suite against several models and compare their outputs side by side
- Score with Exact Match, Contains, or LLM-as-Judge with an independent judge model
- Review pass/fail, actual vs expected, and run history

Change a prompt or a model, rerun the suite, and compare the results before the change reaches production.

## Control

### Human-in-the-Loop (HITL)

Heym has a built-in [Human-in-the-Loop](../reference/human-in-the-loop.md) system that lets agents pause execution, request human review, and resume from exactly where they left off.

- **Agent checkpoints** – Enable `hitlEnabled` on any Agent node to give it a `request_human_review` tool. The agent decides when a decision needs human oversight and calls the tool with a summary and draft.
- **Public review URLs** – Each review request generates a secure one-time link at `/review/{token}` (168-hour TTL). Reviewers can **accept**, **edit & continue**, or **refuse** without signing in.
- **Execution snapshots** – The workflow freezes its full state (conversation history, variables, tool results) so it resumes exactly where it paused after the reviewer responds.
- **Notification branch** – An optional `review` output handle lets you wire a notification flow (Slack, email, webhook) that fires when a review is requested.
- **MCP tool approval policies** – Written HITL guidelines are interpreted into approval scopes (`always` / `once` / `never`) so the agent can auto-approve low-risk tools and escalate high-risk ones.
- **Multiple checkpoints** – A single agent run can pause for review multiple times; each checkpoint is independent.

Public review URLs, edit-and-continue, notification branching, and snapshot-based resume all work from the same agent checkpoint.

See [Human-in-the-Loop](../reference/human-in-the-loop.md) for the full reference.

### LLM Guardrails

Heym has built-in [Guardrails](../reference/guardrails.md) on both [LLM](../nodes/llm-node.md) and [Agent](../nodes/agent-node.md) nodes, so you can block unsafe content before a model response reaches downstream steps.

- **Node-level safety toggle** – Enable guardrails directly on the node that generates or processes user-facing content
- **Broad policy coverage** – Block violence, hate speech, sexual content, NSFW/profanity, harassment, illegal activity, personal-data requests, and prompt injection attempts
- **Multilingual detection** – Apply the same safety rules across Turkish, English, Arabic, Spanish, and other languages
- **Workflow-native fallback** – When a message is blocked, the node throws a typed workflow error that you can route through an [Error Handler](../nodes/error-handler-node.md)

Safety policy lives directly inside the LLM and Agent configuration and plugs straight into workflow branching and error handling.

### Access, Credentials, and Audit

Agents act with real credentials, so access is part of governance. [Credentials](../reference/credentials.md) are encrypted at rest, masked after creation, and shareable with users or [teams](../reference/teams.md), and teams also share workflows, variables, vector stores, and Drive files. [Single sign-on](../reference/sso.md) connects any OpenID Connect provider, including Okta, Entra ID, Keycloak, Auth0, and Google. The [audit trail](../reference/audit.md) records every security-relevant action with its actor, target, and outcome, streamed with your container logs to the log collector or SIEM you already run.

### Self-Hosted, You Own Your Data

Heym runs on your infrastructure. Workflows, credentials, execution history, and traces live in your own database, and model calls go from your servers to the provider you choose, or to a model you host yourself through Ollama or vLLM. For agents that process sensitive documents, customer data, or proprietary knowledge bases, this is often a hard requirement.

Heym is licensed under the **MIT License with the Commons Clause condition**. The source code is source-available: you can use, modify, and self-host it freely. The Commons Clause restricts selling the software, including offering paid hosting or consulting/support services whose value derives substantially from Heym. For commercial licensing, enterprise deployments, or professional support, contact [enterprise@heym.run](mailto:enterprise@heym.run).

## Expose

### APIs and Streaming

Workflows are callable over HTTP at `/api/workflows/{workflow_id}/execute`, which returns JSON, and at `/api/workflows/{workflow_id}/execute/stream`, which streams node events as Server-Sent Events while the run progresses. Both share workflow-level authentication, rate limiting, and response caching. See [Webhooks](../reference/webhooks.md) and [SSE Streaming](../reference/sse-streaming.md).

### MCP (Model Context Protocol) Integration

Heym has native [MCP](../tabs/mcp-tab.md) support on both sides:

- **As a client**: Agent nodes connect to external MCP servers (Filesystem, Browserbase, custom tools) via stdio or SSE and consume their tools automatically
- **As a server**: Workflows with MCP turned on become tools on the default server at `/api/mcp/sse`, or on named servers with their own URL and API key, so Claude Desktop, Cursor, and other MCP clients can call your Heym workflows directly

Agents can consume several MCP servers at once, and any workflow can become a tool for an external MCP client.

### Portal: Publish Workflows as Chat UIs

The [Portal](../reference/portal.md) feature turns any workflow into a public-facing chat interface at `/chat/{slug}`:

- Optional authentication with per-user credentials
- Streaming execution (real-time node progress)
- File upload support
- Multi-turn conversation history

Teams ship internal tools, customer-facing chatbots, and AI-powered forms from a workflow and a URL, with no frontend code to write.

### Workflow-Powered Dashboards

The [Dashboard tab](../tabs/dashboard-tab.md) is a user-built reporting surface where every chart widget is powered by its own hidden Heym workflow. A widget can call APIs, query BigQuery, search RAG/vector stores, run LLM steps, transform rows, and finish with a [Chart Output node](../nodes/chart-output-node.md). You can create widgets manually, generate them with AI, fine-tune them later, cache results, and rearrange the grid visually.

## Compared with Workflow Automation Tools

Many teams arrive at Heym from workflow automation tools. The table below compares Heym with n8n, Zapier, and Make.com on the capabilities that matter once agents run in production, and the footnotes under it cite the official documentation behind the comparison. For a deeper look at one tool at a time, see the comparison pages at [heym.run/compare](https://heym.run/compare).

| Capability | Heym | n8n | Zapier | Make.com |
|---|---|---|---|---|
| Built-in LLM node | ✓ | ✓ | ✓ | ✓ |
| LLM Batch API + status branches | ✓ | limited¹¹ | –¹¹ | limited¹¹ |
| Built-in Agent node (tool calling) | ✓ | ✓ | ✓ | ✓ |
| Multi-agent orchestration | ✓ | ✓ | limited | limited |
| Coding agent nodes (Codex, OpenCode) | ✓ | –²⁰ | –²⁰ | –²⁰ |
| Built-in RAG / vector store | ✓ | ✓ | limited¹ | plugin² |
| WebSocket read / write | ✓ | limited¹² | –¹³ | –¹⁴ |
| Natural language workflow builder | ✓ | limited³ | ✓ | ✓ |
| Workflow Analyzer | ✓ | –¹⁸ | –¹⁸ | –¹⁸ |
| Open an in-flight run on the live canvas | ✓ | limited¹⁹ | limited¹⁹ | –¹⁹ |
| Workflow-powered dashboards | ✓ | limited¹⁷ | limited¹⁷ | limited¹⁷ |
| Agentic Kanban board | ✓ | –²¹ | –²¹ | –²¹ |
| MCP (Model Context Protocol) | ✓ | ✓ | ✓ | ✓ |
| Skills system for agents | ✓ | – | – | – |
| Built-in file drive (share links, teams) | ✓ | limited²² | limited²² | –²² |
| Browser automation node (Playwright) | ✓ | limited²³ | limited²³ | –²³ |
| LLM trace inspection | ✓ | limited⁴ | – | ✓ |
| OpenTelemetry tracing export | ✓ | ✓¹⁶ | –¹⁶ | –¹⁶ |
| LLM token cost tracking (USD) | ✓ | –¹⁵ | –¹⁵ | limited¹⁵ |
| Built-in evals for AI workflows | ✓ | ✓ | – | – |
| Human-in-the-Loop (HITL) | ✓ | ✓⁵ | limited⁶ | limited⁷ |
| LLM guardrails | ✓ | ✓⁸ | ✓⁸ | limited⁸ |
| Automatic context compression | ✓ | – | – | – |
| Parallel DAG execution | ✓ | limited⁹ | – | – |
| Self-hostable, source available | ✓ MIT + Commons Clause | ✓ fair-code¹⁰ | – | – |
| Expression DSL for dynamic data | ✓ | ✓ | limited | ✓ |

> **Footnotes:** ¹ Zapier Knowledge Sources — no exposed vector store or embedding control. ² Make.com has Pinecone/Qdrant modules but no native RAG node. ³ n8n AI Workflow Builder is cloud-only beta with credit caps. ⁴ n8n shows intermediate steps; full tracing requires third-party tools. ⁵ n8n supports AI tool-call approvals through chat, email, and collaboration channels, but it doesn't snapshot and resume the whole execution the way Heym does. ⁶ Zapier Human in the Loop supports approvals and data collection inside Zaps, but it isn't a public-review, snapshot-resume checkpoint system. ⁷ Make.com offers Human in the Loop as an Enterprise app with review requests and adjusted/approved/canceled outcomes, but it remains plan-limited and less agent-native. ⁸ n8n ships a dedicated Guardrails node, Zapier ships AI Guardrails across its AI products, and Make.com documents agent rules plus review flows but not a comparable standalone guardrails feature, so Make is marked limited. ⁹ n8n executes sequentially by default; parallelism requires sub-workflow workarounds. ¹⁰ Sustainable Use License — free to self-host for internal use, commercial redistribution restricted. ¹¹ As of April 22, 2026, n8n's official docs describe HTTP batching and loop/wait patterns rather than a native LLM batch-status branch, Zapier's official ChatGPT app docs list no triggers and only a generic API Request beta, and Make's official OpenAI integration page exposes batch actions like create/watch completed but not a first-class status-branching LLM node, so n8n/Make are marked limited and Zapier is marked unavailable for this specific workflow pattern. ¹² n8n's official docs cover HTTP Webhook and HTTP Request nodes plus Code/custom/community extensibility, but I couldn't find a first-party WebSocket trigger/send node, so n8n is marked limited. ¹³ Zapier's official docs cover inbound webhooks and outbound webhook/API requests over HTTP only, not native WebSocket trigger or send steps. ¹⁴ Make's official docs cover Webhooks modules and HTTP(S) request modules, but I couldn't find a native WebSocket trigger or send module. ¹⁵ n8n has no native LLM token cost tracking; community workaround workflows exist but require manual installation and post-execution API calls (open feature request as of May 2026). Zapier exposes no per-execution token count or USD cost to users; AI steps consume tasks only. Make.com's credits dashboard partially reflects token consumption for Make-hosted AI (since August 2025) but third-party API key connections are billed as 1 operation = 1 credit with no token counting; no per-execution USD breakdown by model is available. ¹⁶ Heym emits native OpenTelemetry spans (one per workflow run plus one per node) over OTLP/HTTP to any compatible backend, with W3C trace-context propagation and no instrumentation code, configured via `HEYM_OTEL_*` env vars and disabled by default. n8n has a documented OpenTelemetry tracing integration for workflow and node executions. Zapier and Make.com do not document OpenTelemetry export of their workflow/scenario executions as of June 2026. ¹⁷ n8n documents an Insights dashboard for production execution metrics, Zapier documents Zap History plus Task Usage, and Make.com documents Scenario History; these are monitoring/history surfaces, not custom dashboard widgets backed by arbitrary workflow logic like Heym's Dashboard tab. ¹⁸ Heym Workflow Analyzer runs the workflow when possible, reads the execution result, and generates a shared editable Markdown report covering improvement areas, purpose, and step-by-step behavior. n8n documents AI Workflow Builder for creating/refining/debugging workflows, Zapier documents AI troubleshooting for errored Zap runs, and Make.com documents scenario history plus AI agent reasoning steps, but their public docs do not describe the same run-aware shared workflow analysis document. ¹⁹ [n8n All executions](https://docs.n8n.io/workflows/executions/all-executions/) lists running executions and can load data from a previous execution into the editor, while [Zapier run statuses](https://help.zapier.com/hc/en-us/articles/20505304170637-Review-run-statuses-in-Zap-workflows) exposes a running state in its editor. [Make Scenario History](https://help.make.com/scenario-history) documents run detail and logs. Their public documentation, checked July 18, 2026, does not describe Heym's exact flow: open an arbitrary in-flight production run from History or a Kanban card, restore its current node snapshot, and continue receiving node animation and Debug logs on the same canvas. ²⁰ Heym's [Codex](../nodes/codex-node.md) and [OpenCode Go](../nodes/opencode-go-node.md) nodes run a real coding agent CLI in an isolated Heym workspace against a GitHub repository — clone, edit, produce a diff, push a branch, open a pull request — as a first-class workflow step. As of July 20, 2026, no competitor documents an equivalent: n8n's [OpenAI node](https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-langchain.openai) covers chat/assistant API calls, not a repository-level coding agent, and native Codex support remains a community request; Zapier's own blog documents the reverse direction — [Codex driving Zapier tools through Zapier MCP](https://zapier.com/blog/automate-codex-zapier-mcp/) — not Codex as a Zap step; Make.com's OpenAI modules expose completions/assistants/batch actions, not a coding agent that clones repos and opens PRs. ²¹ Heym's [Board tab](../tabs/board-tab.md) is a built-in agentic Kanban board whose columns execute workflows and whose cards carry context, conversation history, execution state, and runs. n8n ([Kanban Tool integration](https://n8n.io/integrations/kanban-tool/)), Zapier ([Kanban Tool integrations](https://zapier.com/apps/kanbantool/integrations)), and Make.com ([Kanban Tool integration](https://www.make.com/en/integrations/kanban-tool)) only connect to third-party kanban apps such as Kanban Tool, Wekan, or NocoDB; none documents a built-in board that runs its own workflows, as of July 20, 2026. ²² n8n stores execution binary data internally (optionally on [S3-compatible external storage](https://docs.n8n.io/hosting/scaling/external-storage/)) but documents no user-facing file drive with share links or team sharing, so it is marked limited. Zapier's [Files by Zapier](https://zapier.com/apps/files-by-zapier/integrations) processes files only for the duration of a Zap run and [Storage by Zapier](https://help.zapier.com/hc/en-us/articles/8496293271053-Save-and-retrieve-data-from-Zaps) holds small text values, so Zapier is marked limited. Make.com's [data stores](https://help.make.com/l6du-data-stores) hold structured records and its [file handling](https://help.make.com/working-with-files) passes files between apps without persistent built-in storage, so Make is marked unavailable. ²³ Heym's [Playwright node](../nodes/playwright-node.md) is first-party browser automation with a visual steps mode, AI-generated steps, and a full-code mode. n8n offers only community packages such as [n8n-playwright](https://github.com/toema/n8n-playwright) with a still-open [feature request for native browser automation nodes](https://community.n8n.io/t/front-end-web-mobile-app-test-automation-nodes/129796), so it is marked limited. Zapier Agents can [browse and read pages via web browsing and a Chrome extension](https://help.zapier.com/hc/en-us/articles/29025734470925-Use-Zapier-Agents-Chrome-extension) but Zapier documents no scripted browser automation step, so it is marked limited. Make.com documents HTTP modules and third-party scraping apps rather than any native browser automation module, as of July 20, 2026.

## Related

- [Introduction](./introduction.md) – Platform overview
- [Quick Start](./quick-start.md) – Build your first workflow
- [Workflow Analysis](../reference/workflow-analysis.md) – Generate shared run-aware workflow reports and improvement feedback
- [Dashboard Tab](../tabs/dashboard-tab.md) – Build workflow-backed dashboards with AI-generated chart widgets
- [Agent Node](../nodes/agent-node.md) – LLM node with tool calling, MCP, and skills
- [Agent Architecture](../reference/agent-architecture.md) – Sub-agents, orchestrator, and tool dispatch
- [Board Tab](../tabs/board-tab.md) – Agentic Kanban board with workflow-executing columns
- [Codex Node](../nodes/codex-node.md) – Run the OpenAI Codex coding agent against a GitHub repo
- [OpenCode Go Node](../nodes/opencode-go-node.md) – Provider-agnostic coding agent in a hardened container
- [Drive Tab](../tabs/drive-tab.md) – Built-in file storage with share links, teams, and bulk actions
- [Playwright Node](../nodes/playwright-node.md) – First-party browser automation with AI steps and code mode
- [RAG / Vector Store Node](../nodes/rag-node.md) – Vector search and document insertion (Qdrant or Postgres pgvector)
- [AI Assistant](../reference/ai-assistant.md) – Natural language workflow builder
- [Human-in-the-Loop](../reference/human-in-the-loop.md) – Agent checkpoints with public review URLs
- [Guardrails](../reference/guardrails.md) – Block unsafe prompts before they reach your models
- [Traces Tab](../tabs/traces-tab.md) – LLM call observability
- [Evals Tab](../tabs/evals-tab.md) – Test suites for AI workflows
- [Alerts Tab](../tabs/alerts-tab.md) – Threshold alerts on errors, duration, cost, and run volume
- [OpenTelemetry Tracing](../reference/opentelemetry.md) – Export run, node, and tool spans over OTLP
- [Load Distribution](../reference/cluster.md) – Share runs across instances with leader failover
- [Single Sign-On](../reference/sso.md) – Sign in through any OpenID Connect provider
- [Audit Logging](../reference/audit.md) – Security-relevant actions with actor, target, and outcome
- [Portal](../reference/portal.md) – Publish workflows as public chat UIs
- [Parallel Execution](../reference/parallel-execution.md) – DAG-based concurrent execution
- [MCP Tab](../tabs/mcp-tab.md) – MCP server and client configuration
