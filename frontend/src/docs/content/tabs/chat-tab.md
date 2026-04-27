# Chat Tab

The **Chat** tab provides a direct LLM chat interface. Use it to test models, ask questions, or prototype prompts without building a workflow.

<video src="/features/showcase/chat.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/chat.webm">▶ Watch Chat demo</a></p>

## Setup

1. Select a [credential](./credentials-tab.md) (API key for OpenAI, Google, etc.)
2. Choose a model from the dropdown (models are loaded from the selected credential)
3. Start typing to send messages

## Features

- **Global variables context** – Your [Global Variables](../reference/global-variables.md) are available to the LLM, so you can ask about or reference stored values
- **Workspace template context** – Shared workflow and node templates in your workspace are included as context, so Chat can answer questions about available templates
- **Streaming responses** – See the model's output as it streams
- **Stop response** – Interrupt the current streaming answer at any time
- **Markdown rendering** – Responses support markdown formatting, including inline images
- **Image display** – Images embedded in responses (e.g. from LLM image generation) appear inline; click any image to view it fullscreen. Press **Esc** or the back button (mobile) to close the fullscreen view
- **Copy messages** – Copy any message to the clipboard
- **Clear chat** – Start a new conversation
- **Voice input** – Use the microphone button for speech-to-text (browser-supported). When recording stops, Heym can lightly clean up the transcript before you send it
- **Scheduled workflows** – Ask when cron workflows run (today, this week, this month, or a custom date range). The assistant uses the same schedule data as the [Scheduled](./scheduled-tab.md) tab and can limit results to workflows you own or include those shared with you

## Context Limit

The chat keeps up to 25 recent messages in context. Older messages are trimmed to stay within model limits.

## User Rules

[User Rules](../reference/user-settings.md) (configured in User Settings) are automatically injected into every Chat conversation as system-level instructions. Set them once to apply persistent preferences to all chat requests.

## Related

- [User Settings](../reference/user-settings.md) – Set User Rules applied to all chat requests
- [Credentials Tab](./credentials-tab.md) – Add and manage API keys
- [Variables Tab](./global-variables-tab.md) – Global variables available to Chat
- [Node Types](../reference/node-types.md) – LLM and Agent nodes for workflows
- [Agent Node](../nodes/agent-node.md) – AI Agent with tool calling
- [Execution History](../reference/execution-history.md) – View past runs (History button in header)
- [Scheduled Tab](./scheduled-tab.md) – Calendar of upcoming cron runs (same data Chat can summarize)
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact in-app orientation for this page
