# Heym Full Feature Set

A comprehensive overview of all Heym capabilities. Each section describes a feature or concept in a few sentences. 

---

## Getting Started

### [Introduction](../getting-started/introduction.md)

Heym is an AI-native low-code automation platform with a visual workflow editor. You build automations by connecting nodes on a canvas—no coding required for most use cases. It supports visual workflows, AI-powered nodes ([LLM](../nodes/llm-node.md), [Agent Node](../nodes/agent-node.md), [Qdrant RAG](../nodes/rag-node.md)), an [AI Assistant](./ai-assistant.md), integrations ([HTTP](../nodes/http-node.md), [WebSocket Send](../nodes/websocket-send-node.md), [Telegram](../nodes/telegram-node.md), [Slack](../nodes/slack-node.md), inbound [IMAP Trigger](../nodes/imap-trigger-node.md) email, outbound [Send Email](../nodes/send-email-node.md)), scheduling with [Cron](../nodes/cron-node.md), and [Portal](./portal.md) chat portals for end users.

See also [Core Concepts](../getting-started/core-concepts.md), [Node Types](./node-types.md), and [Third-Party Integrations](./integrations.md).

### [Why Heym](../getting-started/why-heym.md)

Heym is built from the ground up around LLMs, agents, and intelligent automation—unlike trigger-action tools that added AI as a plugin. It ships a first-class [LLM](../nodes/llm-node.md) node and [Agent Node](../nodes/agent-node.md) with tool calling, Python tools, [MCP](../tabs/mcp-tab.md) connections, skills, multi-agent orchestration, and provider-native LLM batch execution with live status branches. Built-in [Qdrant RAG](../nodes/rag-node.md), natural-language workflow building, [Traces](../tabs/traces-tab.md), and [Evals](../tabs/evals-tab.md) make it purpose-built for AI workflows; self-hosting keeps your data on your infrastructure.

See also [Agent Node](../nodes/agent-node.md), [LLM](../nodes/llm-node.md), [Qdrant RAG](../nodes/rag-node.md), and [Agent Architecture](./agent-architecture.md).

### [Quick Start](../getting-started/quick-start.md)

Get your first workflow running in minutes: create a workflow from the [Workflows](../tabs/workflows-tab.md) tab, add an [Input](../nodes/input-node.md) node, an [LLM](../nodes/llm-node.md) node, and an [Output](../nodes/output-node.md) node, then connect them. Configure the [LLM](../nodes/llm-node.md) with a credential and set `userMessage` to `$input.text`; use Run or the [AI Assistant](./ai-assistant.md) to execute or generate workflows with natural language.

Pairs naturally with [Input](../nodes/input-node.md), [LLM](../nodes/llm-node.md), [Output](../nodes/output-node.md), and [Expression DSL](./expression-dsl.md).

### [Core Concepts](../getting-started/core-concepts.md)

Workflows are directed graphs of nodes connected by edges; execution flows from trigger nodes ([Input](../nodes/input-node.md), [Cron](../nodes/cron-node.md), [Telegram Trigger](../nodes/telegram-trigger-node.md), [IMAP Trigger](../nodes/imap-trigger-node.md), [WebSocket Trigger](../nodes/websocket-trigger-node.md)) through processing nodes to [Output](../nodes/output-node.md) nodes. Each node has a type, data (configuration), and inputs/outputs; edges define data flow. Nodes reference upstream data via [Expression DSL](./expression-dsl.md) expressions such as `$nodeLabel.field`; independent nodes run in [parallel](./parallel-execution.md) automatically.

See also [Triggers](./triggers.md), [Parallel Execution](./parallel-execution.md), and [Workflow Structure](./workflow-structure.md).

### [Running & Deployment](../getting-started/running-and-deployment.md)

Heym provides `run.sh` for local development (database in Docker, FastAPI backend, Vite frontend) and `deploy.sh` for production with Docker Compose. Both use a `.env` file; key variables include `SECRET_KEY`, `ENCRYPTION_KEY`, `DATABASE_URL`, and `ALLOW_REGISTER`. Development runs on configurable frontend and backend ports; production serves the API under `/api` through the frontend container.

See also [Security](./security.md), [Enterprise](./enterprise.md), and [User Settings](./user-settings.md).

---

## Nodes

### Triggers

#### [Input](../nodes/input-node.md)

The Input node is the entry point for workflows that receive data from the user or API caller. It supports single or multiple input fields and exposes request metadata (headers, query params). Access body fields via `$nodeLabel.body.fieldKey`, headers via `$nodeLabel.headers`, and query via `$nodeLabel.query`.

Pairs naturally with [Condition](../nodes/condition-node.md), [LLM](../nodes/llm-node.md), and [Output](../nodes/output-node.md). For payload references and field access, see [Expression DSL](./expression-dsl.md) and [Webhooks](./webhooks.md).

#### [Cron](../nodes/cron-node.md)

The Cron node triggers a workflow on a schedule using a standard five-field cron expression. No user input is required—the workflow runs automatically at the specified times (e.g. hourly, daily, every 15 minutes). Output is a trigger event with no payload.

See also [Triggers](./triggers.md), [Wait](../nodes/wait-node.md), and [Execution History](./execution-history.md) for scheduled and delayed runs.

#### [IMAP Trigger](../nodes/imap-trigger-node.md)

The IMAP Trigger node polls an inbox on a configurable minute interval and starts a workflow for each newly detected email. It outputs parsed headers, sender and recipient lists, plain-text and HTML bodies, attachment metadata, and a trigger timestamp. Use it for support inbox triage, mailbox-to-[Slack](../nodes/slack-node.md) routing, or email-driven approval flows with [Human-in-the-Loop](./human-in-the-loop.md).

Pairs with [Send Email](../nodes/send-email-node.md), [LLM](../nodes/llm-node.md), and [Slack](../nodes/slack-node.md) for inbound triage and response workflows.

#### [WebSocket Trigger](../nodes/websocket-trigger-node.md)

The WebSocket Trigger node opens an outbound client connection to an external WebSocket server and starts the workflow on `onMessage`, `onConnected`, or `onClosed`. It exposes parsed message payloads, reconnect state, close metadata, and the socket URL for downstream expressions.

Pairs with [WebSocket Send](../nodes/websocket-send-node.md), [HTTP](../nodes/http-node.md), and [SSE Streaming](./sse-streaming.md) for realtime integrations.

#### [Telegram Trigger](../nodes/telegram-trigger-node.md)

The Telegram Trigger node receives bot webhook updates and starts the workflow immediately. It exposes the full update payload, the primary message object, callback queries, sanitized headers, and a trigger timestamp. Use it for chatbots, AI assistants in [Telegram](../nodes/telegram-node.md), and button-driven flows.

Pairs with [Telegram](../nodes/telegram-node.md), [Agent Node](../nodes/agent-node.md), and [Webhooks](./webhooks.md) for bot-driven workflows.

#### [Slack Trigger](../nodes/slack-trigger-node.md)

The Slack Trigger node receives Slack Events API webhooks and starts a workflow automatically after verifying the request signature. It exposes the event payload and sanitized headers for downstream routing, [LLM](../nodes/llm-node.md)-based classification, and reply flows.

Pairs with [Slack](../nodes/slack-node.md), [Agent Node](../nodes/agent-node.md), and [Third-Party Integrations](./integrations.md).

#### [RabbitMQ](../nodes/rabbitmq-node.md)

The RabbitMQ node sends or receives messages from RabbitMQ queues and exchanges. Use it for message-driven workflows and event processing. Send mode publishes a message with optional delay; receive mode acts as a [trigger](./triggers.md) so the workflow starts when a message arrives. Output includes status, message_id, and body.

Pairs with [Condition](../nodes/condition-node.md), [Error Handler](../nodes/error-handler-node.md), and [Parallel Execution](./parallel-execution.md) for event-driven processing.

#### [Error Handler](../nodes/error-handler-node.md)

The Error Handler node runs automatically when any node in the workflow fails. No incoming edges are needed; it is triggered by the engine. Output includes error message, failed node label, node type, and timestamp. Use it to send notifications through [Slack](../nodes/slack-node.md), [Telegram](../nodes/telegram-node.md), or [Send Email](../nodes/send-email-node.md), log errors, or return custom error responses.

Common notification targets are [Slack](../nodes/slack-node.md), [Telegram](../nodes/telegram-node.md), and [Send Email](../nodes/send-email-node.md); run details are easier to inspect in [Execution History](./execution-history.md).

### AI

#### [Agent Node](../nodes/agent-node.md)

The AI Agent node is an [LLM](../nodes/llm-node.md) node with tool calling. It can run Python tools, connect to [MCP](../tabs/mcp-tab.md) servers, use skills (instruction files and optional Python scripts), act as an orchestrator that delegates to other agent nodes, and call other workflows as tools. Output is available as `$nodeLabel.text`.

The Skills section now includes **AI Build** for creating new skills, an inline AI edit action for existing skills, and per-skill ZIP download. The Skill Builder modal streams a chat conversation on the left, shows a live read-only preview of generated `SKILL.md` and `.py` files on the right, can download that preview as a ZIP, and saves the result back through the same ZIP ingestion flow used by manual skill uploads.

With **[Agent Persistent Memory](./agent-persistent-memory.md)** enabled, each agent node keeps its own knowledge graph: facts are loaded into the system prompt when non-empty, and successful runs trigger a background merge of new entities and relationships. Sub-agents use separate graphs. You can **share** an agent’s graph with other agents (same or other workflows) with read-only or read/write access from the graph dialog. The canvas brain control opens the graph editor.

Agent nodes can also enter [Human-in-the-Loop](./human-in-the-loop.md) mode. In this mode the agent gets a `request_human_review` tool and can pause at specific approval-required steps, create a one-time public review link, expose a `review` canvas branch for notification flows, and wait until a reviewer accepts, edits, or refuses the Markdown review text. The node's HITL field acts as approval guidelines for when to ask, while the reviewer-facing summary is generated from each review request. For [MCP](../tabs/mcp-tab.md) tools, Heym uses the model to interpret those written instructions into `always`, `once`, or `never`, so freeform approval language maps to a concrete runtime policy. The run is marked `pending` and resumes from the stored execution snapshot after the decision arrives, and the same agent run can pause more than once if later steps also require review.

Agent nodes automatically compress their accumulated message history when it approaches 80% of the model's context window. The system prompt, first user message, and most recent user message are always preserved; everything in between is summarized using the same model and credential. Compression events are visible in the Debug panel, [Execution History](./execution-history.md), and the [Traces](../tabs/traces-tab.md) tab.

See also [LLM](../nodes/llm-node.md), [Agent Architecture](./agent-architecture.md), [Agent Persistent Memory](./agent-persistent-memory.md), [Human-in-the-Loop](./human-in-the-loop.md), and [File Generation](./file-generation.md).

#### [LLM](../nodes/llm-node.md)

The LLM node processes text with a language model or generates images. It supports text generation, vision (image input), image generation, structured JSON output, and provider-native Batch API execution for supported OpenAI and OpenAI-compatible endpoints. Configure credential, model, system and user messages, temperature, and max tokens; use [Expression DSL](./expression-dsl.md) in prompts. In batch mode the `userMessage` must resolve to an array, the node emits a `batchStatus` branch with progress updates, and the final output includes per-item batch results. Optional [Guardrails](./guardrails.md) block unsafe content before the call.

Pairs naturally with [Qdrant RAG](../nodes/rag-node.md), [Agent Node](../nodes/agent-node.md), [Guardrails](./guardrails.md), and [Expression Evaluation Dialog](./expression-evaluation-dialog.md).

#### [Qdrant RAG](../nodes/rag-node.md)

The Qdrant RAG node inserts documents into or searches a vector store for retrieval-augmented generation. Choose a vector store from the [Vectorstores](../tabs/vectorstores-tab.md) tab and set the operation to insert or search. Search supports metadata filters and optional Cohere reranking, and returns an array of results with text, score, metadata, reranked flag, and count for use in [LLM](../nodes/llm-node.md) or [Agent Node](../nodes/agent-node.md) flows.

Common downstream nodes are [LLM](../nodes/llm-node.md) and [Agent Node](../nodes/agent-node.md); vector store setup lives in [Vectorstores](../tabs/vectorstores-tab.md).

### Logic

#### [Condition](../nodes/condition-node.md)

The Condition node branches the workflow based on an if/else expression. It has two output handles: one for when the condition is truthy and one for falsy. Use comparison and logical operators from the [Expression DSL](./expression-dsl.md) in the condition expression; the node passes through input to the chosen branch.

See also [Switch](../nodes/switch-node.md), [Throw Error](../nodes/throw-error-node.md), and [Expression DSL](./expression-dsl.md).

#### [Switch](../nodes/switch-node.md)

The Switch node routes execution to different paths by matching a value against cases. Configure an expression to evaluate and a list of case values; each case gets a source handle and a default handle is used for non-matching values. Input is passed through to the matched branch.

Use [Condition](../nodes/condition-node.md) for binary branching and [Merge](../nodes/merge-node.md) to rejoin routed paths; matching rules are covered in [Expression DSL](./expression-dsl.md).

#### [Merge](../nodes/merge-node.md)

The Merge node waits for multiple parallel inputs and combines them into a single output. Set the number of inputs to wait for; the node produces a merged object once all branches have completed. Use it to join results from parallel branches before continuing; do not use it when parallel branches end in separate Output nodes.

See also [Parallel Execution](./parallel-execution.md), [Loop](../nodes/loop-node.md), and [Output](../nodes/output-node.md) when recombining branches.

#### [Loop](../nodes/loop-node.md)

The Loop node iterates over an array, executing downstream nodes for each item. It requires a back-connection from the last node in the iteration body to advance. Inside the loop body use `item`, `index`, `total`, `isFirst`, and `isLast`; the loop has separate outputs for the iteration path and the done path.

Pairs with [Variable](../nodes/variable-node.md), [Merge](../nodes/merge-node.md), and [Expression DSL](./expression-dsl.md) for iterative workflows.

### Data

#### [Set](../nodes/set-node.md)

The Set node transforms and maps input data to custom output. Define key-value mappings where each value is an [Expression DSL](./expression-dsl.md) expression. Use it for uppercase, substring, concatenation, random numbers, and similar transformations. Access output by key (e.g. `$setNode.keyName`). For calling other workflows use the [Execute](../nodes/execute-node.md) node instead.

See also [Variable](../nodes/variable-node.md), [Execute](../nodes/execute-node.md), and [Expression DSL](./expression-dsl.md).

#### [Variable](../nodes/variable-node.md)

The Variable node sets or updates a workflow-local variable (`$vars.variableName`) or a persistent [global variable](./global-variables.md) (`$global.variableName`). Use it for counters, accumulated lists, and shared state. Configure variable name, value expression, type coercion, and whether to store in the global store. Array variables support `$array()` and `.add()`.

Pairs with [Set](../nodes/set-node.md), [Loop](../nodes/loop-node.md), and [Global Variables](./global-variables.md).

#### [Execute](../nodes/execute-node.md)

The Execute node calls another workflow (sub-workflow) and passes input to it. Specify the target workflow by ID and provide input via a single expression or key-value mappings. Output includes workflow_id, status, and outputs; use it for reusable logic, not for data transformation (use Set for that).

See also [Canvas Features](./canvas-features.md) for Extract to Sub-Workflow, [Workflow Structure](./workflow-structure.md), and [Output](../nodes/output-node.md).

### Integrations

#### [HTTP](../nodes/http-node.md)

The HTTP node makes HTTP requests using cURL-style configuration. It can be a workflow starting point (no incoming edge) or receive input from upstream nodes. Response is available as status, headers, and body (parsed JSON when applicable). Use [Credentials](./credentials.md) for Bearer or custom header auth.

Pairs with [Webhooks](./webhooks.md), [Credentials](./credentials.md), and [Third-Party Integrations](./integrations.md).

#### [WebSocket Send](../nodes/websocket-send-node.md)

The WebSocket Send node opens an outbound client connection, sends one text/JSON/binary message, and closes it. Use it to publish workflow output to realtime systems without creating a Heym-hosted socket endpoint.

See also [WebSocket Trigger](../nodes/websocket-trigger-node.md), [SSE Streaming](./sse-streaming.md), and [Third-Party Integrations](./integrations.md).

#### [Telegram](../nodes/telegram-node.md)

The Telegram node sends a bot message to a chat, group, or channel. Configure a Telegram [credential](./credentials.md), set `chatId`, and compose the outgoing `message` with [Expression DSL](./expression-dsl.md) expressions. It pairs naturally with [Telegram Trigger](../nodes/telegram-trigger-node.md) for conversational workflows and with [Error Handler](../nodes/error-handler-node.md) for operator alerts.

See also [Third-Party Integrations](./integrations.md) and [Credentials](./credentials.md) for setup and credential patterns.

#### [Slack](../nodes/slack-node.md)

The Slack node sends a message to a Slack channel via an Incoming Webhook. Configure a Slack [credential](./credentials.md) and a message expression. Use it for notifications, alerts, and error reporting; output passes through input.

Pairs with [Slack Trigger](../nodes/slack-trigger-node.md), [Error Handler](../nodes/error-handler-node.md), and [Third-Party Integrations](./integrations.md).

#### [Send Email](../nodes/send-email-node.md)

The Send Email node sends emails via SMTP. Configure an SMTP [credential](./credentials.md) and [Expression DSL](./expression-dsl.md) expressions for recipient(s), subject, and body. Use it for notifications, alerts, and transactional emails. Output includes status, to, and subject.

The [IMAP Trigger](../nodes/imap-trigger-node.md) complements Send Email by handling inbound mail. Together they let a workflow read incoming email from a shared inbox, summarize or classify it with AI nodes, and send a follow-up or escalation message. The [Telegram Trigger](../nodes/telegram-trigger-node.md) and [Telegram node](../nodes/telegram-node.md) provide the same inbound/outbound pattern for bot-driven chat workflows.

For two-way notification flows, it also pairs well with [LLM](../nodes/llm-node.md), [Agent Node](../nodes/agent-node.md), and [Third-Party Integrations](./integrations.md).

#### [Redis](../nodes/redis-node.md)

The Redis node performs Redis operations: set, get, hasKey, and deleteKey. Use it for caching, rate limiting, and key-value storage. Configure a [credential](./credentials.md), operation type, key expression, and for set operations value and optional TTL. Output varies by operation (value, success, exists, deleted).

Pairs with [Wait](../nodes/wait-node.md), [Variable](../nodes/variable-node.md), and [Parallel Execution](./parallel-execution.md) for caching, throttling, and coordination.

#### [Grist](../nodes/grist-node.md)

The Grist node reads, writes, and manages data in Grist spreadsheets. Operations include getRecord, getRecords, createRecord, updateRecord, deleteRecord, listTables, and listColumns. Provide document ID, table ID, and for create/update the record data using column IDs. Use it for CRUD, batch updates, and spreadsheet automation.

See also [Google Sheets](../nodes/google-sheets-node.md), [DataTable](../nodes/datatable-node.md), and [Third-Party Integrations](./integrations.md).

#### [Google Sheets](../nodes/google-sheets-node.md)

The Google Sheets node reads, writes, and manages spreadsheet data via OAuth2. Use it to read reports, append workflow results, update trackers, and clear or inspect sheet tabs from within a workflow. Like [BigQuery](../nodes/bigquery-node.md), it uses a Google-backed integration credential and fits well beside [Grist](../nodes/grist-node.md) when spreadsheet data is part of the flow.

Pairs with [Grist](../nodes/grist-node.md), [DataTable](../nodes/datatable-node.md), and [Third-Party Integrations](./integrations.md).

#### [BigQuery](../nodes/bigquery-node.md)

The BigQuery node runs SQL queries and inserts rows into Google BigQuery datasets via OAuth2. It is useful for analytics workflows, reporting pipelines, and writing structured event data from workflow runs. It often pairs with [Set](../nodes/set-node.md) for shaping rows and [Google Sheets](../nodes/google-sheets-node.md) for lighter spreadsheet-oriented reporting.

Pairs with [Set](../nodes/set-node.md), [LLM](../nodes/llm-node.md), [Google Sheets](../nodes/google-sheets-node.md), and [Third-Party Integrations](./integrations.md).

#### [DataTable](../nodes/datatable-node.md)

The DataTable node reads, writes, and manages data in Heym DataTables (first-party structured storage). Operations include find, getAll, getById, insert, update, remove, and upsert. No external credentials required. Tables are managed from the [DataTable](../tabs/datatable-tab.md) dashboard tab and accessed directly by the workflow owner.

Pairs with [Set](../nodes/set-node.md), [Variable](../nodes/variable-node.md), and the [DataTable tab](../tabs/datatable-tab.md) for first-party structured storage.

#### [Drive](../nodes/drive-node.md)

The Drive node manages files generated by skills directly from within a workflow. Operations: delete (removes file and all tokens), setPassword (replaces default token with a password-protected one), setTtl (replaces with an expiring token), and setMaxDownloads (replaces with a download-limited token). Reference the file with `$agentLabel._generated_files[0].id`; output includes status, file_id, and updated download_url. This is especially useful with [Agent Node](../nodes/agent-node.md) workflows that use [File Generation](./file-generation.md) and the [Drive](./drive.md) reference model.

Common companions are [Agent Node](../nodes/agent-node.md), [File Generation](./file-generation.md), and [Drive](./drive.md).

### Automation

#### [Crawler](../nodes/crawler-node.md)

The Crawler node scrapes web pages using FlareSolverr with optional HTML extraction via CSS selectors. Configure a FlareSolverr [credential](./credentials.md), URL expression, wait time, and optional selectors for extraction. Output is the raw HTML or extracted content. Use it for web scraping and content extraction.

Pairs with [HTTP](../nodes/http-node.md), [Playwright](../nodes/playwright-node.md), and [LLM](../nodes/llm-node.md) for scrape-and-analyze flows.

#### [Playwright](../nodes/playwright-node.md)

The Playwright node automates browser interactions with configurable steps (navigate, click, type, screenshot, extract, aiStep). It supports custom Playwright code, headless mode, timeouts, optional network capture (responses, cookies, localStorage, sessionStorage), cookie/storageState auth bootstrap from [Global Variables](./global-variables.md) expressions such as `$global.authState`, fallback login steps when auth restore fails, and an AI step with Auto Heal when selectors fail. Use it for web scraping, form filling, and browser-based workflows.

See also [Crawler](../nodes/crawler-node.md), [HTTP](../nodes/http-node.md), and [Execution History](./execution-history.md) for browser automation and debugging.

### Utilities

#### [Output](../nodes/output-node.md)

The Output node is the workflow endpoint that returns the response to the caller. Set the message expression to reference the previous node by label (never use `$input` from the [Input](../nodes/input-node.md) node here). Optional async downstream allows nodes after the output to run in the background after the response is sent.

Common upstream sources are [Input](../nodes/input-node.md), [LLM](../nodes/llm-node.md), and [Execute](../nodes/execute-node.md); response shaping is easier to debug in [Expression Evaluation Dialog](./expression-evaluation-dialog.md).

#### [JSON output mapper](../nodes/json-output-mapper-node.md)

The JSON output mapper node builds a plain JSON object from [Set](../nodes/set-node.md)-style key-value mappings and returns it at the root of the workflow response. Use it when an API caller should receive a raw JSON body instead of the standard [Output](../nodes/output-node.md) node wrapper.

Pairs with [Set](../nodes/set-node.md), [Output](../nodes/output-node.md), [Workflow Structure](./workflow-structure.md), and [Webhooks](./webhooks.md).

#### [Wait](../nodes/wait-node.md)

The Wait node pauses workflow execution for a specified duration in milliseconds. Use it for rate limiting, delayed actions, or polling intervals. It passes through input unchanged.

Pairs with [Cron](../nodes/cron-node.md), [Redis](../nodes/redis-node.md), and [Parallel Execution](./parallel-execution.md) for pacing and polling.

#### [Sticky Note](../nodes/sticky-note-node.md)

The Sticky Note node adds markdown notes to the canvas. It is not executed. Use it for documentation, instructions, or workflow notes alongside other [Canvas Features](./canvas-features.md). Double-click on the canvas to edit the note content.

See also [Canvas Features](./canvas-features.md), [Keyboard Shortcuts](./keyboard-shortcuts.md), and [Workflow Organization](./workflow-organization.md).

#### [Console Log](../nodes/console-log-node.md)

The Console Log node logs a value to the backend (server) console. Use it for debugging and inspection during development. The log message supports [Expression DSL](./expression-dsl.md) expressions; output passes through input.

Pairs with [Execution History](./execution-history.md), [Traces](../tabs/traces-tab.md), and [Expression Evaluation Dialog](./expression-evaluation-dialog.md) for debugging.

#### [Disable Node](../nodes/disable-node.md)

The Disable Node node permanently disables another node in the workflow by setting its `active` flag to false. Specify the target node by label. Use it for one-time operations such as stopping a [Cron](../nodes/cron-node.md) trigger after a condition is met.

See also [Canvas Features](./canvas-features.md), [Edit History](./edit-history.md), and [Cron](../nodes/cron-node.md) for workflow control patterns.

#### [Throw Error](../nodes/throw-error-node.md)

The Throw Error node stops workflow execution immediately and returns an error response with a custom HTTP status code. Set the error message expression and status code (e.g. 400, 401, 403, 404, 429, 500). Use it for validation failures, unauthorized access, or other error conditions, especially when paired with [Condition](../nodes/condition-node.md) and [Error Handler](../nodes/error-handler-node.md).

Pairs with [Condition](../nodes/condition-node.md), [Error Handler](../nodes/error-handler-node.md), and [Security](./security.md) for explicit failure paths.

---

## Reference

### [Node Types](./node-types.md)

Heym provides a variety of node types: triggers such as [Input](../nodes/input-node.md), [Cron](../nodes/cron-node.md), [Telegram Trigger](../nodes/telegram-trigger-node.md), [IMAP Trigger](../nodes/imap-trigger-node.md), [Slack Trigger](../nodes/slack-trigger-node.md), [RabbitMQ](../nodes/rabbitmq-node.md), and [Error Handler](../nodes/error-handler-node.md); AI nodes such as [LLM](../nodes/llm-node.md), [Agent Node](../nodes/agent-node.md), and [Qdrant RAG](../nodes/rag-node.md); logic nodes like [Condition](../nodes/condition-node.md), [Switch](../nodes/switch-node.md), [Merge](../nodes/merge-node.md), and [Loop](../nodes/loop-node.md); data nodes like [Set](../nodes/set-node.md), [Variable](../nodes/variable-node.md), and [Execute](../nodes/execute-node.md); integrations such as [HTTP](../nodes/http-node.md), [Telegram](../nodes/telegram-node.md), [Slack](../nodes/slack-node.md), [Send Email](../nodes/send-email-node.md), [Redis](../nodes/redis-node.md), [Grist](../nodes/grist-node.md), [Google Sheets](../nodes/google-sheets-node.md), [BigQuery](../nodes/bigquery-node.md), [DataTable](../nodes/datatable-node.md), and [Drive](../nodes/drive-node.md); automation nodes like [Crawler](../nodes/crawler-node.md) and [Playwright](../nodes/playwright-node.md); and utilities such as [Wait](../nodes/wait-node.md), [Output](../nodes/output-node.md), [JSON output mapper](../nodes/json-output-mapper-node.md), [Console Log](../nodes/console-log-node.md), [Throw Error](../nodes/throw-error-node.md), [Disable Node](../nodes/disable-node.md), and [Sticky Note](../nodes/sticky-note-node.md). Use expressions like `$input.text` and `$nodeLabel.field` in node configuration.

See also [Triggers](./triggers.md), [Third-Party Integrations](./integrations.md), and [Parallel Execution](./parallel-execution.md).

### [Expression DSL](./expression-dsl.md)

Heym uses a simple expression language to reference data from upstream nodes. Use `$input` for the [Input](../nodes/input-node.md) node, `$nodeLabel.field` for any upstream node, `$credentials.CredentialName` for [credentials](./credentials.md), and `$global.variableName` for [global variables](./global-variables.md). Support includes literals, arithmetic, comparisons, [Loop](../nodes/loop-node.md) context, nested fields, and string/array helpers. When the full value is a single `$expr`, the backend preserves arrays, objects, booleans, and numbers as native types.

See also [Expression Evaluation Dialog](./expression-evaluation-dialog.md), [Global Variables](./global-variables.md), and [Workflow Structure](./workflow-structure.md).

### [Global Variables](./global-variables.md)

The Global Variable Store holds persistent, user-scoped key-value data that survives across workflow executions. Create variables from the [Variables](../tabs/global-variables-tab.md) tab or from a [Variable](../nodes/variable-node.md) node with "Store in Global Variable Store" enabled. Access them with `$global.variableName` in expressions; they can be shared with other users or [teams](./teams.md).

Pairs with [Variable](../nodes/variable-node.md), [Teams](./teams.md), and [Credentials Sharing](./credentials-sharing.md) for shared workflow state.

### [Expression Evaluation Dialog](./expression-evaluation-dialog.md)

The Expression Evaluation Dialog is an expandable editor that appears when you click the expand button next to expression fields. It opens as a large centered modal, keeps autocomplete active, and refreshes backend preview output automatically after you pause typing. Object and array results can be browsed with the output path picker. The dialog accepts a full-line bare dot path (for example `myNode.output.field`) as if it were `$myNode.output.field`; see [Expression DSL](./expression-dsl.md) placement rules.

Pairs naturally with [Expression DSL](./expression-dsl.md), [Output](../nodes/output-node.md), and [JSON output mapper](../nodes/json-output-mapper-node.md).

### [Workflow Structure](./workflow-structure.md)

Workflows are stored as JSON with nodes and edges. The workflow object includes id, name, description, nodes, edges, and auth settings. Each node has id, type, position, and data (label and type-specific config). Edges connect source and target node IDs with optional handle IDs. Expression syntax in data fields follows the [Expression DSL](./expression-dsl.md), and this same shape is used by [Download & Import](./download-import.md).

See also [Node Types](./node-types.md), [Expression DSL](./expression-dsl.md), and [Download & Import](./download-import.md).

### [Canvas Features](./canvas-features.md)

The workflow editor provides Data Pin (pin a node's last output for testing downstream without re-running), Execution Logs (real-time node results and agent progress that complement [Execution History](./execution-history.md)), Enable/Disable (skip nodes during execution), and Extract to Sub-Workflow (move a selection into a new workflow and replace it with an [Execute](../nodes/execute-node.md) node). [Keyboard Shortcuts](./keyboard-shortcuts.md) support copy, paste, run, and inline node search.

See also [Keyboard Shortcuts](./keyboard-shortcuts.md), [Edit History](./edit-history.md), and [Execution History](./execution-history.md).

<video src="/features/showcase/editor.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/editor.webm">▶ Watch Editor demo</a></p>

### [Keyboard Shortcuts](./keyboard-shortcuts.md)

Heym provides shortcuts across the editor: Command Palette (Ctrl+K), Run (Ctrl+Enter), Save (Ctrl+S), Undo/Redo, and Escape to dismiss. On the canvas: select all, multi-select, copy/cut/paste, delete, toggle node enabled (D), toggle pinned data (P), and inline node search by typing. Shortcuts are documented in the in-app reference and work closely with [Canvas Features](./canvas-features.md) such as Data Pin and node enable/disable.

See also [Canvas Features](./canvas-features.md), [Quick Drawer](./quick-drawer.md), and [Contextual Showcase](./contextual-showcase.md).

### [AI Assistant](./ai-assistant.md)

The AI Assistant is a chat panel opened from the Debug panel that lets you create or modify workflows with natural language. Select a [credential](./credentials.md) and model, then describe what you want; the AI streams a response and any valid [workflow JSON](./workflow-structure.md) in a code block is automatically parsed and applied to the canvas. Voice input is supported on compatible browsers.

When the current workflow contains [Agent Node](../nodes/agent-node.md) skills, the assistant sends only each skill's `SKILL.md` into the workflow context. Attached `.py` files and binary skill assets are excluded before the request so large skill bundles do not overflow the model context window.

Pairs well with [Chat with Docs](./chat-with-docs.md), [Agent Architecture](./agent-architecture.md), and [Expression DSL](./expression-dsl.md).

### [Chat with Docs](./chat-with-docs.md)

Chat with Docs is a documentation-header assistant for product questions. It opens in a centered dialog, keeps credential and model selection visible at the top, injects the active docs page path as context, and clears message history when the dialog closes. It complements the broader [AI Assistant](./ai-assistant.md) and the lighter-weight [Contextual Showcase](./contextual-showcase.md).

See also [AI Assistant](./ai-assistant.md), [Contextual Showcase](./contextual-showcase.md), and [Node Types](./node-types.md).

### [Workflow Organization](./workflow-organization.md)

Workflows can be organized in folders and sub-folders in a tree structure. Folders have names and optional parent; workflows are assigned to folders. Workflows can be scheduled for deletion (moved to a trash area before permanent removal). The API supports create, update, delete, and moving workflows between folders, and the same organization model appears in the [Workflows](../tabs/workflows-tab.md) tab.

See also [Quick Drawer](./quick-drawer.md), [Download & Import](./download-import.md), and [Edit History](./edit-history.md).

### [Quick Drawer](./quick-drawer.md)

The Quick Drawer is a fixed right-side fast-run panel for internal non-canvas pages. It lets you search [workflows](../tabs/workflows-tab.md), pin favorites, select inputs, run immediately, and inspect progress or results without opening the editor. Pin order and the last selected workflow are stored in the browser.

See also [Workflow Organization](./workflow-organization.md), [Keyboard Shortcuts](./keyboard-shortcuts.md), and [Execution History](./execution-history.md).

### [Contextual Showcase](./contextual-showcase.md)

The Contextual Showcase is a compact in-app guide rail for authenticated main surfaces such as dashboard tabs, [Evals](../tabs/evals-tab.md), Docs, and the workflow editor. It stays closed by default, gives a short page summary first, offers a little extra detail on demand, and links to the full docs article when you want deeper guidance.

Pairs with [Chat with Docs](./chat-with-docs.md), [Quick Drawer](./quick-drawer.md), and [AI Assistant](./ai-assistant.md) for in-app guidance flows.

### [Credentials](./credentials.md)

Credentials store API keys and secrets used by workflow nodes. Add them in the [Credentials](../tabs/credentials-tab.md) tab and reference them by name or ID in nodes such as [LLM](../nodes/llm-node.md), [Agent Node](../nodes/agent-node.md), [HTTP](../nodes/http-node.md), [Telegram](../nodes/telegram-node.md), [Send Email](../nodes/send-email-node.md), and [Redis](../nodes/redis-node.md). They are encrypted at rest, can be shared with users or [teams](./teams.md), and can also be referenced in [Expression DSL](./expression-dsl.md) via `$credentials.Name`.

See also [Credentials](../tabs/credentials-tab.md), [Credentials Sharing](./credentials-sharing.md), and [Third-Party Integrations](./integrations.md).

### [Credentials Sharing](./credentials-sharing.md)

Credentials can be shared with other users by email or with teams; all team members gain access when a credential is shared with a team. Shared credentials appear with an indicator in the [Credentials](../tabs/credentials-tab.md) tab. At runtime, the workflow owner's context merges owned, user-shared, and team-shared credentials. Use `$credentials.CredentialName` in expressions or set credentialId in node data.

See also [Credentials](./credentials.md), [Teams](./teams.md), and [Third-Party Integrations](./integrations.md).

### [Teams](./teams.md)

Teams let you share workflows, credentials, global variables, and vector stores with a group of users at once. Create teams from the [Teams](../tabs/teams-tab.md) tab and add members by email. Share resources with a team from the relevant share dialogs; all members then have access. The creator can edit and delete the team; deleting a team removes all team shares.

Pairs with [Credentials Sharing](./credentials-sharing.md), [Global Variables](./global-variables.md), and [Enterprise](./enterprise.md).

### [Parallel Execution](./parallel-execution.md)

Heym runs nodes in parallel when they have no dependencies on each other. The executor builds a DAG and runs nodes in the same level concurrently with a thread pool; as soon as a node finishes, its downstream nodes are scheduled. Use the [Merge](../nodes/merge-node.md) node to combine parallel branches when needed. Multiple workflow runs execute concurrently; each run is isolated. [SSE Streaming](./sse-streaming.md) mode emits events as nodes complete.

See also [Merge](../nodes/merge-node.md), [Loop](../nodes/loop-node.md), and [Execution History](./execution-history.md).

### [Agent Architecture](./agent-architecture.md)

The [Agent Node](../nodes/agent-node.md) supports sub-agents (orchestrator calls other agent nodes via call_sub_agent), sub-workflows (agent calls other workflows via call_sub_workflow), skills (instruction content and Python tools from .zip or .md), and [MCP](../tabs/mcp-tab.md) client connections. The orchestrator tool executor routes sub-agent and sub-workflow calls; other tools go to Python, MCP, or skill executors. Max nesting depth for sub-agents and sub-workflows is 5. The tool-calling loop includes automatic context compression: before each iteration, token usage is estimated and if it exceeds 80% of the model's context window the middle messages are summarized using the same model, keeping the system prompt, first user message, and last user message intact.

See also [Agent Node](../nodes/agent-node.md), [Agent Persistent Memory](./agent-persistent-memory.md), [Human-in-the-Loop](./human-in-the-loop.md), and [MCP](../tabs/mcp-tab.md).

### [Agent Persistent Memory](./agent-persistent-memory.md)

Optional per-[Agent Node](../nodes/agent-node.md) knowledge graph stored in Postgres: entities, types, properties, and directed relationships. When `persistentMemoryEnabled` is true, the graph is summarized into the system prompt on each run; after successful completions, an [LLM](../nodes/llm-node.md) extracts structured updates in the background. REST CRUD lives under `/api/workflows/{workflow_id}/nodes/{canvas_node_id}/agent-memory/...`. The editor opens from the pink brain control on the node.

See also [Agent Node](../nodes/agent-node.md), [Agent Architecture](./agent-architecture.md), and [Traces](../tabs/traces-tab.md).

### [Human-in-the-Loop](./human-in-the-loop.md)

Human-in-the-loop lets an [Agent Node](../nodes/agent-node.md) request approval at specific checkpoints, create a public `/review/{token}` page, and wait for a non-logged-in reviewer to accept, edit, or refuse the Markdown review text. HITL-enabled agents also expose a `review` output handle so you can notify [Slack](../nodes/slack-node.md), [Send Email](../nodes/send-email-node.md), or other channels while the run is pending. The node-level HITL text is used as approval guidelines, while the public-page summary is generated from the review request itself. Pending runs appear in [Execution History](./execution-history.md) immediately, can happen more than once in the same run, and resume from the exact stored workflow snapshot once each decision is submitted.

See also [Agent Node](../nodes/agent-node.md), [Portal](./portal.md), [Execution History](./execution-history.md), and [Send Email](../nodes/send-email-node.md).

### [Webhooks](./webhooks.md)

Workflows can be triggered via [HTTP](../nodes/http-node.md) at `POST /api/workflows/{workflow_id}/execute`, or streamed incrementally from `POST /api/workflows/{workflow_id}/execute/stream`. The request body is passed as body to [Input](../nodes/input-node.md) nodes; headers and query params are available in [Expression DSL](./expression-dsl.md) expressions. Configure per-workflow auth: anonymous, JWT, or custom header. Optional response caching, rate limiting, and the editor's Run with cURL dialog all live on the workflow and apply to both modes.

See also [Input](../nodes/input-node.md), [Execution Tokens](./execution-tokens.md), [SSE Streaming](./sse-streaming.md), [HTTP](../nodes/http-node.md), and [Workflow Structure](./workflow-structure.md).

### [Execution Tokens](./execution-tokens.md)

Execution tokens are scoped JWTs that grant access to a single workflow's execute and stream endpoints. When a workflow uses JWT authentication, tokens let external scripts, CI pipelines, and integrations call the workflow without sharing a user session. Each token carries a `wid` claim that pins it to one workflow, a `jti` used for instant revocation, and a configurable TTL (60 seconds to 10 years). Create, select, and revoke tokens directly from the **Run with cURL** dialog — the selected token is embedded in the generated command automatically.

See also [Webhooks](./webhooks.md), [Security](./security.md), and [SSE Streaming](./sse-streaming.md).

### [SSE Streaming](./sse-streaming.md)

The cURL dialog can switch [webhook](./webhooks.md) execution into Server-Sent Events mode. This produces `execution_started`, `node_start`, `node_complete`, and `execution_complete` events in real time, adds `--no-buffer` to the generated cURL command, and lets you configure per-node start messages such as `[START] LLM` or custom text for external terminal consumers.

See also [Webhooks](./webhooks.md), [Execution History](./execution-history.md), and [LLM](../nodes/llm-node.md).

### [Triggers](./triggers.md)

Workflows are started by trigger nodes ([Input](../nodes/input-node.md), [Cron](../nodes/cron-node.md), [Telegram Trigger](../nodes/telegram-trigger-node.md), [IMAP Trigger](../nodes/imap-trigger-node.md), [RabbitMQ](../nodes/rabbitmq-node.md) receive) or entry points: [Webhook/API](./webhooks.md), [MCP](../tabs/mcp-tab.md), [Portal](./portal.md), Cron scheduler, Telegram webhook, IMAP trigger manager, RabbitMQ consumer, or Editor run. Each trigger has its own endpoint or background process; [Cron](../nodes/cron-node.md) runs every 60 seconds, [Telegram Trigger](../nodes/telegram-trigger-node.md) nodes receive bot webhooks, and [IMAP Trigger](../nodes/imap-trigger-node.md) nodes run on their configured polling interval. [Input](../nodes/input-node.md) nodes receive body, headers, and query from webhook requests.

See also [Node Types](./node-types.md), [Webhooks](./webhooks.md), and [Parallel Execution](./parallel-execution.md).

### [Execution History](./execution-history.md)

Execution history records past workflow runs: inputs, outputs, node results, status, and trigger source. Access it from the Editor toolbar, Docs view, Dashboard header, or [Evals](../tabs/evals-tab.md) view. Per-workflow history shows runs for the open workflow; all-history view shows runs across workflows and chat. Currently running executions appear at the top of both dialogs with a **Cancel** button; cancelling from any dialog also closes the active [SSE](./sse-streaming.md) stream in open canvas tabs for that workflow. Bring to Canvas loads a selected run's inputs and node outputs for re-run or debugging. [Human-in-the-Loop](./human-in-the-loop.md)-paused runs are stored immediately as `pending`, including the public review URL and any notification nodes executed from the agent's `review` branch.

See also [SSE Streaming](./sse-streaming.md), [Human-in-the-Loop](./human-in-the-loop.md), and [Traces](../tabs/traces-tab.md).

### [Edit History](./edit-history.md)

Edit History tracks saved versions of a workflow (each Save creates a version). View the list, open a version to see a diff against the current workflow ([nodes](./workflow-structure.md), edges, config), and Revert to restore a past version. Unlike [Execution History](./execution-history.md), Edit History tracks structure changes, not runs.

See also [Execution History](./execution-history.md), [Workflow Structure](./workflow-structure.md), and [Canvas Features](./canvas-features.md).

### [User Settings](./user-settings.md)

User Settings (opened from your name in the header) includes Profile (display name, User Rules) and [Security](./security.md) (change password). User Rules are custom instructions injected into every AI request, including the workflow builder and [Chat](../tabs/chat-tab.md), so you can set language, tone, coding style, or workflow conventions once. Password policy and [MCP](../tabs/mcp-tab.md) API key management are also available from settings.

See also [Security](./security.md), [Chat](../tabs/chat-tab.md), and [AI Assistant](./ai-assistant.md).

### [Download & Import](./download-import.md)

Export the current workflow as JSON from the Editor toolbar (Download button); the file includes nodes and edges. Import by dragging a JSON file onto the [Workflows](../tabs/workflows-tab.md) tab (creates a new workflow) or onto the canvas (replaces or merges). The JSON must include a nodes array; name and edges are optional. Use it for backup, sharing, or migrating between instances.

See also [Workflow Structure](./workflow-structure.md), [Workflows](../tabs/workflows-tab.md), and [Canvas Features](./canvas-features.md).

### [Portal](./portal.md)

The Portal exposes workflows as public chat UIs at `/chat/{slug}`. Configure portal_enabled, slug, optional auth (portal users), streaming, and file upload per workflow. End users interact via a chat interface without logging into Heym; image outputs can be displayed in the chat. Portal workflows can also hand off to [Human-in-the-Loop](./human-in-the-loop.md) review pages when an [Agent Node](../nodes/agent-node.md) requires approval, while the agent's `review` branch sends notifications to other channels. Use it for internal tools, customer-facing chatbots, and AI-powered forms.

See also [Human-in-the-Loop](./human-in-the-loop.md), [Agent Node](../nodes/agent-node.md), and [Drive](./drive.md).

### [File Generation](./file-generation.md)

Skills can generate files such as PDF, DOCX, CSV, JSON, and images during execution by writing into the `_OUTPUT_DIR` workspace. Heym captures those files automatically, stores them, and exposes download metadata under `_generated_files`, which can then be managed with the [Drive node](../nodes/drive-node.md) or reviewed in the [Drive](../tabs/drive-tab.md) tab.

See also [Agent Node](../nodes/agent-node.md), [Drive](./drive.md), and [Drive node](../nodes/drive-node.md).

### [Drive](./drive.md)

Drive is the shared storage and sharing layer for files generated by skills. It lets you browse files, create public or password-protected links, apply expiration and download limits, and manage those files programmatically with the [Drive node](../nodes/drive-node.md) or manually from the [Drive](../tabs/drive-tab.md) tab.

See also [Drive](../tabs/drive-tab.md), [File Generation](./file-generation.md), and [Portal](./portal.md).

### [Security](./security.md)

Heym enforces a password policy (length, uppercase, lowercase, digit), stores access tokens in HttpOnly cookies, and rotates refresh tokens on use. Rate limiting applies to login, register, and [Portal](./portal.md) login. [Credentials](./credentials.md) are encrypted at rest with AES-256 (Fernet). [MCP](../tabs/mcp-tab.md) API key is used for client auth; content safety is available via [Guardrails](./guardrails.md) on [LLM](../nodes/llm-node.md) and [Agent Node](../nodes/agent-node.md) nodes. [Execution Tokens](./execution-tokens.md) provide per-workflow scoped JWTs for external callers.

See also [Execution Tokens](./execution-tokens.md), [Guardrails](./guardrails.md), [Portal](./portal.md), and [Credentials](./credentials.md).

### [Third-Party Integrations](./integrations.md)

Heym connects to external services through credentials stored in the [Credentials](../tabs/credentials-tab.md) tab (encrypted at rest). Supported types include OpenAI, Google, Custom LLM, Cohere, Qdrant, [Grist](../nodes/grist-node.md), SMTP for [Send Email](../nodes/send-email-node.md), [RabbitMQ](../nodes/rabbitmq-node.md), [Redis](../nodes/redis-node.md), [Telegram](../nodes/telegram-node.md), [Slack](../nodes/slack-node.md), Bearer, Header, and FlareSolverr for [Crawler](../nodes/crawler-node.md). Each type documents required fields; credentials can be shared with users or [teams](./teams.md) and referenced by name in nodes or as `$credentials.Name` in expressions.

See also [Credentials](./credentials.md), [Credentials Sharing](./credentials-sharing.md), and [Teams](./teams.md).

### [Guardrails](./guardrails.md)

Guardrails block unsafe or unwanted user messages before they reach an [LLM](../nodes/llm-node.md) or [Agent Node](../nodes/agent-node.md). Enable them per node and select categories to block (e.g. violence, hate speech, sexual content, self-harm, harassment, illegal activity). Set sensitivity (low, medium, high). When triggered, the node throws an error you can catch with an [Error Handler](../nodes/error-handler-node.md). Detection uses the provider moderation API or LLM classification depending on credential type.

See also [Security](./security.md), [LLM](../nodes/llm-node.md), [Agent Node](../nodes/agent-node.md), and [Error Handler](../nodes/error-handler-node.md).

### [Enterprise](./enterprise.md)

Enterprise covers commercial licensing, professional support, and deployment services for teams running Heym in production. It includes workflow architecture help, onboarding, Kubernetes and scaling guidance, priority support, and custom development around advanced features such as [Agent Node](../nodes/agent-node.md), [Human-in-the-Loop](./human-in-the-loop.md), [Parallel Execution](./parallel-execution.md), and [Portal](./portal.md).

See also [Running & Deployment](../getting-started/running-and-deployment.md), [Security](./security.md), and [Teams](./teams.md).

---

## Dashboard Tabs

### [Workflows](../tabs/workflows-tab.md)

The Workflows tab is the default dashboard view. It shows your workflow list in a card grid or list, with folders and sub-folders for [organization](./workflow-organization.md). Create workflows with New Workflow, drag and drop JSON to [import](./download-import.md), and edit or delete from the card menu. Workflows can be moved between folders; deletion is scheduled (trash) before permanent removal.

See also [Workflow Organization](./workflow-organization.md), [Download & Import](./download-import.md), and [Quick Drawer](./quick-drawer.md).

<video src="/features/showcase/workflows.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/workflows.webm">▶ Watch Workflows demo</a></p>

### [Templates](../tabs/templates-tab.md)

The Templates tab lets you save and reuse workflow templates (full workflows) and node templates (single configured nodes). Create workflow templates from the editor (Share as Template) and node templates by right-clicking a node. Browse by visibility (Everyone or Specific users/[teams](./teams.md)), apply a template to create a new workflow or add a node to the canvas, and manage your shared templates.

See also [Workflows](../tabs/workflows-tab.md), [Teams](./teams.md), and [Canvas Features](./canvas-features.md).

<video src="/features/showcase/templates.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/templates.webm">▶ Watch Templates demo</a></p>

### [Variables](../tabs/global-variables-tab.md)

The Variables tab manages the [Global Variable Store](./global-variables.md). Create, edit, and delete global variables; set name, value, and value type (Auto, String, Number, Boolean, Array, Object). Variables are user-scoped and persist across executions. Reference them in any workflow [expression](./expression-dsl.md) as `$global.variableName`. Variables can be shared with other users or [teams](./teams.md).

See also [Global Variables](./global-variables.md), [Variable](../nodes/variable-node.md), and [Expression DSL](./expression-dsl.md).

<video src="/features/showcase/globalvariables.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/globalvariables.webm">▶ Watch Variables demo</a></p>

### [Chat](../tabs/chat-tab.md)

The Chat tab provides a direct [LLM](../nodes/llm-node.md) chat interface. Select a [credential](./credentials.md) and model, then send messages to test models, prototype prompts, or ask questions without building a workflow. It supports streaming, markdown, inline images, copy, clear, and voice input. User Rules from [User Settings](./user-settings.md) apply automatically; [global variables](./global-variables.md) are available to the LLM as context.

See also [AI Assistant](./ai-assistant.md), [Credentials](./credentials.md), and [User Settings](./user-settings.md).

<video src="/features/showcase/chat.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/chat.webm">▶ Watch Chat demo</a></p>

### [Credentials](../tabs/credentials-tab.md)

The Credentials tab manages API keys and secrets used by nodes. Add credentials by type (OpenAI, Google, Custom, Bearer, Header, [Telegram](../nodes/telegram-node.md), [Slack](../nodes/slack-node.md), SMTP, [Redis](../nodes/redis-node.md), Qdrant, Cohere, etc.), name them, and reference them in workflow nodes. Edit or delete from the card; share with users by email or with [teams](./teams.md). All values are encrypted at rest and masked in the UI.

See also [Credentials](./credentials.md), [Credentials Sharing](./credentials-sharing.md), and [Third-Party Integrations](./integrations.md).

<video src="/features/showcase/credentials.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/credentials.webm">▶ Watch Credentials demo</a></p>

### [Vectorstores](../tabs/vectorstores-tab.md)

The Vectorstores tab manages vector stores used by [Qdrant RAG](../nodes/rag-node.md) nodes. Create a store with a name and Qdrant [credential](./credentials.md), optionally set a collection name, then upload documents (PDF, TXT, etc.). Manage content (view, delete sources), edit store details, and share stores with users. In a [Qdrant RAG](../nodes/rag-node.md) node, select the vector store to run insert or search operations.

See also [Qdrant RAG](../nodes/rag-node.md), [Credentials](./credentials.md), and [Teams](./teams.md).

<video src="/features/showcase/vectorstores.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/vectorstores.webm">▶ Watch Vectorstores demo</a></p>

### [MCP](../tabs/mcp-tab.md)

The MCP tab configures Model Context Protocol integration. View and regenerate your MCP API key, copy ready-to-use client JSON, connect Cursor in one click, or follow the Claude setup flow with automatic OAuth registration. Each workflow with an [Agent Node](../nodes/agent-node.md) can expose its tools via MCP; toggle per workflow from this tab. Clients connect to the [SSE](./sse-streaming.md) endpoint at `/api/mcp/sse`.

See also [Agent Architecture](./agent-architecture.md), [Agent Node](../nodes/agent-node.md), and [SSE Streaming](./sse-streaming.md).

<video src="/features/showcase/mcp.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/mcp.webm">▶ Watch MCP demo</a></p>

### [Traces](../tabs/traces-tab.md)

The Traces tab shows [LLM](../nodes/llm-node.md) execution traces. View a paginated list filtered by credential or source; open a trace to see request and response payloads, timing breakdown (llm_ms, tools_ms, mcp_list_ms), tool calls (name, arguments, result), and skills included. Use it to debug [Agent Node](../nodes/agent-node.md) and [LLM](../nodes/llm-node.md) behavior and to copy or export payloads.

See also [Execution History](./execution-history.md), [Agent Node](../nodes/agent-node.md), and [LLM](../nodes/llm-node.md).

<video src="/features/showcase/traces.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/traces.webm">▶ Watch Traces demo</a></p>

### [Analytics](../tabs/analytics-tab.md)

The Analytics tab shows execution metrics and trends. Summary stats include total executions, success rate, error rate, and latency breakdowns. Select a base time range (24h, 7d, 30d, or all), optionally filter by workflow, then drag across any chart to drill into a selected date range. Charts and workflow tables refresh to the selection, and auto refresh keeps metrics updated. It complements [Execution History](./execution-history.md) and the [Scheduled](../tabs/scheduled-tab.md) view when you need both past results and upcoming runs.

See also [Execution History](./execution-history.md), [Scheduled](../tabs/scheduled-tab.md), and [Evals](../tabs/evals-tab.md).

<video src="/features/showcase/analytics.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/analytics.webm">▶ Watch Analytics demo</a></p>

### [Evals](../tabs/evals-tab.md)

The Evals tab (at `/evals`) lets you create evaluation suites, add or generate test cases, optimize the suite prompt, and run evaluations against [Agent Node](../nodes/agent-node.md) workflows. Select one or more models, choose a scoring method (Exact Match, Contains, or LLM-as-Judge), optionally configure a separate judge model, set temperature/reasoning effort/runs-per-test, then compare pass/fail and per-model outputs. Review run history for past evaluations and cross-check the underlying behavior in [Traces](../tabs/traces-tab.md).

See also [Agent Node](../nodes/agent-node.md), [Traces](../tabs/traces-tab.md), and [Execution History](./execution-history.md).

<video src="/features/showcase/evals.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/evals.webm">▶ Watch Evals demo</a></p>

### [Teams](../tabs/teams-tab.md)

The Teams tab lets you create and manage teams. Create a team, add members by email, and remove members (creator cannot be removed). Share [workflows](../tabs/workflows-tab.md), [templates](../tabs/templates-tab.md), [credentials](../tabs/credentials-tab.md), [variables](../tabs/global-variables-tab.md), and [vector stores](../tabs/vectorstores-tab.md) with teams from their respective share dialogs; all team members gain access. Edit team name and description or delete the team (removes all team shares).

See also [Teams](./teams.md), [Credentials Sharing](./credentials-sharing.md), and [Workflow Organization](./workflow-organization.md).

<video src="/features/showcase/teams.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/teams.webm">▶ Watch Teams demo</a></p>

### [Scheduled](../tabs/scheduled-tab.md)

The Scheduled tab shows all active [Cron](../nodes/cron-node.md) workflows on a visual calendar. Switch between day, week, and month views to see when your automations are scheduled to run, then jump back to the related [workflow](../tabs/workflows-tab.md) when you need to edit the schedule.

See also [Cron](../nodes/cron-node.md), [Analytics](../tabs/analytics-tab.md), and [Execution History](./execution-history.md).

<video src="/features/showcase/scheduled.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/scheduled.webm">▶ Watch Scheduled demo</a></p>

### [Logs](../tabs/logs-tab.md)

The Logs tab shows Docker container logs for the Heym stack (backend, frontend, PostgreSQL). Select container(s), filter by log level (All, INFO, WARNING, ERROR, DEBUG), and search within logs. Use it for debugging and troubleshooting. For workflow execution logs (node results, outputs), use [Execution History](./execution-history.md), [Traces](../tabs/traces-tab.md), or the Debug panel in the editor instead.

See also [Execution History](./execution-history.md), [Traces](../tabs/traces-tab.md), and [Canvas Features](./canvas-features.md).

<video src="/features/showcase/logs.mp4" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/logs.mp4">▶ Watch Logs demo</a></p>

### [DataTable](../tabs/datatable-tab.md)

The DataTable tab lets you create and manage structured data tables within Heym. Define typed columns (string, number, boolean, date, JSON), manage rows with inline double-click editing, import/export CSV, and share tables with users or [teams](./teams.md) with read/write permissions. Use the [DataTable node](../nodes/datatable-node.md) to access tables programmatically in workflows.

See also [DataTable node](../nodes/datatable-node.md), [Workflow Structure](./workflow-structure.md), and [Teams](./teams.md).

<video src="/features/showcase/datatable.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/datatable.webm">▶ Watch DataTable demo</a></p>

### [Drive](../tabs/drive-tab.md)

The Drive tab shows all files generated by skills across your workflows. It lists each file with name, type, size, source node, creation date, and provides search, download, share, delete, and pagination controls. It is the dashboard companion to [File Generation](./file-generation.md), the [Drive](./drive.md) reference, and the [Drive node](../nodes/drive-node.md).

See also [Drive](./drive.md), [File Generation](./file-generation.md), and [Drive node](../nodes/drive-node.md).

<video src="/features/showcase/drive.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/drive.webm">▶ Watch Drive demo</a></p>
