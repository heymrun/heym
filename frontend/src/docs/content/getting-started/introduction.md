# Introduction

**Build agentic systems. Run them with confidence.**

Heym is infrastructure for running and governing AI agents in production. Orchestrate agents, automate business processes, inspect every execution, and keep humans in control. Deploy Heym on your own infrastructure.

In Heym, a workflow defines how agents, deterministic steps, tools, and data work together. The runtime executes that graph, records every run, and pauses for human review where you ask it to. The visual canvas is where you build and inspect workflows, and the same workflows also run from APIs, schedules, event triggers, MCP clients, and Portal chats. Visit [heym.run](https://heym.run) for the product site, and see [Why Heym](./why-heym.md) for what Heym handles at each stage of the agent lifecycle.

## What You Can Do

- **Build** – Compose agents and deterministic steps on the [canvas](../reference/canvas-features.md) in the [Workflows](../tabs/workflows-tab.md) tab, describe them to the [AI Assistant](../reference/ai-assistant.md), or start from [Templates](../tabs/templates-tab.md)
- **Orchestrate** – Coordinate [Agent](../nodes/agent-node.md), [LLM](../nodes/llm-node.md), and [RAG](../nodes/rag-node.md) nodes, [sub-agents](../reference/agent-architecture.md), MCP tools, and [integrations](../reference/integrations.md) such as HTTP, Slack, and email, with [parallel execution](../reference/parallel-execution.md) where dependencies allow
- **Run** – Start workflows from [webhooks](../reference/webhooks.md), [Cron](../nodes/cron-node.md) schedules, and event [triggers](../reference/triggers.md), with per-node retries, [error handling](../nodes/error-handler-node.md), and [load distribution](../reference/cluster.md) across instances
- **Observe** – Inspect [execution history](../reference/execution-history.md), [LLM traces](../tabs/traces-tab.md) with token costs, [analytics](../tabs/analytics-tab.md), and [alerts](../tabs/alerts-tab.md), and export [OpenTelemetry](../reference/opentelemetry.md) traces
- **Evaluate** – Test prompts and models against expected outputs in the [Evals](../tabs/evals-tab.md) tab
- **Control** – Pause agents for [human review](../reference/human-in-the-loop.md), block unsafe content with [guardrails](../reference/guardrails.md), and manage access with [credentials](../tabs/credentials-tab.md), [teams](../reference/teams.md), [single sign-on](../reference/sso.md), and an [audit trail](../reference/audit.md)
- **Expose** – Serve workflows over REST and [SSE streaming](../reference/sse-streaming.md), as [MCP](../tabs/mcp-tab.md) tools, and as [Portal](../reference/portal.md) chat interfaces for end users; use the [Chat](../tabs/chat-tab.md) tab to test models directly
- **Chat with Heym** – Ask page-aware product questions from the [Chat with Heym](../reference/chat-with-heym.md) dialog in documentation

## Key Concepts

- **Workflows** – A directed graph of nodes and edges. Manage them in the [Workflows](../tabs/workflows-tab.md) tab. See [Workflow Structure](../reference/workflow-structure.md).
- **Nodes** – Processing units ([Input](../nodes/input-node.md), [LLM](../nodes/llm-node.md), [Condition](../nodes/condition-node.md), etc.). See [Node Types](../reference/node-types.md).
- **Edges** – Connections that define execution flow
- **Credentials** – API keys and secrets stored in the [Credentials](../tabs/credentials-tab.md) tab, referenced by nodes.
- **Variables** – Persistent key-value data in the [Variables](../tabs/global-variables-tab.md) tab, accessible via `$global.variableName`. See [Global Variables](../reference/global-variables.md).
- **Expressions** – Reference upstream data with `$input` and `$nodeName.field`. See [Expression DSL](../reference/expression-dsl.md).

## Related

- [Why Heym](./why-heym.md) – What Heym handles at each stage of the agent lifecycle
- [Quick Start](./quick-start.md) – Build your first workflow
- [Running & Deployment](./running-and-deployment.md) – Start locally with `run.sh` or deploy with `deploy.sh`
- [AI Assistant](../reference/ai-assistant.md) – Create workflows with natural language
- [Chat with Heym](../reference/chat-with-heym.md) – Ask follow-up questions while reading docs
- [Core Concepts](./core-concepts.md) – Workflows, nodes, and execution flow
- [Workflows Tab](../tabs/workflows-tab.md) – Manage workflows and folders
- [Credentials Tab](../tabs/credentials-tab.md) – Add API keys for nodes
