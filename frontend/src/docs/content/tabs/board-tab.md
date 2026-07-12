# Board

The **Board** tab is an agentic kanban board. Work moves through columns, and each
column can execute Heym workflows. A card is not just a task — it is a persistent
agentic job that carries context, conversation history, execution state, outputs,
and workflow runs.

<!-- TODO(board-demo): enable when board.webm is recorded
<video src="/features/showcase/board.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/board.webm">▶ Watch Board demo</a></p>
-->

## Boards and columns

- You can create as many boards as you need. A new board starts with the default
  columns **Backlog → Planning → To Do → Waiting → Development → Done**.
- Columns are fully editable: add, rename, recolor, reorder, or delete them from the
  column settings (a column must be empty before it can be deleted).
- Cards are ordered vertically by priority — drag to reorder.

## Column workflow chains

Each column can be configured with an **ordered list of workflows** (the chain).
When a card moves into a column that has a chain:

1. The chain starts automatically in the background — the move itself never waits.
2. Workflows run **sequentially**. Each workflow's output is appended to the card
   context before the next one starts.
3. If a workflow fails, the chain stops: the remaining links are skipped and the
   card turns **red**.
4. When every link succeeds, the card turns **green**. While the chain is running
   the card pulses **amber**; a run paused for human review shows a static amber
   state.

Runs are recorded in [Execution History](/docs/reference/execution-history) with the
`board` trigger source, and each card keeps its own run list with per-workflow
outputs and errors.

## What workflows receive

The chain passes a standard payload as the workflow's input. Read it with normal
[expressions](/docs/reference/expression-dsl) such as `$input.card.title`:

```json
{
  "triggered_by": "board",
  "rerun": false,
  "card": {
    "id": "…",
    "title": "Write launch email",
    "content": "Draft the launch email for the beta",
    "metadata": { "attachments": [{ "name": "brief", "url": "…" }] },
    "comments": [{ "author": "user", "content": "…", "created_at": "…" }],
    "history": [{ "kind": "event", "content": "…", "created_at": "…" }],
    "previous_outputs": [{ "workflow_name": "…", "output": {}, "finished_at": "…" }]
  },
  "board": { "id": "…", "name": "…" },
  "move": { "from_column": "Backlog", "to_column": "Planning" },
  "chain": { "position": 0, "length": 2, "previous_workflow_outputs": [] }
}
```

- `comments` — every comment on the card, oldest first.
- `history` — the full activity timeline (comments, moves, outputs), capped at the
  most recent 200 entries.
- `previous_outputs` — outputs from earlier completed runs (previous columns and
  follow-up rounds).
- `chain.previous_workflow_outputs` — outputs of earlier links in the *current*
  chain.
- On follow-up rounds `move` is `null` and `rerun` is `true`.

## The planning loop (follow-up rounds)

A common pattern is a **Planning** column whose workflow enriches the card and asks
follow-up questions:

1. Move a card into Planning — the workflow writes an enriched plan and its
   questions back to the card as an output.
2. Answer in the card's comment thread.
3. Press **Run follow-up round** on the card. The same chain runs again with all
   accumulated context — the plan improves with every round.

Follow-up rounds work on any column, not just Planning. A card can only have one
active run at a time.

## Human-in-the-loop

If a chain workflow pauses on a [Human-in-the-Loop](/docs/reference/human-in-the-loop)
node, the run is persisted as pending and the card shows the amber pending state.
Resolve the review from the HITL surface; the chain does not continue past a
pending link.

## Related

- [Workflows](/docs/tabs/workflows-tab)
- [Execution History](/docs/reference/execution-history)
- [Expression DSL](/docs/reference/expression-dsl)
- [Human-in-the-Loop](/docs/reference/human-in-the-loop)
