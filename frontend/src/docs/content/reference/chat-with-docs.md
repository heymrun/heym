# Chat with Docs

Chat with Docs is a page-aware assistant available from the documentation header. It opens in a centered dialog, lets you pick an LLM credential and model, and answers questions with the current docs page as its first context.

## Opening the Dialog

1. Open any page under `/docs`
2. Click **Chat with Docs** in the header
3. Select a [credential](../tabs/credentials-tab.md) and model
4. Ask a question about the page or the platform

On smaller screens the trigger is icon-only; on larger screens it shows the full label.

## What Context It Uses

- The currently open docs path is injected into the request as contextual guidance
- The backend still uses the existing dashboard chat endpoint and documentation search tools
- Your account-level [User Rules](./user-settings.md) continue to apply because the same chat backend is reused
- Live preparation steps stream into the assistant bubble before the final answer, similar to the dashboard chat

When you open the dialog on a specific article, a small badge shows the active docs path so you can confirm which page is being prioritized.

## Session Behavior

- Credential and model selection stay in place while the dialog remains mounted
- Message history is session-only and is cleared when the dialog closes
- Backdrop click, `Escape`, and the close button all reset the session
- **Stop** aborts the current streaming response
- The dialog is intentionally wide and fixed-size; it does not offer a fullscreen toggle

## When to Use It

- Ask follow-up questions while reading a node or reference page
- Clarify feature differences without leaving the docs
- Find the right article before opening the editor

If you want to build or modify workflows directly, use the editor-side [AI Assistant](./ai-assistant.md) instead.

## Related

- [AI Assistant](./ai-assistant.md) – Editor chat for building workflows
- [Credentials Tab](../tabs/credentials-tab.md) – Add LLM credentials used by the dialog
- [User Settings](./user-settings.md) – Global User Rules applied to AI surfaces
- [Quick Start](../getting-started/quick-start.md) – First workflow walkthrough
