# Node Types

Heym provides a variety of node types for building workflows. Use [expressions](./expression-dsl.md) like `$input.text` and `$nodeLabel.field` in node configuration.

## Trigger Nodes

| Node | Description | Outputs |
|------|-------------|---------|
| [Input](../nodes/input-node.md) | Text entry point for the workflow (HTTP/[webhook](./webhooks.md)) | 1 |
| [Cron](../nodes/cron-node.md) | Trigger on a schedule (cron expression) | 1 |
| [Telegram Trigger](../nodes/telegram-trigger-node.md) | Trigger when a Telegram bot webhook update arrives | 1 |
| [IMAP Trigger](../nodes/imap-trigger-node.md) | Trigger when a new email arrives in an IMAP mailbox | 1 |
| [WebSocket Trigger](../nodes/websocket-trigger-node.md) | Trigger from an outbound connection to an external WebSocket server | 1 |
| [RabbitMQ](../nodes/rabbitmq-node.md) | Trigger when a message is received from a queue | 1 |
| [Error Handler](../nodes/error-handler-node.md) | Run when any node errors (no incoming edge) | 1 |

See [Triggers](./triggers.md) for all entry points.

## AI Nodes

| Node | Description | Inputs | Outputs |
|------|-------------|--------|---------|
| [LLM](../nodes/llm-node.md) | Process text with a language model | 1 | 1 |
| [AI Agent](../nodes/agent-node.md) | LLM with tool calling, skills, MCP, optional [human review](./human-in-the-loop.md), and optional [persistent memory graph](./agent-persistent-memory.md). See [Agent Architecture](./agent-architecture.md). | 1 | 1, plus optional `review` output |
| [Qdrant RAG](../nodes/rag-node.md) | Insert or search in [vector store](../tabs/vectorstores-tab.md) for RAG | 1 | 1 |

## Logic Nodes

| Node | Description | Inputs | Outputs |
|------|-------------|--------|---------|
| [Condition](../nodes/condition-node.md) | Branch based on if/else | 1 | 2 (true/false) |
| [Switch](../nodes/switch-node.md) | Route by matching a value to cases | 1 | n |
| [Merge](../nodes/merge-node.md) | Wait for multiple inputs and merge | n | 1 |
| [Loop](../nodes/loop-node.md) | Iterate over an array | 1 | 2 (loop/done) |

## Data Nodes

| Node | Description | Inputs | Outputs |
|------|-------------|--------|---------|
| [Set](../nodes/set-node.md) | Transform and map data | 1 | 1 |
| [Variable](../nodes/variable-node.md) | Set or get a variable (workflow-local or [global](./global-variables.md)) | 1 | 1 |
| [Execute](../nodes/execute-node.md) | Call another workflow | 1 | 1 |

## Integration Nodes

| Node | Description | Inputs | Outputs |
|------|-------------|--------|---------|
| [HTTP](../nodes/http-node.md) | Make HTTP requests (cURL) | 0 or 1 | 1 |
| [WebSocket Send](../nodes/websocket-send-node.md) | Connect to an external WebSocket and send one message | 1 | 1 |
| [Telegram](../nodes/telegram-node.md) | Send Telegram bot messages | 1 | 1 |
| [Slack](../nodes/slack-node.md) | Send Slack messages | 1 | 1 |
| [Send Email](../nodes/send-email-node.md) | Send emails via SMTP | 1 | 1 |
| [Redis](../nodes/redis-node.md) | Redis operations (set, get, hasKey, deleteKey) | 1 | 1 |
| [Grist](../nodes/grist-node.md) | Read/write Grist spreadsheets | 1 | 1 |
| [Google Sheets](../nodes/google-sheets-node.md) | Read/write Google Sheets via OAuth2 | 1 | 1 |
| [BigQuery](../nodes/bigquery-node.md) | Run SQL queries and insert rows in BigQuery | 1 | 1 |
| [DataTable](../nodes/datatable-node.md) | Read/write Heym DataTables (first-party storage) | 1 | 1 |
| [Drive](../nodes/drive-node.md) | Manage Drive files: delete, set password, TTL, max downloads | 1 | 1 |

## Automation Nodes

| Node | Description | Inputs | Outputs |
|------|-------------|--------|---------|
| [Crawler](../nodes/crawler-node.md) | Scrape web pages with FlareSolverr | 1 | 1 |
| [Playwright](../nodes/playwright-node.md) | Browser automation with AI step and Auto Heal | 1 | 1 |

## Utility Nodes

| Node | Description | Inputs | Outputs |
|------|-------------|--------|---------|
| [Wait](../nodes/wait-node.md) | Delay execution | 1 | 1 |
| [Output](../nodes/output-node.md) | Output endpoint | 1 | 1 |
| [JSON output mapper](../nodes/json-output-mapper-node.md) | Map fields to a JSON object; sole terminal = top-level webhook/run body | 1 | 0 |
| [Sticky Note](../nodes/sticky-note-node.md) | Add markdown notes to the canvas (not executed) | 0 | 0 |
| [Console Log](../nodes/console-log-node.md) | Log to backend console | 1 | 1 |
| [Disable Node](../nodes/disable-node.md) | Disable another node in the workflow | 1 | 1 |
| [Throw Error](../nodes/throw-error-node.md) | Stop workflow with error response | 1 | 0 |

## Related

- [Canvas Features](./canvas-features.md) – Data pin, execution logs, enable/disable, extract to sub-workflow
- [Agent Node](../nodes/agent-node.md) – Detailed reference for the AI Agent node
- [Agent Architecture](./agent-architecture.md) – Sub-agents, orchestrator, skills, MCP, tool calling
- [Agent Persistent Memory](./agent-persistent-memory.md) – Per-node knowledge graph, sharing, and background extraction
- [Human-in-the-Loop](./human-in-the-loop.md) – Pause agent output for human approval
- [Expression DSL](./expression-dsl.md) – Referencing data in node config
- [Expression Evaluation Dialog](./expression-evaluation-dialog.md) – Expandable editor with live backend preview
- [WebSocket Trigger](../nodes/websocket-trigger-node.md) – Realtime outbound socket trigger
- [WebSocket Send](../nodes/websocket-send-node.md) – Push messages to external sockets
- [Workflow Structure](./workflow-structure.md) – JSON format for nodes and edges
- [Triggers](./triggers.md) – All workflow entry points
- [Credentials Tab](../tabs/credentials-tab.md) – Add API keys for LLM, HTTP, and other nodes
- [Credentials Sharing](./credentials-sharing.md) – Share credentials with other users
- [Portal](./portal.md) – Expose workflows as public chat UIs
- [Vectorstores Tab](../tabs/vectorstores-tab.md) – Create vector stores for RAG nodes
