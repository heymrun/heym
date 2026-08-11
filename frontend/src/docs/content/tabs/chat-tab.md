# Chat Tab

The **Chat** tab provides a direct LLM chat interface. Use it to test models, ask questions, run existing workflows, or create a new workflow from a natural-language request.

<video src="/features/showcase/chat.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/chat.webm">▶ Watch Chat demo</a></p>

## Setup

1. Select a [credential](./credentials-tab.md) (API key for OpenAI, Google, etc.)
2. Choose a model from the dropdown (models are loaded from the selected credential)
3. Start typing to send messages

You can also start a conversation from the chat box on the [Workflows tab](./workflows-tab.md). It sends your first message and opens the new conversation here with the answer already streaming.

## Features

- **Global variables context** – Your [Global Variables](../reference/global-variables.md) are available to the LLM, so you can ask about or reference stored values
- **Workspace template context** – Shared workflow and node templates in your workspace are included as context, so Chat can answer questions about available templates
- **Long-running agent** – Chat keeps working on the backend even if the browser closes, so you can come back from another device and continue the same conversation
- **Workflow creation** – Ask Chat to create or set up a workflow, and it uses the same Workflow AI Builder engine as the editor assistant to generate and save the workflow
- **Kanban task creation** – Ask naturally to add a task or create a card. Chat adds it to the first column of the requested board; when you have multiple boards and do not name one, Chat presents a board picker before creating the card
- **Queued follow-ups** – Send more messages while an answer is streaming. Queued messages are persisted, can be edited or deleted before they start, and run in order after the active response
- **Planning pauses** – When Chat needs planning details, it asks clarification questions and pauses queued follow-ups until you answer. After the planning answer finishes, queued messages resume
- **Streaming responses** – See the model's output as it streams
- **Stop response** – Interrupt the current streaming answer at any time; stopping also clears queued messages for that conversation
- **Markdown rendering** – Responses support markdown formatting, including inline images
- **Image display** – Images embedded in responses (e.g. from LLM image generation) appear inline; click any image to view it fullscreen. Press **Esc** or the back button (mobile) to close the fullscreen view
- **Copy messages** – Copy any message to the clipboard
- **Clear chat** – Start a new conversation
- **Voice input** – Use the microphone button for speech-to-text (browser-supported). When recording stops, Heym can lightly clean up the transcript before you send it
- **Scheduled workflows** – Ask when cron workflows run (today, this week, this month, or a custom date range). The assistant uses the same schedule data as the [Scheduled](./scheduled-tab.md) tab and can limit results to workflows you own or include those shared with you
- **Live run status** – Ask what is running right now and Chat answers with the count, the workflow names, how long each run has been going, which node it is on, and a link straight to the live run

## Using Chat from an MCP Client

The Chat engine can also be reached from outside the browser. Enable the **Heym Chat Tool** in the [MCP tab](./mcp-tab.md) and MCP clients — Claude, Cursor, and anything else that speaks MCP — get a single `heym_chat` tool that runs this same engine with all of its capabilities.

Those conversations land in this tab's history, marked with a plug icon in the conversation list. Open one to read what the client asked, see the tool cards it triggered, and continue the thread yourself. Answering a clarification question works the same way whether the turn started here or from an MCP client.

## Context Limit

The chat keeps up to 25 recent messages in context. Older messages are trimmed to stay within model limits.

## Creating Workflows

When you ask Chat to create, build, generate, or set up a workflow, it creates a new saved workflow with a generated name and description. The response includes a read-only canvas preview of the generated nodes and edges, plus an **Open workflow** link that opens the workflow editor in a new browser tab. Use the preview card's **Run** button when you want to execute the workflow.

Follow-up feedback in the same chat edits that workflow instead of creating another one. For example, after Chat creates a workflow you can say "add an approval step", "change the output format", or "şöyle yap" and Chat updates the saved workflow and refreshes the preview.

This is best for requests where you want the work done as a reusable automation, not just a one-off answer.

## Creating Kanban Tasks

Ask Chat in ordinary language, for example, “Add a task called Fix login bug” or
“Create a new card Update documentation on the Launch board.” You can include a
description in the same request. Chat always creates the card in the selected board's
first column.

If your workspace has several boards and you do not identify one, Chat pauses with a
single-choice board picker. Select a board to finish creating the card. No slash command
or special message format is required.

## Asking What Is Running

Ask in ordinary language — "what is running?", "how many workflows are active right now?",
"which node is the nightly report on?" — and Chat reports the live picture:

- **How many** executions are in progress, split into running and awaiting human review
- **Which workflows** they belong to, by name
- **How long** each run has been going (for example `1m 35s`, `3h 25m`)
- **Which node** is executing right now, by its canvas label, plus the last node that finished
- **A link** to each live run, which opens the canvas with that execution replaying

Runs paused for a [Human-in-the-Loop](../reference/human-in-the-loop.md) or Codex review are reported as
waiting for you, not as running. This is the same data as the active-runs badge in the header,
so Chat and the badge never disagree. For runs that already finished, ask for recent executions
instead — that reads [Execution History](../reference/execution-history.md).

## Asking About Alerts

Chat can answer questions about the [alerts](./alerts-tab.md) you have defined:

- **What exists** — "what alerts do I have?", "is there an alert on the invoice workflow?",
  "which alerts are firing right now?"
- **How one is set up** — "what is the threshold on the cost alert?", "how is that configured?"
- **Why and when it fired** — "why did the cost alert fire?", "when did this last trigger?"

For a "why did it fire" question, Chat reads the firing record and quotes the actual observed
value, the threshold, and the exact window that was evaluated, plus the contributing detail:
failing execution ids and error messages for error alerts, per-model spend for cost alerts, or
the trigger-source breakdown for execution-count alerts. It reports what was true when the alert
fired rather than recomputing the window, because the window has passed and a fresh calculation
can give a different answer.

## User Rules

[User Rules](../reference/user-settings.md) (configured in Settings) are automatically injected into every Chat conversation as system-level instructions. Set them once to apply persistent preferences to all chat requests.

## Related

- [MCP Tab](./mcp-tab.md) – Expose this engine to MCP clients as the `heym_chat` tool
- [Settings](../reference/user-settings.md) – Set User Rules applied to all chat requests
- [Credentials Tab](./credentials-tab.md) – Add and manage API keys
- [Variables Tab](./global-variables-tab.md) – Global variables available to Chat
- [Node Types](../reference/node-types.md) – LLM and Agent nodes for workflows
- [Agent Node](../nodes/agent-node.md) – AI Agent with tool calling
- [AI Assistant](../reference/ai-assistant.md) – Editor assistant powered by the same workflow builder DSL
- [Execution History](../reference/execution-history.md) – View past runs (History button in header)
- [Scheduled Tab](./scheduled-tab.md) – Calendar of upcoming cron runs (same data Chat can summarize)
- [Alerts Tab](./alerts-tab.md) – Threshold alerts Chat can list and explain
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact in-app orientation for this page
- [Chat Voice (TTS & STT)](../reference/chat-voice.md) – Read messages aloud and talk hands-free with ElevenLabs

## Tool calls and context size

Each time the assistant invokes a tool (running a workflow, listing executions, building a new workflow), a collapsible card appears in the conversation. The card auto-expands while the tool runs, showing the exact arguments. When the tool finishes, the card collapses to a one-line summary with the elapsed time. Click any card to re-expand the arguments and the response summary.

A small ring badge below the input shows the current context usage as a percentage of the model's window (e.g. `12% · ~9.2k`). Hover the badge to see a breakdown: system prompt, AGENTS.md, workflows block, user rules, history, and your draft input. When usage crosses 80% the ring turns amber; at 95% it turns red.

If usage gets close to the limit, Heym automatically compresses older messages into a short summary using the same mechanism agent nodes use. A "Context compressed" card appears inline to show what happened.
