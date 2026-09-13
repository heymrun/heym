<div align="center">

<br/>

<img src="./docs/readme-assets/logo.svg" width="80" height="80" alt="Heym Logo"/>

# Heym

### Build agentic systems. Run them with confidence.

<p align="center">
  Heym is a self-hosted runtime and platform for building, orchestrating, running, observing, evaluating, and controlling agentic systems on your infrastructure.
</p>

<p align="center">
  Visually compose agents and deterministic workflows, or generate them with AI. Connect models, tools, MCP, company knowledge, and internal systems, then operate them with approval checkpoints, retries, and visibility into execution and model costs.
</p>

<p align="center">
  <a href="https://heym.run">heym.run</a>
</p>

<p align="center">
  <strong>Try locally:</strong> <code>git clone https://github.com/heymrun/heym.git && cd heym && ./run.sh</code><br/>
  <a href="#-quick-start">Quick Start</a> ·
  <a href="#deploy--call-workflows">Deploy & Call Workflows</a> ·
  <a href="#extending-heym">Extending Heym</a> ·
  <a href="SECURITY.md">Security</a>
</p>

<br/>

[![PR checks](https://img.shields.io/github/actions/workflow/status/heymrun/heym/pr-checks.yml?style=flat-square&event=pull_request&label=PR%20checks&logo=githubactions&logoColor=white)](https://github.com/heymrun/heym/actions/workflows/pr-checks.yml)
[![Release image](https://img.shields.io/github/actions/workflow/status/heymrun/heym/publish-release-image.yml?style=flat-square&label=release%20image&logo=docker&logoColor=white)](https://github.com/heymrun/heym/actions/workflows/publish-release-image.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)
[![MCP status](https://mcpvitals.com/badge/46f18385ee.svg?theme=flat-square)](https://mcpvitals.com/status/46f18385ee)
[![Commons Clause](https://img.shields.io/badge/Condition-Commons%20Clause-orange.svg?style=flat-square)](COMMONS-CLAUSE.md)
[![Heym Version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fheymrun%2Fheym%2Fmain%2Ffrontend%2Fpackage.json&query=%24.version&label=Heym&prefix=v&color=blueviolet&style=flat-square)](https://github.com/heymrun/heym/releases)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Vue.js](https://img.shields.io/badge/Vue.js-3.x-4FC08D?style=flat-square&logo=vue.js&logoColor=white)](https://vuejs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-Strict-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Bun](https://img.shields.io/badge/Bun-runtime-14151A?style=flat-square&logo=bun&logoColor=white)](https://bun.sh)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![Security](https://img.shields.io/badge/Security-policy-2A6F97?style=flat-square)](SECURITY.md)

<br/>

<img src="./docs/readme-assets/hero.svg" width="100%" alt="Heym self-hosted agentic runtime animation"/>

<br/>

</div>

---

## What Is Heym?

In Heym, a workflow defines how agents, deterministic steps, tools, and data work together. The runtime executes that graph, coordinates dependent and parallel work, records execution history, and supports human review checkpoints.

**The canvas is one interface into Heym. It is not Heym itself.** Use it to build, inspect, debug, and understand systems running on the runtime. Those same workflows also run through APIs, schedules, event triggers, MCP clients, and Portal conversations.

Explore the product site at **[heym.run](https://heym.run)**.

## One Runtime for the Agent Lifecycle

**Build → Orchestrate → Run → Observe → Evaluate → Control → Expose**

These are connected parts of operating an agentic system in Heym.

| Stage | What you do in Heym |
|-------|---------------------|
| **Build** | Compose agents and deterministic workflows visually, generate them with AI, or start from reusable templates and skills. |
| **Orchestrate** | Coordinate agents, sub-agents, sub-workflows, and tools with explicit data flow, branching, and parallel execution where dependencies allow. |
| **Run** | Execute from APIs, schedules, event triggers, or interactive interfaces, with configurable retries, error paths, and browser automation. |
| **Observe** | Inspect execution history, live state, traces, tool calls, tokens, latency, errors, and model costs. Review analytics and alerts, and export OpenTelemetry traces. |
| **Evaluate** | Test prompts and model responses against expected outputs, compare results across models, and inspect saved evaluation runs. |
| **Control** | Pause Agent execution at review checkpoints and resume from saved state after a human decision. Configure guardrails, credentials, authentication, and team access. |
| **Expose** | Serve workflows through REST, SSE streaming, MCP tools, and Portal chat interfaces, or connect their results to in-app dashboard widgets. |

Use observations and evaluation results to refine prompts, tools, and workflow logic, then run and inspect the next iteration.

## 🗺️ Platform Overview

The workflow definition connects the build experience to execution. The runtime uses that definition to coordinate nodes and tools, while execution state feeds the interfaces people use to inspect, review, and consume the results.

| Part of the system | How it fits |
|--------------------|-------------|
| **Build and inspect** | The canvas, AI Assistant, templates, and Expression DSL create and edit workflow definitions. The same canvas can attach to an active execution for inspection. |
| **Orchestrate and execute** | The executor coordinates agents, deterministic nodes, sub-workflows, parallel branches, retries, and review checkpoints. |
| **Connect tools and data** | Nodes and agent tools reach models, HTTP APIs, MCP servers, internal knowledge, persistent memory, databases, queues, and files. |
| **Operate and improve** | History, traces, costs, analytics, alerts, logs, and OpenTelemetry reveal runtime behavior. Evals support prompt and model iteration; access controls and human review shape how systems run. |
| **Serve people and applications** | REST and SSE endpoints, MCP tools, Portal conversations, Board jobs, and workflow-backed dashboards provide ways to invoke systems and use their results. |

<div align="center">

![Heym Banner](./docs/screenshots/heym-banner-standalone.webp)

</div>

---

## ✨ Key Capabilities

### Build: Agents, Workflows, and Connected Tools

- **Visual and AI-assisted authoring.** Build and inspect workflow graphs on the canvas, generate or revise them through the AI Assistant using text or voice, and reuse templates.
- **Agents and deterministic logic.** Combine LLM and Agent nodes with conditions, switches, loops, merges, data transformations, and sub-workflow calls. Use expressions in supported node fields.
- **Multi-agent orchestration.** Give an orchestrator named sub-agents and sub-workflows to call. Independent sub-agent calls can execute concurrently.
- **Knowledge and persistent memory.** Retrieve documents through RAG using Qdrant or PostgreSQL with pgvector. Enable per-agent knowledge graphs to retain facts across runs, with configurable sharing between agents.
- **Tools and integrations.** Connect communication services, developer tools, productivity apps, databases, queues, and storage through built-in nodes, HTTP APIs, and MCP. Use MCP Call nodes for deterministic tool invocation.
- **Skills and custom behavior.** Attach reusable `SKILL.md` instructions and optional Python tools to agents, create or revise skills with AI, install plugins, or implement custom nodes with typed configuration and execution handlers.

### Run: Execute and Coordinate Work

- **Parallel execution and recovery.** Run independent nodes concurrently, synchronize branches with Merge, and configure retries, backoff, error paths, and model fallback.
- **Schedules and triggers.** Start workflows through cron, webhooks, messaging integrations, inbox events, WebSocket messages, and Heym platform events.
- **Browser and coding agents.** Automate browser tasks with Playwright and AI-assisted selector recovery. Run Codex or OpenCode Go against a repository as workflow steps, with diff and pull-request outputs.
- **Agentic Kanban Board.** Cards are persistent agentic jobs. Moving a card into a column runs its ordered workflow chain with card content, comments, history, and previous outputs, then writes results back to the card.
- **Load distribution.** Share eligible background runs across Heym instances through PostgreSQL, with execution weights configured in **Settings → Instances**.

### Observe: Understand Execution and Cost

- **History and live execution.** Open a production run from History or a Board card, inspect its saved state, and follow live node progress, Debug logs, and final output.
- **Traces and model costs.** Inspect model requests, responses, tool calls, input/output tokens, latency, and errors. Calculate USD costs with maintained model pricing and custom overrides, and explore historical spending by model and time range.
- **Analytics, logs, and alerts.** Track execution volume, success rates, and duration; review logs; set alerts for errors, duration, token or USD spend, and run count. Export workflow, node, and Agent tool spans through OpenTelemetry.

### Evaluate & Control: Improve Behavior and Keep Humans Involved

- **Evals and analysis.** Run repeatable prompt evaluations across models, compare expected and actual outputs, and review historical results. The Workflow Analyzer uses execution context to create a shared, editable Markdown report on purpose, step behavior, and improvement areas.
- **Human review.** Agent checkpoints pause execution for acceptance, edits, or refusal, then continue from a saved execution snapshot. A review branch can notify people through existing integrations.
- **Security and access.** Configure input guardrails, encrypted credentials, team sharing, execution tokens, and workflow authentication. Sign in with JWT authentication or OIDC SSO through providers such as Keycloak, Okta, Entra ID, Auth0, and Google.

### Expose: Put Systems to Work

- **REST, SSE, and MCP.** Invoke workflows from applications, stream execution events, or publish workflows as tools for MCP clients.
- **Portal and Chat.** Publish workflow-backed chat interfaces with streaming, uploads, and conversation history. Use the Chat tab to call workflows and work with models and platform data.
- **Dashboards, data, and files.** Build custom dashboard widgets backed by workflows, manage structured Data Tables, and keep generated files in Heym Drive with team sharing and share links.

<div align="center">

<img src="./docs/readme-assets/key-capabilities.svg" width="100%" alt="Animated Heym runtime capabilities grid"/>

</div>

---

## 🎬 Product Tour

One e-commerce sales campaign, followed end to end: workflow generation with the AI Assistant, human review, board execution, structured data, dashboards, traces, RAG, MCP, analytics, and team collaboration.

<div align="center">

<a href="https://www.youtube.com/watch?v=CWUy2zynCqc">
  <img src="https://img.youtube.com/vi/CWUy2zynCqc/maxresdefault.jpg" width="100%" alt="Watch the Heym product tour on YouTube"/>
</a>

</div>

## Product Demos

The demos follow an **orchestrator and sub-agent** system from creation to a chat interface. For a request such as “How do I get from Berlin to Frankfurt?” and “What should I eat there?”, the orchestrator can call independent sub-agents in the same turn, run those tasks concurrently, and combine their results.

### Generate Workflows from Natural Language

Describe the agents, orchestration pattern, and user-facing result you want; Heym builds the workflow on the canvas.

![Workflow Creation Demo](./docs/screenshots/workflow_creation.gif)

**Example prompt**

> Create a workflow for me that includes a Roadmap Agent and a Best Food Agent. When the Orchestrator Agent receives a request, it will invoke these subagents in parallel and return the result to the user.

### Run and Inspect a System

Start a runtime execution from the canvas and inspect each step as results move through the graph. APIs, schedules, triggers, and MCP can invoke the same workflow.

![Workflow Run Demo](./docs/screenshots/run.gif)

### Create Skills for Agents

Create agent skills from natural language, preview the generated `SKILL.md`, and attach them to the agent.

![Skill Creation Demo](./docs/screenshots/skill_creation.gif)

**Example prompt**

> Create a skill for me and add it to the agent. The Orchestrator Agent will call this skill after receiving information from the subagents, and the skill will create a simple execution plan explaining what can actually be done in the destination city.

### Call Workflows from Chat

Turn a workflow into a chat experience so users can invoke the orchestration with a natural request.

![Chat Workflow Demo](./docs/screenshots/chat.gif)

**Example prompt**

> I live in Berlin and am planning to go to Frankfurt. How many kilometers is it on the Autobahn? Also, where can I find the best doner in Frankfurt?

## 📸 Screenshots
<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/canvas.png" alt="Visual workflow canvas" width="100%"/>
      <br/><sub><b>Visual Canvas</b>: Multi-agent orchestration, RAG and MCP nodes, human-in-the-loop checkpoints</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/mcp.png" alt="MCP server settings" width="100%"/>
      <br/><sub><b>MCP Server</b>: Publish workflows as tools for Claude, ChatGPT, or Cursor</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/traces.png" alt="LLM traces" width="100%"/>
      <br/><sub><b>Traces</b>: Inspect model requests, responses, tokens, latency, and cost</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/analytics.png" alt="Analytics dashboard" width="100%"/>
      <br/><sub><b>Analytics</b>: Execution volume, success rate, latency, and time saved per workflow</sub>
    </td>
  </tr>
</table>

<br/>

## Watch Heym Tutorials

<div align="center">

<a href="https://www.youtube.com/playlist?list=PLPXd_ZbA4wgEHP5PXoaRqbsDJdat7OSd4">
  <img src="./docs/readme-assets/tutorial-videos-playlist.png" width="100%" alt="Watch Heym tutorial videos on YouTube"/>
</a>

</div>

---

## 🚀 Quick Start

Prefer to watch it first? **[Set Up Heym Locally in Under 2 Minutes](https://www.youtube.com/watch?v=P6YvlupUboU)** walks the whole path: clone the repository, start PostgreSQL and create your account on a local instance.

```bash
git clone https://github.com/heymrun/heym.git
cd heym
./run.sh

# OR: with .env file (run.sh auto-generates SECRET_KEY and ENCRYPTION_KEY)
git clone https://github.com/heymrun/heym.git
cd heym
cp .env.example .env
./run.sh
```

Open **http://localhost:4017** to create your account and start building. `run.sh` starts PostgreSQL, the backend, and the frontend, and generates `SECRET_KEY` and `ENCRYPTION_KEY` when needed.

**Prerequisites:** [Bun](https://bun.sh/), [Python 3.11+](https://python.org/), [UV](https://github.com/astral-sh/uv), and [Docker](https://docker.com/). For containers, use the [deployment options below](#deployment). See [ENVIRONMENT-VARIABLES.md](ENVIRONMENT-VARIABLES.md) for every setting and its default.

---

<a id="deployment"></a>

## Deployment

Heym runs on your infrastructure with **PostgreSQL as its core database**. The standard Compose setup includes PostgreSQL, the backend, and the frontend, with local volumes for persistent files. RabbitMQ and Redis are integrations you connect when a workflow needs them. RAG can use the built-in PostgreSQL/pgvector backend or an external Qdrant server; S3 is available through its integration node.

### Docker Compose

Use Docker Compose and Python 3 for production deployment:

```bash
cp .env.example .env
./deploy.sh              # Build and deploy (auto-generates keys if empty)
./deploy.sh --down       # Stop services
./deploy.sh --logs       # View logs
./deploy.sh --restart    # Restart services
```

> Register your admin account first, then set `ALLOW_REGISTER=false` in `.env` and restart to close registration in production.

### Prebuilt Docker Image

The release image bundles the frontend and backend. The examples below connect it to an existing PostgreSQL database on the host; set `DATABASE_URL` to your database address and credentials. On Linux, add `--add-host=host.docker.internal:host-gateway` when using that hostname.

<details>
<summary><b>Docker commands with persistent files, plugins, and coding-agent workspaces</b></summary>

```bash
# Docker with .env file
git clone https://github.com/heymrun/heym.git
cd heym
cp .env.example .env
# Generate required keys and write them into the placeholder lines copied from
# .env.example (replace in place: appending with >> would create duplicate entries):
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|; s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${ENCRYPTION_KEY}|" .env && rm -f .env.bak
docker run --env-file .env \
  -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@host.docker.internal:6543/heym \
  -p 4017:4017 \
  --shm-size 2g \
  -e FILE_STORAGE_DIR=/app/data/files \
  -e HEYM_PLUGINS_DIR=/app/data/plugins \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(pwd)/data/files:/app/data/files" \
  -v "$(pwd)/data/plugins:/app/data/plugins" \
  -v heym-codex-workspaces:/app/data/codex-workspaces \
  -v heym-opencode-workspaces:/app/data/opencode-workspaces \
  ghcr.io/heymrun/heym:latest

# OR: minimal, no .env file
docker run \
  -e ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  -e SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@host.docker.internal:6543/heym \
  -e FILE_STORAGE_DIR=/app/data/files \
  -e HEYM_PLUGINS_DIR=/app/data/plugins \
  -p 4017:4017 \
  --shm-size 2g \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(pwd)/data/files:/app/data/files" \
  -v "$(pwd)/data/plugins:/app/data/plugins" \
  -v heym-codex-workspaces:/app/data/codex-workspaces \
  -v heym-opencode-workspaces:/app/data/opencode-workspaces \
  ghcr.io/heymrun/heym:latest
```

</details>

The mounts and runtime settings support these capabilities:

- **Playwright:** `--shm-size 2g` gives Chromium room for browser tasks. Step-based Playwright runs inside the Heym container; custom `playwrightCode` uses a sibling container with its own shared-memory setting. Compose configures this for you.
- **Heym Drive:** `FILE_STORAGE_DIR=/app/data/files` points file storage at the mounted directory, keeping uploads and generated files across container restarts.
- **Plugins:** `HEYM_PLUGINS_DIR=/app/data/plugins` and its mount preserve installed plugin packages.
- **Skills and Codex:** the `heym-codex-workspaces` volume connects the runtime to its hardened sibling containers. Per-run isolation uses Docker Engine 25.0+.
- **OpenCode Go:** the `heym-opencode-workspaces` volume preserves the workspace shared with its sibling runner.
- **Docker access:** the socket supports sandbox containers and MCP `stdio` execution. It grants broad host control, so restrict access to your deployment. Docker log access is configured separately with `DOCKER_LOGS_ENABLED` and `DOCKER_LOGS_ALLOWED_EMAILS`; create allow-listed accounts before opening registration.

### Multi-Instance Execution

Connect additional Heym instances to the same PostgreSQL database to distribute eligible background workflow runs. Configure their shares from **Settings → Instances**. PostgreSQL carries the queue and coordination, so the cluster needs no separate message broker or direct instance-to-instance connection.

The main instance serves the UI, API, MCP, and Portal and owns local files and installed plugins. Workers execute eligible queued runs; workflows that depend on main's local storage or workspaces run there. The [Load Distribution guide](frontend/src/docs/content/reference/cluster.md) covers placement, shared keys, database sizing, ingress, and upgrades, with [cluster](docker-compose.cluster.yml) and [worker](docker-compose.worker.yml) Compose examples.

Heym is in its pre-1.0 release series. Follow the [version badge and releases](https://github.com/heymrun/heym/releases) for updates. The [deployment guide](frontend/src/docs/content/getting-started/running-and-deployment.md) and [security policy](SECURITY.md) provide the operational setup reference.

---

## Extending Heym

Connect Heym to the systems your team already uses. Choose built-in integrations, HTTP APIs, MCP, reusable skills, plugins, or custom nodes to bring tools and data into the runtime.

| Extension path | Best for | How it works |
|----------------|----------|--------------|
| HTTP APIs | APIs and internal services | Configure requests, headers, authentication, and expressions with the HTTP node. |
| Plugins | Installable node types and triggers | Add operator-installed packages with runtime handlers and editor schemas. See [Plugin Authoring](frontend/src/docs/content/reference/plugin-authoring.md). |
| Custom nodes | Product-grade workflow steps and integrations | Add a typed node with editor configuration, execution behavior, and schema metadata. |
| Agent skills | Portable agent abilities | Attach a `SKILL.md` file and optional Python tools to Agent nodes, or generate them with AI Build. |
| MCP | External tools and AI clients | Agent nodes consume MCP servers, and Heym workflows can be exposed as MCP tools. |
| Workflow as tool | Reusable automations | Call workflows through REST, SSE, Portal chat, or MCP without duplicating the logic. |

### Built-In Integrations and Node Library

| Purpose | Representative nodes and connections |
|---------|-------------------------------------|
| **Communication** | Slack, Discord, Telegram, and SMTP/IMAP email for mail services such as Gmail and Outlook |
| **Developer tools and productivity** | GitHub, Jira, Linear, Notion, Google Drive, Google Sheets, Grist, and Sentry |
| **Data, queues, and storage** | BigQuery, ClickHouse, Supabase, Redis, RabbitMQ, Amazon S3, Heym Data Tables, and Drive |
| **Knowledge** | RAG with Qdrant or PostgreSQL/pgvector, plus per-agent persistent memory |
| **APIs and browsers** | HTTP, WebSocket Trigger/Send, MCP Call, Crawler, and Playwright |

The node library brings agents together with deterministic logic, triggers, data, and outputs:

| Category | Nodes |
|----------|-------|
| **Triggers** | Input (Webhook), Cron, Slack, Discord, Telegram, IMAP, WebSocket, File Upload, Heym events, RabbitMQ Receive, Plugin Trigger |
| **AI** | LLM, Agent, RAG, Codex, OpenCode Go |
| **Logic** | Condition, Switch, Loop, Merge |
| **Data** | Set, Variable, DataTable, Execute (sub-workflow), Converter |
| **Output and utilities** | Output, Chart Output, JSON/HTML Output Mapper, Wait, Console Log, Error Handler, Throw Error, Disable Node, Sticky Note |

Heym Drive stores uploaded and generated files with public or password-protected share links, team sharing, and bulk ZIP, share, and delete actions. See [Drive](frontend/src/docs/content/reference/drive.md).

See the [node reference](frontend/src/docs/content/reference/node-types.md) and [integration guides](frontend/src/docs/content/reference/integrations.md) for operations, credentials, and setup.

### MCP (Model Context Protocol)

**As a client:** Agent nodes discover and call tools from configured MCP servers over SSE, Streamable HTTP, or `stdio`. The MCP Call node invokes a selected tool directly when the workflow defines the call.

**As a server:** Publish Heym workflows as tools at `/api/mcp/sse` for Claude Desktop, Cursor, and other MCP clients. See [MCP configuration](frontend/src/docs/content/tabs/mcp-tab.md).

### Skills System

Skills are portable capability bundles: a `SKILL.md` instruction file plus optional Python tools and assets. Drop a `.zip` or `.md` onto an Agent node, or use **AI Build** to draft and iterate on skills from chat. Reuse and share them across workflows and teams.

---

## Build and Orchestrate

<div align="center">

<img src="./docs/readme-assets/workflow-canvas.svg" width="100%" alt="Animated canvas for building and inspecting Heym runtime executions"/>

</div>

### AI Assistant

Describe the system you want in plain text or voice. The assistant generates nodes and edges directly in the editor, where you can inspect and refine the resulting workflow.

When a workflow already contains Agent skills, the assistant sends only each skill's `SKILL.md` into the builder context. Large `.py` files and binary attachments stay out of the prompt so workflow editing remains reliable even with complex skills loaded on the canvas.

<div align="center">

<img src="./docs/readme-assets/ai-assistant.svg" width="100%" alt="AI assistant builds a workflow animation"/>

</div>

### AI Skill Builder

Inside the Agent node's Skills section, use **AI Build** to create a new skill or the inline sparkle action to revise an existing one. The modal streams a chat conversation, previews generated `SKILL.md` and `.py` files live, and saves them back through the same ZIP ingestion path used by manual skill uploads.

### Multi-Agent Orchestration

Build orchestrator/sub-agent pipelines visually. One agent delegates tasks to named sub-agents or sub-workflows, composing their results into a shared response. Configure reasoning effort and temperature per agent.

<div align="center">

<img src="./docs/readme-assets/multi-agent.svg" width="100%" alt="Multi-agent orchestration animation"/>

</div>

### Built-In RAG Pipeline

Upload PDFs, Markdown, CSV, or JSON to a managed vector store backed by Qdrant or PostgreSQL/pgvector. Wire a RAG node into a workflow for semantic search, with retrieved context flowing into an LLM or Agent node.

```
Input → RAG (search) → LLM (answer with context) → Output
```

### Persistent Memory

Enable a knowledge graph for an Agent node to retain entities and relationships across runs. Heym adds graph context to the agent's prompt and merges new facts in the background after successful runs. Use the graph editor to inspect and edit memory or grant other agents read or read/write access. See [Agent Persistent Memory](frontend/src/docs/content/reference/agent-persistent-memory.md).

### LLM Configuration and Batch Processing

Configure reasoning effort, temperature, and fallback models for Agent execution. LLM nodes support text, vision, structured output, and provider-native Batch API mode for supported endpoints, with live status branches and per-item results. Agent message history is automatically compressed as it approaches the model context limit, with compression events visible in Debug logs, History, and Traces. See the [LLM node](frontend/src/docs/content/nodes/llm-node.md) and [Agent node](frontend/src/docs/content/nodes/agent-node.md) references.

---

## Execution Behavior

### Parallel Execution

Independent nodes run concurrently based on graph dependencies. Use the **Merge** node to synchronize parallel branches and combine their results. The graph defines the execution order. See [Parallel Execution](frontend/src/docs/content/reference/parallel-execution.md).

### Browser Automation and Auto Heal

Playwright nodes support visual steps, AI-generated actions, and full-code browser automation. Enable **Auto Heal** to use page context for selector recovery when an action fails. See the [Playwright node](frontend/src/docs/content/nodes/playwright-node.md) reference for configuration.

### Node-Level Error Handling

Configure **retry on failure** and **error branching** on nodes:

```
Input ──→ HTTP ──→ Output
               └─── error ──→ Error Handler
```

- **Retry**: automatically re-run a failed node with configurable attempts and backoff
- **Error branch**: route failures to a dedicated path instead of stopping the workflow
- **Error context**: access `$nodeName.error` in downstream nodes

---

## 🔍 Observability, Evaluations, and Control

### Execution History and Live State

Inspect saved inputs, outputs, node results, errors, timing, and execution logs. History connects a run to its trigger and, in a cluster, the instance that executed it.

### Open any production run live

Open a **Running** entry from either History dialog or the run list inside a Board card, and Heym attaches the editor to that exact execution over SSE. This works for runs started by webhooks, schedules, chat, MCP, integrations, or the Agentic Kanban Board. Completed
nodes are restored immediately; the current and pending nodes keep pulsing; Debug logs and the
final output arrive incrementally. Leaving the editor disconnects only the observer and never
cancels the production run.

### LLM Traces

Inspect model requests and responses, tool-call details, per-call timing, token usage, errors, and skills passed to the model. Use traces alongside workflow history to follow the relationship between model behavior and the surrounding execution. See [Traces](frontend/src/docs/content/tabs/traces-tab.md).

### Model Usage and Cost Visibility

Heym records **input and output tokens** and calculates **USD costs** from maintained model pricing data. Inspect costs per trace and explore historical usage and spending by model and time range. Add **custom model pricing overrides** for your own endpoints or rates.

Cost visibility also connects to operations: alerts can evaluate token or USD spend over a chosen time window. See [Traces and cost analytics](frontend/src/docs/content/tabs/traces-tab.md) for pricing and usage views.

### Analytics and Logs

Review execution volume, success rates, latency, and estimated time saved by workflow in [Analytics](frontend/src/docs/content/tabs/analytics-tab.md). Follow incremental Debug logs while inspecting a run, and enable access-controlled Docker log viewing and streaming through the [Logs tab](frontend/src/docs/content/tabs/logs-tab.md).

### Alerts

Set thresholds over a **time window** on four metrics: error count, run duration (max, average, or p95), LLM token or USD spend, and execution count. Scope an alert to one workflow or all workflows you can access.

A five-step wizard covers type, scope, condition, response, and review. Describe the rule in natural language to fill the form with AI, then preview the condition against historical windows before saving. By default, an alert fires once and waits for the metric to recover before firing again.

An alert can run a workflow with the observed value, threshold, window, and contributing detail as input. Use existing Slack, email, or Telegram nodes to deliver notifications. The Chat tab can explain which alerts exist and why one triggered. See [Alerts](frontend/src/docs/content/tabs/alerts-tab.md).

### Evals: Test, Compare, Improve

Create suites with a system prompt, test inputs, and expected outputs. Run the same cases across multiple models and repeat runs to compare responses. Inspect scores, actual versus expected output, latency, token usage, and saved run history.

Use evaluation results to guide prompt changes, generate additional test data, or request an AI-assisted prompt revision. Pair those results with execution traces and Workflow Analyzer reports to improve the system you operate. See [Evals](frontend/src/docs/content/tabs/evals-tab.md) and [Workflow Analysis](frontend/src/docs/content/reference/workflow-analysis.md).

### Human-in-the-Loop (HITL)

Agent review checkpoints turn human approval into part of execution. When an agent requests review, Heym saves an execution snapshot and marks the run as pending. The agent's `review` branch can send the review link and summary to Slack, email, or another notification flow.

A reviewer can **Accept**, **Edit & Continue**, or **Refuse**. Heym resumes from the saved snapshot with the decision and reviewed text available to downstream nodes. An agent can request further checkpoints during the same run. See [Human-in-the-Loop](frontend/src/docs/content/reference/human-in-the-loop.md).

### Guardrails and Access Controls

Configure category-based and multilingual guardrails on LLM and Agent input messages. Checks run before the model call and route violations through the workflow's error-handling paths.

Manage encrypted credentials and team sharing, use scoped execution tokens, configure workflow authentication and rate limits, and connect an OIDC identity provider for SSO. See [Guardrails](frontend/src/docs/content/reference/guardrails.md), [Teams](frontend/src/docs/content/reference/teams.md), [Credentials Sharing](frontend/src/docs/content/reference/credentials-sharing.md), [SSO](frontend/src/docs/content/reference/sso.md), and [Security](SECURITY.md).

### OpenTelemetry Tracing

Export a root span per workflow run, a child span per node, and Agent tool spans (`heym.agent.tool.execute`) over OTLP/HTTP to Jaeger, Grafana Tempo, Honeycomb, Datadog, or any OpenTelemetry backend. Spans carry workflow id, node type, status, duration, LLM token usage, and tool identity/status, with W3C trace context propagated across inbound webhooks, outbound HTTP, and sub-workflows. Enable tracing with the `HEYM_OTEL_*` environment variables and review status under **Settings → Observability**. See [OpenTelemetry Tracing](frontend/src/docs/content/reference/opentelemetry.md) for configuration and span details.

---

## Deploy & Call Workflows

The same runtime can serve people, backend services, and external agents. Choose an interface for how the system will be used:

| Interface | Endpoint or surface | Use |
|-----------|---------------------|-----|
| **REST** | `POST /api/workflows/{workflow_id}/execute` | Invoke a workflow from an application or HTTP webhook. |
| **SSE** | `POST /api/workflows/{workflow_id}/execute/stream` | Stream execution progress and node events to a client. |
| **MCP server** | `/api/mcp/sse` | Publish workflows as tools for MCP clients. |
| **Portal** | `/chat/{slug}` | Provide a workflow-backed chat interface for people. |
| **Dashboard** | Dashboard tab | Run workflow-backed widgets to produce charts and operational views. |
| **Board** | Board tab | Run workflow chains as persistent jobs with card context and history. |
| **Schedules and events** | Cron and integration triggers | Execute in response to time, messages, uploads, or platform events. |

The editor's **Run with cURL** dialog generates commands for REST or SSE, including per-node start messages and live event output. See [Webhooks](frontend/src/docs/content/reference/webhooks.md) and [SSE Streaming](frontend/src/docs/content/reference/sse-streaming.md) for authentication, request bodies, and event formats.

### Portal

Turn a workflow into a public chat interface at `/chat/{slug}` with optional per-user authentication, streaming responses, file uploads, and multi-turn conversation history. Build internal tools and customer-facing chat interfaces directly from your workflow. See [Portal](frontend/src/docs/content/reference/portal.md).

### Workflow-Powered Dashboards

Each custom dashboard widget is backed by its own hidden Heym workflow. Fetch, transform, retrieve, or generate data through workflow logic and display the result as a chart in the dashboard. See [Dashboard](frontend/src/docs/content/tabs/dashboard-tab.md).

---

## 📝 Expression DSL

Reference and transform data between nodes with a clean syntax:

```js
$input.text                         // Trigger input
$nodeName.field                     // Any upstream node output
$global.variableName                // Persistent global variable
$now.format("YYYY-MM-DD HH:mm")    // Date/time formatting
$UUID                               // Random unique ID
$range(1, 10)                       // Generate number range
$input.items.filter("item.active")  // Array filtering
$input.users.map("item.email")      // Array mapping
$input.text.upper()                // String helpers
```

Use expressions in supported node fields, including prompts, HTTP headers, conditions, email bodies, and Redis keys. See the [Expression DSL reference](frontend/src/docs/content/reference/expression-dsl.md).

---

## 🏗️ Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Vue.js 3 + TypeScript (strict) + Vite + Bun |
| **UI Components** | Shadcn Vue + Tailwind CSS |
| **Canvas** | Vue Flow |
| **State Management** | Pinia |
| **Backend** | Python 3.11+ + FastAPI + UV |
| **Database** | PostgreSQL 16 + SQLAlchemy 2.0 (async) |
| **Auth** | JWT (access + refresh), bcrypt, optional OpenID Connect SSO login |

---

## 📁 Project Structure

```
heym/
├── frontend/src/
│   ├── components/     # Canvas, Nodes, Panels, Credentials, Evals, MCP, Teams
│   ├── views/          # DashboardView, EditorView, ChatPortalView
│   ├── stores/         # Pinia (workflow, auth, folder)
│   ├── services/       # API clients
│   └── docs/content/   # In-app documentation (Markdown)
├── backend/
│   ├── app/
│   │   ├── api/        # Routes: workflows, auth, mcp, portal, evals, traces
│   │   ├── models/     # Pydantic schemas
│   │   ├── services/   # Executor, node handlers, LLM, RAG, agent engine
│   │   └── db/         # SQLAlchemy models and database configuration
│   ├── tests/          # Backend unit tests
│   └── alembic/        # Database migrations
├── docker-compose.yml
├── run.sh              # Local development launcher
├── check.sh            # Project validation script
└── deploy.sh           # Docker production deployer
```

---

## ⚙️ Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Optional database connection string override | auto-built from `POSTGRES_*` |
| `POSTGRES_HOST` | Database host used when `DATABASE_URL` is empty | `localhost` |
| `POSTGRES_PORT` | Database port used when `DATABASE_URL` is empty | `6543` |
| `SECRET_KEY` | JWT signing key | Not set |
| `ENCRYPTION_KEY` | Encrypts stored credentials at rest. Required at startup; generate with `python -c "import secrets; print(secrets.token_hex(32))"` | Not set |
| `BACKEND_PORT` | Backend server port | `10105` |
| `FRONTEND_PORT` | Frontend server port | `4017` |
| `ALLOW_REGISTER` | Enable user registration | `true` |
| `REQUEST_BODY_MAX_SIZE_MB` | Maximum backend HTTP request body size; defaults to `100`, one MB above `FILE_MAX_SIZE_MB` to allow multipart overhead | `100` |
| `HEYM_OTEL_ENABLED` | Enable OpenTelemetry tracing for workflow, node, and Agent tool executions | `false` |
| `HEYM_OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP/HTTP base endpoint, e.g. `http://collector:4318` (spans posted to `/v1/traces`) | Not set |
| `HEYM_OTEL_EXPORTER_OTLP_HEADERS` | Comma-separated `key=value` exporter headers for auth | Not set |
| `HEYM_OTEL_SERVICE_NAME` | `service.name` resource attribute | `heym` |
| `HEYM_OTEL_TRACES_SAMPLER_RATIO` | Parent-based head sampling ratio (`0.0`–`1.0`) | `1.0` |
| `HEYM_OTEL_CAPTURE_NODE_IO` | Attach truncated node input/output to node spans | `false` |
| `HEYM_MCP_ALLOW_PRIVATE_URLS` | Allow MCP HTTP/SSE servers on private/loopback/metadata addresses (SSRF guard off). Keep `false` on hosted/multi-tenant | `false` |

See [ENVIRONMENT-VARIABLES.md](ENVIRONMENT-VARIABLES.md) for the complete reference.

---

## 🛠️ Development

**Prerequisites:** [Bun](https://bun.sh/) ≥ 1.0 · [Python](https://python.org/) ≥ 3.11 · [UV](https://github.com/astral-sh/uv) · [Docker](https://docker.com/)

```bash
# Start all services (recommended)
./run.sh
./run.sh --no-debug    # INFO logging instead of DEBUG
```

Or start each service manually:

```bash
# Start database only
docker-compose up -d postgres

# Backend
cd backend && uv sync && uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 10105

# Frontend (separate terminal)
cd frontend && bun install && bun run dev
```

**Validation:**

```bash
./check.sh    # Frontend lint/typecheck; backend format, lint, and tests
# If SECRET_KEY is not exported locally:
SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh

# Frontend unit and browser tests run separately
(cd frontend && bun run test)
./run_e2e.sh
```

Or run individually:

```bash
(cd frontend && bun run lint && bun run typecheck && bun run test)
(cd backend && uv run ruff check . && uv run ruff format .)
```

Every pull request runs the [PR checks](https://github.com/heymrun/heym/actions/workflows/pr-checks.yml) workflow: a file line-limit check, frontend ESLint, TypeScript strict typecheck, frontend Vitest unit tests, production build, backend Ruff format and lint, the backend unit test suite, and Playwright E2E tests against a live Postgres service.

The backend publishes its OpenAPI reference at `/docs` on the backend server (port `10105` in local development).

---

## Documentation and Full Feature Set

For a complete list of all features with short descriptions, see **[Full Feature Set](frontend/src/docs/content/reference/features.md)**. It covers Getting Started, every node type, reference topics (Expression DSL, workflow structure, webhooks, SSE streaming, AI Assistant, Chat with Docs, Portal, security, etc.), and all dashboard tabs (Workflows, Templates, Variables, Chat, Credentials, Vectorstores, MCP, Traces, Alerts, Analytics, Evals, Teams, Logs and more).

Use **Chat with Docs** from the documentation header for questions grounded in the current article. **Ctrl+K** opens search, navigation, and workflow actions from the command palette.

<div align="center">

<img src="./docs/readme-assets/full-feature-showcase.svg" width="100%" alt="Animated Heym full feature set showcase"/>

</div>

---

## 📄 License

Heym is **source available** under the **[MIT License](LICENSE)** with the **[Commons Clause](COMMONS-CLAUSE.md)** condition. You can use, modify, distribute, and self-host it under those terms. Commercial licensing is available for rights restricted by the Commons Clause, including selling products or services whose value derives substantially from Heym. See both license files for the full terms.

---

## 💬 Community

Join our Discord to connect with the community, ask questions, share workflows, and stay up to date:

[![Discord](https://img.shields.io/badge/Discord-Join%20us-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/T2wXvuVdMX )

---

## 🧩 Share a Template

Want to publish a workflow template for the community? Submit it directly from the **[Templates page](https://heym.run/submit)**: open the dialog, paste your workflow DSL, and send it for review. No pull request needed.

If you'd rather contribute through code, please **[start a Discussion](https://github.com/heymrun/heym/discussions)** so we can talk it through together **before** opening a pull request.

---

## ⭐ Stay Up To Date

<div align="center">

![Workflow Creation Demo](./docs/screenshots/heym-star.gif)

</div>

Heym is built for developers who want control and enterprise teams that need a trusted path to production. Star Heym ⭐ on GitHub to follow releases and help more builders discover it.

---

## 🏢 Enterprise

Commercial licensing, deployment services, and professional support help teams build and operate agentic systems on private infrastructure.

**What we offer:**

- Commercial licensing for your product or service
- Deployment planning, architecture reviews, and infrastructure support
- Custom integrations and feature development
- Assistance with enterprise security and identity requirements
- Onboarding, training, troubleshooting, and solution support
- Priority support and SLA agreements

Core runtime capabilities, including execution history, observability, evals, team controls, SSO, load distribution, and Portal, are part of the self-hosted product.

<div align="center">

<img src="./docs/readme-assets/no-gatekeeping.svg" width="100%" alt="Core capabilities for building and operating systems in the self-hosted Heym runtime"/>

</div>

📧 **Contact:** [enterprise@heym.run](mailto:enterprise@heym.run)

---

<div align="center">

**Built with ❤️ using Vue.js, FastAPI, and a lot of LLM tokens.**

[⭐ Star this repo](https://github.com/heymrun/heym/stargazers) · [🐛 Report a bug](https://github.com/heymrun/heym/issues) · [💡 Request a feature](https://github.com/heymrun/heym/discussions)

</div>
