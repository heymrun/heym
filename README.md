<div align="center">

<br/>

<img src="./docs/readme-assets/logo.svg" width="80" height="80" alt="Heym Logo"/>

# Heym

### AI-Native Workflow Automation Platform

<p align="center">
  <strong>Build, visualize, and run intelligent AI workflows without writing code.</strong><br/>
  Drag-and-drop canvas · LLM & Agent nodes · RAG pipelines · Multi-agent orchestration · MCP support
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

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)
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

<img src="./docs/readme-assets/hero.svg" width="100%" alt="Heym animated AI-native workflow automation hero"/>

<br/>

</div>

---

## What Is Heym?

Heym is an **AI-native automation platform** built from the ground up around LLMs, agents, and intelligent tooling. Wire together AI agents, vector stores, web scrapers, HTTP calls, and message queues on a visual canvas — then deploy instantly via Docker.

Unlike platforms that started as classic trigger-action automation and layered AI on later, in Heym **AI is the execution model**.

Explore the product site at **[heym.run](https://heym.run)**.

## Build, Observe, Call

| Build | Observe | Call |
|-------|---------|------|
| Create workflows from a visual canvas, natural language, voice, templates, or Agent skills. | Inspect executions with run history, LLM traces, evals, logs, OpenTelemetry export, and real USD cost tracking. | Invoke the same workflow from the canvas, REST execution endpoints, SSE streaming, MCP clients, or a public Portal chat UI. |

<div align="center">

<img src="./docs/readme-assets/workflow-canvas.svg" width="100%" alt="Animated Heym workflow canvas"/>

</div>

## No Enterprise Gatekeeping

Many automation platforms turn essential production features into upgrade pressure: global variables, execution history and search, insights, AI Builder / Motherboard capabilities, observability, audit-style logs, team controls, scaling, or customer-facing portals.

Heym takes the opposite position. These are core workflow primitives, not enterprise bait. They ship in the free self-hostable product because serious AI automation should be inspectable, shareable, observable, and deployable from day one without any kind of weird production run limits. 

Our enterprise offering is for commercial licensing, deployment help, dedicated support, and additional security layers. It is not a strategy for hiding core workflow and AI-native capabilities behind a sales call, now or later.

<div align="center">

<img src="./docs/readme-assets/no-gatekeeping.svg" width="100%" alt="No enterprise gatekeeping animation"/>

</div>

---

## Product Demos

The demos below illustrate an **agent–subagent** layout instead of a purely step-by-step, single-thread agent chain. For a request like “How do I get from Berlin to Frankfurt?” *and* “What should I eat there?”, subagents can work on those parts **in parallel**. That tends to finish faster, keeps each model turn focused (less context bloat), and avoids pressuring one model to produce two large, unrelated answers in a single reply.

You can still answer with **two separate LLM calls** (one per question) or run **several calls in sequence** and merge the results in a final step—those patterns work—but for this kind of multi-part ask they are usually **slower** than parallel subagents behind an orchestrator.

### Generate Workflows from Natural Language

Describe the agents, orchestration pattern, and user-facing result you want; Heym builds the workflow on the canvas.

![Workflow Creation Demo](./docs/screenshots/workflow_creation.gif)

**Example prompt**

> Create a workflow for me that includes a Roadmap Agent and a Best Food Agent. When the Orchestrator Agent receives a request, it will invoke these subagents in parallel and return the result to the user.

### Running Workflows

Execute the workflow directly from the canvas and inspect each step as results move through the graph.

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

---

## 📸 Screenshots
<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/login.png" alt="Login Page" width="100%"/>
      <br/><sub><b>Login</b> — Workflow canvas preview in the background</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/dashboard_light.png" alt="Workflows Dashboard" width="100%"/>
      <br/><sub><b>Dashboard</b> — Manage workflows, credentials, vector stores, and teams</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/canvas_selected.png" alt="Workflow Canvas" width="100%"/>
      <br/><sub><b>Workflow Canvas</b> — Nodes connected and selected, with the properties panel open</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/node_properties.png" alt="Node Configuration" width="100%"/>
      <br/><sub><b>Node Config</b> — LLM node with model, prompt, and expression fields</sub>
    </td>
  </tr>
</table>

<br/>

---

## ✨ Key Capabilities

<div align="center">

<img src="./docs/readme-assets/key-capabilities.svg" width="100%" alt="Animated Heym key capabilities grid"/>

</div>

- **Visual Workflow Editor** — Drag-and-drop canvas powered by Vue Flow with a broad node library
- **AI Assistant** — Describe what you want in natural language (or voice) and the assistant generates and wires nodes on the canvas automatically
- **Chat with Docs** — Ask context-aware questions directly from the documentation header while the current article path is prioritized in the prompt
- **AI Skill Builder** — Create new Agent skills or revise existing ones from a modal chat with live `SKILL.md` and Python file previews
- **LLM & Agent Nodes** — First-class LLM node and a full Agent node with tool calling, canvas node tools, sandboxed Python tools, MCP connections, skills, optional persistent memory (per-node knowledge graph with background extraction), and LLM Batch API mode with live status branches for supported providers
- **Multi-Agent Orchestration** — One agent orchestrates named sub-agents and sub-workflows, all wired visually
- **Human-in-the-Loop (HITL)** — Pause agent execution to request user approval or input before proceeding
- **Guardrails** — Content filtering, NSFW protection, and multilingual safety checks on LLM and Agent nodes
- **Built-In RAG** — Insert documents and run semantic search against managed vector stores (Qdrant or built-in Postgres/pgvector) in two nodes
- **MCP Support** — Connect Agent nodes to any MCP server as a client; expose your workflows as an MCP server for Claude, Cursor, and other clients
- **Portal** — Turn any workflow into a public chat UI at `/chat/{slug}` with streaming responses and file uploads
- **Webhook SSE Streaming** — Generate ready-to-run cURL commands for `/execute` or `/execute/stream`, with per-node start messages and live node event output in the terminal
- **Data Tables** — Manage structured data directly in the dashboard and reference it from workflows
- **Workflow Analyzer** — Run-aware AI feedback that generates a shared Markdown report with improvement areas, purpose, and step-by-step behavior
- **Workflow-Powered Dashboards** — Build custom chart dashboards where every widget is backed by its own hidden Heym workflow
- **Templates** — Start from pre-built workflow templates to get up and running quickly
- **Parallel Execution** — Independent nodes run concurrently based on the graph structure, no configuration needed
- **Auto Heal** — Playwright selectors break? AI automatically detects and fixes them at runtime
- **LLM Fallback** — Automatic model fallback when the primary LLM fails or is unavailable
- **Reasoning Support** — Configure reasoning effort and temperature per Agent node for fine-grained control
- **Command Palette** — Ctrl+K for instant search, navigation, and workflow actions
- **Evals** — Define test suites and run them against any workflow with one click
- **LLM Traces** — Full observability for every agent call: requests, responses, tool calls, and timing
- **LLM Cost Tracking** — Per-trace token counts (input / output) with real-time USD cost calculation, historical analytics with time-range filtering, and a synced pricing table covering all major models
- **Self-Hosted** — Your data, your infrastructure

---

## Full Feature Set

For a complete list of all features with short descriptions, see **[Full Feature Set](frontend/src/docs/content/reference/features.md)**. It covers Getting Started, every node type, reference topics (Expression DSL, workflow structure, webhooks, SSE streaming, AI Assistant, Chat with Docs, Portal, security, etc.), and all dashboard tabs (Workflows, Templates, Variables, Chat, Credentials, Vectorstores, MCP, Traces, Analytics, Evals, Teams, Logs and more).

<div align="center">

<img src="./docs/readme-assets/full-feature-showcase.svg" width="100%" alt="Animated Heym full feature set showcase"/>

</div>

---

## ⭐ Stay Up To Date

<div align="center">

![Workflow Creation Demo](./docs/screenshots/heym-star.gif)

</div>

Heym Built for developers who want control and enterprise teams that need a trusted path to production. Star Heym ⭐ on GitHub to follow releases and help more builders discover it.

---

## 🎯 Why Heym?

| Capability | **Heym** | n8n | Zapier | Make.com |
|---|:---:|:---:|:---:|:---:|
| Built-in LLM node | ✅ | ✅ | ✅ | ✅ |
| LLM Batch API + status branches | ✅ | partial¹⁵ | ❌¹⁵ | partial¹⁵ |
| AI Agent node (tool calling) | ✅ | ✅ | ✅ | ✅ |
| Agent persistent memory (knowledge graph) | ✅ | limited¹¹ | limited¹¹ | limited¹¹ |
| Multi-agent orchestration | ✅ | ✅ | limited | limited |
| Human-in-the-Loop (HITL) | ✅ | ✅⁵ | limited⁶ | limited⁷ |
| LLM Guardrails | ✅ | ✅⁸ | ✅⁸ | limited⁸ |
| Automatic context compression | ✅ | ❌ | ❌ | ❌ |
| Built-in RAG / vector store | ✅ | ✅ | limited¹ | plugin² |
| WebSocket read / write | ✅ | limited¹² | ❌¹³ | ❌¹⁴ |
| Natural language workflow builder | ✅ | limited³ | ✅ | ✅ |
| Workflow Analyzer | ✅ | ❌¹⁸ | ❌¹⁸ | ❌¹⁸ |
| Workflow-powered dashboards | ✅ | partial¹⁹ | partial¹⁹ | partial¹⁹ |
| MCP (Model Context Protocol) | ✅ | ✅ | ✅ | ✅ |
| Skills system for agents | ✅ | ❌ | ❌ | ❌ |
| Auto Heal (Playwright) | ✅ | ❌ | ❌ | ❌ |
| Data Tables | ✅ | ✅ | ✅ | ❌ |
| Workflow Templates | ✅ | ✅ | ✅ | ✅ |
| LLM trace inspection | ✅ | limited⁴ | ❌ | ✅ |
| OpenTelemetry tracing export | ✅ | ✅¹⁷ | ❌¹⁷ | ❌¹⁷ |
| LLM token cost tracking (USD) | ✅ | ❌¹⁶ | ❌¹⁶ | limited¹⁶ |
| Built-in evals for AI workflows | ✅ | ✅ | ❌ | ❌ |
| Parallel DAG execution | ✅ | limited⁹ | ❌ | ❌ |
| Self-hostable, source-available | ✅ MIT + Commons Clause | ✅ fair-code¹⁰ | ❌ | ❌ |
| Expression DSL for dynamic data | ✅ | ✅ | limited | ✅ |

<details>
<summary><b>Table footnotes</b></summary>

1. Zapier Agents support "Knowledge Sources" (upload docs, connect apps) but no user-exposed vector store or control over embeddings/chunking
2. Make.com has Pinecone and Qdrant modules but no native one-click RAG node — you assemble the pipeline manually
3. n8n's AI Workflow Builder is cloud-only beta with monthly credit caps, not available for self-hosted
4. n8n shows intermediate steps (tool calls, results) but full prompt/response tracing requires third-party tools like Langfuse
5. n8n pauses AI tool calls for review through chat, email, and collaboration channels, but it is centered on tool approval rather than snapshotting and editing the whole execution state
6. Zapier Human in the Loop supports approvals and data collection inside Zaps, but it doesn't resume from a captured agent/runtime snapshot the way Heym checkpoints do
7. Make Human in the Loop is available as an Enterprise app with review requests and adjusted/approved/canceled outcomes, but it is plan-limited and less tightly coupled to agent state
8. n8n ships a dedicated Guardrails node, Zapier ships AI Guardrails across its AI products, and Make documents agent rules plus review flows but not a comparable standalone guardrails feature, so Make is marked limited
9. n8n executes sequentially by default; parallel execution requires sub-workflow workarounds
10. n8n uses the Sustainable Use License — free to self-host for internal use, commercial redistribution restricted
11. First-class per-agent knowledge graph with prompt injection and post-run LLM merge is uncommon; other platforms typically rely on external vector DB or manual memory patterns, hence limited
12. n8n's official docs cover HTTP Webhook and HTTP Request nodes plus Code/custom/community extensibility, but I couldn't find a first-party WebSocket trigger/send node, so n8n is marked limited
13. Zapier's official docs cover inbound webhooks and outbound webhook/API requests over HTTP only, not native WebSocket trigger or send steps
14. Make's official docs cover Webhooks modules and HTTP(S) request modules, but I couldn't find a native WebSocket trigger or send module
15. As of April 22, 2026, n8n's official docs document HTTP batching and loop/wait patterns rather than a native LLM batch-status branch, Zapier's official ChatGPT app docs list no triggers and only a generic API Request beta, and Make's official OpenAI integration page exposes batch actions like create/watch completed but not a first-class status-branching LLM node, so n8n/Make are marked partial and Zapier is marked unavailable for this specific pattern
16. n8n has no native LLM token cost tracking; community workaround workflows exist (e.g. "Token Estim8r") but require manual installation and post-execution API calls — an open feature request exists as of May 2026. Zapier exposes no per-execution token count or USD cost to users; AI steps consume tasks only, with no model pricing table. Make switched to a credits model in August 2025 that partially reflects token consumption for Make-hosted AI, but third-party connections using your own API key are billed as 1 operation = 1 credit with no token counting, and there is no per-execution USD breakdown by model
17. Heym emits native OpenTelemetry spans (one per workflow run plus one per node) over OTLP/HTTP to any compatible backend, with W3C trace-context propagation and no instrumentation code, configured via `HEYM_OTEL_*` env vars and disabled by default. n8n has a documented OpenTelemetry tracing setup for workflow and node executions (blog.n8n.io). Zapier and Make.com do not document OpenTelemetry export of their workflow/scenario executions as of June 2026
18. Heym Workflow Analyzer runs the workflow when possible, reads the execution result, and generates a shared editable Markdown report covering improvement areas, purpose, and step-by-step behavior. n8n AI Workflow Builder can create/refine/debug workflows, Zapier AI troubleshooting explains errored runs, and Make scenario history/agent reasoning exposes run details, but their public docs do not describe the same shared run-aware workflow analysis document
19. n8n Insights, Zapier Zap History/Task Usage, and Make Scenario History are monitoring/history surfaces. They do not document custom dashboard widgets backed by arbitrary workflow logic like Heym's Dashboard tab, where each widget can fetch, transform, retrieve, or generate data through its own hidden workflow

</details>

---

## 🚀 Quick Start

```bash
git clone https://github.com/heymrun/heym.git
cd heym
./run.sh

# OR — with .env file (run.sh auto-generates SECRET_KEY and ENCRYPTION_KEY)
git clone https://github.com/heymrun/heym.git
cd heym
cp .env.example .env
./run.sh

# OR — Docker with .env file
git clone https://github.com/heymrun/heym.git
cd heym
cp .env.example .env
# Generate required keys and write them into the placeholder lines copied from
# .env.example (replace in place — appending with >> would create duplicate entries):
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|; s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${ENCRYPTION_KEY}|" .env && rm -f .env.bak
docker run --env-file .env \
  -p 4017:4017 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(pwd)/data/files:/app/data/files" \
  ghcr.io/heymrun/heym:latest

# OR — minimal, no .env file
docker run \
  -e ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  -e SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@host.docker.internal:6543/heym \
  -p 4017:4017 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(pwd)/data/files:/app/data/files" \
  ghcr.io/heymrun/heym:latest
```

Open the editor in your browser at port `4017` in either setup.
For direct `docker run` setups, the `data/files` mount keeps Drive uploads and skill-generated files available across container restarts.
The Docker socket mount supports Docker-based MCP stdio tools and grants broad host control. Docker log access remains disabled unless you also set `DOCKER_LOGS_ENABLED=true` and `DOCKER_LOGS_ALLOWED_EMAILS=admin@example.com` for trusted users. Create the trusted admin account before enabling Docker logs, or keep `ALLOW_REGISTER=false`, so an unverified self-registration cannot claim an allow-listed email.

## Deploy & Call Workflows

Heym workflows are not limited to the editor. Run them from the canvas, call them through `/execute`, stream progress through `/execute/stream`, expose them as MCP tools at `/api/mcp/sse`, or publish them as Portal chat apps at `/chat/{slug}`. The same workflow can serve people, backend services, and AI clients without rebuilding the automation.

## Production Readiness

Heym is built to be inspected and operated in your own infrastructure. Docker deployment, JWT auth, team controls, shared credentials, `SECURITY.md`, execution history, logs, LLM traces, OpenTelemetry export, evals, and per-model USD cost tracking all live in the core self-hostable product.

<details>
<summary><b>🐳 Docker Production Deployment</b></summary>

```bash
cp .env.example .env
./deploy.sh              # Build and deploy (auto-generates keys if empty)
./deploy.sh --down       # Stop services
./deploy.sh --logs       # View logs
./deploy.sh --restart    # Restart services
```

> Set `ALLOW_REGISTER=false` in `.env` to lock down registration in production.

</details>

---

## 🗺️ Platform Overview

<table>
  <thead>
    <tr>
      <th align="center" colspan="3">🧠 Heym Platform</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td valign="top" width="33%">
        <b>⚡ Workflow Editor</b><br/><br/>
        Vue Flow canvas<br/>
        Drag-and-drop nodes<br/>
        AI Assistant (chat-to-workflow)<br/>
        Voice input<br/>
        Expression DSL<br/>
        Edit history · Download · Share
      </td>
      <td valign="top" width="33%">
        <b>🤖 AI Engine</b><br/><br/>
        LLM Node + Batch API mode<br/>
        AI Agent Node (tool calling)<br/>
        Persistent memory graph (agents)<br/>
        Multi-agent orchestration<br/>
        RAG / Vector store (Qdrant or pgvector)<br/>
        MCP Client & Server<br/>
        Skills system
      </td>
      <td valign="top" width="34%">
        <b>🌐 Integrations</b><br/><br/>
        HTTP · Slack · Send Email<br/>
        Redis · RabbitMQ<br/>
        Crawler (FlareSolverr)<br/>
        Playwright browser automation<br/>
        Grist spreadsheets<br/>
        Drive file management<br/>
        Cron · Webhooks
      </td>
    </tr>
    <tr>
      <td valign="top">
        <b>🔍 Observability</b><br/><br/>
        LLM Traces (requests, tool calls)<br/>
        LLM Cost Tracking (tokens + USD)<br/>
        Evals (AI test suites)<br/>
        Execution History<br/>
        Analytics · Logs
      </td>
      <td valign="top">
        <b>👥 Teams & Auth</b><br/><br/>
        JWT Auth<br/>
        Team management<br/>
        Credentials store & sharing<br/>
        Global variables<br/>
        Folder organization
      </td>
      <td valign="top">
        <b>💬 Portal</b><br/><br/>
        Publish workflows as chat UIs<br/>
        Public URL: <code>/chat/{slug}</code><br/>
        Optional authentication<br/>
        File upload support<br/>
        Streaming responses
      </td>
    </tr>
  </tbody>
</table>

<div align="center">

![Heym Banner](./docs/screenshots/heym-banner-standalone.webp)

</div>

---

## 🧩 Node Library

**A broad node library** across workflow categories:

| Category | Nodes |
|----------|-------|
| **Triggers** | Input (Webhook), Cron, RabbitMQ Receive, Error Handler |
| **AI** | LLM, AI Agent, Qdrant RAG |
| **Logic** | Condition, Switch, Loop, Merge |
| **Data** | Set, Variable, DataTable, Execute (sub-workflow) |
| **Integrations** | HTTP, Slack, Send Email, Redis, RabbitMQ Send, Grist, Drive.. |
| **Automation** | Crawler, Playwright |
| **Utilities** | Wait, Output, Console Log, Throw Error, Disable Node, Sticky Note |

---

## Extending Heym

Extend Heym at the layer that matches the job. Add first-class canvas behavior with custom nodes, give agents portable capabilities with skills, connect outside tools through MCP, or expose a finished workflow as a callable tool for other apps and AI clients.

| Extension path | Best for | How it works |
|----------------|----------|--------------|
| Custom nodes | Product-grade workflow steps and integrations | Add a typed node with editor configuration, execution behavior, and schema metadata. |
| Agent skills | Portable agent abilities | Attach a `SKILL.md` file and optional Python tools to Agent nodes, or generate them with AI Build. |
| MCP | External tools and AI clients | Agent nodes consume MCP servers, and Heym workflows can be exposed as MCP tools. |
| Workflow as tool | Reusable automations | Call workflows through REST, SSE, Portal chat, or MCP without duplicating the logic. |

---

## 🧠 AI-Native Features

### AI Assistant
Describe what you want in plain text or via voice — the assistant generates nodes and edges and applies them to the canvas instantly. No other automation platform ships a natural-language workflow builder that works directly inside the editor.

When a workflow already contains Agent skills, the assistant sends only each skill's `SKILL.md` into the builder context. Large `.py` files and binary attachments stay out of the prompt so workflow editing remains reliable even with complex skills loaded on the canvas.

<div align="center">

<img src="./docs/readme-assets/ai-assistant.svg" width="100%" alt="AI assistant builds a workflow animation"/>

</div>

### AI Skill Builder
Inside the Agent node's Skills section, use **AI Build** to create a new skill or the inline sparkle action to revise an existing one. The modal streams a chat conversation, previews generated `SKILL.md` and `.py` files live, and saves them back through the same ZIP ingestion path used by manual skill uploads.

### Multi-Agent Orchestration
Build orchestrator/sub-agent pipelines visually. One agent delegates tasks to named sub-agents or sub-workflows — composing complex behavior without custom orchestration code. Configure reasoning effort and temperature per agent for fine-grained control.

<div align="center">

<img src="./docs/readme-assets/multi-agent.svg" width="100%" alt="Multi-agent orchestration animation"/>

</div>

### Human-in-the-Loop (HITL)
Pause agent execution at any point to request user approval, clarification, or input before proceeding. Build workflows where AI proposes and humans decide — combining automation speed with human judgment.

n8n, Zapier, and Make now offer native review or approval flows too. Heym's edge is agent-directed checkpoints with public review URLs, edit-and-continue, and full execution-state resume.

### Guardrails
Apply content filtering, NSFW protection, and multilingual safety checks on LLM and Agent node outputs. Define rules in the node configuration — unsafe responses are caught before reaching downstream nodes.

n8n and Zapier now ship native AI safety tooling as well. Heym's edge is that guardrails live directly on the LLM and Agent nodes, support multilingual policy checks, and flow naturally into the workflow's existing error-handling paths.

### MCP (Model Context Protocol)
**As a client:** Agent nodes connect to any external MCP server and gain all its tools automatically.
**As a server:** Your Heym workflows are exposed as an MCP server at `/api/mcp/sse` — callable from Claude Desktop, Cursor, or any MCP client.

### Skills System
Skills are portable capability bundles — a `SKILL.md` instruction file plus optional Python tools. Drop a `.zip` or `.md` onto an Agent node, or use **AI Build** to draft and iterate on skills from chat. Reuse and share across workflows and teams.

### Built-In RAG Pipeline
Upload PDFs, Markdown, CSV, or JSON to a managed vector store. Then wire a RAG node into any workflow for semantic search — results flow directly into your LLM or Agent node.

```
Input → RAG (search) → LLM (answer with context) → Output
```

### Auto Heal
Playwright browser automation nodes detect broken selectors at runtime and use AI to automatically find the correct replacement — no manual maintenance when the target page changes.

### Parallel Execution
Independent nodes run concurrently based on the graph structure. Use the **Merge** node to synchronize parallel branches. No configuration needed — the graph defines the execution order.

---

## 🔍 Observability

### LLM Traces
Full visibility into every agent call: request and response payloads, tool call names and results, per-call timing, and skills passed to the model.

### LLM Cost Tracking
Every trace records input and output token counts alongside a real-time USD cost calculated from a synced pricing table that covers all major models (OpenAI, Anthropic, Google, and more). A time-range filtered cost analytics view lets you see spending trends across workflows — no third-party cost dashboard needed.

### Evals
Define test cases with expected outputs. Run the entire suite with one click. Review pass/fail, actual vs expected, and historical run data. Ship AI workflows with confidence.

### OpenTelemetry Tracing
Export a root span per workflow run plus a child span per node over OTLP/HTTP to Jaeger, Grafana Tempo, Honeycomb, Datadog, or any OpenTelemetry backend. Spans carry workflow id, node type, status, duration, and LLM token usage, with W3C trace context propagated across inbound webhooks, outbound HTTP, and sub-workflows. Disabled by default; turn it on with the `HEYM_OTEL_*` environment variables and review status under **Settings → Observability**. See the in-app docs (Reference > OpenTelemetry Tracing) for details.

---

## 💬 Portal
Turn any workflow into a public chat interface at `/chat/{slug}`. Optional per-user authentication, streaming responses, file uploads, and multi-turn conversation history. Ship internal tools and customer-facing chatbots — no frontend code required.

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
upper($input.text)                  // String helpers
```

Expressions work in every field — prompts, HTTP headers, conditions, email bodies, Redis keys, and more. 

---

## 🔐 Node-Level Error Handling

Every node supports **retry on failure** and **error branching**:

```
Input ──→ HTTP ──→ Output
               └─── error ──→ Error Handler
```

- **Retry** — automatically re-run a failed node with configurable attempts and backoff
- **Error branch** — route failures to a dedicated path instead of stopping the workflow
- **Error context** — access `$nodeName.error` in downstream nodes

---

## 🏗️ Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Vue.js 3 + TypeScript (strict) + Vite + Bun |
| **UI Components** | Shadcn Vue + Tailwind CSS |
| **Canvas** | Vue Flow |
| **State Management** | Pinia |
| **Backend** | Python 3.11+ + FastAPI + UV |
| **Database** | PG 16 + SQLAlchemy 2.0 (async) |
| **Auth** | JWT (access + refresh) + bcrypt |

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
├── backend/app/
│   ├── api/            # Routes: workflows, auth, mcp, portal, evals, traces…
│   ├── models/         # Pydantic schemas + SQLAlchemy models
│   ├── services/       # Executor, LLM, RAG, agent engine
│   └── db/             # Database configuration
├── alembic/            # Database migrations
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
| `SECRET_KEY` | JWT signing key | — |
| `BACKEND_PORT` | Backend server port | `10105` |
| `FRONTEND_PORT` | Frontend server port | `4017` |
| `ALLOW_REGISTER` | Enable user registration | `true` |
| `REQUEST_BODY_MAX_SIZE_MB` | Maximum backend HTTP request body size; defaults to `100`, one MB above `FILE_MAX_SIZE_MB` to allow multipart overhead | `100` |
| `HEYM_OTEL_ENABLED` | Enable OpenTelemetry tracing for workflow and node executions | `false` |
| `HEYM_OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP/HTTP base endpoint, e.g. `http://collector:4318` (spans posted to `/v1/traces`) | — |
| `HEYM_OTEL_EXPORTER_OTLP_HEADERS` | Comma-separated `key=value` exporter headers for auth | — |
| `HEYM_OTEL_SERVICE_NAME` | `service.name` resource attribute | `heym` |
| `HEYM_OTEL_TRACES_SAMPLER_RATIO` | Parent-based head sampling ratio (`0.0`–`1.0`) | `1.0` |
| `HEYM_OTEL_CAPTURE_NODE_IO` | Attach truncated node input/output to node spans | `false` |

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

**Validation (lint + typecheck + tests):**
```bash
./check.sh    # Run all checks — required before pushing
```

Or run individually:
```bash
cd frontend && bun run lint && bun run typecheck
cd backend  && uv run ruff check . && uv run ruff format .
```

---

## 📄 License

This project is licensed under the **[MIT License](LICENSE)** with the **[Commons Clause](COMMONS-CLAUSE.md)** condition applied. In other words, Heym is **source-available** rather than OSI-open-source. See both files for details.

**TL;DR:** You are free to use, modify, distribute, and self-host this software — but you may **not sell** it or offer it as a paid service. Commercial licensing is available for teams that need those rights.

---

## Watch Heym Tutorials

<div align="center">

<a href="https://www.youtube.com/playlist?list=PLPXd_ZbA4wgEHP5PXoaRqbsDJdat7OSd4">
  <img src="./docs/readme-assets/tutorial-videos-playlist.png" width="100%" alt="Watch Heym tutorial videos on YouTube"/>
</a>

</div>

---

## 💬 Community

Join our Discord to connect with the community, ask questions, share workflows, and stay up to date:

[![Discord](https://img.shields.io/badge/Discord-Join%20us-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/T2wXvuVdMX )

---

## 🧩 Share a Template

Want to publish a workflow template for the community? You can now submit it directly from the **[Templates page](https://heym.run/submit)** — open the dialog, paste your workflow DSL, and send it for review. No pull request needed.

If you'd rather contribute through code, please **[start a Discussion](https://github.com/heymrun/heym/discussions)** so we can talk it through together **before** opening a pull request.

---

## 🏢 Enterprise

Commercial licensing, enterprise deployment help, and professional support are available.

**What we offer:**
- Workflow automation infrastructure & deployment
- Custom feature development on Heym
- Debugging, troubleshooting & solution support
- Priority support & SLA guarantees

📧 **Contact:** [enterprise@heym.run](mailto:enterprise@heym.run)

---

<div align="center">

**Built with ❤️ using Vue.js, FastAPI, and a lot of LLM tokens.**

[⭐ Star this repo](https://github.com/heymrun/heym/stargazers) · [🐛 Report a bug](https://github.com/heymrun/heym/issues) · [💡 Request a feature](https://github.com/heymrun/heym/discussions)

## ⭐ Star History

<a href="https://www.star-history.com/#heymrun/heym&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=heymrun/heym&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=heymrun/heym&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=heymrun/heym&type=Date" />
  </picture>
</a>

## Contributors

<a href="https://github.com/heymrun/heym/graphs/contributors">
  <img alt="Heym contributors" src="https://contrib.rocks/image?repo=heymrun/heym&amp;v=0.0.55" />
</a>

</div>
