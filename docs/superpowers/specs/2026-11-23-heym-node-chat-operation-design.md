# Heym node: Send Chat Message operation

Date: 2026-11-23
Status: design approved in chat, spec under review

## Goal

Let a workflow send a message to Heym Chat, the same agent the Chat tab, MCP `heym_chat`
and A2A talk to, from the existing **Heym** node. The node reads today (workflows, execution
history, boards); this adds one operation that acts.

## Decisions

| Question | Decision |
|----------|----------|
| Which LLM runs the turn | The user's Chat default only (`preferred_credential_id` + `preferred_model`). The node has no credential or model field. |
| May the turn build | Yes, like MCP `heym_chat`: save, test-run and finish workflows, `apply_skill`, eval suite tools, `insert_agent_memory`. |
| Credential questions | `CredentialPromptMode.ASK_AND_LINK`, like MCP. Nobody is in the loop to fill the in-chat dialog, so credential forms come back as links. |
| Whose chat | The person who ran the workflow (canvas, MCP, API, execution token, Chat). The workflow owner when nobody did (Cron and other triggers). |
| Continue with a missing conversation | The node fails. It never starts a new conversation instead. |
| Output handles | Two (OUT and QUESTION, like Codex) for this operation only. Other Heym operations keep one. |

## Node fields

New operation `sendChatMessage`, label **Send Chat Message**.

| Key | Type | Default | Notes |
|-----|------|---------|-------|
| `heymChatMessage` | String | `""` | Required. Expression-capable, AI autofill eligible, Agent-tool suppliable. Max 20,000 characters, same as `heym_chat`. |
| `heymChatNoHistory` | Boolean | `false` | **Don't save chat history.** |
| `heymChatContinue` | Boolean | `false` | **Continue a conversation.** |
| `heymChatConversationId` | String | `""` | Shown only while `heymChatContinue` is on. Expression-capable, AI autofill eligible, Agent-tool suppliable. |
| `heymChatFireAndForget` | Boolean | `false` | **Don't wait for the reply.** |

`heymChatNoHistory` and `heymChatContinue` are mutually exclusive. The panel disables one
while the other is on; the handler rejects a node that has both on (`ValueError`), so an
AI-written or imported node cannot reach a contradictory state.

## Behaviour matrix

| No history | Continue | Fire and forget | What happens | Output |
|---|---|---|---|---|
| off | off | off | New conversation, `source="workflow"`, turn runs, node waits | full result |
| off | on | off | Turn appended to the given conversation, node waits | full result |
| on | off | off | Temporary conversation, turn runs, conversation deleted, node waits | full result, `conversation_id: null` |
| off | off | on | New conversation, turn started, node returns at once | `{conversation_id, status: "started"}` |
| off | on | on | Turn started in the given conversation, node returns at once | `{conversation_id, status: "started"}` |
| on | off | on | Temporary conversation, turn started, deleted when the turn ends | `{conversation_id: null, status: "started"}` |

Full result (wait mode):

```json
{
  "conversation_id": "uuid or null",
  "status": "completed | input_required | auth_required | canceled",
  "reply": "assistant text, without a clarify block",
  "questions": [{"id": "q1", "question": "...", "type": "text"}],
  "tool_names": ["..."],
  "verified": false,
  "workflow_links": [{"name": "...", "url": "..."}],
  "eval_suite_links": [{"name": "...", "url": "..."}],
  "credential_form_urls": ["..."]
}
```

`status` is `AgentOutcome`. A clarifying question (`input_required`) or an open credential
form (`auth_required`) does not fail the node; it leaves through the **question** handle (see
below). A temporary conversation is deleted when the turn ends, so its question cannot be
answered later; the docs say so and recommend leaving history on when the prompt may need
clarification.

### Two output handles

With **Send Chat Message** selected the Heym node has two output handles, like Codex:
`output` (OUT) and `question` (QUESTION). Every other Heym operation keeps its single output.
The optional error handle (`onErrorEnabled`) works as on any node, independent of these two.

| Turn ends with | Handle that fires | Output carries |
|----------------|-------------------|----------------|
| `completed` | `output` | full result |
| `canceled` (Chat tab Stop while the node waits) | `output` | full result, `status: "canceled"` |
| `input_required` (clarifying question) | `question` | full result; `questions` holds the parsed `heym-clarify` questions |
| `auth_required` (credential form opened) | `question` | full result; `credential_form_urls` holds the links |
| fire and forget | `output` | `{conversation_id, status: "started"}` |

Routing uses the existing `_skip_source_handles` mechanism: the handler returns
`["question"]` or `["output"]`. Unlike Codex, the question branch does not pause the run. It
hands the question and `conversation_id` to the next node, for example a Slack or email node
that asks a person. A later run answers by sending the reply with **Continue a conversation**
and that `conversation_id`.

In fire and forget mode the reply never reaches the node, so the `question` handle never
fires; it stays on the node so edges do not disappear when the toggle changes.

Canvas: `BaseNode.vue` shows the QUESTION handle when `type === "heym"` and
`heymOperation === "sendChatMessage"`. Switching to another operation removes edges that
leave the `question` handle, so no edge points at a handle that is gone. The plan step checks
that `_skip_source_handles: ["output"]` also skips edges saved with a `null` source handle,
which existing single-output Heym nodes may have.

## Architecture

### Reuse the agent turn

`run_agent_chat_turn` in `backend/app/api/chats.py` already runs one Chat turn for MCP and
A2A: it creates or resolves the conversation, persists messages and tool calls, registers
the task so Chat tab Stop works, streams to any open Chat tab and returns an
`AgentTurnResult`. The node calls it through `run_agent_turn` with `source="workflow"` and
`AgentSettings(enabled=True, credential_id=None, model=None)`, which makes
`resolve_agent_llm` fall back to the Chat default. The MCP/A2A-specific wording in
`resolve_agent_llm` errors ("Open the MCP / A2A tab") is wrong for this surface; the node
maps `AgentError` to a message that points at the Chat tab's model picker.

### Run on the application event loop

Node handlers are synchronous and run in executor threads (`asyncio.to_thread`). The chat
turn needs the application loop: the async engine's pooled asyncpg connections, `_chat_tasks`,
the chat task registry and `chat_stream_bus` all belong to it. `run_async` (a fresh
`asyncio.run` loop) would hand pooled connections across loops and break.

New module `backend/app/services/app_loop.py`:

- `set_app_loop(loop)` called once from `main.py` lifespan;
- `submit(coro) -> concurrent.futures.Future` wrapping `asyncio.run_coroutine_threadsafe`;
- raises a clear error when no loop is registered (scripts, tests without lifespan).

Wait mode: the handler polls `future.result(timeout=0.5)` in a loop and calls
`ctx.executor.check_cancelled()` between polls. On `WorkflowCancelledError` (Stop or
workflow timeout) it calls `future.cancel()`, which cancels the turn task like Chat tab Stop,
then re-raises.

Fire and forget: the handler waits only until the conversation exists and its user message
is committed (so `conversation_id` is real and "already running" errors still surface), then
returns. The rest of the turn runs on the app loop and outlives the workflow run. A process
restart loses it, exactly like a Chat tab turn; existing recovery clears `is_running`.

To get the id early, the coroutine creates the conversation first (`create_agent_conversation`)
for new and temporary conversations, then runs the turn with that id. A small
`asyncio.Event`/future pair reports "accepted or refused" back to the thread.

### Temporary conversations (no history)

The turn runs in a normal conversation created with `source="workflow_temp"`; a `finally`
in the submitted coroutine deletes it (messages cascade) whether the turn completed, failed
or was cancelled. `GET /api/chats` excludes `workflow_temp`, so it never shows up while it
runs. Heym Work reads the same table for its chat list; the matching filter there is a
separate change in the heym-work repo, made after this one merges. User memory written during the turn (Chat user memory) stays;
only the conversation is removed. The docs state that.

### Continue a conversation

`heymChatConversationId` is resolved through `_resolve`, parsed as a UUID and passed as
`conversation_id`. `_get_or_create_agent_conversation` already scopes it to the run's user and
refuses one that is running.

If the conversation cannot be found, the node **fails**. That covers a deleted chat history,
an id that is not a UUID, an empty id, and a conversation that belongs to someone else. It
never falls back to starting a new conversation. All of these produce the same message,
"Conversation not found or not accessible: <id>", so the node cannot be used to probe for
other users' conversation ids. With the error handle on, the failure leaves through `error`
like any node error. In fire and forget mode the check happens before the node returns, so a
missing conversation fails the node there too.

### Whose chat the message goes to

The message goes to the chat of **the person who ran the workflow**, when Heym knows who
that is. That is the run's actor (`executor.actor_user_id`), the same user recorded as
executed-by in the run history:

- run from the canvas: the person in the editor;
- run over MCP, the API with a signed-in session or API key, an execution token, or Chat: the
  authenticated caller.

A collaborator who runs a shared workflow therefore writes to their own Chat, with their own
Chat default model, and never touches the owner's.

When nobody runs the workflow (Cron, portal, platform event, anonymous webhook and other
triggers), there is no caller to recognise, and the message goes to the **workflow owner's**
chat. This is the existing `_run_user_id` rule, the same one the read operations and
credentials follow. The node's Access Scope section in the docs states both cases.

### Recursion guard

A chat turn can run workflows; a workflow can send a chat message. Without a guard, a prompt
like "run workflow A" inside workflow A loops forever, and fire and forget makes it free to do
so.

- New ContextVar `chat_workflow_depth` (in `app_loop.py` or a sibling module). The submitted
  coroutine sets it to `executor depth + 1` before the turn task is created; `create_task`
  copies the context, so every tool call in the turn sees it.
- Chat paths that start a workflow run pass `sub_workflow_invocation_depth=chat_workflow_depth.get()`
  into the executor: the dashboard chat run tool in `ai_assistant.py`, build test runs in
  `chat_build.py`, and dashboard widget runs in `dashboard_data.py`. The plan step verifies
  this list against every `execute_workflow` / `dispatch_workflow` call reachable from a turn.
- The handler refuses when `ctx.executor._sub_workflow_invocation_depth >= 5`, the limit the
  Execute node and Agent sub-workflow tools already use, with the same message style.

### Cluster placement

`heym` becomes a predicate in `node_placement.py`: `MAIN_ONLY` when
`heymOperation == "sendChatMessage"`, `ANYWHERE` otherwise. Reasons: the turn reads and writes
Heym Drive files through chat tools (`FILE_STORAGE_DIR`), build tools call `audit()`, which
must stay on the main instance, and the turn registers in the main process's chat task map.
`test_cluster_node_placement.py` gets a case for both branches.

### OpenCode session

The conversation id is the turn's OpenCode session, as for every Chat turn. A temporary
conversation still has a real id for its lifetime, so the header is never empty. No change
needed; a test asserts the turn receives the conversation id as its session.

### Conversation source in the UI

`ChatListItem.vue` gets a "Workflow" badge for `source === "workflow"`, next to the MCP and A2A
ones. `DashboardConversation.source` comment lists the new values. `String(20)` fits both.

## Frontend

- `heymOperationOptions` gains **Send Chat Message**.
- New `HeymChatFields.vue` under `propertiesPanel/nodes/` (keeps `HeymNodeProperties.vue`
  under 300 lines): message `ExpressionInput`, three checkboxes, conversation id
  `ExpressionInput` shown when Continue is on, mutual exclusion, help text per toggle.
- Both expression fields join the Heym expression navigation (`1/n`) and AI autofill
  metadata. The access note under Operation explains that the message is sent as the run's
  user, with their Chat default model.
- Workflow picker and Limit stay hidden for this operation.

## Docs, DSL, tour

- `workflow_dsl_prompt.py`: operation, fields, defaults, output shape, mutual exclusion.
- `frontend/src/docs/content/nodes/heym-node.md`: operation section, matrix, output, access
  and recursion notes. `reference/features.md` and `node-types.md` operation lists.
- Release tour: section in the current unreleased entry of `releaseRegistry.ts`, listed in
  `sectionOrder`, with a mock visual `HeymChatMessageTourVisual.vue` registered in
  `tourVisuals.ts`.

## Error handling

All failures raise `ValueError` with a user-facing message (node handlers already do this;
the executor packages it): empty message, message too long, both exclusive toggles on, bad or
foreign conversation id, conversation already running, no Chat default model, depth limit,
app loop missing. An `AgentError` from the turn becomes a `ValueError` with the same text,
except the model-configuration ones, which are reworded for the Chat tab.

## Tests

Backend (`unittest.IsolatedAsyncioTestCase`, `AsyncMock`):

- `test_heym_chat_node.py`: each matrix row against a stubbed `run_agent_turn`; output
  shapes; handle routing per outcome (`completed`/`canceled` skip `question`,
  `input_required`/`auth_required` skip `output`); exclusive toggles rejected; empty and
  oversized message; Continue with a deleted, missing, malformed or empty conversation id
  fails with the same message in both wait and fire and forget modes; cancel during wait
  cancels the future; depth limit refusal; temporary conversation deleted on success, error
  and cancel.
- Executor routing: a Heym chat node returning `["output"]` skips edges on `output` and on a
  `null` source handle, and runs the `question` branch.
- `test_app_loop.py`: submit from a worker thread runs on the registered loop; missing loop
  error.
- `test_cluster_node_placement.py`: both `heym` branches.
- `test_advisory_heym_chat_node_scope.py`: a foreign conversation id is refused with the
  same message as a missing one; a collaborator's canvas run writes to the collaborator's
  chat, not the owner's; a Cron run writes to the owner's chat.
- Recursion: a chat-started run carries the depth into the executor.
- Chat list excludes `workflow_temp`.

Frontend: Vitest for `HeymChatFields` mutual exclusion and field visibility, and for the
QUESTION handle appearing only for `sendChatMessage`; Playwright `heym-chat-node.spec.ts`
selects the operation, checks the node shows OUT and QUESTION, fills the message, toggles
Continue to reveal the id field, checks the exclusive toggle is disabled, and checks that
switching back to List Workflows leaves one output and drops the question edge.

## Out of scope

- Per-node credential or model selection.
- Queueing into a running conversation (Chat's queue). A running conversation is refused.
- Attachments, image input, knowledge base selection in the node.
- Waiting for a credential form (`wait_for_credential_form`).
