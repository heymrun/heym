# Execution History: Ask AI and Run Timeline: Design

Date: 2026-10-22
Status: approved

## Goal

Two additions to the **Execution History** dialogs: the canvas dialog (`ExecutionHistoryDialog.vue`, opened from the editor) and the All History dialog (`ExecutionHistoryAllDialog.vue`, opened from the dashboard, Evals, Docs, Board and Chats). In All History both appear only for workflow runs (`run_type === "workflow"` with a `workflow_id`), never for chat or assistant runs.

1. **Ask AI.** A sparkle button next to the dialog title opens the Chat tab with the workflow and the selected run attached as removable context chips. The user then asks a question ("why did this workflow slow down?", "what was the error here, can you fix it?") and the chat model reads that run itself.
2. **Run timeline.** The run detail can switch from the node log list to a span timeline that shows how long each node took and where it sat in the run.

## Decisions

| Topic | Decision |
|---|---|
| Scope | Both history dialogs. All History shows Ask AI and the toggle for workflow runs only. Shared pieces: `ExecutionHistoryAskAiButton.vue`, `ExecutionHistoryViewToggle.vue`, `ExecutionHistoryTimeline.vue`. |
| Chat opens | Same tab. `/chats` creates a new conversation, like the showcase "Ask about this page" flow. |
| Context transport | A sessionStorage draft plus a window event, mirroring `showcaseChatDraft.ts`. Survives a reload before the draft is consumed. |
| Context in the message | Appended to the user message as a `[HEYM CONTEXT]` block that carries full IDs. The UI renders it as chips in the sent bubble. |
| Timeline placement | One ghost button next to Expand All / Collapse All that names the view it switches to: **Timeline** (timer icon) from the logs, **Logs** (list icon) from the timeline. A two-tab segmented control and an active-state toggle were tried first and dropped on the user's feedback. |
| Timeline renderer | The existing `ExecutionTimeline.vue` from the Debug panel. No new chart. |
| Backend | One change: conversation titles stop at the context block. The chat tools that read runs already exist. |
| Release tour | None, by the user's call. |

## 1. Ask AI

### Button

- Rendered in the `Dialog` `header-actions` slot, so it sits right of the title behind the divider (and wraps to its own row on mobile like other header actions).
- `Button` `variant="outline"` `size="sm"`, `Sparkles` icon, label **Ask AI**, `data-testid="execution-history-ask-ai"`.
- Disabled when no run is selected or the workflow has no id.
- On click: save the context draft, emit `close`, `router.push("/chats")`.

### Context items

```ts
interface ChatContextItem {
  kind: "workflow" | "execution";
  /** Workflow id for both kinds; an execution is looked up through its workflow. */
  workflowId: string;
  /** Display name of the workflow (workflow kind). */
  workflowName?: string;
  /** Execution history row id (execution kind). */
  executionId?: string;
}
```

The dialog produces two items: the open workflow (`currentWorkflow.id`, `currentWorkflow.name`) and the selected run (`selectedEntry.id`, plus the workflow id).

Chip labels stay short:

- `Workflow: <name>`, truncated with CSS (`max-w` + `truncate`), full name in `title`.
- `Execution: <first 8 chars>…`, full id in `title`.

### Draft hand-off

`frontend/src/lib/chatContext.ts` holds the draft helpers next to the format helpers:

- `saveChatContextDraft(items)` writes JSON to sessionStorage key `heym-chat-context-draft` and dispatches `heym:chat-context-draft`.
- `hasChatContextDraftPending()` and `consumeChatContextDraft()` mirror the showcase draft API. Consume validates the shape and drops anything malformed.

`ChatsView.vue` already creates a conversation on mount when a showcase draft is pending and no conversation id is in the route. It also does so when a context draft is pending.

`ChatConversation.vue` consumes the draft on mount and on the event into a `contextItems` ref, and focuses the input.

### Composer

- A new `ChatContextChips.vue` (props: `items`, `removable`; emits `remove(index)`) renders the chips. It is used in the composer and in user bubbles.
- In the composer the chips appear in the row above the textarea that already holds the attachment chip. That row shows when there are queued messages, an attachment, or context items.
- Each chip has an `X` button (`aria-label="Remove workflow context"` / `"Remove execution context"`). A removed chip is not sent.
- Sending still requires typed text. Chips alone do not enable the send button.
- `contextItems` is cleared after the message is handed to the store. Follow-ups do not repeat it; the context lives in the conversation history.

### Message format

`appendChatContext(text, items)` returns the text unchanged when `items` is empty, else:

```
<question>

[HEYM CONTEXT]
- Workflow: Lead details (workflow_id: 9f1c2b7e-...)
- Execution: 3f2a91c4-... (workflow_id: 9f1c2b7e-...)
```

The execution line carries the workflow id because `get_workflow_run_history` needs both ids. Removing the workflow chip still leaves the run readable.

The workflow name is sanitized for the line format: newlines collapse to spaces and parentheses are kept as is (the parser reads the id from the last `(workflow_id: …)` group).

`extractChatContext(content)` returns `{ text, items }`:

- Finds the `\n\n[HEYM CONTEXT]\n` marker, reads the following `- Workflow:` / `- Execution:` lines, and removes the block (header plus the parsed lines) from the text. Any content after the block (for example an attachment block) stays in the text.
- Content without the marker, or with a marker followed by no valid line, comes back unchanged with no items.

### Where the parsed form is used

- User bubbles render `extractChatContext(msg.content).text` as markdown and the items as non-removable chips under it. This also applies to the optimistic message the store adds before the server echoes it, since it carries the same content.
- Copy message and read aloud use the extracted text.
- Queued message previews show the extracted text.
- `chat.ts` `_titleFromContent` cuts at the marker, like it cuts at `[ATTACHED FILE:`.
- Backend `chats.py` `_fallback_title_from_content` cuts at `[HEYM CONTEXT` too, so the persisted title is the question only.

### What the model does with it

Nothing new is needed on the backend. The Chat tab sends `allow_build: true`, and the chat model already has:

- `get_workflow_run_history(workflow_id, execution_id)`: inputs, outputs, and the per-node trace with errors and durations of that run.
- `get_workflow_run_history(workflow_id)`: run metadata, including the average duration, for "why did it slow down" comparisons.
- `get_workflow_definition(workflow_id, full_details)` and build mode tools to fix and test-run the workflow.

With full ids in the message, the model skips `list_workflows`.

## 2. Run timeline in the dialog

### Shared entry builder

`DebugPanel.vue` builds `timelineResults` inline: it drops condition, sticky, skipped and retry-attempt rows, folds failed retry attempts into the final row (`retryFailedAttempts`, `retryFinalAttempt`, `retryMaxAttempts`, `retryLastError`), and marks delegated sub-agent rows.

This moves to `buildTimelineEntries(rows, isSubAgentRow)` in `components/Panels/executionTimeline.ts`. The sub-agent predicate stays a parameter because it depends on the canvas nodes. A `buildDelegatedSubAgentLabelSet(nodes)` and `buildSubAgentLabelToParentId(nodes)` pair moves next to it so both callers derive the same sets. The Debug panel keeps its behavior.

### Dialog

- The section header keeps **Node Execution Logs**. On the right, before **Expand All** / **Collapse All**, a ghost button with the same classes as its neighbours switches the view (`data-testid="execution-history-timeline-toggle"`): it reads **Timeline** with a `Timer` icon in the logs, and **Logs** with a `List` icon in the timeline. The button row is `items-center` so the buttons share one baseline.
- **Expand All** and **Collapse All** only show in Logs mode.
- Timeline mode renders a new `ExecutionHistoryTimeline.vue` wrapper. It takes the selected entry's `node_results` and the run's workflow graph (`nodes`, `edges` props), builds the entries with the shared helper (sub-agent sets from the graph's nodes), and renders `ExecutionTimeline` in a bordered box that grows with its rows up to `max-h-[26rem]`, after which the timeline scrolls internally.
  - `executionRows`: the run's full `node_results`.
  - `edges`: the graph's edges (used for span inputs). The canvas dialog passes `workflowStore.nodes` / `edges`; All History has no open canvas, so it loads the run's workflow with `workflowApi.get` the first time Timeline is shown for it and caches the graph by workflow id while the dialog lives. If that load fails the timeline still draws, without span inputs and sub-agent nesting.
  - `totalTimeMs`: the run's `execution_time_ms`.
  - No server clock offset: history runs are finished, or paused for review.
- Hover, span details, image lightbox and **Open trace** come from `ExecutionTimeline` unchanged. Its `selectNode` event is not wired in the dialog.
- Runs recorded before span timing metadata existed fall back to the component's existing sequential layout.
- The toggle keeps its value while the dialog is open (switching runs keeps Timeline), and resets to Logs when the dialog closes.
- In All History the section keeps its **Steps** title; the Timeline button shows before Expand All for workflow runs only. Chat and assistant runs keep the single synthetic step list.
- Timeline tracks keep a right gutter, and a near-zero span at the very end keeps its 3px minimum inside the track, so the last bar and the end time label never touch the box border (Debug panel included).

### Dialog slot

`Dialog.vue` read `header-actions` through a `computed` over `useSlots()`, which is not reactive, so a slot that appears or disappears later (All History swaps it with the selected run) was never noticed. It now reads `$slots['header-actions']` in the template, like `subtitle` and `header-trailing`.

## 3. Out of scope

- Re-adding a removed chip, or attaching context from other places.
- A dedicated tool or system-prompt rule for the context block.

## 4. Tests

- **Vitest**
  - `chatContext.test.ts`: append with zero, one and two items; extract round trip; extract leaves unrelated content alone; text after the block survives; names with newlines; draft save/consume, including malformed storage.
  - `executionTimeline` entry builder: filtering, retry folding, sub-agent marking, source index.
- **Backend**: `_fallback_title_from_content` stops at the context block.
- **Playwright**
  - Editor history dialog: **Ask AI** lands on `/chats/<id>` with two chips; removing one leaves one; sending posts a message whose content has the remaining line only.
  - Editor history dialog: switching to **Timeline** shows timeline rows for the selected run.
  - All History, workflow run: **Timeline** shows the run's rows and **Ask AI** lands on `/chats/<id>` with both chips.
  - All History, chat run (mocked list and detail): no **Ask AI**, no toggle, the step list stays.

## 5. Docs

- `reference/execution-history.md`: Ask AI and the Timeline toggle.
- `tabs/chat-tab.md`: context chips.
