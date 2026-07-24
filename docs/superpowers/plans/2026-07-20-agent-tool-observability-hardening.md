# Agent Tool Observability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the Agent Tool Observability MVP without changing existing Agent execution results or breaking historical records.

**Architecture:** Keep the current JSON/JSONB storage and SSE contracts, adding only optional fields. Normalize tool-call lifecycle records in `llm_service.py`, sanitize persisted payloads before trace storage, and add opt-in `heym.agent.tool.execute` spans around tool execution. Existing trace rows remain readable through compatibility defaults.

**Tech Stack:** Python 3.11+, FastAPI/Pydantic, SQLAlchemy JSONB, OpenTelemetry SDK, pytest, Vue 3 + TypeScript.

## Global Constraints

- Work directly on `main`; do not create worktrees or branches.
- Preserve existing Agent outputs, tool execution behavior, and old trace/dashboard records.
- New fields are optional and historical records must continue to parse.
- Raw tool arguments/results are not persisted unless explicit opt-in configuration enables them.
- OTel tool spans must be no-op when OTel is disabled and must never affect execution.
- Use TDD: write each regression test, observe failure, implement, then rerun.

### Task 1: Align tool-call status contracts

**Files:**
- Modify: `backend/app/models/chat_schemas.py`
- Modify: `frontend/src/types/chat.ts`
- Test: `backend/tests/test_dashboard_chat_api.py`

- [x] Add a regression test proving a persisted cancelled tool call validates as a `MessageResponse`.
- [x] Run the focused test and observe the current Pydantic validation failure.
- [x] Add `cancelled`, `pending`, and `timeout` as compatible statuses in the backend and frontend contracts.
- [x] Rerun the focused test and existing dashboard chat tests.

### Task 2: Add stable tool-call IDs and lifecycle records

**Files:**
- Modify: `backend/app/services/llm_service.py`
- Modify: `backend/app/services/workflow_executor.py`
- Modify: `frontend/src/lib/traceSteps.ts`
- Test: `backend/tests/test_agent_tool_observability.py`

- [x] Add failing tests for persisted `tool_call_id`, pending HITL records, and failed/cancelled records.
- [x] Normalize entries with optional `tool_call_id`, `status`, `started_at`, and `finished_at` fields while retaining current keys.
- [x] Emit a completed entry for HITL pending calls and preserve entries on abort/error paths.
- [x] Use ID-first matching in trace rendering and retain name/order fallback for historical data.
- [ ] Run focused tests and the existing Agent tool tests.

### Task 3: Add safe payload sanitization

**Files:**
- Create: `backend/app/services/agent_tool_observability.py`
- Modify: `backend/app/services/llm_trace.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_agent_tool_observability.py`

- [x] Add failing tests for recursive truncation and redaction of common secret fields.
- [x] Implement bounded JSON-compatible sanitization with configurable maximum length/depth and opt-in raw capture.
- [x] Apply sanitization only to persisted trace request/response payloads; keep execution inputs/results unchanged.
- [x] Verify historical trace response handling remains unchanged.

### Task 4: Add opt-in Agent tool OTel spans

**Files:**
- Modify: `backend/app/services/llm_service.py`
- Modify: `backend/app/observability/tracing.py`
- Test: `backend/tests/test_observability_tracing.py`
- Test: `backend/tests/test_agent_tool_observability.py`

- [x] Add failing tests for a `heym.agent.tool.execute` child span, status/error attributes, and disabled no-op behavior.
- [x] Wrap only the tool executor call; preserve existing timeout, retry, HITL, and result packaging behavior.
- [x] Add `heym.agent.tool.*` attributes without storing raw arguments by default.
- [x] Ensure nested node/MCP/sub-workflow spans inherit the active context.

### Task 5: Add tool-level metrics and compatibility UI behavior

**Files:**
- Modify: `backend/app/services/agent_tool_observability.py`
- Modify: `backend/app/services/llm_service.py`
- Modify: `frontend/src/components/Traces/TraceStepCard.vue`
- Test: `backend/tests/test_agent_tool_observability.py`

- [x] Add tests for wall-clock duration, cumulative tool duration, and status aggregation metadata.
- [x] Store optional aggregate metadata in the existing response object without changing existing timing keys.
- [x] Display pending/timeout/cancelled states consistently while leaving historical rows unchanged.

### Task 6: Verification

- [x] Run focused standalone tests; OTel/Agent integration tests remain blocked by local backend dependency setup.
- [x] Run frontend lint/typecheck and production build; backend Ruff/full check remains blocked by local `uv sync`.
- [ ] Run the full `check.sh` with the test `SECRET_KEY` if required.
- [x] Inspect the final diff for accidental behavior changes and confirm no secrets/config files were added.
