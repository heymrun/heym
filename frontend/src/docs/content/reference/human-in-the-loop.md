# Human-in-the-Loop

Human-in-the-loop (HITL) lets an [Agent Node](../nodes/agent-node.md) request approval at specific moments, wait for a human decision, then continue the workflow from the same execution snapshot.

## What It Does

- Adds explicit approval checkpoints to an agent without building a separate approval workflow
- Creates a one-time public review URL at `/review/{token}`
- Lets a reviewer `Accept`, `Edit & Continue`, or `Refuse`
- Marks the execution as `pending` until a decision arrives
- Resumes the paused execution and lets the agent continue after approval
- Supports multiple sequential HITL checkpoints in the same agent run

## Agent Configuration

Enable HITL in the agent properties panel.

| Setting | Description |
|---------|-------------|
| `hitlEnabled` | Turns on human review for this agent |
| `hitlSummary` | Approval guidelines for when the agent should request human review |

HITL adds a `request_human_review` tool to the agent. Use the system prompt and `hitlSummary`
guidelines to tell the agent which actions need approval. When the agent decides a checkpoint
needs review, it sends a single Markdown review text to the human. The reviewer-facing summary is
generated from the agent's request at runtime; if the agent omits it, Heym derives one from the
Markdown body. In v1, HITL supports text-mode agent outputs only, so it cannot be combined with
`jsonOutputEnabled`.

For MCP tools, Heym asks the model to interpret the written HITL instructions into one of three
approval scopes:

- `always` for phrases like "always", "on each", or "for each"
- `once` for phrases like "once" or "only one time"
- `never` for phrases like "never", "do not ask", or "already approved"

That interpretation controls whether repeated MCP calls pause again, stay approved once, or skip
human review entirely.

When HITL is enabled, the agent also exposes a second canvas output handle labeled `review`. Use that branch to send the pending review URL and summary to Slack, email, logging, or any other notification flow while the main execution waits for a person.

## Review Flow

1. The agent reaches an approval-required step and calls `request_human_review`
2. Heym creates a public review request and returns a review URL
3. Any nodes connected to the agent's `review` handle run immediately with the pending HITL payload
4. The workflow execution moves to `pending`
5. A reviewer opens `/review/{token}` without logging in
6. The reviewer chooses one action:
   - `Accept` continues with the original Markdown
   - `Edit & Continue` continues with the edited Markdown
   - `Refuse` continues with `decision: "refused"` and skips further agent action
7. Heym resumes the workflow from the stored snapshot and lets the agent continue with the approved Markdown context
8. If a later step also requires approval, the agent can call HITL again and create another pending checkpoint

Review links expire after 168 hours if nobody responds.

## Public Review Page

The public review page shows:

- The workflow name and agent label
- An auto-generated reviewer summary from the agent's review request
- The Markdown review text first, as the main content
- An edit box that opens only after the reviewer clicks `Edit`
- A live Markdown preview while editing
- Action buttons for `Accept`, `Edit & Continue`, and `Refuse`

Once a decision is submitted, the token is locked and cannot be reused.

## Outputs and Execution State

While waiting for review, the agent output contains a pending payload:

```json
{
  "decision": null,
  "summary": "Review the customer-ready reply before it is sent.",
  "draftText": "# Goal\n...\n\n# Planned Tool Calls / Actions\n- ...",
  "reviewUrl": "https://example.com/review/abc123",
  "requestId": "uuid",
  "expiresAt": "2026-03-29T10:00:00Z",
  "shareMarkdown": "Review the customer-ready reply before it is sent.\n\n[Open review page](https://example.com/review/abc123)"
}
```

After the reviewer responds and the workflow resumes, the final agent output includes the decision metadata:

```json
{
  "text": "Final agent output after approval and execution",
  "decision": "accepted",
  "summary": "Review the customer-ready reply before it is sent.",
  "originalDraft": "# Goal\n...\n\n# Planned Tool Calls / Actions\n- ...",
  "requestId": "uuid"
}
```

Use `$agentLabel.decision` in downstream nodes to branch on accepted, edited, or refused outcomes.

## Canvas Review Branch

The `review` output handle is available only when `hitlEnabled` is turned on for an agent.

- It runs before the human decision arrives
- It receives the pending HITL payload, including `summary`, `draftText`, `reviewUrl`, `shareText`, and `shareMarkdown`
- It is intended for notification or handoff steps such as Slack, email, or audit logging
- It runs once for each HITL checkpoint
- It does not run again after the reviewer responds; only the normal agent output path continues on resume

## Where It Appears

- [Execution History](./execution-history.md) shows `pending` runs immediately and stores the review URL in node results
- [Portal](./portal.md) chat responses show the human review link instead of an empty answer
- The Debug panel and history dialogs show the final HITL decision and the reviewed text
- The review output handle can notify external channels even when the workflow was triggered by cron, curl, or portal traffic
- Multiple HITL checkpoints reuse the same execution history entry while creating a new one-time review link for each pause

## Current Limits

- HITL is available on Agent nodes only
- HITL uses the agent's text output and does not support JSON output in v1
- A paused execution resumes from the stored workflow snapshot, not the latest edited workflow version
- Nested sub-workflows cannot enter a pending HITL state in v1; request review from the parent agent before calling them

## Related

- [Agent Node](../nodes/agent-node.md) - Configure HITL on an agent
- [Agent Architecture](./agent-architecture.md) - How agents, tools, sub-agents, and HITL fit together
- [Execution History](./execution-history.md) - Inspect pending and resumed runs
- [Portal](./portal.md) - Public chat flows and HITL review links
