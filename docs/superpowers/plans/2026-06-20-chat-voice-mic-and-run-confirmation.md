# Chat Voice Mic + Run Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the interactive voice mic a "I'm done, answer me" finalize control, and stop auto-running chat-generated workflows in favor of a "Run" button on the workflow card.

**Architecture:** Two independent changes. Backend (`ai_assistant.py`): the two AI-builder tools save the workflow without executing, renamed `create_workflow` / `edit_workflow`; the existing `execute_workflow` tool powers an Approach-A "Run" button that sends a normal chat message. Frontend voice (`useInteractiveVoice.ts` / `InteractiveVoiceMode.vue`): a shared `finalizeUtterance()` used by both the silence timer and the mic button so tapping the mic commits the current utterance instead of discarding it.

**Tech Stack:** Python 3.11 + FastAPI (pytest), Vue 3 + TypeScript (no Vitest harness — verify via `bun run lint` + `bun run typecheck` + manual).

**Spec:** `docs/superpowers/specs/2026-06-20-chat-voice-mic-and-run-confirmation-design.md`

---

## Part 2A — Backend: tools save without running

### Task 1: Stop auto-execute in the create/edit builder tools

**Files:**
- Modify: `backend/app/api/ai_assistant.py` (functions at 1088 and 1204; payload builder at 1052)
- Test: `backend/tests/test_dashboard_chat_api.py` (existing test at 557; imports at 16/18)

- [ ] **Step 1: Update the existing test to assert no execution (create)**

In `backend/tests/test_dashboard_chat_api.py`, rename the test and change its assertions so the tool saves but does NOT call `run_execute_workflow_tool`. Replace the body of `test_create_and_run_generated_workflow_saves_and_executes` (lines 557-636) with:

```python
    async def test_create_generated_workflow_saves_without_running(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        user.user_rules = None

        credential = MagicMock()
        credential.id = uuid.uuid4()
        credential.owner_id = user.id
        credential.type = CredentialType.openai

        builder_content = """
```json
{
  "name": "Echo Assistant",
  "description": "Echoes the incoming text through an LLM.",
  "nodes": [
    {
      "id": "input",
      "type": "textInput",
      "position": {"x": 0, "y": 0},
      "data": {"label": "request", "inputFields": [{"key": "text"}]}
    },
    {
      "id": "llm",
      "type": "llm",
      "position": {"x": 260, "y": 0},
      "data": {
        "label": "reply",
        "credentialId": "YOUR_CREDENTIAL_ID",
        "model": "",
        "userMessage": "$request.text"
      }
    }
  ],
  "edges": [{"id": "e1", "source": "input", "target": "llm"}]
}
```
"""
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=builder_content))]
        client = MagicMock()
        client.chat.completions.create.return_value = response

        db = MagicMock()
        credential_result = MagicMock()
        credential_result.scalars.return_value.all.return_value = [credential.id]
        db.execute = AsyncMock(return_value=credential_result)
        db.flush = AsyncMock()

        with (
            patch(
                "app.api.ai_assistant.template_service.list_node_templates",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.api.ai_assistant.run_execute_workflow_tool",
                AsyncMock(),
            ) as run_tool,
        ):
            raw_result = await create_and_run_generated_workflow_tool(
                db=db,
                user=user,
                client=client,
                model="gpt-4o-mini",
                selected_credential=credential,
                selected_model="gpt-4o-mini",
                goal="Create an echo workflow",
                inputs={"text": "hello"},
                available_workflows=[],
                public_base_url="http://localhost",
            )

        saved_workflow = db.add.call_args.args[0]
        self.assertEqual(saved_workflow.name, "Echo Assistant")
        self.assertEqual(saved_workflow.nodes[1]["data"]["credentialId"], str(credential.id))
        self.assertEqual(saved_workflow.nodes[1]["data"]["model"], "gpt-4o-mini")
        run_tool.assert_not_awaited()
        payload = json.loads(raw_result)
        self.assertEqual(payload["status"], "created")
        self.assertNotIn("execution", payload)
        self.assertEqual(payload["workflow_preview"]["name"], "Echo Assistant")
```

Keep the existing imports (the Python helper functions are NOT renamed — only the
LLM-facing tool name strings change in Task 2). Ensure `import json` is present at the top of
the test file (add it if missing).

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_dashboard_chat_api.py::DashboardChatWorkflowBuilderTests::test_create_generated_workflow_saves_without_running -v`
Expected: FAIL — `create_generated_workflow_tool` not defined (ImportError) or status still `created_and_ran`.

- [ ] **Step 3: De-execute the create tool**

In `backend/app/api/ai_assistant.py`, keep the function name `create_and_run_generated_workflow_tool` (line 1088) but update its docstring to "Generate a workflow with the AI Builder prompt and save it (no execution)." Delete the execution block (lines 1177-1196) and replace with a save-only payload. The function body from after `await db.flush()` (line 1165) onward becomes:

```python
        await db.flush()

        run_inputs = dict(inputs or {})
        input_fields = extract_input_fields_from_workflow(workflow)
        if attachment is not None:
            field_keys = [field.key for field in input_fields]
            inject_key = _find_injection_field(field_keys, attachment.kind)
            if inject_key:
                run_inputs[inject_key] = attachment.content
        if not run_inputs and input_fields:
            run_inputs[input_fields[0].key] = goal

        return _build_saved_workflow_payload(
            workflow,
            nodes,
            edges,
            input_fields,
            run_inputs,
            None,
            status_value="created",
        )
    except Exception as exc:
        logger.exception("Dashboard chat create_workflow failed")
        return json.dumps({"status": "error", "error": str(exc)})
```

- [ ] **Step 4: Make `execution` optional in the payload builder**

In `_build_saved_workflow_payload` (line 1052), change the signature param `execution_payload: Any` to `execution_payload: Any = None` and only include the key when present. Replace the returned dict's `"execution": execution_payload,` line with conditional assembly:

```python
def _build_saved_workflow_payload(
    workflow: Workflow,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    input_fields: list[Any],
    run_inputs: dict[str, Any],
    execution_payload: Any = None,
    *,
    status_value: str,
) -> str:
    payload: dict[str, Any] = {
        "status": status_value,
        "workflow_id": str(workflow.id),
        "workflow_name": workflow.name,
        "workflow_description": workflow.description,
        "workflow_url": f"/workflows/{workflow.id}",
        "workflow_link_markdown": (
            f'[Open "{workflow.name}" in a new tab](/workflows/{workflow.id})'
        ),
        "workflow_preview": {
            "id": str(workflow.id),
            "name": workflow.name,
            "description": workflow.description,
            "url": f"/workflows/{workflow.id}",
            "nodes": nodes,
            "edges": edges,
        },
        "input_fields": [field.model_dump(by_alias=True) for field in input_fields],
        "run_inputs": run_inputs,
    }
    if execution_payload is not None:
        payload["execution"] = execution_payload
    return json.dumps(payload, default=str)
```

- [ ] **Step 5: De-execute the edit tool**

In `backend/app/api/ai_assistant.py`, keep the function name `edit_and_run_generated_workflow_tool` (line 1204) but update its docstring to "Edit a saved workflow with the AI Builder prompt and save it (no execution)." Delete the execution block (lines 1319-1330) and the `status_value="edited_and_ran"` call, replacing the tail (from `await db.flush()` at line 1307 onward) with:

```python
        await db.flush()

        run_inputs = dict(inputs or {})
        input_fields = extract_input_fields_from_workflow(workflow)
        if attachment is not None:
            field_keys = [field.key for field in input_fields]
            inject_key = _find_injection_field(field_keys, attachment.kind)
            if inject_key:
                run_inputs[inject_key] = attachment.content
        if not run_inputs and input_fields:
            run_inputs[input_fields[0].key] = instructions

        return _build_saved_workflow_payload(
            workflow,
            nodes,
            edges,
            input_fields,
            run_inputs,
            None,
            status_value="edited",
        )
    except Exception as exc:
        logger.exception("Dashboard chat edit_workflow failed")
        return json.dumps({"status": "error", "error": str(exc)})
```

- [ ] **Step 6: Run the create test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_dashboard_chat_api.py::DashboardChatWorkflowBuilderTests::test_create_generated_workflow_saves_without_running -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/ai_assistant.py backend/tests/test_dashboard_chat_api.py
git commit -m "feat(chat): save AI-built workflows without auto-running"
```

### Task 2: Rename the LLM tool names and update wiring

**Files:**
- Modify: `backend/app/api/ai_assistant.py` (tool defs 417/438; dispatch 2623/2678/2760/2825; summary text 2056/2069; prompt 367/369/379/380; user message 996)
- Modify: `backend/app/services/workflow_dsl_prompt.py` (CLARIFY_PROTOCOL_PROMPT, line 4170 — heymrun-only, not in the synced `WORKFLOW_DSL_SYSTEM_PROMPT`)

- [ ] **Step 1: Rename the tool definitions**

In `backend/app/api/ai_assistant.py`, change tool name `"create_and_run_workflow"` (line 417) to `"create_workflow"` and update its description first sentence to: `"Create a brand-new workflow using the Workflow AI Builder Heym DSL generator and save it to the user's workflows. Do NOT run it; the user runs it from the workflow card."` Change `"edit_and_run_workflow"` (line 438) to `"edit_workflow"` and update its description to: `"Edit an existing workflow using the Workflow AI Builder engine and save the changes to the same workflow. Do NOT run it; the user runs it from the workflow card. Use this for follow-up feedback in the same chat about a workflow that was just created or previously linked."`

- [ ] **Step 2: Update the dispatch branches**

In the streaming dispatch, change only the branch conditions and labels (the Python helper
function names are unchanged, so leave the `await create_and_run_generated_workflow_tool(...)`
and `await edit_and_run_generated_workflow_tool(...)` calls as-is). Change `elif name == "create_and_run_workflow":` (line 2623) to `elif name == "create_workflow":`, and change every occurrence of the label `"Building and running a new workflow..."` in that branch (lines 2638, 2646, 2662) to `"Building a new workflow..."`. Change `elif name == "edit_and_run_workflow":` (line 2760) to `elif name == "edit_workflow":`, and change its analogous "...and running..." labels to the build-only wording (e.g. `"Updating the workflow..."`).

- [ ] **Step 3: Update the tool-result summary text**

In `_summarize_tool_result`, change `if tool_name == "create_and_run_workflow":` (line 2056) to `if tool_name == "create_workflow":` and simplify the body to return a save-only summary:

```python
    if tool_name == "create_workflow":
        if not isinstance(data, dict):
            return str(data)[:200]
        if data.get("error"):
            return f"Error: {str(data.get('error'))[:150]}"
        workflow_name = str(data.get("workflow_name") or "").strip()
        if workflow_name:
            return f"Created workflow: {workflow_name}"
        return f"Status: {str(data.get('status') or '')[:80]}"
```

Change `if tool_name == "edit_and_run_workflow":` (line 2069) to `if tool_name == "edit_workflow":` and likewise return `f"Updated workflow: {workflow_name}"` on success (mirror the block above, swapping the verb).

- [ ] **Step 4: Update the system-prompt instructions**

In `DASHBOARD_CHAT_SYSTEM_PROMPT` text:
- Line 367: replace `Before calling create_and_run_workflow for a new automation` with `Before calling create_workflow for a new automation`.
- Line 369: replace `via create_and_run_workflow or edit_and_run_workflow` with `via create_workflow or edit_workflow`.
- Line 379: replace `call create_and_run_workflow. This tool uses the Workflow AI Builder engine to generate Heym DSL, saves it, and runs it immediately.` with `call create_workflow. This tool uses the Workflow AI Builder engine to generate Heym DSL and saves it. It does NOT run the workflow; the user runs it from the Run button on the workflow card. Do not run the workflow yourself unless the user explicitly asks you to.`
- Line 380: replace `call edit_and_run_workflow with the workflow_id` with `call edit_workflow with the workflow_id`.

- [ ] **Step 5: Update the builder user message**

In `_build_workflow_builder_user_message`, change the line `"The workflow will be saved and run immediately after your response.",` (line 996) to `"The workflow will be saved but not run automatically; the user runs it manually.",`.

- [ ] **Step 6: Update the clarify-protocol prompt reference (generic wording)**

`CLARIFY_PROTOCOL_PROMPT` is appended to BOTH the dashboard-chat prompt AND `CANVAS_ASK_SYSTEM_PROMPT` (the canvas workflow assistant), but NOT to the synced `WORKFLOW_DSL_SYSTEM_PROMPT`. The canvas workflow assistant must not be behaviorally affected, and it exposes none of these tools. To keep the text accurate for chat without naming now-renamed tools, use generic wording. In `backend/app/services/workflow_dsl_prompt.py`, inside `CLARIFY_PROTOCOL_PROMPT` (line 4170), change `` do NOT call `create_and_run_workflow` or `edit_and_run_workflow` `` to `do NOT call the workflow create/edit tools`. (No behavior change for the canvas assistant — it has no such tools — and the heymweb sync guard is unaffected.)

- [ ] **Step 7: Verify no stale LLM-facing references remain**

The Python helper names `create_and_run_generated_workflow_tool` / `edit_and_run_generated_workflow_tool` are intentionally kept, so grep only for the renamed tool-name strings, status values, and prompt phrasing:

Run: `grep -rn '"create_and_run_workflow"\|"edit_and_run_workflow"\|created_and_ran\|edited_and_ran\|saved and run immediately\|runs it immediately' backend/app backend/tests`
Expected: no matches (empty output).

- [ ] **Step 8: Run the full dashboard-chat test module**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_dashboard_chat_api.py -v`
Expected: PASS (all tests, including the renamed builder test).

- [ ] **Step 9: Confirm the heymweb-sync guard still passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest -k "sync and prompt" -v`
Expected: PASS (the `WORKFLOW_DSL_SYSTEM_PROMPT` sync test is unaffected because only `CLARIFY_PROTOCOL_PROMPT` changed). If no such test is collected, this step is a no-op — proceed.

- [ ] **Step 10: Commit**

```bash
git add backend/app/api/ai_assistant.py backend/app/services/workflow_dsl_prompt.py
git commit -m "refactor(chat): rename builder tools to create_workflow/edit_workflow"
```

## Part 2B — Frontend: "Run" button on the workflow card

### Task 3: Add a Run button to the chat workflow card

**Files:**
- Modify: `frontend/src/components/Chat/ChatConversation.vue` (card at 1042-1050; helpers near `sendVoiceText` at 545)

- [ ] **Step 1: Add a `runWorkflowFromCard` helper**

In the `<script setup>` of `ChatConversation.vue`, add a helper next to `sendVoiceText` (after line 553). It reuses the existing send pipeline so streaming, tool cards, and voice all work:

```ts
async function runWorkflowFromCard(workflow: WorkflowPreview): Promise<void> {
  if (!selectedCredentialId.value || !selectedModel.value) return;
  if (isThisConvStreaming.value) return;
  await chatStore.sendMessage(
    props.conversationId,
    `Run the "${workflow.name}" workflow now (id: ${workflow.id}).`,
    selectedCredentialId.value,
    selectedModel.value,
  );
}
```

`WorkflowPreview` is already imported (line 24). Confirm `isThisConvStreaming` is a ref/computed in this file; if it is a plain boolean computed, drop the `.value`.

- [ ] **Step 2: Add the Run button to the card header**

In the template, inside the card header actions, add a Run button before the existing "Open workflow" anchor (line 1042). Import `Play` from `lucide-vue-next` alongside the existing `ExternalLink` import:

```vue
                <button
                  type="button"
                  :disabled="isThisConvStreaming"
                  class="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-border/60 bg-primary px-2.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                  @click="runWorkflowFromCard(msg.workflowPreview)"
                >
                  <Play class="h-3.5 w-3.5" />
                  Run
                </button>
```

Wrap the Run button and the "Open workflow" anchor in a flex container if they are not already siblings in one, so they sit side by side (`class="flex shrink-0 items-center gap-2"`).

- [ ] **Step 3: Typecheck and lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS (no unused imports; `Play` used; `runWorkflowFromCard` used).

- [ ] **Step 4: Manual smoke**

Run the app (`./run.sh`), open chat, ask to create a workflow, confirm the card appears WITHOUT auto-running, click **Run**, and confirm a new assistant turn runs the workflow via `execute_workflow`. Note the result in the commit body.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Chat/ChatConversation.vue
git commit -m "feat(chat): add Run button to workflow preview card"
```

## Part 1 — Voice mic: finalize utterance instead of discarding

> No Vitest harness in this repo (per convention) — verify via typecheck/lint + manual.

### Task 4: Shared finalize path in the voice composable

**Files:**
- Modify: `frontend/src/composables/useInteractiveVoice.ts`

- [ ] **Step 1: Add a `finalizeUtterance` helper**

In `useInteractiveVoice.ts`, add this helper after `monitor()` (after line 124). It stops the level monitor and finalizes: if the user has spoken, it stops the recorder while keeping its `onstop` handler (so the existing `onstop` transcribes); otherwise it releases the recorder and goes idle.

```ts
  function finalizeUtterance(): void {
    if (silenceTimer) {
      window.clearTimeout(silenceTimer);
      silenceTimer = null;
    }
    if (rafId) {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
    level.value = 0;
    if (recorder?.state === "recording") {
      if (speechStarted) {
        // Keep onstop → transcribe → onUtterance → "thinking".
        recorder.stop();
      } else {
        recorder.onstop = null;
        recorder.stop();
        setState("idle");
      }
    } else {
      setState("idle");
    }
  }
```

- [ ] **Step 2: Route the silence timer through `finalizeUtterance`**

In `monitor()`, replace the silence-timeout body (lines 117-119) so the silence path uses the shared helper:

```ts
        silenceTimer = window.setTimeout(() => {
          finalizeUtterance();
        }, SILENCE_MS);
```

This preserves existing behavior: `finalizeUtterance` stops the recording recorder with `speechStarted === true`, so `onstop` transcribes exactly as before.

- [ ] **Step 3: Make `toggleMute` finalize on mute and resume only when idle**

Replace `toggleMute` (lines 168-176) with:

```ts
  function toggleMute(): void {
    muted.value = !muted.value;
    if (muted.value) {
      // Turning the mic off means "I'm done — process what I said."
      if (state.value === "listening") {
        finalizeUtterance();
      }
      // While speaking/thinking/transcribing, leave state alone; the answer
      // keeps playing and listening will not auto-resume (muted flag).
    } else {
      // Re-enable: start listening only if we are not mid-answer.
      if (state.value === "idle") {
        listen();
      }
    }
  }
```

- [ ] **Step 4: Keep the orb out of `transcribing` when muted**

In `transcribe()`, update the two non-meaningful / error fallbacks (lines 88-90 and 94) so a muted session lands in `idle` instead of re-listening or hanging:

```ts
      if (isMeaningful(text)) {
        onUtterance(text);
      } else if (!muted.value) {
        // Nothing meaningful was said (silence or noise); keep listening.
        listen();
      } else {
        setState("idle");
      }
    } catch {
      error.value = "Transcription failed.";
      if (!muted.value) listen();
      else setState("idle");
    }
```

- [ ] **Step 5: Typecheck and lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS (`finalizeUtterance` used by both `monitor` and `toggleMute`; no unused vars).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/composables/useInteractiveVoice.ts
git commit -m "feat(voice): finalize utterance on mic-off instead of discarding"
```

### Task 5: Voice UI labels and post-answer state

**Files:**
- Modify: `frontend/src/components/Chat/InteractiveVoiceMode.vue` (label map 30-36; watcher 86; button 173-189)

- [ ] **Step 1: Relabel the idle state**

In `InteractiveVoiceMode.vue`, change the `stateLabel` map (line 31) entry `idle: "Paused",` to `idle: "Mic off",`.

- [ ] **Step 2: Return to a clean idle when muted after an answer**

In the `isStreaming` watcher, replace line 86 (`if (props.open && !voice.muted.value) await voice.start();`) with:

```ts
        if (props.open && !voice.muted.value) {
          await voice.start();
        } else if (props.open) {
          voice.setState("idle");
        }
```

This stops the orb from staying in the `speaking` pulse after the answer ends while the mic is off.

- [ ] **Step 3: Update the mic button aria-label**

In the mic button (lines 173-189), change the `:aria-label` expression from the mute/unmute wording to mic on/off:

```vue
          :aria-label="voice.muted.value ? 'Turn microphone on' : 'Turn microphone off'"
```

- [ ] **Step 4: Typecheck and lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS.

- [ ] **Step 5: Manual smoke**

Run the app, open interactive voice mode. Verify: (a) speak then go silent → it transcribes and answers (unchanged); (b) speak then tap the mic → it finalizes and answers; (c) tapping the mic while the assistant is speaking does not cut the answer and does not auto-resume listening; label reads "Mic off". Note results in the commit body.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Chat/InteractiveVoiceMode.vue
git commit -m "feat(voice): mic on/off labeling and clean idle after answer"
```

## Final verification

- [ ] **Step 1: Run the full check suite**

Run: `SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
Expected: PASS (frontend lint/typecheck, backend Ruff, backend tests). Commit any formatting-only diffs with the related task.
