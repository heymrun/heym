# Heym

The **Heym** node reads workflows, execution history, and [kanban boards](../tabs/board-tab.md), and sends messages to [Heym Chat](../tabs/chat-tab.md). Use it to build instance inventories, execution digests, or reports about cards on a board, or to hand a task to the Heym assistant from a workflow.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1, or 2 (OUT and QUESTION) with Send Chat Message while it waits for the reply and saves chat history |
| Operations | `listWorkflows`, `getWorkflow`, `getExecutionHistory`, `getBoard`, `getBoardColumn`, `getBoardCardId`, `sendChatMessage` |
| Credential | None required |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `heymOperation` | Select | Which read to perform |
| `heymWorkflowId` | UUID | Target workflow. Required for `getWorkflow` and `getExecutionHistory`. Set it to `all` on `getExecutionHistory` to read every workflow you can reach. Expression-capable. |
| `heymLimit` | String | Maximum rows to return. **Leave it empty or enter `0` to return everything** — that is the default. Expression-capable. |
| `heymStatus` | String | Optional status filter for `getExecutionHistory`. Expression-capable. |
| `heymSinceDays` | String | Optional lookback in days for `getExecutionHistory`. Expression-capable. |
| `heymBoardId` | UUID | **Board ID** for `getBoard`. Use the board UUID from the Board tab URL. |
| `heymBoardColumnId` | UUID | **Column ID** for `getBoardColumn`. Use a column UUID from `getBoard`. |
| `heymBoardCardId` | UUID | **Card ID** for `getBoardCardId`. Use a card UUID from `getBoardColumn` or the last segment of the card URL. |
| `heymChatMessage` | String | **Message** for `sendChatMessage`. Required, up to 20,000 characters. Expression-capable. |
| `heymChatNoHistory` | Boolean | **Don't save chat history**. Off by default. |
| `heymChatContinue` | Boolean | **Continue a conversation**. Off by default. Cannot be on together with **Don't save chat history**. |
| `heymChatConversationId` | UUID | **Conversation ID** to continue. Shown when **Continue a conversation** is on. Expression-capable. |
| `heymChatFireAndForget` | Boolean | **Don't wait for the reply**. Off by default. |

The workflow picker is a searchable dropdown listing every workflow you can reach. For Get Execution History, its first item is **All workflows**.

Use the searchable picker to select an accessible board by name. For a column or card, select its board first, then choose the column by name or the card by title. The selection fills the corresponding ID field. You can also type a UUID or an expression directly into that field. When Heym is connected as an Agent tool, use the Agent icon beside the ID to let the agent supply it at runtime.

## Access Scope

Results are scoped to **the user the run belongs to**, the same user its credentials and global variables resolve for:

- **Someone runs the workflow.** A run started from the canvas, the API, an execution token, Chat or MCP reads with the reach of the person who started it. A collaborator who runs a shared workflow sees the workflows they can open themselves, not the owner's.
- **Nobody runs it.** Cron, portal, platform event, anonymous webhook and other triggered runs belong to the **workflow owner**, so the node reads with the owner's reach.

For that user, the visible set is:

- workflows they own,
- workflows shared with them directly,
- workflows shared with a team they belong to,
- every workflow on the instance when they are an [instance administrator](../tabs/workflows-tab.md#instance-administration).

The same workflow can therefore return different results depending on who runs it. A scheduled report built on this node returns the owner's view on every Cron run, while a teammate testing it from the editor sees their own.

> **Write access reaches triggered runs.** Anyone with **Write** on a workflow can put a Cron or another trigger in front of a Heym node. That run belongs to the owner, so it reads with the owner's reach, and its output lands in the workflow's run history, which collaborators can open. Give **Read** to people who should not reach what you can, see [Sharing Workflows](../reference/workflow-organization.md#sharing-workflows). To keep a workflow's run data out of every Heym node, switch on [Encrypt run history](../reference/run-history-encryption.md): encrypted runs are counted but never listed. Keep secrets in credentials rather than pasting them into node fields, because **Get Workflow** returns node configuration as it was saved.

A workflow you cannot reach and a workflow that does not exist produce the same error message, so the node cannot be used to probe for workflow ids.

Board operations use board permissions. The run's user can read boards they own or that are shared with them directly or through a team. Columns and cards inherit access from their parent board.

**Send Chat Message** follows the same rule: the message goes to the Chat of the person who ran the workflow, and to the workflow owner's Chat on a Cron, portal, event or other triggered run. A collaborator who runs a shared workflow writes to their own Chat with their own default model, never to the owner's. Because a **Write** collaborator can put a trigger in front of the node, they can make the owner's Chat act, building workflows included, the same way triggered runs use the owner's credentials. Share **Read** with people who should not.

## Operations

### List Workflows

Returns every workflow the run's user can reach, most recently updated first.

| Expression | Description |
|------------|-------------|
| `$nodeLabel.workflows` | Array of workflow summaries |
| `$nodeLabel.workflows[0].id` | Workflow UUID |
| `$nodeLabel.workflows[0].name` | Workflow name |
| `$nodeLabel.workflows[0].description` | Description, or `null` |
| `$nodeLabel.workflows[0].active` | Whether the workflow is active |
| `$nodeLabel.workflows[0].folder_id` | Folder UUID, or `null` |
| `$nodeLabel.workflows[0].updated_at` | ISO timestamp of the last save |
| `$nodeLabel.workflows[0].node_count` | How many nodes the workflow contains |
| `$nodeLabel.total` | Full accessible count **before** the limit is applied |

`total` is deliberately the unlimited count, so `$inventory.total` still reports the real size when you cap the returned rows. Clearing **Limit**, or setting it to `0`, returns every workflow — which is the default.

### Get Workflow

Returns one workflow's identity and shape.

| Expression | Description |
|------------|-------------|
| `$nodeLabel.id`, `$nodeLabel.name`, `$nodeLabel.description` | Workflow identity |
| `$nodeLabel.active`, `$nodeLabel.folder_id`, `$nodeLabel.updated_at` | Workflow metadata |
| `$nodeLabel.node_count` | Number of nodes |
| `$nodeLabel.nodes` | Array of `{ id, type, label, position, data }` |
| `$nodeLabel.edges` | Array of `{ id, source, target, sourceHandle, targetHandle }` |

`data` is the **full node configuration** — every field as it was saved. That is what makes auditing possible: you cannot scan a workflow for an API key someone pasted into a field if the node refuses to show the field.

This grants no reach the run's user did not already have. The node is scoped to workflows that user can open in the editor anyway (the owner, on a triggered run), and stored credential secrets are still not here: node data holds only credential **ids**, while the secrets themselves live encrypted in the credentials table.

### Scanning for hardcoded secrets

```
cron → heym (listWorkflows) → loop → heym (getWorkflow) → agent → slack
```

Give the agent `$detail.nodes` and ask it to flag any `data` value that looks like a live key or token. Fields worth watching are the free-text ones — `curl` on HTTP nodes, `userMessage` and `systemInstruction` on LLM and Agent nodes, and Python tool bodies — because a credential id is a harmless UUID, but a pasted `sk-…` is not.

### Get Execution History

Returns execution-history entries for one workflow, or for every workflow you can reach when you pick **All workflows**, newest first.

| Expression | Description |
|------------|-------------|
| `$nodeLabel.executions` | Array of history entries |
| `$nodeLabel.executions[0].id` | Execution UUID |
| `$nodeLabel.executions[0].status` | `success`, `error`, and so on |
| `$nodeLabel.executions[0].started_at` | ISO timestamp |
| `$nodeLabel.executions[0].execution_time_ms` | Wall-clock duration |
| `$nodeLabel.executions[0].trigger_source` | What started the run, for example `cron` or `heym_event` |
| `$nodeLabel.executions[0].recovered` | Whether the run was recovered after a crash |
| `$nodeLabel.executions[0].inputs` | What the run received - the trigger payload or the caller's input |
| `$nodeLabel.executions[0].outputs` | The workflow's output for that run |
| `$nodeLabel.workflow_id`, `$nodeLabel.workflow_name` | The workflow the history belongs to, or `null` with **All workflows** |
| `$nodeLabel.executions[0].workflow_id`, `$nodeLabel.executions[0].workflow_name` | With **All workflows**, the workflow each run belongs to |
| `$nodeLabel.total` | Total matching executions **before** the limit |
| `$nodeLabel.by_status` | Counts keyed by status, for example `{ "success": 41, "error": 3 }` |
| `$nodeLabel.since` | Start of the window, or `null` for the full history |
| `$nodeLabel.encrypted_skipped` | Runs left out of `executions` because their workflow [encrypts its run history](../reference/run-history-encryption.md) |

Entries carry both `inputs` and `outputs` - what the run received and what it answered - but never `node_results`: the per-node trace is the largest column in the table and would dwarf everything downstream. Fetch a single execution through the API when you need the full trace.

`total` and `by_status` always describe the **whole** matching history, even when **Limit** caps the returned entries — so you can pull the five most recent runs and still report an accurate failure count.

Leave **Since (days)** empty to cover everything, **Status filter** empty to include every status, and **Limit** empty or `0` to return every entry.

**All workflows** covers the same set as [List Workflows](#list-workflows), and `total` and `by_status` then count runs across all of it. It answers instance-wide questions in a single node, such as how many runs failed in the last day, without looping over the workflow list first.

### Board reads

| Operation | Result |
|-----------|--------|
| **Get Board** (`getBoard`) | The board's `id`, `name`, `description`, `auto_advance`, and `columns` in board order. Each column has `id`, `board_id`, `name`, `position`, and `color`. |
| **Get Board Column** (`getBoardColumn`) | The column's fields, `ai_instructions`, and `cards` in column order. Each card has `id`, `board_id`, `column_id`, `title`, `position`, `run_status`, and `path`. An empty column returns `cards: []`. |
| **Get Board Card by ID** (`getBoardCardId`) | The card's fields plus `content`, `card_metadata`, `created_at`, and `updated_at`. The `fields` object contains `assignee_user_id`, `priority`, `due_date`, and `labels`. |

For example, set **Board ID** to `$input.board_id` on a node labelled `board`. On the next Heym node, labelled `column`, set **Column ID** to `$board.columns[0].id`. If the column has cards, pass `$column.cards[0].id` to **Get Board Card by ID**. Use the returned `path` with your Heym address to link directly to the card.

Use `$board.columns[0].name` for the column name and `$column.cards[0].title` for the card's display name.

### Send Chat Message

Sends one message to [Heym Chat](../tabs/chat-tab.md), the same assistant as the Chat tab, MCP `heym_chat` and A2A. It can answer, use its tools, run workflows and build: save, test and finish workflows, and create skills. The turn uses the **Chat default model** of the user the run belongs to, so the node has no model or credential field. Pick that model in the Chat tab; without one the node fails and says so.

| Switch | Off (default) | On |
|--------|---------------|----|
| **Don't save chat history** | The turn is saved as a conversation in the Chat tab, shown with a workflow icon | The turn runs in a temporary conversation that is never listed and is deleted when the turn ends |
| **Continue a conversation** | A new conversation starts | The message is written into the conversation in **Conversation ID** |
| **Don't wait for the reply** | The node waits for the reply | The node returns as soon as the message is accepted; the turn finishes in the background |

**Don't save chat history** and **Continue a conversation** cannot both be on: a conversation that is continued is saved.

With **Continue a conversation**, a conversation that was deleted, does not exist, or belongs to someone else fails the node with `Conversation not found or not accessible`. The node never starts a new conversation instead. A conversation that is still running fails the node too. With **Don't wait for the reply** these checks still happen before the node returns.

**Outputs.** While the node waits for the reply and saves chat history, it has two outputs:

| The turn ends with | Output | `status` |
|--------------------|--------|----------|
| A reply | OUT | `completed` |
| Stop in the Chat tab while the node waits | OUT | `canceled` |
| A clarifying question | QUESTION | `input_required` |
| A credential form to fill in | QUESTION | `auth_required` |

The QUESTION output does not pause the run. Connect it to a node that asks a person, for example Slack or email, and answer in a later run with **Continue a conversation** and the same `conversation_id`.

With **Don't wait for the reply** the reply never reaches the node, and with **Don't save chat history** the conversation is deleted, so a question could not be answered later. In both cases the node has only OUT: it fires with `status: "started"` without waiting, and with every `status`, `input_required` included, without history. Turning either switch on removes the edges that left QUESTION.

| Expression | Description |
|------------|-------------|
| `$nodeLabel.conversation_id` | The conversation the message went to, or `null` without history |
| `$nodeLabel.status` | `completed`, `canceled`, `input_required`, `auth_required`, or `started` |
| `$nodeLabel.reply` | The assistant's reply |
| `$nodeLabel.questions` | On QUESTION, the clarifying questions it asked, each with `id`, `question` and `type`, plus `options` when it offers choices; `[]` otherwise |
| `$nodeLabel.tool_names` | The tools the turn used |
| `$nodeLabel.verified` | `true` when the turn saved a workflow whose latest test run passed |
| `$nodeLabel.workflow_links` | `{ name, url }` for each workflow the turn saved |
| `$nodeLabel.eval_suite_links` | `{ name, url }` for each eval suite the turn saved |
| `$nodeLabel.credential_form_urls` | Credential forms to open in Heym, on `auth_required` |

Without waiting, the output is only `conversation_id` and `status: "started"`.

**Stopping and timeouts.** Stopping the run, or reaching the workflow timeout, while the node waits also stops the chat turn. A turn started with **Don't wait for the reply** keeps running after the workflow ends; stop it from the Chat tab.

**Loops.** A chat turn can run a workflow that sends a chat message again. Each such hop, and each sub-workflow call, counts toward a limit of 5; the next message fails with `Max Heym Chat call depth exceeded`.

**Clusters.** A workflow with this operation runs on the main instance.

## Example Workflow

**Daily instance digest**

```
cron → heym (listWorkflows) → loop → heym (getExecutionHistory) → llm → sendEmail
```

- **Heym** `listWorkflows` labelled `inventory`
- **Loop** over `$inventory.workflows`
- **Heym** `getExecutionHistory` with `heymWorkflowId` set to the loop item's `id`, `heymSinceDays` of `1`, and `heymLimit` of `5`
- **LLM** turns the collected runs and status counts into a readable summary

## Notes

- No credential is needed; the node reads the same database Heym runs on. Send Chat Message uses the run user's Chat default model.
- **Limit** is the same field for both list operations, and it means the same thing in both: empty or `0` returns everything.
- The node takes a normal input and can be attached to an Agent node as a tool, so an agent can answer questions about your Heym instance — or audit it.
- `getWorkflow` payloads grow with the workflow: long prompts and Python tool bodies all travel inside `data`.
- Pair it with [Heym Trigger](./heym-trigger-node.md) to react to workflow changes as they happen instead of polling on a schedule.

## Related

- [Heym Trigger](./heym-trigger-node.md) – Start a workflow from platform events
- [Execute](./execute-node.md) – Run another workflow rather than describe it
- [Loop](./loop-node.md) – Iterate over the returned workflow list
