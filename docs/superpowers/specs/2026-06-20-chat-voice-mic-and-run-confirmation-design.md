# Chat Workflow Creation: Voice Mic Control + Run Confirmation

Date: 2026-06-20
Status: Approved (design)

Two small, independent improvements to the chat-based workflow creation experience.

## Part 1 — Interactive voice mode: pure microphone on/off

### Problem
In the interactive voice orb (`InteractiveVoiceMode.vue` + `useInteractiveVoice.ts`):

- The mic button maps to `toggleMute()`, which on mute calls `stopListening()`. That
  helper sets `recorder.onstop = null` before stopping, so any audio captured so far is
  **discarded** — the user's in-progress utterance is dropped and no answer is produced.
- Muting also forces `setState("idle")`, which overrides the `speaking`/`thinking` state
  while the assistant's TTS answer keeps playing, so the UI looks "paused" mid-answer.
- The `idle` state label reads "Paused", framing the control as pause/resume rather than a
  microphone toggle.

### Desired behavior
Tapping the mic button means **"I'm done speaking — process my input and answer."** Two
ways to finish an utterance must converge on the same flow:

1. **Silence** (no button press): existing behavior — after speech starts, `SILENCE_MS`
   (1200 ms) of silence stops the recorder, which transcribes and advances to `thinking`.
   Preserved as-is.
2. **Mic button**: pressing it while speaking finalizes the current utterance the same way.

State-by-state when the mic button turns the mic **off**:

- `listening` + the user has spoken (`speechStarted`): **finalize** the utterance — stop the
  recorder **without** nulling `onstop`, so the existing `onstop` handler
  (`speechStarted && blob.size > 0`) transcribes → `onUtterance` → `thinking` → answer.
- `listening` + nothing spoken yet: nothing to send — release the recorder, go `idle`.
- `speaking` / `thinking` / `transcribing`: do **not** override state; only set the `muted`
  flag so the answer keeps playing and listening does not auto-resume afterward (the user
  chose not to interrupt).

Turning the mic back **on**: if state is `idle`, start listening; if the assistant is still
speaking, do nothing (the post-answer watcher handles resume when not muted).

### Implementation
`useInteractiveVoice.ts`:

- Add a shared `finalizeUtterance()` helper used by **both** the silence timer (in
  `monitor()`) and the mic-off path. It stops the level monitor and stops the recorder while
  keeping the `onstop` → `transcribe` handler intact when `speechStarted` is true. When no
  speech was captured, it releases the recorder and sets `idle`.
- `toggleMute()`:
  - On mute: if `listening`, call `finalizeUtterance()`; for other states leave state
    untouched and only flip `muted`.
  - On unmute: if `idle`, call `listen()`; otherwise no-op.
- `transcribe()`: when the result is not meaningful or STT fails **and** `muted` is true,
  fall back to `setState("idle")` instead of `listen()` so the orb does not hang in
  `transcribing` while muted.
- Keep `stopListening()` (discarding semantics) for `teardown()` / close.

`InteractiveVoiceMode.vue`:

- Post-answer watcher: after playback ends, `if (open && !muted) voice.start()` else
  `voice.setState("idle")`, so a muted session returns to a clean `idle` ("Mic off") instead
  of remaining in the `speaking` pulse.
- `stateLabel.idle` → "Mic off". Mic button `aria-label` → "Turn microphone on/off".

### Testing
No Vitest harness for frontend (per repo convention) — verify via `bun run lint` +
`bun run typecheck` and manual smoke. Add Playwright coverage only if practical.

## Part 2 — Replace auto-run with a "Run" button on the workflow card

### Problem
`create_and_run_workflow` and `edit_and_run_workflow` (`ai_assistant.py`) generate/save the
workflow and **execute it immediately** with guessed inputs. The user wants creation to stop
short of running and let them decide.

### Backend (`ai_assistant.py`)
- The two tools create/save the workflow but **do not execute**. Remove the
  `run_execute_workflow_tool` call and the auto `run_inputs` execution; still compute
  `input_fields` for the preview card.
- Rename the tools to `create_workflow` / `edit_workflow` so names match behavior. Update:
  - tool definitions + descriptions,
  - system-prompt references (`build_assistant_prompt` text around lines 367/379/380),
  - dispatch branches (around 2056/2069/2623),
  - tool-result summary text ("Created workflow: X", "Updated workflow: X"),
  - `_build_workflow_builder_user_message` line "will be saved and run immediately".
- Payload `status` → `"created"` / `"edited"`; drop the `execution` field. `workflow_preview`
  is unchanged.
- The existing `execute_workflow` tool (id + inputs) stays and powers the Run button.

### Frontend (`ChatConversation.vue`)
- Add a **"Run"** button next to "Open workflow" on the workflow preview card.
- **Approach A**: the button sends a short user message through the existing chat send
  pipeline, e.g. `Run the "<name>" workflow now (id: <id>).` The assistant runs it via the
  existing `execute_workflow` tool.
  - Reuses streaming, tool-call cards, voice mode, and the ask-for-missing-inputs behavior;
    no new endpoint or card result state.
- For workflows that need inputs, the assistant can now ask instead of guessing — the point
  of removing auto-run.

### Testing
- Backend: update the existing create/edit tests to assert the tools **save without
  executing** (no `execute_workflow` call, no `execution` in payload).
- Frontend: Playwright coverage for the Run button when practical.

## Scope guarantee — only the chat is affected
- The `create_and_run_workflow` / `edit_and_run_workflow` tools live only in
  `DASHBOARD_CHAT_TOOLS` and are used solely by the `/dashboard-chat` endpoint (the chat).
  The de-execute + rename change is therefore confined to the chat.
- The canvas **workflow assistant** (`/workflow-assistant`, `stream_llm_response` with
  `CANVAS_ASK_SYSTEM_PROMPT` / `build_assistant_prompt`) does not expose these tools and is
  not affected.
- **heymweb** `/convert` uses `WORKFLOW_DSL_SYSTEM_PROMPT` (via `expressions.py`), which is
  not touched. Only `CLARIFY_PROTOCOL_PROMPT` (heymrun-only, not in the synced prompt) is
  edited, with generic wording so the canvas assistant's behavior is unchanged.

## Out of scope
- Tuning `SILENCE_MS` (kept at 1200 ms).
- Any change to the simple press-to-talk dictation mic in the text composer.
- Inline execution-result rendering on the card (Approach B) — not chosen.
- The canvas workflow assistant and heymweb `/convert` — unchanged by design.
