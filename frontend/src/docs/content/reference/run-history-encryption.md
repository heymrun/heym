# Run History Encryption

Run history encryption keeps the inputs, outputs and node results of a workflow's runs encrypted at rest. Nobody sees them by default, the workflow owner and instance administrators included. When someone needs a run, they unlock it in [Execution History](./execution-history.md), the server decrypts it for that one request, and the unlock is written to the [audit log](./audit.md).

## When to use it

Use it for production workflows whose runs carry data people should not browse: personal data from forms, chats and inboxes, HR and payroll steps, patient or customer records, payment details. The workflow keeps running and keeps its history; only the content is sealed, and opening it is a recorded decision rather than a click anyone can make.

The [Workflow Analysis](./workflow-analysis.md) report suggests turning it on when a workflow appears to process personal data or is shared with other people.

## Turning it on

Open the workflow, deselect all nodes, and switch on **Encrypt run history** in the workflow-level **Properties** panel. Only the workflow owner can change it; collaborators see its state. Every change is audited as `workflow.run_history_encryption` with `enabled=true` or `enabled=false`.

The setting applies from that moment on:

- Runs written while it is on are encrypted, whatever started them: webhooks, triggers, cron, MCP, the Portal, boards, dashboard widgets, and editor test runs on the canvas.
- Sub-workflow runs started by an encrypted run are encrypted too.
- Turning it off does not decrypt anything. Runs recorded while it was on stay encrypted.

## What is stored

| Part of the run | Stored as |
|-----------------|-----------|
| Inputs, outputs | Encrypted |
| Node outputs, errors, tool calls, review details | Encrypted |
| Which nodes ran, their status and duration | Plain, so timelines, analytics and alerts keep working |
| Status, start time, duration, trigger, instance | Plain, as for every run |

While a run is still going, the registry row other instances read it from holds its inputs and node results sealed the same way.

A run that waits in a [concurrency queue](./webhooks.md#concurrency-limit-and-queued-runs) or goes through [Load Distribution](./cluster.md) also leaves a queue row behind. Its inputs and the outputs part of its result are sealed with the same key, and the instance that runs it decrypts them in memory.

The setting covers run history. LLM and Agent calls are also recorded as [Traces](../tabs/traces-tab.md), which are kept separately from run history.

Encryption is AES-256-GCM. Each run is sealed with a key that belongs to the workflow owner and is derived from a random secret kept for that user. The secret is wrapped with the server's `ENCRYPTION_KEY`, is never returned by any API, and is re-encrypted by [key rotation](./security.md#rotating-the-key) like credentials. Each ciphertext is bound to its own run, so it cannot be copied onto another one.

## Unlocking a run

Encrypted runs show a lock icon in both history dialogs. Selecting one shows **Encrypted run** in place of its data.

1. Click **Unlock**.
2. Confirm in the dialog. It tells you that your account, the workflow, the run and the time will be written to the audit log.
3. The run opens with its inputs, outputs and node results for the rest of the session.

The history dialogs never receive the data of an encrypted run until it is unlocked, so it does not travel over the network beforehand. Unlocking needs at least read access to the workflow and is audited as `workflow.history_unlock` for owners, collaborators and administrators alike, with `permission` and `owned` fields. A refused unlock is audited with `outcome=denied`.

A locked run cannot be brought to the canvas, by **Bring to Canvas** or by double-clicking it, until it is unlocked. An execution link to a locked run asks **Open this encrypted run?** first, and confirming it is the same audited unlock.

History search runs on the server, which matches an encrypted run by its workflow, status and trigger only. Runs you have unlocked in this session are also matched by their content, in your browser, in both history dialogs.

## Watching a running run

When the canvas attaches to a run of such a workflow that is still going or waiting for a [review](./human-in-the-loop.md), through **Open live**, an execution link, or following someone, it first asks **Watch this encrypted run?** (or **Open this encrypted run?** for a paused one). A run you started in the editor that pauses for review asks too before the canvas keeps following it. Nothing streams until you confirm. The confirmation is audited as `workflow.live_run_unlock`, and the run then streams with its inputs and node results, its final result included. The person who started a run in the editor watches it directly.

[Heym Work](./heym-work.md) shows encrypted runs the same way in Activity and the Quick Drawer, and unlocks them through the same audited step.

## What skips encrypted runs

Everything else that reads run content leaves encrypted runs out and says how many it left out:

| Reader | Behavior |
|--------|----------|
| Chat `get_workflow_run_history` (also `heym_chat` over MCP) | Lists runs without encrypted ones, adds `encrypted_runs_skipped`; refuses the detail of an encrypted run |
| Chat `get_recent_executions` | Leaves encrypted runs out, adds `encrypted_runs_skipped` |
| [Heym node](../nodes/heym-node.md) **Get Execution History** | Leaves encrypted runs out of `executions`, adds `encrypted_skipped` |
| Run status URL and MCP `heym_execution_status` | Return outputs only to the caller that started the run, with the `status_token` (MCP: `run_token`) its queued response returned; everyone else gets the status with `encrypted: true` and no outputs |
| [Evals](../tabs/evals-tab.md) sample inputs | Uses the latest run that is not encrypted |
| History search | Matches workflow name, status and trigger of encrypted runs, never their content |

Counts and durations still include encrypted runs, so [Analytics](../tabs/analytics-tab.md), [Alerts](../tabs/alerts-tab.md) and status breakdowns are unchanged. Work that continues a paused run, such as a [Human-in-the-Loop](./human-in-the-loop.md) resume or a [Board](../tabs/board-tab.md) chain, decrypts on the server to carry on and never shows the data.

## Related

- [Execution History](./execution-history.md)
- [Audit Logging](./audit.md)
- [Security](./security.md)
- [Workflow Analysis](./workflow-analysis.md)
