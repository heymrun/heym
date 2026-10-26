# Evals Tab

The **Evals** tab is a separate page at `/evals`. It lets you create evaluation suites, define test cases, and run evaluations against your [Agent](../nodes/agent-node.md) workflows. An [agent suite](#agent-suites) runs an agent or reads its real runs, and checks the tools it calls, its latency, its USD cost, its tokens and its number of tool calls.

<video src="/features/showcase/evals.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/evals.webm">▶ Watch Evals demo</a></p>

## Access

- Click **Evals** in the dashboard tab bar
- Or navigate to `/evals`
- Or use **Ctrl+K** (Cmd+K) and select "Evals" from the command palette

## Eval Suites

- **New Suite** – Choose **Prompt suite** to test a system prompt across models, or **Agent suite** to check an agent's real runs (see [Agent Suites](#agent-suites))
- **Suite picker** – Lists prompt and agent suites together with the type beside each name; type to search
- **Create suite** – Define a suite with a name and description
- **Select workflow** – Choose which workflow to evaluate
- **Select credential** – API key for running the workflow
- **System prompt** – Edit the suite-level system prompt directly in the left panel
- **Optimize Prompt** – Ask an LLM to improve the current system prompt

## Test Cases

- Add test cases with input prompts and expected outputs
- Each case can have a custom expected value for comparison
- Edit or delete cases from the suite
- **Generate Test Data** – Use the selected credential/model to auto-create test cases from the suite prompt

## Running Evaluations

- **Select one or more models** – Run the same suite against multiple models in one evaluation
- **Scoring method** – Choose `Exact Match`, `Contains`, or `LLM-as-Judge`
- **Judge** – For `LLM-as-Judge`, optionally pick an OpenAI, OpenAI compatible (Custom), Gemini (Google) or [Decision Model](../nodes/decision-node.md) credential and type the judge's model (for example `gpt-4o-mini` or `jev-latest`) to score with an independent judge
- **Runs per test** – Repeat each test case multiple times in one run
- **Remembered settings** – A suite opens with its newest run's settings: credential, models, scoring method and judge, temperature, reasoning effort and runs per test. Opening a past run loads that run's settings, so **Re-Run Evals** repeats it
- **Temperature** – Set model temperature (`Exact Match` and `Contains`)
- **Reasoning effort** – Set reasoning effort for reasoning models, from Low to Extra high and Max like the LLM and Agent nodes (`Exact Match` and `Contains`)

### LLM-as-Judge

With a judge, each model answers the test input with the suite prompt alone, then the judge rates how closely the answer matches the expected output from 0 to 100:

- **A model judge** (OpenAI, OpenAI compatible or Gemini) reads the question, the expected output and the answer, and returns a score with a one-line reason. It runs at temperature `0`, or at `low` reasoning effort for a reasoning model, so the same answer gets the same verdict.
- **A decision model judge** rates the answer on a five-level rubric, from *Completely off* to *Fully matches*. The score is the probability-weighted position on that rubric, so it comes from a distribution the model computed rather than a number it wrote.

The cell's hover card shows the judge's reason, or for a decision model the level, the score and its confidence. Latency and tokens describe the model under test; the judge's own calls appear in [Traces](./traces-tab.md) under the **Evals** source. The model picker leaves out Model Router credentials, because an eval compares specific models.

Without a judge, each model answers and scores its own answer in a single request.

Temperature and reasoning effort are hidden in this mode, and the run uses fixed settings: temperature `0.7` for standard models, and `medium` reasoning effort for reasoning models (`low` when they score their own answers).

## Results

- View pass/fail per test case
- Inspect actual vs expected outputs
- Compare per-model outputs side by side when a run includes multiple models
- Review run history for past evaluations; an `LLM-as-Judge` run shows its judge model in the history list
- Open historical runs from the results panel and inspect saved prompt/input/output snapshots
- Opening a past run loads its scoring method and judge into the left panel, so **Re-Run Evals** repeats the same evaluation
- **Export** downloads the run as JSON, including `judge_credential_id` and `judge_model`

## Agent Suites

An agent suite checks one [Agent](../nodes/agent-node.md) node against its runs. It reads them from [Traces](./traces-tab.md), where every run already records its time, tokens, cost and tool calls, and it can also run the workflow for you.

Create one with **New Suite** → **Agent suite** and follow three steps:

1. **Agent** – Pick the workflow, then its agent node. Only workflows with an agent node are listed; a workflow or agent that has not run yet is shown but cannot be picked. The picked agent's settings (model, instructions, tools and limits) show on the right, and a read-only canvas of its workflow, with the agent highlighted, shows below.
2. **Baseline** – The agent's last 10 runs: latency p50 and p95, cost per run, tokens per run and tool calls per run, which tools it called and how often, and each run's own numbers. Runs that ended in an error are listed but left out of the baseline.
3. **Checks** – Mark each tool **Must call**, **Must not call** or **Either**. Every kind of call is listed with its type: Python and node tools, **MCP** tools with their server, **sub-agents** by label, **sub-workflows** by name and **skills**. Add one by kind and name when it has not run yet, and remove it again with its **X**. Set upper bounds for latency, cost, total tokens and tool calls; each starts 20% above the baseline's p95 and can be turned off.

A saved suite opens on **Results**, with **Baseline** and **Edit checks** next to it:

- **Run the workflow** – Choose how many runs (up to 20); four run at a time. The inputs are filled from the workflow's most recent run and can be edited, and every run uses them. Turn on **Generate inputs** (the sparkle), then pick a credential and model, to have the model write a different input for each run. It reads the agent's system instructions and stays close to the values you typed, so typing a city name gets other city names. Each run executes the whole workflow like any other run and is listed in Execution History with the `agent_suite` trigger. To skip later steps, such as one that sends email, open the workflow with **Go to workflow** in the panel and disable those nodes first. **Stop** ends a suite run: no new runs start and the ones going are cancelled. A suite run whose server stopped, for example during a restart, shows as interrupted after a minute instead of staying stuck.
- **Results** – The latest suite run is scored by default. Every suite run is kept with its date in the run picker, where you can open or delete it; or switch to the last 10, 20 or 50 runs of the agent to include its other runs. You see the pass rate, how often each check passed, latency, cost, tokens and tool calls next to the saved baseline, and each run with the reason it failed and a link to its trace.
- **Go to workflow** opens the agent's workflow in a new tab. In the name field, **Esc** or the **X** clears it.

How the numbers are read:

- **Latency** is the model's time plus the time of the run's tool calls.
- **Cost** uses the same prices as Traces. A run of a model without a price skips the cost check instead of failing it.
- A run **passes** when it finished without an error and every check passed.
- The suite reads your own traces only, the same rule as the Traces tab.
- **Use latest runs as baseline** in **Edit checks** replaces the saved baseline with the agent's latest runs.

A suite's baseline comes from one of three places. **Edit checks** shows which one next to **Saved baseline**:

- the agent's latest runs (the default, and what **Use latest runs as baseline** takes),
- one finished suite run,
- numbers entered by hand.

The last two are set from [Chat](./chat-tab.md#working-with-evals) or the API:

- `PATCH /api/evals/agent-suites/{id}` takes `baseline: {"source": "suite_run", "run_id": "…"}` or `{"source": "manual", "values": {"latency_p95_ms": 3000, "cost_avg_usd": 0.01}}`.
- `POST /api/evals/agent-suites/{id}/runs` takes `inputs_list`: one input object per run, up to 20.

### From Chat and MCP

[Chat](./chat-tab.md#working-with-evals) and the MCP `heym_chat` tool can create, change and run prompt and agent suites:

- They write test cases and run inputs themselves.
- They ask which credential to use before creating a prompt suite, unless only one fits.
- They link every suite they mention on this page.

## Benchmark Matrix Ideas

When you build a benchmark matrix for agent workflows, include HITL scenarios as first-class cases instead of treating them as edge cases.

- Cover all three review decisions: `accepted`, `edited`, and `refused`
- Include multiple trigger sources such as editor runs, portal, curl/webhook, and cron-triggered executions
- Add repeated-review scenarios where one agent run pauses more than once
- Verify notification branches connected to the agent's `review` output
- Assert downstream behavior after refusal, especially if later nodes branch on `$agent.decision`

## Related

- [Why Heym](../getting-started/why-heym.md) – Evals as the test stage of the agent lifecycle
- [Agent Node](../nodes/agent-node.md) – Workflows being evaluated
- [Credentials Tab](./credentials-tab.md) – Credentials for eval runs
- [Traces Tab](./traces-tab.md) – Detailed trace inspection
- [Workflows Tab](./workflows-tab.md) – Create workflows to evaluate
- [Execution History](../reference/execution-history.md) – View past runs (History button in header)
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide available on the evals page
