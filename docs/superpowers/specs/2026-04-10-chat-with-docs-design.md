# Chat with Docs — Design Spec
**Date:** 2026-04-10  
**Status:** Approved

## Summary

Add a "Chat with Docs" button to the documentation page header. Pressing it opens a centered dialog where users can select credentials and a model, then chat with an AI assistant that is context-aware of the currently open documentation page.

## Goals

- Mobile-friendly button in the `DocsView` header (icon-only on mobile, icon + label on desktop)
- Magic wand icon (`Wand2`), purple background (`bg-purple-600`)
- Dialog opens centered on screen, `size="2xl"`, supports fullscreen toggle
- Closes on backdrop click, Escape key, or explicit close button
- Credential + model selection always visible at top of dialog
- Session-only chat history (cleared on dialog close)
- Zero backend changes — reuses existing `/api/ai/dashboard-chat` endpoint

## Out of Scope

- Persistent chat history (localStorage)
- New backend endpoint
- Extracting a shared `useChatStream` composable from `DashboardChatPanel`

---

## Architecture

### New File

**`frontend/src/components/Docs/DocsChatDialog.vue`**

Self-contained dialog component. All chat state lives here (messages, streaming, credential/model selection). No shared state with `DashboardChatPanel`.

Props:
```ts
interface Props {
  open: boolean
  docPath: string | null  // e.g. "nodes/llm-node", null on docs home
}
emit: ['close']
```

### Changed Files

**`frontend/src/views/DocsView.vue`**
- Add `docsChatOpen = ref(false)` state
- Add "Chat with Docs" button in `#actions` slot of `AppHeader`
- Mount `<DocsChatDialog :open="docsChatOpen" :doc-path="docPath" @close="docsChatOpen = false" />`
- Register `docsChatOpen` with `onDismissOverlays` so overlay back-handler also closes it

---

## Component Design

### Button (`DocsView.vue` → `AppHeader #actions`)

```
[Wand2 icon]                     ← mobile: icon only, purple bg
[Wand2 icon] Chat with Docs      ← desktop: icon + label
```

- Classes: `bg-purple-600 hover:bg-purple-700 text-white rounded-xl`
- Touch target: `min-h-[44px] min-w-[44px]`
- Positioned to the left of the existing GitHub and History buttons

### Dialog Layout (`DocsChatDialog.vue`)

```
┌─────────────────────────────────────────────┐
│ [Wand2] Chat with Docs          [⤢] [✕]    │  ← Dialog header
│─────────────────────────────────────────────│
│ [Credential ▾]  [Model ▾]                   │  ← Always-visible selects
│─────────────────────────────────────────────│
│                                             │
│  (empty state: Wand2 icon + hint text)      │  ← Message area (flex-1 scroll)
│  or                                         │
│  [user bubble]          → right, bg-primary │
│          [assistant bubble] ← left, bg-muted│
│                                             │
│─────────────────────────────────────────────│
│ 📄 nodes/llm-node  (context badge, if any) │  ← Only shown when docPath set
│ [textarea ...................] [Send/Stop]   │  ← Input row
└─────────────────────────────────────────────┘
```

- Dialog: `size="2xl"`, `allowFullscreen=true`, `h-[70vh]`
- Backdrop click → `emit('close')` (handled by `Dialog.vue` automatically)
- Escape → `emit('close')` (handled by `Dialog.vue` automatically)

### Credential & Model Selection

Pattern mirrors `DashboardChatPanel.vue`:
- `credentialsApi.listLLM()` on mount → auto-select first credential
- `credentialsApi.getModels(credentialId)` on credential change → auto-select via `pickDefaultModel()` (Cerebras/GLM priority)
- Mobile: 2-column grid; Desktop: row
- `loadingModels` spinner state on model dropdown

### Empty State

When `messages.length === 0`:
- Centered `Wand2` icon (large, `opacity-50`)
- Text: `"Ask anything about the docs"`

### Context Badge

When `docPath` is not null, show above the input:
```
📄 nodes/llm-node
```
Small pill, `text-xs text-muted-foreground`, so user knows which page is being used as context.

### Markdown Rendering

Same as `DashboardChatPanel`: `marked` + `DOMPurify` with the same `ALLOWED_TAGS` list.

---

## Backend Integration

**Endpoint:** `POST /api/ai/dashboard-chat` — no changes.

**Context injection via `userRules`:**
```ts
userRules: docPath
  ? `The user is currently reading the Heym documentation page: /docs/${docPath}. Prioritize answers relevant to this page.`
  : undefined
```

The existing `search_documentation` tool in the system prompt handles fetching actual doc content when needed.

**Full request shape:**
```ts
aiApi.dashboardChatStream({
  credentialId: selectedCredentialId,
  model: selectedModel,
  message: userInput,
  conversationHistory: messages
    .filter(m => m.role === 'user' || m.role === 'assistant')
    .slice(-25)
    .map(m => ({ role: m.role, content: m.content })),
  userRules: docPath ? `...` : undefined,
  clientLocalDatetime: new Date().toLocaleString(),
})
```

---

## Error Handling

| Scenario | Behavior |
|---|---|
| No credentials | Dropdown shows "No credentials" (disabled), send button disabled |
| Model load error | Dropdown shows "Failed to load", send button disabled |
| Stream error | Inline error text inside assistant message bubble |
| Stop button clicked | `AbortController.abort()`, empty assistant bubble removed |
| Dialog closed mid-stream | `onUnmounted` calls `AbortController.abort()` |

---

## State Lifecycle

- On `open = true`: load credentials (if not already loaded), focus textarea
- On `open = false` (any trigger — backdrop, Escape, X button): `messages = []`, `inputText = ""`, abort any active stream
- `selectedCredentialId` and `selectedModel` persist within the dialog session (not reset on close, so re-opening is fast)

---

## Testing

One backend unit test is not applicable here (pure frontend component). A lightweight frontend smoke test is out of scope per AGENTS.md (no frontend tests yet). Manual test checklist:

- [ ] Button appears in docs header on mobile (icon only) and desktop (icon + label)
- [ ] Dialog opens/closes via button, backdrop click, Escape, X button
- [ ] Credential and model dropdowns populate correctly
- [ ] Chat works end-to-end with a real credential
- [ ] `docPath` badge shows current page path
- [ ] Stream can be stopped mid-response
- [ ] Closing dialog mid-stream aborts cleanly (no console errors)
- [ ] Dialog is usable on 375px mobile width
