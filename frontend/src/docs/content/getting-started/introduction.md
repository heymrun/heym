# Introduction

Heym is an AI-native low-code automation platform with a visual workflow editor. Build powerful automations by connecting nodes on a canvas—no coding required for most use cases. Visit [heym.run](https://heym.run) for the product site, and see [Why Heym](./why-heym.md) for how Heym compares to n8n, Zapier, and Make.com.

## What You Can Do

- **Visual workflows** – Drag and drop [nodes](../reference/node-types.md) to create automation flows in the [Workflows](../tabs/workflows-tab.md) tab
- **AI-powered nodes** – [LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md), and [RAG](../nodes/rag-node.md) nodes for intelligent automation
- **AI Assistant** – Build workflows with natural language via the [AI Assistant](../reference/ai-assistant.md) panel in the editor
- **Chat with Docs** – Ask page-aware product questions from the [Chat with Docs](../reference/chat-with-docs.md) dialog in documentation
- **Integrations** – HTTP, Slack, email, and more via dedicated nodes
- **Scheduling** – Trigger workflows on a cron schedule
- **Chat portals** – Expose workflows as chat interfaces for end users; use the [Chat](../tabs/chat-tab.md) tab to test models directly

## Key Concepts

- **Workflows** – A directed graph of nodes and edges. Manage them in the [Workflows](../tabs/workflows-tab.md) tab. See [Workflow Structure](../reference/workflow-structure.md).
- **Nodes** – Processing units ([Input](../nodes/input-node.md), [LLM](../nodes/llm-node.md), [Condition](../nodes/condition-node.md), etc.). See [Node Types](../reference/node-types.md).
- **Edges** – Connections that define execution flow
- **Credentials** – API keys and secrets stored in the [Credentials](../tabs/credentials-tab.md) tab, referenced by nodes.
- **Variables** – Persistent key-value data in the [Variables](../tabs/global-variables-tab.md) tab, accessible via `$global.variableName`. See [Global Variables](../reference/global-variables.md).
- **Expressions** – Reference upstream data with `$input` and `$nodeName.field`. See [Expression DSL](../reference/expression-dsl.md).

## Related

- [Why Heym](./why-heym.md) – How Heym compares to n8n, Zapier, and Make.com
- [Quick Start](./quick-start.md) – Build your first workflow
- [Running & Deployment](./running-and-deployment.md) – Start locally with `run.sh` or deploy with `deploy.sh`
- [AI Assistant](../reference/ai-assistant.md) – Create workflows with natural language
- [Chat with Docs](../reference/chat-with-docs.md) – Ask follow-up questions while reading docs
- [Core Concepts](./core-concepts.md) – Workflows, nodes, and execution flow
- [Workflows Tab](../tabs/workflows-tab.md) – Manage workflows and folders
- [Credentials Tab](../tabs/credentials-tab.md) – Add API keys for nodes
