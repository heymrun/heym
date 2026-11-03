# Slack files (download + send) Implementation Plan

> Executed inline in the session that wrote it (Burak asleep, "devam et"). Local diff only:
> no commits in heymrun or heym-work. No release tour work.

**Goal:** Slack node `downloadFile` / `sendFile` operations in Heym Core, used by Heym Work
Flows for the legal case-file intake (download → agent analysis → approval → outcome).

**Spec:** `docs/superpowers/specs/2026-11-03-slack-files-design.md`

**Architecture:** One new service module `backend/app/services/slack_files.py` holds both
operations; `slack_operations.run_bot_operation` dispatches to it. Drive writes go through
`file_storage.store_file_sync`, Drive reads through `file_sandbox.manifest.resolve_files` with the
run's `RunFileScope`. Work builds the extra `files` node and switches its AI node to `agent`.

---

## File map

heymrun
- Create `backend/app/services/slack_files.py`: input normalizer, message fetch, `files.info`,
  authenticated download, Drive store with rollback cleanup, upload (get URL, POST bytes, complete).
- Modify `backend/app/services/slack_service.py`: `call_slack(..., form=True)` form-encoded POST.
- Modify `backend/app/services/slack_operations.py`: two operations in `OPERATIONS`, dispatch.
- Modify `backend/app/services/file_sandbox/scope.py`: public `file_refs(value)` (moved from the
  Code node's `_file_ids`); `code_node.py` imports it.
- Modify `backend/app/api/slack.py`: `slackEventFilesOnly` in `_event_matches`; bot-user echo in
  `_is_bot_echo`.
- Modify `backend/app/services/cluster/node_placement.py`: `_slack_placement`.
- Modify `backend/app/services/workflow_dsl_prompt.py`: slack + slackTrigger sections.
- Modify `frontend/src/components/Panels/propertiesPanel/nodes/slackOperations.ts`,
  `SlackTriggerNodeProperties.vue`, `frontend/src/types/workflow.ts`,
  `frontend/src/components/Credentials/slackBotSetup.ts`.
- Modify docs `frontend/src/docs/content/nodes/slack-node.md`, `slack-trigger-node.md`.
- Tests: create `backend/tests/test_slack_files.py`; extend `test_slack_events_fanout.py`,
  `test_cluster_node_placement.py`.

heym-work
- Modify `backend/heym_work/api/flow_schemas.py` (`slack_files`, `sendFile`),
  `services/flow_steps.py` (sendFile data, anchors), `services/flow_graph.py` (files node, agent),
  `services/flow_checks.py` (two checks).
- Modify `frontend/src/types/flows.ts`, `lib/flowCatalog.ts` (action, idea), `lib/flows.ts`
  (tokens, newStep, emptyFlow), `lib/flowChecks.ts`, `components/flows/FlowTriggerCard.vue`
  (switch), `FlowActionGrid.vue` (needs files), `FlowSlackStepFields.vue` (sendFile fields),
  `FlowAiCard.vue` (idea turns files on), `views/FlowBuilderView.vue` (wiring).
- Tests: extend `backend/tests/test_flow_graph.py`, `frontend/src/lib/flows.test.ts`.

## Tasks

### Task 1: shared file-ref normalizer
- Move `_file_ids` from `nodes/code_node.py` to `file_sandbox/scope.py` as `file_refs(value) ->
  list[str]` (dict `id`/`file_id`, list, comma/newline text, order kept, deduped). Code node calls it.
- Run `uv run pytest tests -k "code_node or codeFiles" -q`: unchanged results.

### Task 2: `call_slack` form mode
- `call_slack(token, method, payload=None, *, read=False, form=False)`: `form` posts `data=payload`.

### Task 3: `slack_files.download_files(ctx, token) -> dict` (TDD)
Tests first in `backend/tests/test_slack_files.py` (patch `slack.call_slack`, the guarded client and
`store_file_sync`):
- event object → files + text/channel/ts/user; trigger output with `event` unwraps.
- file id text, file object (`slack_file_id` or `F…` `id`), file permalink, list.
- message permalink → `conversations.history` (`latest`=`oldest`=ts, `inclusive`) ; reply permalink
  → `conversations.replies` on `thread_ts`.
- message without files → `count 0`, text kept; input naming nothing → ValueError.
- Download host not `files.slack.com` → ValueError and no HTTP call (negative); the input's own
  `url_private` is never fetched (negative: only `files.info`'s URL is used).
- External / hidden_by_limit / no download URL / size over limit → ValueError.
- 3xx or `text/html` body for a PDF → ValueError naming `files:read`.
- Second file fails → rollback, first file's written path removed.
- Stored row gets `workflow_id`, `owner_id = trace_user_id`, metadata `slack_file_id`.
- More than 10 files → ValueError.

### Task 4: `slack_files.send_files(ctx, token, channel) -> dict` (TDD)
- Refs resolve with `resolve_files(db, actor_id, refs, scope=executor.file_scope)`; out-of-scope id
  → ValueError "not found" and no Slack call (negative).
- `files.getUploadURLExternal` form POST with `filename`, `length`; upload URL not
  `files.slack.com` → ValueError; upload POST carries no Authorization header (negative).
- One `files.completeUploadExternal` with all ids, `channel_id`, `thread_ts`, `initial_comment`
  (mrkdwn).
- Output `channel`, `threadTs`, `files`, `count`.

### Task 5: dispatch + placement
- `OPERATIONS` gains `downloadFile`, `sendFile`; `run_bot_operation` dispatches.
- `_slack_placement`: MAIN_ONLY for the two operations. Tests in `test_cluster_node_placement.py`.

### Task 6: Slack Trigger filter + echo guard (TDD in `test_slack_events_fanout.py`)
- `slackEventFilesOnly`: event without `files` → no start (also with scope `all`).
- Event whose `user` equals an `authorizations[]` bot `user_id` → echo.

### Task 7: frontend Core
- `slackOperations.ts`: "Files" group; `slackFile`, `slackUploadFile` keys and field specs.
- `types/workflow.ts`: `slackFile`, `slackUploadFile`, `slackEventFilesOnly`.
- `SlackTriggerNodeProperties.vue`: checkbox "Only messages with files"; output hint
  `.event.files`.
- `slackBotSetup.ts`: `files:read`, `files:write`.
- `bun run lint && bun run typecheck`.

### Task 8: DSL prompt + docs
- DSL slack section: operations list, fields, outputs, scopes; slackTrigger `slackEventFilesOnly`.
- Docs pages: operations table rows, trigger option, reinstall note for new scopes.

### Task 9: Work backend (TDD in `test_flow_graph.py`)
- Schema: `FlowTrigger.slack_files: bool = False`; `FlowAction` + `sendFile`.
- Graph with `slack_files`: trigger has `slackEventFilesOnly`; `files` node after the trigger with
  `slackOperation: downloadFile`, `slackFile: $slackEvent.event`; AI node type `agent` and its user
  message carries `$files.text` and `$files.file_ids`. Without it nothing changes.
- `sendFile` step: `slackUploadFile: $files.file_ids`, channel/thread as other Slack steps; never an
  anchor.
- Checks: `slack_files` on a non-Slack trigger; `sendFile` without `slack_files`.

### Task 10: Work frontend
- Types, catalog action (`needsFiles`), grid disables it with "Needs the shared files option on the
  Slack trigger", step fields for sendFile, trigger switch, idea "Review the case file" (`files:
  true`) that FlowAiCard emits and the builder applies, tokens, flowChecks mirror, flows.test.ts.
- `bun run lint && bun run typecheck && bun run test`.

### Task 11: verification
- heymrun: `uv run ruff format . && uv run ruff check .`, focused pytest, then
  `SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh`.
- heym-work: its `./check.sh` (or backend pytest + frontend lint/typecheck/test).
- No commits.
