# Dashboard Chat Composer

Date: 2026-08-07
Status: Approved, ready for implementation plan

## Summary

Add a horizontal chat composer to the top of the dashboard Workflows tab. It greets the
user by name, asks what they want to automate, accepts a file attachment, and lets them
pick an LLM credential and model. Submitting creates a conversation, sends the first
message, and navigates to `/chats/:id` where the response streams in.

## Goals

- Let a user start an assistant chat from the dashboard without first opening the Chats tab.
- Carry the same capabilities the chat composer already has: file attachment, credential
  selection, model selection.
- Reuse existing store and composable contracts instead of adding backend surface.

## Non-goals

- Multiple file attachments. The chat API takes one attachment per message.
- Voice input, quick prompts, or queued messages on the dashboard. Those stay in the chat view.
- Any backend change. No new endpoint, model, or migration.

## User-visible behavior

Placement: dashboard Workflows tab only, directly above the `Workflows` heading block,
below `DashboardNav`. Other tabs (credentials, drive, mcp, and so on) do not render it.

Copy (short, natural English, no em dashes):

- Heading: `Welcome {name},` when `authStore.user.name` is set, otherwise `Welcome,`
- Subheading: `What do you want to automate?`
- Textarea placeholder: `Ask anything, or describe a workflow to build`
- No credentials: `Add an LLM credential to start chatting`
- Model list failure: `This credential's model list could not be loaded.`
- Create failure: `Could not start chat. Try again.`

Layout: one row on desktop (attach button, textarea, credential select, model select, send
button), stacked on mobile. The attachment chip and any error text sit under the row.

Dismiss: an `x` in the top right hides the composer and persists that in
`localStorage["heym-dashboard-chat-composer-dismissed"]`. When dismissed, a small
`Ask AI` button appears next to the `Workflows` heading and restores the composer.

Keyboard: Enter sends, Shift+Enter inserts a newline. The textarea auto-resizes.

## Architecture

### New: `frontend/src/components/Chat/DashboardChatComposer.vue`

Self-contained component, roughly 200 lines. Emits `dismiss`. Owns its draft text,
attachment state, and submit state. Uses `SearchableSelect` for both dropdowns, matching
the chat composer.

### New: `frontend/src/composables/useChatModelSelection.ts`

Extracts the credential and model bootstrap that currently lives inline in
`ChatConversation.vue`.

Exposed contract:

- State: `credentials`, `models`, `selectedCredentialId`, `selectedModel`,
  `credentialOptions`, `modelOptions`, `isLoadingModels`, `modelsLoadFailed`,
  `credentialError`, `hasCredentials`, `isReady`
- Actions: `bootstrap()`, `selectCredential(id)`,
  `applySavedSelection({ credentialId, model })`

Resolution rules are the ones in place today: `useAiDefaults.resolveCredentialId` picks the
saved credential, then the user's `preferred_credential_id`, then the first credential;
`useAiDefaults.resolveModel` picks the saved model, then `preferred_model`, then the last
model in the list. `applySavedSelection` covers the chat view's need to restore a
conversation's `last_credential_id` and `last_model`.

### Edited: `frontend/src/views/DashboardView.vue`

Around 15 lines. Renders `<DashboardChatComposer>` in the Workflows tab, holds the
dismissed flag, and renders the `Ask AI` restore button.

### Edited: `frontend/src/components/Chat/ChatConversation.vue`

Replaces its local credential and model state with `useChatModelSelection`. Behavior is
unchanged, including the conversation session restore path (`_applyConversationSession`)
and the disabled states around `modelsLoadFailed`.

## Data flow

1. Composer mounts and calls `bootstrap()`: `credentialsApi.listLLM()`, resolve credential,
   `credentialsApi.getModels(credId)`, resolve model.
2. User types, optionally attaches a file through `useFileAttachment.processFile`.
3. Submit calls `chatStore.createConversation()`.
4. Submit then calls
   `chatStore.sendMessage(conv.id, text, selectedCredentialId, selectedModel, attachedFile)`.
5. Submit navigates to `/chats/${conv.id}`.
6. `ChatsView` mounts `ChatConversation`, which calls `chatStore.loadConversation(id)`.
   Since `activeConversation.id` already matches, the store keeps the optimistic user
   message, and `foregroundSubscribedConvIds` prevents a second stream subscription. The
   user lands mid-stream.
7. The composer clears its text and attachment after a successful submit.

Double submit is blocked by an `isSubmitting` flag. Send is disabled when any of these
hold: empty trimmed text, no selected model, `modelsLoadFailed`, `attachmentLoading`,
`attachmentError`, `isSubmitting`.

## Error handling

| Case | Behavior |
| --- | --- |
| No LLM credentials | Selects and send disabled, `Add an LLM credential to start chatting` link switches the dashboard to the Credentials tab |
| `getModels` fails | `modelsLoadFailed` true, model select disabled, warning text shown, send disabled |
| `createConversation` fails | No navigation. User stays on the dashboard, sees `Could not start chat. Try again.`, and keeps their text and attachment |
| `sendMessage` fails | `chatStore.sendMessage` already swallows its own errors and clears the stream state, so the composer does not special case it. The conversation exists, so still navigate to `/chats/:id` and let the chat view surface the state |
| Unsupported or oversized file | `useFileAttachment` error text, send stays disabled until cleared |

## Testing and verification

No backend change, so no new pytest coverage. Per project preference, no frontend UI tests
are written for this repo.

Automated: `bun run lint`, `bun run typecheck`, and `./check.sh` from the repo root.

Manual checks:

1. Composer opens with the user's preferred credential and model preselected.
2. Sending with a text file, an image, and a PDF each reaches the chat view with the
   attachment name on the user message.
3. An account with no LLM credential shows the CTA and cannot send.
4. Dismiss hides the composer, survives a reload, and `Ask AI` restores it.
5. The stream started on the dashboard continues without interruption in the chat tab, and
   no duplicate assistant message appears.

## Documentation

This is a medium-sized UI addition, so the docs update runs through the
`heym-documentation` skill: a short section on the dashboard composer in the chat or
dashboard docs page.

## Risks

- `ChatConversation.vue` is large and its credential and model bootstrap is entangled with
  focus handling and context summary loading. The composable extraction must keep
  `focusInputWhenReady` and `_maybeLoadContextSummary` firing at the same points.
- Navigation timing: `router.push` must happen after `sendMessage` has set the streaming
  state, otherwise the chat view may briefly render an empty conversation.
