# Agent Memory Graph — Second Brain UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the agent memory graph dialog's "New relationship" Source/Target pickers searchable (matching the existing node-operations pattern), and replace the top-down tree layout with an animated, force-directed "second brain" graph (Karpathy/Obsidian style): colored circles sized by connection count, clustered by entity type, with hover-dim and a connections panel.

**Architecture:** Frontend-only, no backend or dependency changes. Source/Target native `<select>` elements become `SearchableSelect` comboboxes. The tree layout algorithm is replaced by a small pure-TS module (`agentMemoryGraphView.ts`) that computes node degree, radius, cluster color, and deterministic seed positions, plus a renderless force-simulation component (`AgentMemoryGraphForceSim.vue`) that ticks positions via `requestAnimationFrame` inside the existing Vue Flow context (same pattern already used by `AgentMemoryFlowViewportFitter.vue` and `AgentMemoryGraphFlowHotkeys.vue`). A position-preservation step (capture live node positions before every graph reload) is required because Vue Flow's node reconciliation (`parseNode` → `Object.assign(existingNode, incomingNode, ...)`) overwrites `position` on every prop change — without this, positions would snap back to the seed layout on every add/delete/undo.

**Tech Stack:** Vue 3 `<script setup>` + TypeScript strict, `@vue-flow/core` (existing dependency, no `d3-force`), Tailwind utility classes, `SearchableSelect.vue` (existing component, `radix-vue` Combobox under the hood).

---

## File Map

| File | Action | What changes |
|------|--------|--------------|
| `frontend/src/components/Dialogs/AgentMemoryGraphDialog.vue` | Modify | Source/Target → `SearchableSelect`; `flowNodes`/`flowEdges` gain radius/color/degree/dimmed data + position preservation; remove `layoutMemoryGraphDownward` and `flowLayoutEpoch`; unified circle+caption node template; hover-dim wiring; cluster legend overlay; Connections section in detail panel; `tidyMemoryGraphLayout` reheats the sim instead of remounting |
| `frontend/src/components/Dialogs/agentMemoryGraphView.ts` | Create | Pure TS: `computeDegrees`, `nodeRadius`, `clusterColorForType`, `distinctEntityTypes`, `seedPositions` |
| `frontend/src/components/Dialogs/AgentMemoryGraphForceSim.vue` | Create | Renderless force-simulation component rendered inside `<VueFlow>`; exposes `reheat()` and `snapshotPositions()` |
| `frontend/src/components/Dialogs/AgentMemoryGraphFlowPane.vue` | Modify | Hosts the sim; forwards `reheat()`, `snapshotPositions()`, `focusNode(id)`; reheats sim on `node-drag-stop` |
| `frontend/src/components/Dialogs/AgentMemoryFlowViewportFitter.vue` | Modify | Add `focusOnNode(id)` (fitView on a single node), reusing its existing `useVueFlow()` context |
| `frontend/src/components/Dialogs/AgentMemoryGraphEdge.vue` | Modify | Path computed circle-rim to circle-rim (via `findNode` + radius) instead of handle-based bezier; opacity dims via `data.dimmed` |
| `frontend/src/docs/content/reference/agent-persistent-memory.md` | Modify | Update "Graph editor" section wording |
| `frontend/src/docs/content/reference/canvas-features.md` | Modify | Update "Agent memory graph" section wording |

---

### Task 1: Searchable Source/Target relationship pickers

**Files:**
- Modify: `frontend/src/components/Dialogs/AgentMemoryGraphDialog.vue:8-10` (imports), `:1019` (add computed), `:1673-1702` (template)

- [ ] **Step 1: Import `SearchableSelect`**

In `frontend/src/components/Dialogs/AgentMemoryGraphDialog.vue`, add the import next to the other UI component imports (around line 9):

```ts
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
```

- [ ] **Step 2: Add an options computed next to `entityNames`**

Find (around line 1019):

```ts
const entityNames = computed(() => graph.value?.nodes.map((n) => n.entity_name) ?? []);
```

Add immediately after it:

```ts
const entityNameOptions = computed(() =>
  entityNames.value.map((name) => ({ value: name, label: name })),
);
```

- [ ] **Step 3: Replace the native selects with `SearchableSelect`**

Find (around line 1673-1702):

```vue
              <select
                v-model="edgeSource"
                class="w-full h-9 rounded-md border border-input bg-background px-2 text-sm"
              >
                <option value="">
                  Source…
                </option>
                <option
                  v-for="name in entityNames"
                  :key="`s-${name}`"
                  :value="name"
                >
                  {{ name }}
                </option>
              </select>
              <select
                v-model="edgeTarget"
                class="w-full h-9 rounded-md border border-input bg-background px-2 text-sm"
              >
                <option value="">
                  Target…
                </option>
                <option
                  v-for="name in entityNames"
                  :key="`t-${name}`"
                  :value="name"
                >
                  {{ name }}
                </option>
              </select>
```

Replace with:

```vue
              <SearchableSelect
                v-model="edgeSource"
                placeholder="Source…"
                search-placeholder="Search entities…"
                :options="entityNameOptions"
                clearable
                class="h-9"
              />
              <SearchableSelect
                v-model="edgeTarget"
                placeholder="Target…"
                search-placeholder="Search entities…"
                :options="entityNameOptions"
                clearable
                class="h-9"
              />
```

Note: `SearchableSelect`'s `modelValue` type is `string | undefined`; `edgeSource`/`edgeTarget` are `ref("")`. Since `""` is falsy and `addEdge()` already trims and validates non-empty strings, binding `undefined` (from clearing) to a `ref<string>` is compatible at runtime (Vue coerces) but not at the type level — fix by widening the refs:

Find (around line 616-617):

```ts
const edgeSource = ref("");
const edgeTarget = ref("");
```

Replace with:

```ts
const edgeSource = ref<string | undefined>("");
const edgeTarget = ref<string | undefined>("");
```

`addEdge()` already does `edgeSource.value.trim()` — update it to guard `undefined`:

Find (around line 990-991):

```ts
  const s = edgeSource.value.trim();
  const t = edgeTarget.value.trim();
```

Replace with:

```ts
  const s = (edgeSource.value ?? "").trim();
  const t = (edgeTarget.value ?? "").trim();
```

- [ ] **Step 4: Typecheck and lint**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend && bun run typecheck && bun run lint:check
```

Expected: no errors.

- [ ] **Step 5: Manual verification**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend && bun run dev
```

Open the app, open an agent node's memory graph dialog (brain icon), and confirm:
- Source and Target fields are now searchable comboboxes with a search icon, typing filters the entity list, and each is clearable.
- Selecting a source and target and clicking "Add edge" still creates the relationship.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Dialogs/AgentMemoryGraphDialog.vue
git commit -m "$(cat <<'EOF'
feat: make agent memory relationship pickers searchable

Replace the native Source/Target <select> elements in the "New
relationship" form with the SearchableSelect combobox already used
for node operations, so large entity lists are searchable.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `agentMemoryGraphView.ts` pure helper module

**Files:**
- Create: `frontend/src/components/Dialogs/agentMemoryGraphView.ts`

- [ ] **Step 1: Write the module**

```ts
import type { AgentMemoryEdgeDTO, AgentMemoryNodeDTO } from "@/types/agentMemory";

export interface XYPosition {
  x: number;
  y: number;
}

/** Total in+out edge count per node id. */
export function computeDegrees(
  nodes: AgentMemoryNodeDTO[],
  edges: AgentMemoryEdgeDTO[],
): Map<string, number> {
  const degree = new Map<string, number>();
  for (const n of nodes) {
    degree.set(n.id, 0);
  }
  for (const e of edges) {
    if (degree.has(e.source_node_id)) {
      degree.set(e.source_node_id, (degree.get(e.source_node_id) ?? 0) + 1);
    }
    if (degree.has(e.target_node_id)) {
      degree.set(e.target_node_id, (degree.get(e.target_node_id) ?? 0) + 1);
    }
  }
  return degree;
}

const MIN_RADIUS = 16;
const MAX_RADIUS = 34;
const MAX_DEGREE_FOR_SCALE = 8;

/** Circle radius in px, scaled by connection count (capped so hub nodes don't dominate). */
export function nodeRadius(degree: number): number {
  const clamped = Math.max(0, Math.min(degree, MAX_DEGREE_FOR_SCALE));
  const t = clamped / MAX_DEGREE_FOR_SCALE;
  return Math.round(MIN_RADIUS + t * (MAX_RADIUS - MIN_RADIUS));
}

/** Subtle blue-family palette; stable per entity type via hashing (no external deps). */
const CLUSTER_PALETTE = [
  "#60a5fa",
  "#38bdf8",
  "#818cf8",
  "#22d3ee",
  "#a5b4fc",
  "#7dd3fc",
  "#93c5fd",
  "#5eead4",
];

function hashString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i++) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

function normalizedType(entityType: string): string {
  return entityType.trim().toLowerCase() || "unknown";
}

export function clusterColorForType(entityType: string): string {
  const key = normalizedType(entityType);
  return CLUSTER_PALETTE[hashString(key) % CLUSTER_PALETTE.length]!;
}

/** Stable, sorted list of distinct entity types (for cluster anchoring and the legend). */
export function distinctEntityTypes(nodes: AgentMemoryNodeDTO[]): string[] {
  const seen = new Set<string>();
  for (const n of nodes) {
    seen.add(normalizedType(n.entity_type));
  }
  return [...seen].sort((a, b) => a.localeCompare(b));
}

export interface SeedPositionOptions {
  centerX?: number;
  centerY?: number;
  clusterRadius?: number;
}

/**
 * Deterministic cluster-anchored seed layout: each entity type gets a ring anchor around the
 * canvas center, and nodes jitter around their type's anchor by a stable per-id hash. Used only
 * to place brand-new nodes; existing nodes keep their live (dragged/simulated) position — see
 * AgentMemoryGraphDialog.vue's `knownPositions`.
 */
export function seedPositions(
  nodes: AgentMemoryNodeDTO[],
  opts?: SeedPositionOptions,
): Map<string, XYPosition> {
  const centerX = opts?.centerX ?? 480;
  const centerY = opts?.centerY ?? 320;
  const clusterRadius = opts?.clusterRadius ?? 260;

  const types = distinctEntityTypes(nodes);
  const anchors = new Map<string, XYPosition>();
  if (types.length <= 1) {
    anchors.set(types[0] ?? "unknown", { x: centerX, y: centerY });
  } else {
    types.forEach((type, i) => {
      const angle = (2 * Math.PI * i) / types.length;
      anchors.set(type, {
        x: centerX + clusterRadius * Math.cos(angle),
        y: centerY + clusterRadius * Math.sin(angle),
      });
    });
  }

  const pos = new Map<string, XYPosition>();
  for (const n of nodes) {
    const anchor = anchors.get(normalizedType(n.entity_type)) ?? { x: centerX, y: centerY };
    const h = hashString(n.id);
    const jitterAngle = (h % 360) * (Math.PI / 180);
    const jitterRadius = 30 + (h % 70);
    pos.set(n.id, {
      x: anchor.x + jitterRadius * Math.cos(jitterAngle),
      y: anchor.y + jitterRadius * Math.sin(jitterAngle),
    });
  }
  return pos;
}
```

- [ ] **Step 2: Typecheck**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend && bun run typecheck
```

Expected: no errors (module isn't imported anywhere yet, so this only validates its own syntax/types).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Dialogs/agentMemoryGraphView.ts
git commit -m "$(cat <<'EOF'
feat: add pure-TS layout helpers for the memory graph second-brain view

Degree count, radius-by-degree, stable blue-family cluster color by
entity type, and deterministic cluster-anchored seed positions. Not
wired up yet.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Extend `AgentMemoryFlowViewportFitter.vue` with `focusOnNode`

**Files:**
- Modify: `frontend/src/components/Dialogs/AgentMemoryFlowViewportFitter.vue`

- [ ] **Step 1: Add `focusOnNode`**

Find (line 5, the composable destructure):

```ts
const { dimensions, minZoom, maxZoom, getNodesInitialized, setViewport, fitView } = useVueFlow();
```

No change needed here — `fitView` is already destructured. Add a new function after `fitViewAfterLoad` (before `defineExpose`, around line 53):

```ts
async function focusOnNode(id: string): Promise<void> {
  await nextTick();
  try {
    await fitView({ nodes: [id], padding: 0.35, duration: 300 });
  } catch {
    /* Flow not ready */
  }
}
```

Update the `defineExpose` call:

Find:

```ts
defineExpose({ fitViewAfterLoad });
```

Replace with:

```ts
defineExpose({ fitViewAfterLoad, focusOnNode });
```

- [ ] **Step 2: Typecheck**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend && bun run typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

Hold this commit — it will be bundled with Task 4's FlowPane wiring since `focusOnNode` has no caller yet. Move to Task 4.

---

### Task 4: `AgentMemoryGraphForceSim.vue` + `AgentMemoryGraphFlowPane.vue` wiring

**Files:**
- Create: `frontend/src/components/Dialogs/AgentMemoryGraphForceSim.vue`
- Modify: `frontend/src/components/Dialogs/AgentMemoryGraphFlowPane.vue`

- [ ] **Step 1: Write the force simulation component**

```vue
<script setup lang="ts">
import { onUnmounted, watch } from "vue";
import { useVueFlow } from "@vue-flow/core";

interface ForceLink {
  source: string;
  target: string;
}

const props = defineProps<{
  links: ForceLink[];
  active: boolean;
}>();

const { getNodes, findNode, updateNode } = useVueFlow();

const LINK_DISTANCE = 140;
const LINK_STRENGTH = 0.06;
const REPULSION_STRENGTH = 2600;
const CENTER_STRENGTH = 0.02;
const CLUSTER_STRENGTH = 0.015;
const COLLISION_PADDING = 6;
const VELOCITY_DAMPING = 0.82;
const ALPHA_DECAY = 0.985;
const ALPHA_MIN = 0.006;

let alpha = 0;
let rafId: number | null = null;
const velocity = new Map<string, { vx: number; vy: number }>();

function nodeRadiusOf(id: string): number {
  const radius = (findNode(id)?.data as { radius?: number } | undefined)?.radius;
  return typeof radius === "number" ? radius : 20;
}

function nodeTypeOf(id: string): string {
  const entityType = (findNode(id)?.data as { entityType?: string } | undefined)?.entityType;
  return typeof entityType === "string" ? entityType : "unknown";
}

function clusterCentroids(): Map<string, { x: number; y: number; count: number }> {
  const out = new Map<string, { x: number; y: number; count: number }>();
  for (const n of getNodes.value) {
    const type = nodeTypeOf(n.id);
    const c = out.get(type) ?? { x: 0, y: 0, count: 0 };
    c.x += n.position.x;
    c.y += n.position.y;
    c.count += 1;
    out.set(type, c);
  }
  for (const c of out.values()) {
    c.x /= c.count;
    c.y /= c.count;
  }
  return out;
}

function tick(): void {
  const allNodes = getNodes.value;
  const movableNodes = allNodes.filter((n) => !n.dragging);
  if (allNodes.length === 0) {
    rafId = null;
    return;
  }

  for (const n of movableNodes) {
    if (!velocity.has(n.id)) {
      velocity.set(n.id, { vx: 0, vy: 0 });
    }
  }

  let cx = 0;
  let cy = 0;
  for (const n of allNodes) {
    cx += n.position.x;
    cy += n.position.y;
  }
  cx /= allNodes.length;
  cy /= allNodes.length;

  const centroids = clusterCentroids();

  // Pairwise repulsion + circle-collision separation.
  for (const a of movableNodes) {
    const va = velocity.get(a.id)!;
    let fx = 0;
    let fy = 0;
    for (const b of allNodes) {
      if (a.id === b.id) {
        continue;
      }
      const dx = a.position.x - b.position.x;
      const dy = a.position.y - b.position.y;
      const distSq = Math.max(dx * dx + dy * dy, 1);
      const dist = Math.sqrt(distSq);
      const force = REPULSION_STRENGTH / distSq;
      fx += (dx / dist) * force;
      fy += (dy / dist) * force;

      const minDist = nodeRadiusOf(a.id) + nodeRadiusOf(b.id) + COLLISION_PADDING;
      if (dist < minDist) {
        const overlap = (minDist - dist) / 2;
        fx += (dx / dist) * overlap * 0.5;
        fy += (dy / dist) * overlap * 0.5;
      }
    }
    va.vx += fx * alpha;
    va.vy += fy * alpha;
  }

  // Link springs pull connected nodes toward LINK_DISTANCE apart.
  for (const link of props.links) {
    const a = findNode(link.source);
    const b = findNode(link.target);
    if (!a || !b) {
      continue;
    }
    const dx = b.position.x - a.position.x;
    const dy = b.position.y - a.position.y;
    const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
    const displacement = (dist - LINK_DISTANCE) * LINK_STRENGTH;
    const fx = (dx / dist) * displacement;
    const fy = (dy / dist) * displacement;
    const va = velocity.get(a.id);
    const vb = velocity.get(b.id);
    if (va && !a.dragging) {
      va.vx += fx * alpha;
      va.vy += fy * alpha;
    }
    if (vb && !b.dragging) {
      vb.vx -= fx * alpha;
      vb.vy -= fy * alpha;
    }
  }

  // Centering + same-cluster gravity, then integrate + damp.
  for (const n of movableNodes) {
    const v = velocity.get(n.id)!;
    v.vx += (cx - n.position.x) * CENTER_STRENGTH * alpha;
    v.vy += (cy - n.position.y) * CENTER_STRENGTH * alpha;

    const centroid = centroids.get(nodeTypeOf(n.id));
    if (centroid) {
      v.vx += (centroid.x - n.position.x) * CLUSTER_STRENGTH * alpha;
      v.vy += (centroid.y - n.position.y) * CLUSTER_STRENGTH * alpha;
    }

    v.vx *= VELOCITY_DAMPING;
    v.vy *= VELOCITY_DAMPING;

    updateNode(n.id, {
      position: {
        x: n.position.x + v.vx,
        y: n.position.y + v.vy,
      },
    });
  }

  alpha *= ALPHA_DECAY;
  rafId = alpha > ALPHA_MIN ? requestAnimationFrame(tick) : null;
}

function reheat(): void {
  alpha = 1;
  if (rafId === null) {
    rafId = requestAnimationFrame(tick);
  }
}

function stop(): void {
  if (rafId !== null) {
    cancelAnimationFrame(rafId);
    rafId = null;
  }
  alpha = 0;
}

function snapshotPositions(): Map<string, { x: number; y: number }> {
  const out = new Map<string, { x: number; y: number }>();
  for (const n of getNodes.value) {
    out.set(n.id, { x: n.position.x, y: n.position.y });
  }
  return out;
}

watch(
  () => props.active,
  (active) => {
    if (active) {
      reheat();
    } else {
      stop();
    }
  },
  { immediate: true },
);

onUnmounted(() => {
  stop();
});

defineExpose({ reheat, snapshotPositions });
</script>

<template>
  <span
    class="sr-only"
    aria-hidden="true"
  />
</template>
```

- [ ] **Step 2: Host the sim in `AgentMemoryGraphFlowPane.vue` and forward its API + `focusNode`**

Find the imports (lines 1-9):

```vue
<script setup lang="ts">
import { ref } from "vue";
import { Background } from "@vue-flow/background";
import { VueFlow } from "@vue-flow/core";
import type { Edge, Node } from "@vue-flow/core";

import AgentMemoryGraphEdge from "@/components/Dialogs/AgentMemoryGraphEdge.vue";
import AgentMemoryGraphFlowHotkeys from "./AgentMemoryGraphFlowHotkeys.vue";
import AgentMemoryFlowViewportFitter from "./AgentMemoryFlowViewportFitter.vue";
```

Replace with:

```vue
<script setup lang="ts">
import { computed, ref } from "vue";
import { Background } from "@vue-flow/background";
import { VueFlow } from "@vue-flow/core";
import type { Edge, Node } from "@vue-flow/core";

import AgentMemoryGraphEdge from "@/components/Dialogs/AgentMemoryGraphEdge.vue";
import AgentMemoryGraphForceSim from "./AgentMemoryGraphForceSim.vue";
import AgentMemoryGraphFlowHotkeys from "./AgentMemoryGraphFlowHotkeys.vue";
import AgentMemoryFlowViewportFitter from "./AgentMemoryFlowViewportFitter.vue";
```

Find the props/emits/fitterRef block:

```ts
withDefaults(
  defineProps<{
    flowId: string;
    nodes: Node[];
    edges: Edge[];
    hotkeysEnabled?: boolean;
  }>(),
  { hotkeysEnabled: true },
);

const emit = defineEmits<{
  nodeClick: [payload: { node: Node }];
  paneClick: [];
  deleteSelection: [payload: { nodeIds: string[]; edgeIds: string[] }];
}>();

const fitterRef = ref<InstanceType<typeof AgentMemoryFlowViewportFitter> | null>(null);

async function fitViewAfterLoad(opts?: { padding?: number; duration?: number }): Promise<void> {
  await fitterRef.value?.fitViewAfterLoad(opts);
}

defineExpose({ fitViewAfterLoad });
```

Replace with:

```ts
const props = withDefaults(
  defineProps<{
    flowId: string;
    nodes: Node[];
    edges: Edge[];
    hotkeysEnabled?: boolean;
  }>(),
  { hotkeysEnabled: true },
);

const emit = defineEmits<{
  nodeClick: [payload: { node: Node }];
  paneClick: [];
  deleteSelection: [payload: { nodeIds: string[]; edgeIds: string[] }];
}>();

const fitterRef = ref<InstanceType<typeof AgentMemoryFlowViewportFitter> | null>(null);
const simRef = ref<InstanceType<typeof AgentMemoryGraphForceSim> | null>(null);

const simLinks = computed(() => props.edges.map((e) => ({ source: e.source, target: e.target })));

async function fitViewAfterLoad(opts?: { padding?: number; duration?: number }): Promise<void> {
  await fitterRef.value?.fitViewAfterLoad(opts);
}

async function focusNode(id: string): Promise<void> {
  await fitterRef.value?.focusOnNode(id);
}

function reheat(): void {
  simRef.value?.reheat();
}

function snapshotPositions(): Map<string, { x: number; y: number }> {
  return simRef.value?.snapshotPositions() ?? new Map();
}

function handleNodeDragStop(): void {
  simRef.value?.reheat();
}

defineExpose({ fitViewAfterLoad, focusNode, reheat, snapshotPositions });
```

Find the template's `<VueFlow>` opening tag and its children:

```vue
  <VueFlow
    :id="flowId"
    class="agent-memory-vue-flow flex-1 min-h-[200px] lg:min-h-0 w-full h-full bg-background"
    :nodes="nodes"
    :edges="edges"
    :delete-key-code="null"
    :fit-view-on-init="true"
    :min-zoom="0.2"
    :max-zoom="1.5"
    @node-click="emit('nodeClick', $event)"
    @pane-click="emit('paneClick')"
  >
    <AgentMemoryFlowViewportFitter ref="fitterRef" />
    <AgentMemoryGraphFlowHotkeys
      :enabled="hotkeysEnabled"
      @delete-selection="emit('deleteSelection', $event)"
    />
```

Replace with:

```vue
  <VueFlow
    :id="flowId"
    class="agent-memory-vue-flow flex-1 min-h-[200px] lg:min-h-0 w-full h-full bg-background"
    :nodes="nodes"
    :edges="edges"
    :delete-key-code="null"
    :fit-view-on-init="true"
    :min-zoom="0.2"
    :max-zoom="1.5"
    @node-click="emit('nodeClick', $event)"
    @pane-click="emit('paneClick')"
    @node-drag-stop="handleNodeDragStop"
  >
    <AgentMemoryFlowViewportFitter ref="fitterRef" />
    <AgentMemoryGraphForceSim
      ref="simRef"
      :links="simLinks"
      :active="nodes.length > 0"
    />
    <AgentMemoryGraphFlowHotkeys
      :enabled="hotkeysEnabled"
      @delete-selection="emit('deleteSelection', $event)"
    />
```

- [ ] **Step 3: Typecheck**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend && bun run typecheck
```

Expected: no errors. (`AgentMemoryGraphDialog.vue` doesn't call the new `focusNode`/`reheat`/`snapshotPositions` yet — that's Task 8 — but the existing `tidyMemoryGraphLayout`/`flowLayoutEpoch` bump still compiles fine since it's untouched until Task 8.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Dialogs/AgentMemoryGraphForceSim.vue \
        frontend/src/components/Dialogs/AgentMemoryGraphFlowPane.vue \
        frontend/src/components/Dialogs/AgentMemoryFlowViewportFitter.vue
git commit -m "$(cat <<'EOF'
feat: add force-directed simulation engine for the memory graph

Renderless AgentMemoryGraphForceSim runs a link-spring + repulsion +
centering + cluster-gravity + collision simulation via
requestAnimationFrame, ticking node.position through Vue Flow's own
updateNode (skips nodes currently being dragged). FlowPane hosts it
and forwards reheat()/snapshotPositions()/focusNode(id); dragging a
node reheats the sim so neighbors resettle. Not wired to the graph
data yet.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Wire node data (radius/color/degree) + position preservation in the Dialog

**Files:**
- Modify: `frontend/src/components/Dialogs/AgentMemoryGraphDialog.vue`

This is the task that makes the Task 2 helpers and Task 4 sim actually apply to real graph data, and fixes the position-reset problem described in the plan header.

- [ ] **Step 1: Import the helper module**

Add near the other local imports (around line 18-19):

```ts
import {
  clusterColorForType,
  computeDegrees,
  distinctEntityTypes,
  nodeRadius,
  seedPositions,
} from "@/components/Dialogs/agentMemoryGraphView.ts";
```

- [ ] **Step 2: Remove `layoutMemoryGraphDownward`**

Delete the entire function (lines 372-535, from the `/** Longest-path layering...` comment through the closing `}` before `const flowNodes = computed<Node[]>(...)`). It is fully superseded by `seedPositions` + the force sim.

- [ ] **Step 3: Add `knownPositions` state and a capture helper**

Add near the other top-level refs (right after `const selectedNodeId = ref<string | null>(null);`, around line 163):

```ts
/** Last known live position per node id, captured before every reload so the force sim's
 * settled/dragged layout survives graph refreshes (Vue Flow's node reconciliation would
 * otherwise overwrite `position` from `flowNodes` on every prop change). */
const knownPositions = ref<Map<string, { x: number; y: number }>>(new Map());

function captureLivePositions(): void {
  const live = flowPaneRef.value?.snapshotPositions();
  if (live && live.size > 0) {
    knownPositions.value = live;
  }
}
```

- [ ] **Step 4: Call `captureLivePositions()` before every graph reload**

Find (around line 630):

```ts
async function loadGraph(opts?: LoadGraphOptions): Promise<void> {
  if (!props.workflowId || !props.canvasNodeId) {
    return;
  }
  const silent = Boolean(opts?.silent);
```

Replace with:

```ts
async function loadGraph(opts?: LoadGraphOptions): Promise<void> {
  if (!props.workflowId || !props.canvasNodeId) {
    return;
  }
  captureLivePositions();
  const silent = Boolean(opts?.silent);
```

- [ ] **Step 5: Rewrite `flowNodes` and `flowEdges`**

Find (the computed built in Task-context, originally right after `layoutMemoryGraphDownward`):

```ts
const flowNodes = computed<Node[]>(() => {
  const g = graph.value;
  if (!g?.nodes.length) {
    return [];
  }
  const compactOpts = labelsHidden.value
    ? { hDist: 90, vGap: 60, cx: 160 }
    : undefined;
  const positions = layoutMemoryGraphDownward(g.nodes, g.edges, compactOpts);
  return g.nodes.map((node) => ({
    id: node.id,
    type: "default",
    position: positions.get(node.id) ?? { x: 40, y: 40 },
    data: {
      title: `${node.entity_name} (${node.entity_type})`,
      propertyRows: propertyRowsFromRecord(node.properties),
    },
  }));
});

const flowEdges = computed<Edge[]>(() => {
  const g = graph.value;
  if (!g) {
    return [];
  }
  return g.edges.map((e) => ({
    id: e.id,
    type: "agentMemory",
    source: e.source_node_id,
    target: e.target_node_id,
    data: {
      relationshipType: e.relationship_type,
      pathCurvature: edgePathCurvature(e.id),
    },
    animated: true,
  }));
});
```

Replace with:

```ts
const flowNodes = computed<Node[]>(() => {
  const g = graph.value;
  if (!g?.nodes.length) {
    return [];
  }
  const seeds = seedPositions(g.nodes);
  const degrees = computeDegrees(g.nodes, g.edges);
  return g.nodes.map((node) => {
    const degree = degrees.get(node.id) ?? 0;
    return {
      id: node.id,
      type: "default",
      position: knownPositions.value.get(node.id) ??
        seeds.get(node.id) ?? { x: 480, y: 320 },
      data: {
        title: `${node.entity_name} (${node.entity_type})`,
        entityType: node.entity_type,
        propertyRows: propertyRowsFromRecord(node.properties),
        radius: nodeRadius(degree),
        color: clusterColorForType(node.entity_type),
        degree,
      },
    };
  });
});

const flowEdges = computed<Edge[]>(() => {
  const g = graph.value;
  if (!g) {
    return [];
  }
  const hovered = hoveredNodeId.value;
  return g.edges.map((e) => ({
    id: e.id,
    type: "agentMemory",
    source: e.source_node_id,
    target: e.target_node_id,
    data: {
      relationshipType: e.relationship_type,
      pathCurvature: edgePathCurvature(e.id),
      dimmed: hovered !== null && hovered !== e.source_node_id && hovered !== e.target_node_id,
    },
    animated: true,
  }));
});

const clusterLegend = computed(() =>
  distinctEntityTypes(graph.value?.nodes ?? []).map((type) => ({
    type,
    color: clusterColorForType(type),
  })),
);
```

Note: `hoveredNodeId` is introduced in Task 7 — this task will not typecheck standalone until Task 7 adds it. That's expected; Tasks 5-8 are verified together at the end of Task 8 (see Task 8's verification step). If you are executing tasks strictly in order and want an intermediate green typecheck, temporarily add `const hoveredNodeId = ref<string | null>(null);` near `selectedNodeId` now (Task 7 will reuse this same declaration rather than re-adding it).

- [ ] **Step 6: Reheat the sim after each successful reload**

Find (inside `loadGraph`, around line 649-653):

```ts
    const shouldRefit =
      Boolean(opts?.refit) || (silent && (graph.value.nodes.length !== prevCount || prevCount === 0));
    if (shouldRefit && graph.value.nodes.length > 0) {
      await tryFitView();
    }
```

Replace with:

```ts
    const shouldRefit =
      Boolean(opts?.refit) || (silent && (graph.value.nodes.length !== prevCount || prevCount === 0));
    if (shouldRefit && graph.value.nodes.length > 0) {
      await tryFitView();
    }
    flowPaneRef.value?.reheat();
```

- [ ] **Step 7: Commit**

This will not typecheck cleanly until Task 7 adds `hoveredNodeId` (see the note in Step 5) — hold the commit and continue to Task 6, then commit Tasks 5-8 together at the end of Task 8. Do not run `git commit` yet.

---

### Task 6: Unified circle + caption node template, hover-dim, cluster legend

**Files:**
- Modify: `frontend/src/components/Dialogs/AgentMemoryGraphDialog.vue` (template + script)

- [ ] **Step 1: Add hover state and dimming helpers**

Add near `selectedNodeId` (around line 163), alongside `knownPositions`:

```ts
const hoveredNodeId = ref<string | null>(null);

const hoveredNeighborIds = computed<Set<string>>(() => {
  const hovered = hoveredNodeId.value;
  const g = graph.value;
  if (!hovered || !g) {
    return new Set();
  }
  const out = new Set<string>([hovered]);
  for (const e of g.edges) {
    if (e.source_node_id === hovered) {
      out.add(e.target_node_id);
    }
    if (e.target_node_id === hovered) {
      out.add(e.source_node_id);
    }
  }
  return out;
});

function isNodeDimmed(id: string): boolean {
  return hoveredNodeId.value !== null && !hoveredNeighborIds.value.has(id);
}

function flowNodeRadius(data: Record<string, unknown> | undefined): number {
  const r = data?.radius;
  return typeof r === "number" ? r : 20;
}

function flowNodeColor(data: Record<string, unknown> | undefined): string {
  const c = data?.color;
  return typeof c === "string" ? c : "#60a5fa";
}

function onNodeHoverEnter(id: string, data: Record<string, unknown> | undefined, e: MouseEvent): void {
  hoveredNodeId.value = id;
  onNodePinEnter(data, e);
}

function onNodeHoverLeave(): void {
  hoveredNodeId.value = null;
  onNodePinLeave();
}
```

(If you added a placeholder `hoveredNodeId` in Task 5 Step 5, remove that placeholder line now — this step is its real home.)

- [ ] **Step 2: Replace the node-default template**

Find (the two-mode template from the original file, roughly lines 1398-1431):

```vue
            <template #node-default="{ id, data }">
              <!-- Normal label mode -->
              <div
                v-if="!labelsHidden"
                class="agent-memory-node-inner px-2 py-1.5 rounded-md border border-border bg-card text-foreground text-[11px] leading-tight max-w-[220px] min-w-0 cursor-pointer shadow-sm"
                :class="selectedNodeId === id ? 'ring-2 ring-pink-500 ring-offset-2 ring-offset-background' : ''"
              >
                <div class="whitespace-pre-wrap font-medium">
                  {{ flowNodeTitle(data) }}
                </div>
                <ul
                  v-if="flowNodePropertyRows(data).length"
                  class="mt-1.5 pt-1.5 border-t border-border/60 text-[10px] text-muted-foreground space-y-0.5 list-none m-0 p-0"
                >
                  <li
                    v-for="row in flowNodePropertyRows(data)"
                    :key="row.key"
                    class="break-words"
                  >
                    <span class="text-foreground/70">{{ row.key }}</span>: {{ row.value }}
                  </li>
                </ul>
              </div>
              <!-- Compact needle/pin mode -->
              <div
                v-else
                class="agent-memory-node-inner needle-pin-compact cursor-pointer"
                :class="selectedNodeId === id ? 'needle-selected' : ''"
                @mouseenter="onNodePinEnter(data, $event)"
                @mouseleave="onNodePinLeave"
              >
                <div class="needle-pin-head" />
              </div>
            </template>
```

Replace with:

```vue
            <template #node-default="{ id, data }">
              <div
                class="agent-memory-node-inner flex flex-col items-center gap-1 cursor-pointer select-none"
                @mouseenter="onNodeHoverEnter(id, data, $event)"
                @mouseleave="onNodeHoverLeave"
              >
                <div
                  class="agent-memory-node-circle rounded-full shadow-sm"
                  :class="[
                    selectedNodeId === id ? 'ring-2 ring-pink-500 ring-offset-2 ring-offset-background' : '',
                    isNodeDimmed(id) ? 'agent-memory-node-dimmed' : '',
                  ]"
                  :style="{
                    width: `${flowNodeRadius(data) * 2}px`,
                    height: `${flowNodeRadius(data) * 2}px`,
                    background: flowNodeColor(data),
                  }"
                />
                <div
                  v-if="!labelsHidden"
                  class="agent-memory-node-caption max-w-[110px] truncate text-center text-[10px] font-medium text-foreground"
                  :class="isNodeDimmed(id) ? 'agent-memory-node-dimmed' : ''"
                >
                  {{ flowNodeTitle(data) }}
                </div>
              </div>
            </template>
```

- [ ] **Step 3: Add the cluster legend overlay**

Find the fullscreen toggle button (the last `<Button>` inside `.agent-memory-graph-flow`, around lines 1521-1538, ending with `</Button>` right before the closing `</div>` of `graphAreaRef`). Add the legend immediately after that `</Button>` and before the closing `</div>`:

```vue
          <div
            v-if="clusterLegend.length > 1"
            class="absolute top-2 right-2 z-[5] max-w-[55%] rounded-lg border border-border bg-card/90 backdrop-blur-sm p-2 shadow-sm"
          >
            <div class="flex flex-wrap gap-x-3 gap-y-1">
              <div
                v-for="item in clusterLegend"
                :key="item.type"
                class="flex items-center gap-1.5 text-[10px] text-muted-foreground"
              >
                <span
                  class="inline-block h-2 w-2 rounded-full shrink-0"
                  :style="{ background: item.color }"
                />
                <span class="truncate">{{ item.type }}</span>
              </div>
            </div>
          </div>
```

- [ ] **Step 4: Remove the now-unused needle-pin CSS**

In the `<style scoped>` block, delete these rules (they belonged to the old compact-mode-only pin visual, now replaced by the unified circle):

```css
/* Compact dot node */
.needle-pin-compact {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 3px;
}

.needle-pin-head {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: hsl(var(--primary));
  border: 1.5px solid hsl(var(--primary) / 0.55);
  box-shadow: 0 0 7px hsl(var(--primary) / 0.35);
  flex-shrink: 0;
}

.needle-selected .needle-pin-head {
  box-shadow: 0 0 0 2px hsl(var(--background)), 0 0 0 4px hsl(var(--primary));
}

.needles-spinning.compact-mode .needle-pin-compact {
  opacity: 0;
  pointer-events: none;
}
```

Add in their place:

```css
.agent-memory-node-circle {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.agent-memory-node-caption {
  transition: opacity 0.15s ease;
}

.agent-memory-node-dimmed {
  opacity: 0.25;
}

.needles-spinning.compact-mode .agent-memory-node-inner {
  opacity: 0;
  pointer-events: none;
}
```

(The last rule preserves the existing whirl-animation behavior of hiding node visuals while the vortex overlay plays.)

- [ ] **Step 8: Hold verification and commit**

Continue to Task 7 (edge rendering) before typechecking — the edge component still reads `sourceX/sourceY` from `EdgeProps`, which is visually inconsistent with circle nodes until Task 7 is done, though it will still typecheck. Do not commit yet.

---

### Task 7: Circle-rim-to-circle-rim edge paths + dim opacity

**Files:**
- Modify: `frontend/src/components/Dialogs/AgentMemoryGraphEdge.vue`

- [ ] **Step 1: Replace the path computation to use node centers + radius instead of handle coordinates**

Find:

```vue
<script setup lang="ts">
import { computed } from "vue";
import { BaseEdge, EdgeLabelRenderer, getBezierPath } from "@vue-flow/core";
import type { EdgeProps } from "@vue-flow/core";

const props = defineProps<EdgeProps>();

function pathCurvatureFromData(): number {
  const d = props.data;
  if (!d || typeof d !== "object") {
    return 0.25;
  }
  const v = (d as Record<string, unknown>).pathCurvature;
  if (typeof v === "number" && Number.isFinite(v)) {
    return Math.min(0.4, Math.max(0.12, v));
  }
  return 0.25;
}

/** True geometric midpoint along the stroke (parametric t=0.5 from getBezierPath is often off the visual center). */
function labelOnPathMidpoint(edgePath: string, fallbackX: number, fallbackY: number): { x: number; y: number } {
  if (typeof document === "undefined") {
    return { x: fallbackX, y: fallbackY };
  }
  try {
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", edgePath);
    const len = p.getTotalLength();
    if (!Number.isFinite(len) || len <= 0) {
      return { x: fallbackX, y: fallbackY };
    }
    const pt = p.getPointAtLength(len / 2);
    return { x: pt.x, y: pt.y };
  } catch {
    return { x: fallbackX, y: fallbackY };
  }
}

const path = computed(() => {
  const curvature = pathCurvatureFromData();
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetPosition: props.targetPosition,
    curvature,
  });
  const mid = labelOnPathMidpoint(edgePath, labelX, labelY);
  return { edgePath, labelX: mid.x, labelY: mid.y };
});

const dashedPathStyle = computed(() => ({
  ...((props.style as Record<string, string> | undefined) ?? {}),
  strokeDasharray: "6 4",
}));
```

Replace with:

```vue
<script setup lang="ts">
import { computed } from "vue";
import { BaseEdge, EdgeLabelRenderer, useVueFlow } from "@vue-flow/core";
import type { EdgeProps } from "@vue-flow/core";

const props = defineProps<EdgeProps>();

const { findNode } = useVueFlow();

function pathCurvatureFromData(): number {
  const d = props.data;
  if (!d || typeof d !== "object") {
    return 0.25;
  }
  const v = (d as Record<string, unknown>).pathCurvature;
  if (typeof v === "number" && Number.isFinite(v)) {
    return Math.min(0.4, Math.max(0.12, v));
  }
  return 0.25;
}

function radiusOf(id: string): number {
  const r = (findNode(id)?.data as { radius?: number } | undefined)?.radius;
  return typeof r === "number" ? r : 20;
}

/** Straight line trimmed to each circle's rim, with a gentle quadratic-bezier bow for
 * per-edge separation (replaces getBezierPath, which assumes fixed Top/Bottom handle
 * positions that no longer match a radially-arranged force-directed layout). */
function circleToCirclePath(
  sourceCenter: { x: number; y: number },
  sourceRadius: number,
  targetCenter: { x: number; y: number },
  targetRadius: number,
  curvature: number,
): { edgePath: string; labelX: number; labelY: number } {
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;
  const dist = Math.max(Math.hypot(dx, dy), 1);
  const ux = dx / dist;
  const uy = dy / dist;

  const startX = sourceCenter.x + ux * sourceRadius;
  const startY = sourceCenter.y + uy * sourceRadius;
  const endX = targetCenter.x - ux * targetRadius;
  const endY = targetCenter.y - uy * targetRadius;

  const midX = (startX + endX) / 2;
  const midY = (startY + endY) / 2;
  const nx = -uy;
  const ny = ux;
  const offset = curvature * dist;
  const controlX = midX + nx * offset;
  const controlY = midY + ny * offset;

  const edgePath = `M${startX},${startY} Q${controlX},${controlY} ${endX},${endY}`;
  const labelX = 0.25 * startX + 0.5 * controlX + 0.25 * endX;
  const labelY = 0.25 * startY + 0.5 * controlY + 0.25 * endY;
  return { edgePath, labelX, labelY };
}

const path = computed(() => {
  const sourceNode = findNode(props.source);
  const targetNode = findNode(props.target);
  if (!sourceNode || !targetNode) {
    return { edgePath: "", labelX: props.sourceX, labelY: props.sourceY };
  }
  return circleToCirclePath(
    sourceNode.position,
    radiusOf(props.source),
    targetNode.position,
    radiusOf(props.target),
    pathCurvatureFromData(),
  );
});

function isDimmed(): boolean {
  const d = props.data;
  return Boolean(d && typeof d === "object" && (d as { dimmed?: unknown }).dimmed === true);
}

const dashedPathStyle = computed(() => ({
  ...((props.style as Record<string, string> | undefined) ?? {}),
  strokeDasharray: "6 4",
  stroke: "hsl(217 91% 60% / 0.45)",
  strokeWidth: 1.25,
  opacity: isDimmed() ? 0.15 : 1,
  transition: "opacity 0.15s ease",
}));
```

Note: the inline `stroke`/`strokeWidth` here make the edge a fainter, thinner, blue-tinted line (per the spec's "second brain" minimal-noise look) instead of the vue-flow theme's default gray/black edge stroke.

- [ ] **Step 2: Shrink and fade the label chip**

Find (in the `<template>`):

```vue
      <span
        v-if="relationshipLabel"
        class="rounded border border-border bg-card px-2 py-1 text-[10px] font-medium text-foreground shadow-sm"
      >
        {{ relationshipLabel }}
      </span>
```

Replace with:

```vue
      <span
        v-if="relationshipLabel"
        class="rounded border border-border bg-card/70 px-1.5 py-0.5 text-[9px] font-medium text-foreground shadow-sm backdrop-blur-sm transition-opacity duration-150"
        :style="{ opacity: isDimmed() ? 0.15 : 1 }"
      >
        {{ relationshipLabel }}
      </span>
```

- [ ] **Step 3: Typecheck the whole feature so far**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend && bun run typecheck
```

Expected: no errors across `AgentMemoryGraphDialog.vue`, `AgentMemoryGraphEdge.vue`, `AgentMemoryGraphForceSim.vue`, `AgentMemoryGraphFlowPane.vue`, `AgentMemoryFlowViewportFitter.vue`, `agentMemoryGraphView.ts`.

- [ ] **Step 4: Manual verification**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend && bun run dev
```

Open a workflow with an agent node that has memory entities (or add a few via the "New entity" sidebar form), open the memory graph dialog, and confirm:
- Nodes render as colored circles with captions below, roughly clustered by entity type, and gently animate into a settled layout on open (not a static tree).
- Dragging a node causes nearby nodes/edges to gently readjust (spring/repulsion), and dropping it lets it settle.
- Hovering a node dims unrelated nodes and edges; the tooltip still shows name/type/properties.
- Adding a new entity via the sidebar makes it appear and settle near other nodes of the same type, **without existing nodes jumping back to a different layout**.
- Toggling the eye icon hides/shows captions without moving the whole graph to a different scale.
- The cluster legend (top-right) lists each entity type with its color swatch when there's more than one type.
- Edges now run from circle rim to circle rim (not fixed top/bottom attachment points), and relationship labels sit at each edge's midpoint.

- [ ] **Step 5: Commit Tasks 5-7 together**

```bash
git add frontend/src/components/Dialogs/AgentMemoryGraphDialog.vue \
        frontend/src/components/Dialogs/AgentMemoryGraphEdge.vue
git commit -m "$(cat <<'EOF'
feat: render the agent memory graph as an animated second-brain view

Nodes become colored circles (radius by connection count, color by
entity-type cluster) with captions below, driven by the force
simulation instead of the old top-down tree layout. Node positions
are captured before every reload so drag/settle state survives graph
refreshes. Edges route circle-rim to circle-rim. Hovering a node dims
unrelated nodes and edges; a cluster legend lists entity-type colors.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Connections panel + tidy-layout/label-toggle cleanup

**Files:**
- Modify: `frontend/src/components/Dialogs/AgentMemoryGraphDialog.vue`

- [ ] **Step 1: Remove `flowLayoutEpoch` and simplify `tidyMemoryGraphLayout`/`toggleLabels`**

Find:

```ts
/** Bumps to remount Vue Flow so node positions snap back to the auto layout. */
const flowLayoutEpoch = ref(0);
```

Delete this declaration entirely.

Find:

```ts
function tidyMemoryGraphLayout(): void {
  if (!flowNodes.value.length) {
    return;
  }
  flowLayoutEpoch.value += 1;
  void fitGraphViewportAfterLayoutChange();
}
```

Replace with:

```ts
function tidyMemoryGraphLayout(): void {
  flowPaneRef.value?.reheat();
}
```

Find (inside `toggleLabels`):

```ts
function toggleLabels(): void {
  const enteringCompactMode = !labelsHidden.value;
  clearCompactModeAnimationTimer();
  labelsHidden.value = enteringCompactMode;
  tooltipState.value = null;
  flowLayoutEpoch.value += 1;

  if (!enteringCompactMode) {
```

Replace with:

```ts
function toggleLabels(): void {
  const enteringCompactMode = !labelsHidden.value;
  clearCompactModeAnimationTimer();
  labelsHidden.value = enteringCompactMode;
  tooltipState.value = null;

  if (!enteringCompactMode) {
```

- [ ] **Step 2: Remove the `:key="flowLayoutEpoch"` binding**

Find:

```vue
          <AgentMemoryGraphFlowPane
            v-if="flowNodes.length"
            :key="flowLayoutEpoch"
            ref="flowPaneRef"
```

Replace with:

```vue
          <AgentMemoryGraphFlowPane
            v-if="flowNodes.length"
            ref="flowPaneRef"
```

- [ ] **Step 3: Add Connections computeds**

Add near `edgesForSidebarList` (around line 575-581):

```ts
interface ConnectionRow {
  edgeId: string;
  otherNodeId: string;
  otherName: string;
  relationship: string;
}

const outgoingConnections = computed<ConnectionRow[]>(() => {
  const node = selectedNode.value;
  const g = graph.value;
  if (!node || !g) {
    return [];
  }
  return g.edges
    .filter((e) => e.source_node_id === node.id)
    .map((e) => ({
      edgeId: e.id,
      otherNodeId: e.target_node_id,
      otherName: g.nodes.find((n) => n.id === e.target_node_id)?.entity_name ?? "?",
      relationship: e.relationship_type,
    }));
});

const incomingConnections = computed<ConnectionRow[]>(() => {
  const node = selectedNode.value;
  const g = graph.value;
  if (!node || !g) {
    return [];
  }
  return g.edges
    .filter((e) => e.target_node_id === node.id)
    .map((e) => ({
      edgeId: e.id,
      otherNodeId: e.source_node_id,
      otherName: g.nodes.find((n) => n.id === e.source_node_id)?.entity_name ?? "?",
      relationship: e.relationship_type,
    }));
});

async function focusOnConnection(nodeId: string): Promise<void> {
  selectedNodeId.value = nodeId;
  await flowPaneRef.value?.focusNode(nodeId);
}
```

- [ ] **Step 4: Add the Connections section to the detail panel**

Find (the end of the "Attributes" block and the start of the Save/Delete buttons, inside `v-if="selectedNode"`):

```vue
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    class="h-9 w-full text-sm"
                    @click="addEditPropertyRow"
                  >
                    Add attribute
                  </Button>
                </div>
                <div class="flex gap-2 pt-1">
```

Replace with:

```vue
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    class="h-9 w-full text-sm"
                    @click="addEditPropertyRow"
                  >
                    Add attribute
                  </Button>
                </div>
                <div
                  v-if="outgoingConnections.length || incomingConnections.length"
                  class="space-y-2 pt-1"
                >
                  <div class="font-medium text-[10px] uppercase text-muted-foreground tracking-wide">
                    Connections
                  </div>
                  <button
                    v-for="row in outgoingConnections"
                    :key="`out-${row.edgeId}`"
                    type="button"
                    class="flex w-full items-center justify-between gap-2 rounded-md border border-border/60 bg-background/60 px-2 py-1.5 text-left text-xs hover:bg-muted"
                    @click="focusOnConnection(row.otherNodeId)"
                  >
                    <span class="truncate">{{ row.otherName }}</span>
                    <span class="shrink-0 text-muted-foreground">{{ row.relationship }} →</span>
                  </button>
                  <button
                    v-for="row in incomingConnections"
                    :key="`in-${row.edgeId}`"
                    type="button"
                    class="flex w-full items-center justify-between gap-2 rounded-md border border-border/60 bg-background/60 px-2 py-1.5 text-left text-xs hover:bg-muted"
                    @click="focusOnConnection(row.otherNodeId)"
                  >
                    <span class="shrink-0 text-muted-foreground">← {{ row.relationship }}</span>
                    <span class="truncate">{{ row.otherName }}</span>
                  </button>
                </div>
                <div class="flex gap-2 pt-1">
```

- [ ] **Step 5: Typecheck and lint**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend && bun run typecheck && bun run lint:check
```

Expected: no errors. This is the first point where all of Tasks 5-8 must compile together cleanly.

- [ ] **Step 6: Manual verification**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend && bun run dev
```

With the memory graph dialog open and at least two connected entities:
- Click a node to select it; the "Edit node" panel shows a **Connections** section listing outgoing (`name — relationship →`) and incoming (`← relationship — name`) rows.
- Clicking a connection row selects and centers that node in the canvas (zooms/pans to it).
- Click the wand ("Tidy layout") button — the graph should visibly resettle (nodes nudge apart/back into place) without a jarring full reset or losing the current pan/zoom.
- Toggle the eye icon a few times — captions hide/show without any layout jump.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Dialogs/AgentMemoryGraphDialog.vue
git commit -m "$(cat <<'EOF'
feat: add connections panel; tidy layout reheats the sim in place

Selecting a node now shows its outgoing and incoming relationships in
the detail panel, each clickable to select+center that node. "Tidy
layout" and the label-visibility toggle no longer remount Vue Flow
(flowLayoutEpoch removed) — tidy now just reheats the force
simulation so the existing arrangement resettles instead of jumping
back to a fresh seed layout.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Documentation updates

**Files:**
- Modify: `frontend/src/docs/content/reference/agent-persistent-memory.md:16-18`
- Modify: `frontend/src/docs/content/reference/canvas-features.md:75`

- [ ] **Step 1: Update the "Graph editor" section**

Find (in `agent-persistent-memory.md`):

```markdown
## Graph editor

The dialog provides a visual graph of entities and edges, plus editing and navigation (fit view, keyboard shortcuts). You can **add, edit, or delete** nodes and edges manually; changes apply to **this** agent’s graph only (the graph for the canvas node whose brain you opened).
```

Replace with:

```markdown
## Graph editor

The dialog renders entities as an animated, force-directed graph — colored circles sized by connection count and clustered by entity type — plus editing and navigation (fit view, tidy layout, keyboard shortcuts). You can **add, edit, or delete** nodes and edges manually; the Source/Target relationship pickers are searchable for graphs with many entities. Selecting a node shows its outgoing and incoming connections, each clickable to jump to that node. Changes apply to **this** agent’s graph only (the graph for the canvas node whose brain you opened).
```

- [ ] **Step 2: Update the "Agent memory graph" section**

Find (in `canvas-features.md`):

```markdown
## Agent memory graph

[Agent](../nodes/agent-node.md) nodes with **[persistent memory](./agent-persistent-memory.md)** enabled show a pink **brain** control on the node. Click it to open the memory graph editor: view entities and relationships, add or edit nodes and edges, and use graph-specific shortcuts. The same dialog includes **Share memory with other agents** (workflow → agent → read or read/write) for [cross-agent memory sharing](./agent-persistent-memory.md#sharing-with-other-agents). While the dialog is open, main canvas undo/redo is deferred so graph editing keeps its own history.
```

Replace with:

```markdown
## Agent memory graph

[Agent](../nodes/agent-node.md) nodes with **[persistent memory](./agent-persistent-memory.md)** enabled show a pink **brain** control on the node. Click it to open the memory graph editor: entities render as an animated, force-directed graph clustered by entity type, with searchable Source/Target pickers for adding relationships and a connections panel for jumping between linked entities. The same dialog includes **Share memory with other agents** (workflow → agent → read or read/write) for [cross-agent memory sharing](./agent-persistent-memory.md#sharing-with-other-agents). While the dialog is open, main canvas undo/redo is deferred so graph editing keeps its own history.
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/docs/content/reference/agent-persistent-memory.md \
        frontend/src/docs/content/reference/canvas-features.md
git commit -m "$(cat <<'EOF'
docs: describe the second-brain memory graph view

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Full repo verification

**Files:** (no changes — verification only)

- [ ] **Step 1: Run the full frontend check**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend && bun run lint && bun run typecheck
```

Expected: no errors.

- [ ] **Step 2: Run the full repo check script**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && ./check.sh
```

Expected: frontend lint/typecheck pass, backend Ruff checks and tests pass unchanged (no backend files touched by this plan).

- [ ] **Step 3: Final manual pass**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend && bun run dev
```

Walk the full flow once more end to end:
1. Open the memory graph dialog for an agent with several entities and relationships (create some via "New entity"/"New relationship" if needed, using the searchable pickers).
2. Confirm the graph settles into a clustered, animated layout; drag a node and confirm neighbors readjust and settle.
3. Hover nodes/edges to confirm dimming; click a node and use its Connections panel to jump around the graph.
4. Delete a node/edge and undo it (Ctrl+Z) — confirm the graph reloads correctly and other nodes' positions are not disturbed.
5. Toggle fullscreen and the eye (compact) icon — confirm no layout regressions.
6. Confirm no console errors throughout.

- [ ] **Step 4: Report status**

No commit needed for this task (verification only). If any step surfaced an issue, fix it in the relevant task's file and re-run `bun run typecheck` before proceeding.
