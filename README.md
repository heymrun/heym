<div align="center">

<br/>

<img src="./docs/readme-assets/logo.svg" width="80" height="80" alt="Heym Logo"/>

# Heym

### AI-Native Workflow Automation Platform

<p align="center">
  <strong>Build, visualize, and run intelligent AI workflows without writing code.</strong><br/>
  Drag-and-drop canvas · LLM & Agent nodes · RAG pipelines · Multi-agent orchestration · MCP support · OIDC SSO
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
[![MCP Toplist](https://mcptoplist.com/badge/glama%2Fheymrun%2Fheym.svg)](https://mcptoplist.com/server/glama%2Fheymrun%2Fheym)

<br/>

<img src="./docs/readme-assets/hero.svg" width="100%" alt="Heym animated AI-native workflow automation hero"/>

<br/>

</div>

---

## What Is Heym?

Heym is an **AI-native automation platform** built from the ground up around LLMs, agents, and intelligent tooling. Wire together AI agents, vector stores, web scrapers, HTTP calls, and message queues on a visual canvas — then deploy instantly via Docker.

Unlike platforms that started as classic trigger-action automation and layered AI on later, in Heym **AI is the execution model**.

Explore the product site at **[heym.run](https://heym.run)**.

## 🎬 Product Tour

One e-commerce sales campaign, followed end to end: workflow generation with the AI Assistant, human review, board execution, structured data, dashboards, traces, RAG, MCP, analytics, and team collaboration.

<div align="center">

<a href="https://www.youtube.com/watch?v=CWUy2zynCqc">
  <img src="https://img.youtube.com/vi/CWUy2zynCqc/maxresdefault.jpg" width="100%" alt="Watch the Heym product tour on YouTube"/>
</a>

</div>

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
      <img src="docs/screenshots/canvas.png" alt="Visual workflow canvas" width="100%"/>
      <br/><sub><b>Visual Canvas</b> — Multi-agent orchestration, RAG and MCP nodes, human-in-the-loop checkpoints</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/mcp.png" alt="MCP server settings" width="100%"/>
      <br/><sub><b>MCP Server</b> — Expose any workflow as a tool for Claude, ChatGPT, or Cursor</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/traces.png" alt="LLM traces" width="100%"/>
      <br/><sub><b>Traces</b> — Every LLM call with request, response, tokens, latency, and cost</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/analytics.png" alt="Analytics dashboard" width="100%"/>
      <br/><sub><b>Analytics</b> — Execution volume, success rate, latency, and time saved per workflow</sub>
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
- **OIDC SSO Login**: Let teams sign in through Keycloak, Okta, Entra ID, Auth0, Google, or any OpenID Connect provider
- **Load Distribution** — Run two or more Heym instances against one database and split background workflow execution between them by percentage, configured from **Settings → Instances**. Postgres is the only channel between the instances; no broker, and no direct connection between them, is required
- **Portal** — Turn any workflow into a public chat UI at `/chat/{slug}` with streaming responses and file uploads
- **Webhook SSE Streaming** — Generate ready-to-run cURL commands for `/execute` or `/execute/stream`, with per-node start messages and live node event output in the terminal
- **Live Execution Canvas** — Open any running production execution from History or a Kanban card and watch the existing run continue node by node on the animated canvas with incremental Debug logs
- **Data Tables** — Manage structured data directly in the dashboard and reference it from workflows
- **Workflow Analyzer** — Run-aware AI feedback that generates a shared Markdown report with improvement areas, purpose, and step-by-step behavior
- **Workflow-Powered Dashboards** — Build custom chart dashboards where every widget is backed by its own hidden Heym workflow
- **Agentic Kanban Board** — Cards are persistent agentic jobs; moving a card into a column runs that column's ordered workflow chain with the card's full context (content, comments, history, previous outputs), and results are written back to the card
- **Templates** — Start from pre-built workflow templates to get up and running quickly
- **Parallel Execution** — Independent nodes run concurrently based on the graph structure, no configuration needed
- **Auto Heal** — Playwright selectors break? AI automatically detects and fixes them at runtime
- **LLM Fallback** — Automatic model fallback when the primary LLM fails or is unavailable
- **Reasoning Support** — Configure reasoning effort and temperature per Agent node for fine-grained control
- **Command Palette** — Ctrl+K for instant search, navigation, and workflow actions
- **Evals** — Define test suites and run them against any workflow with one click
- **LLM Traces** — Full observability for every agent call: requests, responses, tool calls, and timing
- **Alerts** — Threshold rules over a time window on error count, run duration, LLM spend, and execution count, built in an AI-fillable wizard that backtests the condition before you save it and can run any workflow when it fires
- **LLM Cost Tracking** — Per-trace token counts (input / output) with real-time USD cost calculation, historical analytics with time-range filtering, and a synced pricing table covering all major models
- **Self-Hosted** — Your data, your infrastructure

---

## Full Feature Set

For a complete list of all features with short descriptions, see **[Full Feature Set](frontend/src/docs/content/reference/features.md)**. It covers Getting Started, every node type, reference topics (Expression DSL, workflow structure, webhooks, SSE streaming, AI Assistant, Chat with Docs, Portal, security, etc.), and all dashboard tabs (Workflows, Templates, Variables, Chat, Credentials, Vectorstores, MCP, Traces, Alerts, Analytics, Evals, Teams, Logs and more).

<div align="center">

<img src="./docs/readme-assets/full-feature-showcase.svg" width="100%" alt="Animated Heym full feature set showcase"/>

</div>

---

## ⭐ Stay Up To Date

<div align="center">

![Workflow Creation Demo](./docs/screenshots/heym-star.gif)

</div>

Heym is built for developers who want control and enterprise teams that need a trusted path to production. Star Heym ⭐ on GitHub to follow releases and help more builders discover it.

---

## 🎯 Why Heym?

| Capability | **Heym** | n8n | Zapier | Make.com |
|---|:---:|:---:|:---:|:---:|
| Built-in LLM node | ✅ | ✅ | ✅ | ✅ |
| LLM Batch API + status branches | ✅ | partial¹⁵ | ❌¹⁵ | partial¹⁵ |
| AI Agent node (tool calling) | ✅ | ✅ | ✅ | ✅ |
| Agent persistent memory (knowledge graph) | ✅ | limited¹¹ | limited¹¹ | limited¹¹ |
| Multi-agent orchestration | ✅ | ✅ | limited | limited |
| Coding agent nodes (Codex, OpenCode) | ✅ | ❌²¹ | ❌²¹ | ❌²¹ |
| Human-in-the-Loop (HITL) | ✅ | ✅⁵ | limited⁶ | limited⁷ |
| LLM Guardrails | ✅ | ✅⁸ | ✅⁸ | limited⁸ |
| Automatic context compression | ✅ | ❌ | ❌ | ❌ |
| Built-in RAG / vector store | ✅ | ✅ | limited¹ | plugin² |
| WebSocket read / write | ✅ | limited¹² | ❌¹³ | ❌¹⁴ |
| Natural language workflow builder | ✅ | limited³ | ✅ | ✅ |
| Workflow Analyzer | ✅ | ❌¹⁸ | ❌¹⁸ | ❌¹⁸ |
| Open an in-flight run on the live canvas | ✅ | limited²⁰ | limited²⁰ | ❌²⁰ |
| Workflow-powered dashboards | ✅ | partial¹⁹ | partial¹⁹ | partial¹⁹ |
| Agentic Kanban board | ✅ | ❌²² | ❌²² | ❌²² |
| MCP (Model Context Protocol) | ✅ | ✅ | ✅ | ✅ |
| Skills system for agents | ✅ | ❌ | ❌ | ❌ |
| Built-in file drive (share links, teams) | ✅ | limited²³ | limited²³ | ❌²³ |
| Browser automation node (Playwright) | ✅ | limited²⁴ | limited²⁴ | ❌²⁴ |
| Auto Heal (Playwright) | ✅ | ❌ | ❌ | ❌ |
| Data Tables | ✅ | ✅ | ✅ | ❌ |
| Workflow Templates | ✅ | ✅ | ✅ | ✅ |
| LLM trace inspection | ✅ | limited⁴ | ❌ | ✅ |
| OpenTelemetry tracing export | ✅ | ✅¹⁷ | ❌¹⁷ | ❌¹⁷ |
| LLM token cost tracking (USD) | ✅ | ❌¹⁶ | ❌¹⁶ | limited¹⁶ |
| Metric alerts (errors, duration, cost, run count) | ✅ | limited²⁵ | limited²⁵ | limited²⁵ |
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
17. Heym emits native OpenTelemetry spans (one per workflow run, one per node, plus Agent tool spans) over OTLP/HTTP to any compatible backend, with W3C trace-context propagation and no instrumentation code, configured via `HEYM_OTEL_*` env vars and disabled by default. n8n has a documented OpenTelemetry tracing setup for workflow and node executions (blog.n8n.io). Zapier and Make.com do not document OpenTelemetry export of their workflow/scenario executions as of June 2026
18. Heym Workflow Analyzer runs the workflow when possible, reads the execution result, and generates a shared editable Markdown report covering improvement areas, purpose, and step-by-step behavior. n8n AI Workflow Builder can create/refine/debug workflows, Zapier AI troubleshooting explains errored runs, and Make scenario history/agent reasoning exposes run details, but their public docs do not describe the same shared run-aware workflow analysis document
19. n8n Insights, Zapier Zap History/Task Usage, and Make Scenario History are monitoring/history surfaces. They do not document custom dashboard widgets backed by arbitrary workflow logic like Heym's Dashboard tab, where each widget can fetch, transform, retrieve, or generate data through its own hidden workflow
20. [n8n All executions](https://docs.n8n.io/workflows/executions/all-executions/) lists running executions and can load previous execution data into the editor, while [Zapier run statuses](https://help.zapier.com/hc/en-us/articles/20505304170637-Review-run-statuses-in-Zap-workflows) exposes a running editor state. [Make Scenario History](https://help.make.com/scenario-history) documents run details and logs. Their public docs, checked July 18, 2026, do not describe Heym's exact combination: open an arbitrary in-flight production run from History or a Kanban card, restore its current snapshot, and keep receiving node animation and Debug logs on the same canvas.
21. Heym's Codex and OpenCode Go nodes run a real coding agent CLI in an isolated workspace against a GitHub repository — clone, edit, diff, push a branch, open a pull request — as a first-class workflow step. As of July 20, 2026, no competitor documents an equivalent: n8n's OpenAI node covers chat/assistant API calls and native Codex support remains a community request, Zapier's own blog documents the reverse direction ([Codex driving Zapier tools through Zapier MCP](https://zapier.com/blog/automate-codex-zapier-mcp/)), and Make's OpenAI modules expose completions/assistants/batch actions only
22. Heym's Board tab is a built-in agentic Kanban board whose columns execute workflows and whose cards carry context, conversation history, execution state, and runs. n8n, Zapier, and Make only integrate with third-party kanban apps (Kanban Tool, Wekan, NocoDB); none documents a built-in board that runs its own automations, as of July 20, 2026
23. Heym's Drive tab stores workflow/skill-generated files with public or password-protected share links, team sharing, and bulk ZIP/share/delete actions. n8n keeps execution binary data internally (optionally on [S3-compatible external storage](https://docs.n8n.io/hosting/scaling/external-storage/)) with no user-facing file drive; Zapier's Files by Zapier holds files only for the duration of a Zap run and Storage by Zapier holds small text values; Make's data stores hold structured records and its file handling passes files between apps without persistent built-in storage
24. Heym's Playwright node is first-party browser automation with visual steps, AI-generated steps, and a full-code mode. n8n offers only community packages with a still-open [feature request for native browser automation nodes](https://community.n8n.io/t/front-end-web-mobile-app-test-automation-nodes/129796); Zapier Agents can browse and read pages but Zapier documents no scripted browser-automation step; Make documents HTTP modules and third-party scraping apps rather than a native browser module, as of July 20, 2026

25. Heym Alerts are user-defined thresholds evaluated over a time window across four metrics — error count, run duration (max/avg/p95), LLM token or USD spend, and execution count — built in a wizard that backtests the condition before saving and can run a workflow when it fires. The competitors notify per failed run rather than on a windowed threshold, and none documents user-set duration or cost alerts. [n8n Insights](https://docs.n8n.io/insights/) displays failure rate and run time average (dashboard on Pro and above) but sets no thresholds and sends no alerts; n8n's alerting path is the per-execution [error workflow](https://docs.n8n.io/flow-logic/error-handling/). [Zapier](https://help.zapier.com/hc/en-us/articles/8496289225229-Manage-notifications-when-errors-occur-in-Zap-workflows) sends configurable per-error notifications and applies one Zapier-set rule (a Zap erroring 95% of the time across 20+ runs in 7 days), which the user cannot define or extend to other metrics. [Make](https://help.make.com/introduction-to-errors-and-warnings) reports scenario errors and warnings, and a per-scenario operations threshold remains an open community request. Checked August 9, 2026

</details>

### Open any production run live

Runs started by webhooks, schedules, chat, MCP, integrations, or the Agentic Kanban Board do
not become black boxes. Open a **Running** entry from either History dialog—or from the run list
inside a Board card—and Heym attaches the editor to that exact execution over SSE. Completed
nodes are restored immediately; the current and pending nodes keep pulsing; Debug logs and the
final output arrive incrementally. Leaving the editor disconnects only the observer and never
cancels the production run.

---

## 🚀 Quick Start

Prefer to watch it first? **[Set Up Heym Locally in Under 2 Minutes](https://www.youtube.com/watch?v=P6YvlupUboU)** walks the whole path: clone the repository, start PostgreSQL and create your account on a local instance.

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
  --shm-size 2g \
  -e FILE_STORAGE_DIR=/app/data/files \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(pwd)/data/files:/app/data/files" \
  -v heym-codex-workspaces:/app/data/codex-workspaces \
  -v heym-opencode-workspaces:/app/data/opencode-workspaces \
  ghcr.io/heymrun/heym:latest

# OR — minimal, no .env file
docker run \
  -e ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  -e SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@host.docker.internal:6543/heym \
  -e FILE_STORAGE_DIR=/app/data/files \
  -p 4017:4017 \
  --shm-size 2g \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(pwd)/data/files:/app/data/files" \
  -v heym-codex-workspaces:/app/data/codex-workspaces \
  -v heym-opencode-workspaces:/app/data/opencode-workspaces \
  ghcr.io/heymrun/heym:latest
```

Open the editor on port `4017`. See [ENVIRONMENT-VARIABLES.md](ENVIRONMENT-VARIABLES.md) for every setting and its default.

Three things about the `docker run` setup are worth knowing:

- **`--shm-size 2g` keeps Playwright working.** Docker gives a container 64 MB of `/dev/shm` by default, and Chromium crashes its renderer under that. Step-based Playwright nodes run Chromium as a subprocess inside this container, so the limit is this container's. (Custom `playwrightCode` runs in a sibling container that sets its own.) `docker-compose.yml` already sets it; a plain `docker run` does not.
- **`FILE_STORAGE_DIR=/app/data/files` is load-bearing.** The release image runs the backend from `/app/backend`, so the default relative path would land inside the container instead of your mount and Drive uploads would vanish on restart. `./run.sh` and `./deploy.sh` are unaffected.
- **Keep `heym-codex-workspaces` mounted.** Python skills and the Codex node run there in a hardened sibling container; without it, skill execution fails closed. Per-run isolation needs Docker Engine 25.0+.
- **Keep `heym-opencode-workspaces` mounted** if you use the OpenCode Go node. The sibling runner shares that volume; without it the wrapper fails closed.
- **The Docker socket grants broad host control.** MCP `stdio` servers need it, because the caller-supplied command runs in a throwaway container rather than on the host. Docker log access stays off unless you set `DOCKER_LOGS_ENABLED=true` and `DOCKER_LOGS_ALLOWED_EMAILS`. Create that admin account first, or keep `ALLOW_REGISTER=false`, so nobody can self-register into an allow-listed email.

## Deploy & Call Workflows

Heym workflows are not limited to the editor. Run them from the canvas, call them through `/execute`, stream progress through `/execute/stream`, expose them as MCP tools at `/api/mcp/sse`, or publish them as Portal chat apps at `/chat/{slug}`. The same workflow can serve people, backend services, and AI clients without rebuilding the automation.

## Production Readiness

Heym is built to be inspected and operated in your own infrastructure. Docker deployment, JWT auth, team controls, shared credentials, `SECURITY.md`, execution history, logs, LLM traces, OpenTelemetry export, evals, and per-model USD cost tracking all live in the core self-hostable product.

When one machine is not enough, a second instance pointed at the same database joins as a worker and takes a configurable share of background runs — see [Load Distribution](frontend/src/docs/content/reference/cluster.md) for the roles, the environment variables, and the two deployment rules the cluster cannot enforce for you.

Every pull request runs the [PR checks](https://github.com/heymrun/heym/actions/workflows/pr-checks.yml) workflow: a file line-limit check, frontend ESLint, TypeScript strict typecheck, frontend Vitest unit tests, production build, backend Ruff format and lint, the backend unit test suite, and Playwright E2E tests against a live Postgres service.

<details>
<summary><b>🐳 Docker Production Deployment</b></summary>

```bash
cp .env.example .env
./deploy.sh              # Build and deploy (auto-generates keys if empty)
./deploy.sh --down       # Stop services
./deploy.sh --logs       # View logs
./deploy.sh --restart    # Restart services
```

> Register your admin account first, then set `ALLOW_REGISTER=false` in `.env` and restart to lock down registration in production. There is no first-user bootstrap, so disabling registration against an empty database leaves no way to create an account.

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

### Alerts
Set thresholds over a **time window** on four metrics: error count, run duration (max, average, or p95), LLM token or USD spend, and execution count. Every alert is judged over a window you choose rather than on a single event, because one failed run is noise and a burst is an incident. Scope an alert to one workflow or to everything you can access.

A five-step wizard covers type, scope, condition, response, and review, and the review step **backtests** the condition before you save it: *over the last 24 hours this would have fired 3 times, peaking at 14 errors*. Describe what you want in plain English and AI fills the whole form for you. By default an alert fires once and stays quiet until the metric recovers, so a broken workflow checked every minute does not produce 60 notifications an hour. An alert can run any workflow when it fires, receiving the observed value, threshold, window, and contributing detail as input, which is how alerts reach Slack, email, or Telegram with nodes you already have. The Chat tab can tell you what alerts exist and why one triggered.

### Evals
Define test cases with expected outputs. Run the entire suite with one click. Review pass/fail, actual vs expected, and historical run data. Ship AI workflows with confidence.

### OpenTelemetry Tracing
Export a root span per workflow run, a child span per node, and Agent tool spans (`heym.agent.tool.execute`) over OTLP/HTTP to Jaeger, Grafana Tempo, Honeycomb, Datadog, or any OpenTelemetry backend. Spans carry workflow id, node type, status, duration, LLM token usage, and tool identity/status, with W3C trace context propagated across inbound webhooks, outbound HTTP, and sub-workflows. Disabled by default; turn it on with the `HEYM_OTEL_*` environment variables and review status under **Settings → Observability**. See the in-app docs (Reference > OpenTelemetry Tracing) for details.

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
| `ENCRYPTION_KEY` | Encrypts stored credentials at rest. Required at startup; generate with `python -c "import secrets; print(secrets.token_hex(32))"` | — |
| `BACKEND_PORT` | Backend server port | `10105` |
| `FRONTEND_PORT` | Frontend server port | `4017` |
| `ALLOW_REGISTER` | Enable user registration | `true` |
| `REQUEST_BODY_MAX_SIZE_MB` | Maximum backend HTTP request body size; defaults to `100`, one MB above `FILE_MAX_SIZE_MB` to allow multipart overhead | `100` |
| `HEYM_OTEL_ENABLED` | Enable OpenTelemetry tracing for workflow, node, and Agent tool executions | `false` |
| `HEYM_OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP/HTTP base endpoint, e.g. `http://collector:4318` (spans posted to `/v1/traces`) | — |
| `HEYM_OTEL_EXPORTER_OTLP_HEADERS` | Comma-separated `key=value` exporter headers for auth | — |
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

**Validation (lint + typecheck + tests):**
```bash
./check.sh    # Run all checks — required before pushing
```

Or run individually:
```bash
cd frontend && bun run lint && bun run typecheck && bun run test
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

## Contributors

<a href="https://github.com/heymrun/heym/graphs/contributors">
  <img alt="Heym contributors" src="https://contrib.rocks/image?repo=heymrun/heym&amp;v=0.0.100" />
</a>

</div>
