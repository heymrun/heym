# Heym node Send Chat Message Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `sendChatMessage` operation to the Heym node that runs one Heym Chat turn for the run's user, with no-history, continue and fire-and-forget toggles and OUT/QUESTION handles.

**Architecture:** The node handler (sync, executor thread) submits a coroutine to the application event loop through a new `app_loop` module. The coroutine resolves the user's Chat default model, prepares the conversation, and runs `run_agent_chat_turn` (the MCP/A2A engine). A ContextVar carries a chat hop depth into every executor the turn starts, so chat <-> workflow loops stop at 5.

**Tech Stack:** FastAPI, SQLAlchemy 2 async + sync sessions, asyncio, Vue 3 + Vue Flow, Vitest, Playwright.

Spec: `docs/superpowers/specs/2026-11-23-heym-node-chat-operation-design.md`

---

## File map

| File | Responsibility |
|------|----------------|
| `backend/app/services/app_loop.py` (new) | Register the app loop; `submit(coro)` from threads; chat hop depth ContextVar |
| `backend/app/main.py` | `set_app_loop(asyncio.get_running_loop())` at lifespan start |
| `backend/app/services/heym_chat_node.py` (new) | Async side: resolve Chat default LLM, validate/create conversation, run turn, delete temporary conversation, build output |
| `backend/app/services/node_execution/nodes/heym_node.py` | Sync side: read fields, validate, depth guard, submit + wait with cancellation, route handles |
| `backend/app/services/workflow_executor.py` | `chat_turn_depth` on executor (from ContextVar), pass to sub-executors; `output` skip matches a null source handle |
| `backend/app/services/node_execution/nodes/execute_node.py` | Pass `chat_turn_depth` to sub-executor |
| `backend/app/services/cluster/node_placement.py` | `heym` predicate: MAIN_ONLY for `sendChatMessage` |
| `backend/app/api/chats.py` | Source constants `workflow`, `workflow_temp`; list excludes `workflow_temp` |
| `backend/app/db/models.py` | Source comment |
| `backend/app/services/workflow_dsl_prompt.py` | DSL section |
| `frontend/src/lib/heymOperations.ts` | `HEYM_CHAT_OPERATION`, `isHeymChatOperation`, `heymChatOperationOption` |
| `frontend/src/components/Panels/propertiesPanel/operationOptions.ts` | Add option |
| `frontend/src/components/Panels/propertiesPanel/nodes/HeymChatFields.vue` (new) | Message, toggles, conversation id |
| `frontend/src/components/Panels/propertiesPanel/nodes/HeymNodeProperties.vue` | Mount `HeymChatFields`, hide other fields for chat |
| `frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts` | Expression navigation keys for chat fields |
| `frontend/src/components/Nodes/BaseNode.vue` | QUESTION handle for Heym chat |
| `frontend/src/components/Canvas/WorkflowCanvas.vue` | Drop `question` edges when leaving the chat operation |
| `frontend/src/components/Chat/ChatListItem.vue` | "Workflow" badge |
| `frontend/src/stores/workflow.ts` | Validation: message required |
| `frontend/src/types/node.ts`, `frontend/src/types/workflow.ts` | Defaults and field types |
| Docs: `frontend/src/docs/content/nodes/heym-node.md`, `reference/features.md`, `reference/node-types.md` | Operation docs |

No release tour (user asked not to).

## Tasks

### Task 1: app loop + depth ContextVar
- [ ] Test `backend/tests/test_app_loop.py`: submit from a thread runs on the registered loop and returns the value; `submit` without a registered loop raises `RuntimeError`; `chat_turn_depth()` defaults to 0 and `chat_turn_depth_scope(n)` sets it.
- [ ] Implement `app_loop.py`; register in `main.py` lifespan.

### Task 2: executor depth + output skip
- [ ] Test: executor built inside `chat_turn_depth_scope(2)` has `chat_turn_depth == 2`; explicit param wins; sub-executors inherit.
- [ ] Test: `_edge_matches_source_handle(edge_with_null_handle, "output")` is True for a non-condition node and False for condition.
- [ ] Implement in `workflow_executor.py` and `execute_node.py`.

### Task 3: chat node service
- [ ] Tests `backend/tests/test_heym_chat_node.py` (service part): default LLM missing -> ValueError mentioning Chat tab; continue with missing/foreign/malformed id -> same "Conversation not found or not accessible" message; running conversation refused; new conversation created with `source="workflow"`; temporary with `workflow_temp` and deleted after success, error and cancel; output shape from `AgentTurnResult`; fire and forget returns id before the turn finishes; depth var set inside the turn.
- [ ] Implement `heym_chat_node.py`.

### Task 4: handler
- [ ] Tests: field validation (empty, too long, both exclusive toggles), depth guard, handle routing per outcome, cancellation cancels the future, user resolution uses actor else owner.
- [ ] Implement in `heym_node.py`.

### Task 5: placement + chat list
- [ ] Tests in `test_cluster_node_placement.py` and a chat list test for `workflow_temp`.
- [ ] Implement.

### Task 6: advisory test
- [ ] `backend/tests/test_advisory_heym_chat_node_scope.py`: foreign conversation id refused with the missing-id message; collaborator canvas run uses the collaborator; cron run uses owner.

### Task 7: DSL + docs
- [ ] DSL section, docs pages.

### Task 8: frontend
- [ ] Operation option, `HeymChatFields.vue`, properties wiring, expression navigation, validation, BaseNode handle, canvas edge pruning, chat badge, types.
- [ ] Vitest: `heymOperations.test.ts` for the chat helpers and handle predicate.
- [ ] Playwright `frontend/e2e/heym-chat-node.spec.ts`.

### Task 9: verify
- [ ] `cd backend && uv run ruff format . && uv run ruff check .`, focused pytest, `bun run lint`, `bun run typecheck`, `bun run test`, then `./check.sh` with a throwaway Postgres, then the new Playwright spec.
- [ ] Commit locally on `feat/heym-node-chat-message` without attribution; do not push.
