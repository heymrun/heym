# Alerts Tab

The **Alerts** tab lets you define threshold conditions over a time window and be told when they are crossed. Heym already records execution outcomes, run duration, and LLM spend, but it never volunteers any of it. An alert is how you ask it to.

Every alert is evaluated over a **time window** you choose, never on a single event. One failed run is noise. Twelve failed runs in ten minutes is an incident.

## Alert Types

| Type | The question it answers | Where the number comes from |
|---|---|---|
| **Error threshold** | Did this fail more than N times in the window? | [Execution history](../reference/execution-history.md) rows with an error status |
| **Workflow duration** | Did runs get slower than expected in the window? | Execution time, aggregated as max, average, or 95th percentile |
| **Token / USD cost** | Did spend cross a budget in the window? | [LLM traces](./traces-tab.md) plus the LLM cost table |
| **Execution count** | Did this run far more often than it should have? | Execution history row count |

### Error threshold

Counts failed runs across the window and fires when the count reaches your threshold. Because it counts over a window rather than hooking each failure, a single transient error will not page you.

### Workflow duration

Measures run duration inside the window. Choose **max** (the slowest run), **average**, or **p95**. The p95 figure uses the same percentile calculation as the [Analytics tab](./analytics-tab.md), so the alert and the latency chart never disagree about the same window.

**Minimum runs in the window** keeps this honest. The slowest run in a nearly empty window is just that one run, so setting a minimum of, say, 3 stops the alert firing on noise.

### Token / USD cost

Sums LLM spend across the window, either as total tokens or as US dollars. Dollar amounts resolve through the same pricing table the [Traces tab](./traces-tab.md) and the [LLM Cost Table](./datatable-tab.md#llm-cost-table-system-table) use, so a cost alert and the cost page always agree.

When the scope is all your workflows, this includes LLM calls made outside a workflow, such as the [Chat tab](./chat-tab.md) and the [AI Assistant](../reference/ai-assistant.md). Coding agent usage (Codex, OpenCode) is not included.

Models with no pricing row are reported in the alert's context as unpriced rather than silently counted as zero.

### Execution count

Counts runs of any status in the window. This is the one that catches a trigger gone wrong: a workflow that normally runs 20 times an hour suddenly running 2,000 times. The firing record includes a per-trigger-source breakdown, because that is usually the answer to "why did this happen".

## Scope

An alert watches either **one workflow** or **all your workflows**.

"All your workflows" means every workflow the alert's owner can access. It deliberately does not mean every workflow on the Heym instance: alerts can be shared, and sharing an alert should not hand someone aggregate numbers for workflows they cannot open.

## The Wizard

Creating an alert walks through five steps.

1. **Type** — pick one of the four above.
2. **Scope** — one workflow, or all of them.
3. **Condition** — the time window, plus the threshold fields for that type.
4. **Response** — what runs when it fires, and how often to keep telling you.
5. **Review** — name it, and see the backtest.

### The backtest

The Review step answers the question that actually matters before you save: *over the last 24 hours, how often would this have fired?*

It reports the firing count and the highest observed value against your threshold. If it says the condition would have fired 400 times, you fix the threshold before saving instead of after being paged. You can widen the lookback to 3 or 7 days.

## AI Drafting

At the top of the first step is a box where you describe what you want in plain language:

> Warn me if the invoice sync fails more than 5 times in 10 minutes

Heym turns that into an alert definition, fills every step it can, and jumps ahead with the AI-filled fields marked, so you confirm rather than retype. A complete request lands you on Review.

**A partial request still moves you forward.** Say only "warn me if it fails 5 times" and you get an error threshold alert with the count filled in, defaults for the rest, and the wizard opens on the first step that still needs you: in that case Scope, because no workflow was named. A note at the top says what is left to decide. It never blocks Next or Create.

The same applies when the model names a workflow you cannot access, or returns a condition with fields missing. The parts that make sense are kept, the rest falls back to the defaults for that alert type, and you adjust from there. Nothing here bypasses validation: the wizard's own rules and the API both re-check the alert when you save.

## Repeat Behaviour

Once an alert fires, it enters a triggered state. What happens next is your choice on step 4.

- **Notify once, until it recovers** (the default) — fires once, then stays quiet while the condition holds. When the metric drops back under the threshold the alert returns to OK and becomes eligible to fire again. Recovery is a state change, not an event: it does not create a firing record and does not run the notify workflow.
- **Keep notifying on an interval** — fires again every N minutes for as long as the condition holds.

The default exists because a broken workflow checked every 60 seconds would otherwise produce 60 firings an hour, which is how alerting gets muted.

## Running a Workflow on Fire

Step 4 offers three answers to "what should happen when this fires":

- **Create and assign a new workflow** (the default) — saving the alert also creates a workflow called *"&lt;alert name&gt; notification"* and links it. It arrives with an input node whose fields are exactly the payload below, so `$alert.body.observed_value` and the rest resolve immediately and you only have to attach the node that delivers the message. **Go to workflow** on the alert card opens it. This is the default because an alert that fires into nothing is easy to miss.
- **Pick an existing workflow** — run something you have already built.
- **Do nothing** — the firing is still recorded in the tab, it just does not run anything.

The alert payload arrives as that workflow's input body:

```json
{
  "alert_id": "...",
  "alert_name": "Invoice sync failures",
  "alert_type": "error_threshold",
  "condition": "5+ errors in 10m",
  "scope": "workflow",
  "workflows": [{ "id": "...", "name": "Invoice Sync", "value": 12 }],
  "observed_value": 12,
  "threshold_value": 5,
  "window_start": "2026-08-09T11:50:00+00:00",
  "window_end": "2026-08-09T12:00:00+00:00",
  "window_minutes": 10,
  "context": { "error_count": 12 }
}
```

### Which workflow produced the number

`workflows` is the only place a workflow appears. It lists every workflow that contributed to the reading, each with its own `value` — that workflow's error count, run count, slowest run in milliseconds, or spend, depending on the alert type. The list is sorted by `value`, highest first, so `workflows[0]` is the worst offender.

It is **always an array**: single-element under one-workflow scope, many under "all my workflows", and empty rather than null when nothing is attributable. A notify workflow can iterate it without a shape check.

There is deliberately no singular `workflow_id`. It described the alert's scope rather than the metric, so it was `null` under system scope, which is exactly the case where "which workflow?" matters most. `observed_value` remains the aggregate the threshold was compared against; the per-workflow `value` fields explain where it came from.

This is how alerts reach Slack, email, Telegram, or anywhere else: with the [nodes](../reference/node-types.md) you already have, rather than a separate notification system.

An alert cannot notify the workflow it is watching. That would be a loop, most obviously for an execution count alert where each notification adds to the count it measures.

Notify runs are ordinary executions, so they appear in [execution history](../reference/execution-history.md) like any other run. A notify workflow that fails is recorded on the firing but never prevents the firing itself from being recorded.

## Firing History

Below the alert list is the firing history: what fired, when, the observed value against the threshold, the exact window that was evaluated, and the notify outcome.

Acknowledging a firing marks the row and changes the alert's badge from **Firing** to **Acknowledged**. That is a statement about you, not about the alert: the condition still holds, and the alert returns to **OK** on its own when the metric drops back under the threshold.

Each record stores the contributing detail at the moment it fired: failing execution ids and error messages, per-model spend, or the trigger-source breakdown. This is deliberate. The window has passed, and recomputing it later can give a different answer.

Firing records are kept for 90 days.

## Asking Chat About Alerts

The [Chat tab](./chat-tab.md) can answer questions about your alerts:

- "What alerts do I have?"
- "Is there an alert on the invoice workflow?"
- "Why did the cost alert fire?"
- "When did this last trigger?"

For a "why did it fire" question, Chat quotes the actual observed value, the threshold, and the time window from the firing record, along with the contributing detail.

## Sharing

Alerts can be shared with individual users or with [teams](./teams-tab.md). People you share with can see the alert and its firing history. Only the owner can edit, pause, delete, or re-share it.

## Managing Alerts

- **Pause / Resume** — a paused alert is never evaluated. Resuming checks it immediately rather than waiting for the next interval.
- **Edit** — changes are validated as a whole, so a partial edit cannot leave the alert in an invalid state.
- **Delete** — removes the alert and its firing history.

## See Also

- [Analytics Tab](./analytics-tab.md) — the charts these thresholds are drawn from
- [Traces Tab](./traces-tab.md) — where LLM cost figures come from
- [Execution History](../reference/execution-history.md) — the runs that error, duration, and count alerts measure
- [Chat Tab](./chat-tab.md) — querying alerts in natural language
- [Teams](./teams-tab.md) — sharing alerts with a team
