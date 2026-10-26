# Eval suites from Chat and MCP

Date: 2026-10-26
Status: approved design, awaiting spec review

## Goal

A message in the Chat tab or a call to MCP `heym_chat` can create, edit and run both kinds of
eval suite:

- **Prompt suites**: a system prompt, test cases (input and expected output), a scoring method,
  and runs over one or more models.
- **Agent suites**: one agent node's runs checked against tool-call assertions and thresholds,
  compared with a baseline.

The chat writes the content itself: it fills in test-case inputs and expected outputs, and the
inputs of agent runs. It asks the user which credential to use before it creates a suite,
unless exactly one credential fits.

For agent suites, the chat handles the baseline three ways:

1. It reads and reports the baseline: metrics from the agent's latest runs, plus suggested
   thresholds.
2. It builds a baseline by running the workflow with inputs it writes, then stores those runs
   as the baseline.
3. It stores baseline values the user states (manual baseline).

## Non-goals

- **The canvas assistant.** The editor's AI assistant and its YOLO loop get no eval tools.
  Evals are created from a chat message or an MCP call only.
- **Deleting.** No suite or run deletion from chat. Removing test cases inside an edit is
  allowed.
- **New UI flows.** Evals UI changes are limited to a label for the baseline's source.
- **Model-written inputs on chat runs.** The existing `generate_inputs` run option, where a
  second model writes agent inputs, is not offered to the chat. The chat writes the inputs
  itself.

## Principle: one implementation

Every suite and run operation has exactly one implementation. The HTTP routers and the chat
tools both call it. The suite logic currently written inline in the eval routers moves into
service functions, and the routers become thin wrappers. Chat-only code is limited to:

- tool schemas,
- argument parsing,
- compact summaries of results,
- prompt instructions.

## Where the tools are offered

The eval tools join the build-mode tool set. `ChatBuildSession` is created only for dashboard
chat turns that carry `allow_build`:

- **Chat tab**: always sends `allow_build`.
- **MCP `heym_chat`**: always runs with `BuildRequest()`.
- **Heym Work Chat**: also sends `allow_build`.

Skill-only turns (`allow_skill_write` without `allow_build`) do not get them. The canvas
assistant never creates a `ChatBuildSession`, so it cannot reach them.

`ChatBuildSession` holds a `ChatEvalTools` instance and delegates to it:

| `ChatBuildSession` method | Delegation |
|---|---|
| `tools()` | appends the eval schemas |
| `handles()` | delegates eval names |
| `call()` | delegates eval names |
| `step_label()` | delegates eval names |
| `display_args()` | delegates eval names |
| `prompt()` | appends the eval instructions |

## Internal API (service layer)

### `backend/app/services/prompt_suite_service.py` (new)

Errors:

- `EvalSuiteNotFoundError(LookupError)`: routers map it to 404.
- `ValueError`: invalid input; routers map it to 400.

Functions, each taking the existing Pydantic models from `eval_schemas.py` as input:

- `load_owned_prompt_suite(db, suite_id, user_id, *, with_test_cases=False) -> EvalSuite`
- `create_prompt_suite(db, user_id, body: EvalSuiteCreate) -> EvalSuite`
- `update_prompt_suite(db, suite, body: EvalSuiteUpdate) -> EvalSuite`
- `add_test_case(db, suite_id, body: EvalTestCaseCreate) -> EvalTestCase`
  - Owns the `order_index` rule that `add_test_case` and `generate_suite_test_data` both use
    today.
- `update_test_case(db, suite_id, tc_id, user_id, body: EvalTestCaseUpdate) -> EvalTestCase`
- `delete_test_case(db, suite_id, tc_id, user_id) -> None`
- `apply_test_case_changes(db, suite, upserts, delete_ids) -> None`
  - Used by the chat. It is built from the three per-item functions above.
  - An upsert with an `id` updates that case; an upsert without one adds a new case.
  - An `id`, in an upsert or in `delete_ids`, that is not one of this suite's cases is a
    `ValueError`, and nothing is written.
- `launch_prompt_run(db, user, suite_id, body: RunEvalsRequest) -> EvalRunLaunch`
  - Calls `create_run` and returns the run row and a `job: Callable[[], Awaitable[None]]`.
  - The router schedules it with `background_tasks.add_task(launch.job)`.
  - The chat schedules it with the detached-task helper.
- `prompt_run_response(run) -> EvalRunResponse`
  - Replaces the two copies of this construction in `start_run` and `get_run`.
- `score_to_pct(score) -> int`
  - Moved out of `list_runs`, so the run list and the chat summary agree on what passes.

### `backend/app/services/agent_suite_service.py` (new)

Lookups:

- `load_owned_agent_suite(db, suite_id, user_id) -> AgentSuite`
- `load_accessible_workflow(db, workflow_id, user_id) -> Workflow`

Both raise `EvalSuiteNotFoundError` (or a workflow variant). The router helpers
`owned_agent_suite` and `accessible_workflow` stay as names, wrap these, and raise 404.

Operations:

- `agent_metrics(db, user_id, workflow_id, node_id, limit) -> AgentMetricsResponse`
  - Moved from the `get_agent_metrics` route.
- `create_agent_suite(db, user_id, body: AgentSuiteCreate) -> AgentSuiteResponse`
- `update_agent_suite(db, user_id, suite, body: AgentSuiteUpdate) -> AgentSuiteResponse`
- `resolve_baseline(db, user_id, *, workflow_id, node_id, suite_id: uuid.UUID | None,
  source: AgentBaselineSource) -> dict` returns the stored baseline JSON. `suite_id` is
  `None` on create. Sources:
  - `latest_runs`: today's `_baseline_snapshot`.
  - `suite_run`: `summarize_runs` over the trace ids of one `AgentSuiteRun` of this suite.
    Refused when the run belongs to another suite, is still running, or recorded no agent
    traces.
  - `manual`: validated values, `captured_at` set to now.
- `agent_suite_report(db, user_id, suite, limit, run_id) -> AgentSuiteReportResponse`
  - Moved from the `get_agent_suite_report` route.
- `agent_run_inputs(db, user_id, suite) -> AgentSuiteRunInputsResponse`
  - Moved from the `get_run_inputs` route.

### `backend/app/api/agent_suite_runs.py`

`launch_agent_suite_run(db, user_id, suite, body, public_base_url) -> AgentSuiteRunLaunch`
becomes the one place that:

- refuses a second concurrent run by raising `AgentSuiteBusyError` (409 in the router, an
  error result in chat),
- creates the `AgentSuiteRun` row,
- returns the job that calls `execute_agent_suite_run`.

It stays in the API package because `execute_agent_suite_run` uses `run_execute_workflow_tool`
from `app.api.ai_assistant`. `chat_evals.py` is in the same package.

### Model listing

The model-listing body of `GET /credentials/{id}/models` moves into
`list_credential_models(credential) -> list[LLMModel]`, which:

- handles the model router,
- calls `fetch_models`,
- annotates `KNOWN_LIMITS`,
- raises `ValueError` for credential types without model listing.

The route resolves access and calls it. The chat tool resolves access with
`get_accessible_credential`, which covers owned, shared and team-shared credentials, and calls
the same function.

### Schema additions (HTTP and chat share them)

In `agent_suite_schemas.py`:

```python
class AgentBaselineValues(BaseModel):
    # Every field optional; at least one required. Same units as AgentBaselineResponse.
    latency_p50_ms, latency_p95_ms: float | None (gt 0)
    cost_avg_usd, cost_p95_usd: float | None (ge 0)
    tokens_avg, tokens_p95: float | None (gt 0)
    tool_calls_avg: float | None (ge 0)
    tool_calls_max: int | None (ge 0)

class AgentBaselineSource(BaseModel):
    source: Literal["latest_runs", "suite_run", "manual"] = "latest_runs"
    run_id: uuid.UUID | None = None          # required for suite_run
    values: AgentBaselineValues | None = None  # required for manual
```

Changes to existing models:

- **`AgentSuiteCreate`**: gains `baseline: AgentBaselineSource` (default `latest_runs`, which
  is today's behavior). `suite_run` is refused on create, because a new suite has no runs.
- **`AgentSuiteUpdate`**: gains `baseline: AgentBaselineSource | None`.
  `refresh_baseline: true` stays as it is and means `{"source": "latest_runs"}`. Sending both
  is a 422.
- **`AgentBaselineResponse`**: gains `source` (default `latest_runs`, so stored baselines read
  as before) and `suite_run_id: uuid.UUID | None`. The stored JSON carries both. No migration.
- **`AgentSuiteRunCreate`**: gains `inputs_list: list[dict[str, Any]] | None` (1 to 20 items).
  When given, `count` is its length and each run uses its own input. It cannot be combined
  with `generate_inputs`.

The frontend types in `frontend/src/types/evals.ts` gain the same fields.

## Chat tools

Module layout:

- **`backend/app/services/chat_eval_mode.py`** (no DB or model access): tool names, wait
  limits, the instructions block, and the pure functions that shape compact results.
- **`backend/app/api/chat_evals.py`**: `ChatEvalTools`, which runs the tools. It returns the
  existing `BuildToolOutcome` (result, summary, status).

Every result that names a suite carries `url`: the absolute
`<public_base_url>/evals?suite=<id>`. Absolute links work in the Chat tab, in MCP clients and in
Heym Work.

### Read

**`list_eval_suites`**: both suite types, each with `id`, `name`, `suite_type` and `url`.

**`get_eval_suite(suite_id)`**

- Prompt suite:
  - system prompt and scoring method,
  - test cases (`id`, `input`, `expected_output`),
  - the latest 3 runs with pass counts.
- Agent suite:
  - workflow, node label, assertions, thresholds,
  - the stored baseline with its source,
  - `input_fields` and `previous_inputs` from `agent_run_inputs`,
  - the latest suite run with its status.

**`list_eval_agents`**: agent nodes (`workflow_id`, `workflow_name`, `node_id`, `node_label`,
`run_count`, `last_run_at`) from `list_agent_nodes`.

**`get_agent_baseline(workflow_id, node_id, limit?)`**: from `agent_metrics`:

- the baseline metrics,
- per-tool usage,
- suggested thresholds,
- the run count.

Individual runs are left out.

**`list_llm_models(credential_id)`**: model ids from `list_credential_models`.

### Write

**`save_prompt_suite`**

- Arguments: `suite_id?`, `name`, `description?`, `system_prompt`, `scoring_method?` (one of
  `exact_match`, `contains`, `llm_judge`), `test_cases?: [{id?, input, expected_output}]`,
  `delete_test_case_ids?`.
- Without `suite_id` it creates a suite. With one it updates that suite through
  `update_prompt_suite` and `apply_test_case_changes`.
- Returns the suite with test-case ids and its `url`.

**`save_agent_suite`**

- Arguments: `suite_id?`, `name`, `workflow_id` and `node_id` (create only),
  `tool_assertions?`, `thresholds?`, `baseline?: AgentBaselineSource`.
- Returns:
  - the suite,
  - its stored baseline,
  - the thresholds suggested from that baseline (`suggest_thresholds`), so the chat can
    propose them,
  - `url`.

### Run

**`run_eval_suite(suite_id, …)`**

Prompt suite arguments:

- `credential_id`, `models` (1 or more),
- `scoring_method?` (defaults to the suite's),
- `judge_credential_id?`, `judge_model?`,
- `runs_per_test?` (1 to 20), `temperature?`.

Agent suite arguments:

- `inputs: [{...}]`, 1 to 20 objects, one per run, written by the chat.

Behavior:

- Starts the run through `launch_prompt_run` or `launch_agent_suite_run`, then starts the job
  with `_spawn_detached_task` from `app.api.workflows`, which `ai_assistant.py` already
  imports.
- Waits up to `RUN_WAIT_SECONDS = 60`, polling every 2 seconds with a fresh short-lived
  session, so it sees the background job's commits.
- Stops waiting when the turn's `cancel_event` is set. The run itself keeps going and stays
  visible in Evals.

Result:

- **Finished prompt run**:
  - per model: passed/total, average latency and tokens;
  - up to 5 failed cases: input, expected and actual (truncated), score, judge explanation.
- **Finished agent run**:
  - execution statuses;
  - the report for exactly that run (`agent_suite_report(run_id=…)`): pass rate, per-check
    pass and fail counts, deltas against the baseline;
  - up to 5 failed runs with their failed checks.
- **Not finished**: `status: running`, `run_id` and `url`.

**`get_eval_run(run_id, wait_seconds?)`**

- Looks the id up among the user's prompt runs, then among the user's agent suite runs.
  Both are owner-scoped.
- Waits for a started run: default 30 seconds, at most 120.
- Returns the same shape as `run_eval_suite`.

### Links after create and edit

A saved suite returns its link the way a saved workflow does:

- **Stream event:** `save_prompt_suite` and `save_agent_suite` send an `eval_suite_saved` event with `suite_id`, `suite_name`, `suite_type` and the relative `suite_url` (`/evals?suite=<id>`).
- **Chat tab:** the event becomes a card under the reply, with **Open in Evals**, like the workflow card. The URL must start with `/evals?`.
- **Hidden marker:** the turn appends `<!-- heym-eval-suite-id:<id> heym-eval-suite-name:<name> -->` to the stored reply, so a later turn knows the suite's id.
- **MCP:** `heym_chat` strips that marker from its text. Its result lists "Eval suites saved in this call", built only from the turn's own events and only for suites the user still owns.

### Access and errors

Each tool call opens its own short database session. A refused change is discarded with that
session and never reaches the turn's own session.

Each tool resolves access exactly like the routers, through the same service functions:

- suites are owner-only;
- agent suites need workflow access;
- credentials go through `get_accessible_credential`.

A missing or foreign suite, workflow or credential returns an error result. It never says
whether the item exists for someone else. `ValueError` messages from the services become tool
errors.

## Chat instructions

The eval section of the build-mode prompt says the following.

### Prompt suites

**Before creating a prompt suite**, or before running one when this conversation has not
already settled it, the chat settles three run settings:

1. **The LLM credential.** Fitting credentials are the user's credentials of type `openai`,
   `google`, `custom` or `model_router` in the Credentials list.
   - If exactly one fits, the chat uses it without asking and names it in the reply.
   - Otherwise it asks with one `heym-clarify` single question listing them.
   - The usual credential rules apply, including the create option and `request_credential_form`
     over MCP.
2. **The models.** The chat calls `list_llm_models` for the chosen credential and asks which
   models to compare, unless the user already named them.
3. **The judge**, when scoring is `llm_judge`: a separate judge credential and model, or each
   model scoring its own answer.

**Content.** The chat writes the test cases itself, each with an input and an expected output,
drawn from the system prompt and the user's goal. It writes 5 cases unless the user asks for
another number. It chooses the scoring method that fits the expected outputs:

- `exact_match` for fixed labels,
- `contains` for key facts,
- `llm_judge` for free text.

### Agent suites

**Choosing the agent.** The chat picks the agent with `list_eval_agents`. When the user's
description matches several agents, it asks.

**Inputs.** The chat writes the run inputs itself:

- one object per run,
- keyed by `input_fields`,
- shaped like `previous_inputs` when there is one,
- varied and realistic.

**Running.** Agent runs execute the real workflow, and its side effects happen. The chat runs a
suite only when the user asked for runs or for a baseline built from runs, and it says how many
runs it starts. The limit is 20 runs per call.

**Baseline.**

- To report the baseline, the chat uses `get_agent_baseline` or the stored baseline from
  `get_eval_suite`.
- When the agent has no runs, or the user wants a fresh baseline from runs, the chat:
  1. runs the suite with inputs it writes,
  2. waits for the run to finish,
  3. saves `{"source": "suite_run", "run_id": …}`,
  4. offers the suggested thresholds.
- When the user states numbers, the chat saves `{"source": "manual", "values": …}`.

### Every reply

- Every reply about a suite links it with its `url`.
- The chat never repeats a question this conversation has already answered.

## Evals UI

The Checks step already shows "Saved baseline: <time>". It now adds the baseline's source:

- "from the latest runs",
- "from a suite run",
- "entered manually".

The label comes from a helper in `agentSuiteFormat.ts`.

## MCP

- `MCP_CHAT_TOOL_DESCRIPTION` gains one clause: "create, edit and run prompt and agent eval
  suites, including an agent's baseline".
- No new MCP tool. The eval tools are internal to the chat engine. `heym_chat` calls them
  inside its turn, and an MCP client never sees them in `tools/list`.
- A test asserts that `tools/list` on the global server and on a named server still exposes
  only the existing tools, with no eval tool name.

## Docs and release tour

**Docs:**

- `chat-tab.md`: what the chat can do with evals, with example messages.
- `evals-tab.md`: suites created from Chat or MCP; the three baseline sources;
  `inputs_list`.
- `mcp-tab.md` and `reference/features.md`: the `heym_chat` capability list.

**Release tour:** one section, "Evals from Chat", in the current unreleased entry of
`releaseRegistry.ts`, with a mock visual registered in `tourVisuals.ts`.

## Testing

Backend tests use `unittest` with `AsyncMock`, like the neighbouring tests.

**`test_prompt_suite_service.py`**:

- create and update;
- test-case add, update and delete;
- `apply_test_case_changes`: mixed upserts and deletes, and an unknown id refused;
- foreign suite → not found;
- `launch_prompt_run` returns a job and a running row;
- `score_to_pct`.

**`test_agent_suite_service.py`**:

- the three baseline sources;
- `suite_run` refused for another suite's run, a running run, and a run without traces;
- manual values validated, with an empty `values` refused;
- `source` defaults on old stored baselines.

**Extended existing tests:**

- `test_agent_suites_api.py`: `baseline` on create and patch; both `refresh_baseline` and
  `baseline` → 422.
- `test_agent_suite_runs.py`: `inputs_list` creates one run per input; not combinable with
  `generate_inputs`.
- `test_eval_order_index.py` and the other existing eval tests keep passing unchanged, which
  shows the routers behave as before.

**`test_chat_eval_mode.py`** (pure functions):

- result shaping and truncation;
- the instructions mention the credential rule and the baseline sources.

**`test_chat_evals.py`**:

- tools offered on build turns and not on skill-only turns;
- each tool dispatches to the service;
- foreign suite, workflow or credential → error result;
- the run waits and returns a summary;
- a timeout returns `running` and `url`;
- a set `cancel_event` stops the wait;
- urls are absolute.

**Frontend:** a Vitest case for the baseline source label helper.

No new LLM call path is added. The chat's own model calls already carry the conversation id as
their OpenCode session, and eval runs keep their existing session handling.

## Constraints checked against AGENTS.md

- **Audit:** the eval routers do not audit today, and the chat tools add none. Audit stays an
  API-layer concern.
- **Cluster:** eval jobs run in-process on the instance that handled the turn, as router
  `BackgroundTasks` already do.
- **Heym Work imports:** no module on Work's import list changes.
- **Build mode rules:** the save, test and finish rules for workflows are untouched. Eval tools
  do not count against the workflow test budget.
