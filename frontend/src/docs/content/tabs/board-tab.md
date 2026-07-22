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
  columns **Backlog → Planning → Development → Done**.
- Every board needs an **Agentic Kanban Model** (a credential plus a model). It is
  mandatory — the New board dialog will not create a board without one, and a board
  that has none keeps its actions disabled — because it is the model that maps each
  card into the inputs of the workflows it runs and turns their output back into
  readable text.
- The gear icon in the board header opens the board settings: name, description
  (shown under the header) and the Agentic Kanban Model.
- Columns are fully editable: add, rename, recolor, reorder, or delete them from the
  column settings (a column must be empty before it can be deleted).
- Cards are ordered vertically by priority — drag to reorder.
- You can also create a card from the [Chat tab](/docs/tabs/chat-tab) with a natural-language
  request. Chat asks you to select a board when needed and always adds the card to that
  board's first column.

## Sharing a board

Board settings also share the board with **users** (by email) and with **teams**, with
`read` or `write` permission:

- **read** — the board and its cards are visible, but nothing can be changed: no new
  cards, no moves, no comments, no runs.
- **write** — full use of the board: cards, moves, comments and runs.
- Only the **owner** sees the gear and delete buttons, and only the owner can change the
  board's settings, its Agentic Kanban Model or its shares.

Chains on a shared board always run with the **owner's** credentials and Agentic Kanban
Model, so collaborators never need their own.

## Card attachments

Open a card and use **Attach file** to add files to it — drop them on the box or pick them
with the button, and remove them from the same list. Attachments are stored in
[Drive](/docs/tabs/drive-tab).

Every run **resolves the attachments before the workflows start**, by type:

- **Documents** (pdf, markdown, csv, json, text) are extracted to text, capped at 20,000
  characters per file, in the attachment's `text` field.
- **Images** are handed over as a `url` the vision path loads directly (an LLM node's image
  input accepts it as-is).
- **Anything else** is passed through as a plain reference (`name`, `url`, `mime_type`).

Workflows read them at `$input.card.attachments` (and always at `$input.board.attachments`,
whatever the mapper mapped). The Agentic Kanban Model sees the extracted text and the image
URLs too, so it can map an attachment straight into the field a workflow expects.

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
outputs and errors. Open a card while a workflow is running and choose **Open live** beside
the run to attach the editor to that exact execution. The same canvas animation, incremental
Debug logs, and final result appear without starting a second run.

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

A common pattern is to put a planning workflow on the **second column** (by default
named Planning — the name does not matter; the slot does). That workflow enriches the
card and asks follow-up questions:

1. Move a card into the second column — the workflow writes an enriched plan and its
   questions back to the card as an output.
2. Answer in the card's comment thread. The answer releases the card: it moves on to
   the next column, which picks it up with the answer in context. The second column's
   chain is not run again.
3. To improve the plan in place instead, press **Run follow-up round**. The same
   chain runs again with all accumulated context, then the card waits in that column
   until you add a comment to release it.

The planning gate is positional, not name-based: the leftmost column and the column
immediately to its right never move on by themselves — they run their chain and wait
there for you (a comment releases the second column). From the third column on, a
successful chain advances the card to the right on its own, all the way to the last
column. Renaming or removing the default "Planning" label does not change which slot
is the gate. A card can only have one active run at a time.

## Human-in-the-loop and Codex questions

If a chain workflow pauses — on a [Human-in-the-Loop](/docs/reference/human-in-the-loop)
node, on an agent's HITL tool, or because a [Codex](/docs/nodes/codex-node) node needs
more information — the run is persisted as pending and the card shows the amber pending
state. Each pause keeps its own answer surface: a HITL review link for HITL, the Codex
follow-up screen for Codex.

Once you answer, the chain resumes on its own: the paused workflow finishes, its output
lands on the card, the rest of that column's chain runs, and the card advances as usual.
If the resumed run fails, the card turns red and the remaining links are skipped.

## Related

- [Workflows](/docs/tabs/workflows-tab)
- [Execution History](/docs/reference/execution-history)
- [Expression DSL](/docs/reference/expression-dsl)
- [Human-in-the-Loop](/docs/reference/human-in-the-loop)
