# Agent Memory Graph — "Second Brain" UI Iteration + Searchable Relationship Pickers

Date: 2026-07-07
Status: Approved direction from user (Karpathy/Obsidian "second brain" style, animated force-directed graph; searchable Source/Target dropdowns like node operations).

## Goals

1. **Searchable relationship pickers.** The "New relationship" Source/Target dropdowns in the
   agent memory graph dialog must be searchable comboboxes, matching the pattern already used
   for node operations (`SearchableSelect.vue`).
2. **Second-brain graph view.** Replace the layered top-down tree layout with an animated
   force-directed layout: entity nodes rendered as colored circles (sized by connection count,
   colored by entity type cluster), name captions below, subtle blue palette, minimal visual
   noise, dark-mode friendly. Clicking a node opens the existing detail panel, extended with a
   **Connections** section (backlinks + outgoing links, clickable navigation).

Non-goals: backend changes, new dependencies, changes to memory sharing UI, e2e coverage for
the dialog (none exists today; no frontend unit-test harness per repo policy).

## Approach

Keep Vue Flow as the render engine (zoom/pan, selection, drag, deletion, undo, fullscreen and
compact mode all already work) and add a small custom force simulation — no D3 dependency.
Rejected alternatives: (a) raw canvas/D3 rewrite per the reference prompt — loses all existing
edit/undo/selection infrastructure; (b) `d3-force` package — adds a dependency for ~120 lines
of well-understood physics.

## Components

- `frontend/src/components/Dialogs/agentMemoryGraphView.ts` (new, pure TS):
  degree computation, `nodeRadius(degree)`, stable entity-type → blue-family cluster color,
  deterministic cluster-anchored seed positions (types on a ring, per-id hash jitter).
- `frontend/src/components/Dialogs/AgentMemoryGraphForceSim.vue` (new, renderless, rendered
  inside the Vue Flow context): custom force simulation (link springs, pairwise repulsion,
  centering, mild same-cluster gravity, collision by radius) driven by requestAnimationFrame
  with alpha decay; mutates `node.position` per tick; skips nodes being dragged; exposes
  `reheat()`.
- `AgentMemoryGraphFlowPane.vue`: hosts the sim; exposes `reheat()` and `focusNode(id)`
  (fitView on a single node).
- `AgentMemoryGraphEdge.vue`: path is computed circle-center to circle-center via `findNode`
  (trimmed at each circle rim using the radius carried in node data), keeps per-edge curvature
  separation; thinner, fainter, blue-tinted stroke; smaller translucent label chip; dims when
  another node is hovered (hover state via provide/inject).
- `AgentMemoryGraphDialog.vue`:
  - Source/Target native selects → `SearchableSelect` (clearable, entity-name options).
  - `flowNodes` uses seeded positions and node data `{title, entityType, radius, color, degree,
    propertyRows}`; the old `layoutMemoryGraphDownward` tree layout is removed.
  - Node slot renders a circle + caption; caption hidden in compact (eye) mode; hover shows the
    existing tooltip (name, type, properties) and sets the shared hover state that dims
    non-neighbor nodes and edges.
  - Cluster legend overlay (entity type → color chips) in the graph area.
  - "Tidy layout" wand now reheats the simulation.
  - Detail panel gains **Connections**: outgoing (`name — relationship →`) and incoming
    backlinks; clicking selects and centers that node.

## Error handling / edge cases

- Empty graph: unchanged empty state.
- Nodes without edges: pulled by centering force only; seeded near their type anchor.
- Dragging during simulation: dragged node position is owned by the drag, sim skips it.
- Reduced clutter at scale: caption font stays 10px; tooltip carries the details.

## Testing

Frontend: `bun run lint` + `bun run typecheck` (repo policy: no frontend unit-test harness;
manual visual verification). Backend untouched; `./check.sh` must stay green.

## Docs

Update `frontend/src/docs/content/reference/agent-persistent-memory.md` (graph editor section)
and `canvas-features.md` if it describes the dialog layout.
