# Evals Tab

The **Evals** tab is a separate page at `/evals`. It lets you create evaluation suites, define test cases, and run evaluations against your [Agent](../nodes/agent-node.md) workflows.

<video src="/features/showcase/evals.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/evals.webm">▶ Watch Evals demo</a></p>

## Access

- Click **Evals** in the dashboard tab bar
- Or navigate to `/evals`
- Or use **Ctrl+K** (Cmd+K) and select "Evals" from the command palette

## Eval Suites

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
- **Temperature** – Set model temperature (`Exact Match` and `Contains`)
- **Reasoning effort** – Set reasoning effort for reasoning models (`Exact Match` and `Contains`)

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

## Benchmark Matrix Ideas

When you build a benchmark matrix for agent workflows, include HITL scenarios as first-class cases instead of treating them as edge cases.

- Cover all three review decisions: `accepted`, `edited`, and `refused`
- Include multiple trigger sources such as editor runs, portal, curl/webhook, and cron-triggered executions
- Add repeated-review scenarios where one agent run pauses more than once
- Verify notification branches connected to the agent's `review` output
- Assert downstream behavior after refusal, especially if later nodes branch on `$agent.decision`

## Related

- [Why Heym](../getting-started/why-heym.md) – Built-in evals as an AI-native feature
- [Agent Node](../nodes/agent-node.md) – Workflows being evaluated
- [Credentials Tab](./credentials-tab.md) – Credentials for eval runs
- [Traces Tab](./traces-tab.md) – Detailed trace inspection
- [Workflows Tab](./workflows-tab.md) – Create workflows to evaluate
- [Execution History](../reference/execution-history.md) – View past runs (History button in header)
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide available on the evals page
