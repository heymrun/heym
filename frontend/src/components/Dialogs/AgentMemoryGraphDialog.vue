<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import type { Edge, Node } from "@vue-flow/core";
import { Eye, EyeOff, Maximize2, Minimize2, RefreshCw, Trash2, Wand2 } from "lucide-vue-next";

import AgentMemoryGraphFlowPane from "@/components/Dialogs/AgentMemoryGraphFlowPane.vue";
import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import { useToast } from "@/composables/useToast";
import { workflowApi } from "@/services/api";
import { useWorkflowStore } from "@/stores/workflow";
import type {
  AgentMemoryEdgeDTO,
  AgentMemoryGraphResponse,
  AgentMemoryNodeDTO,
} from "@/types/agentMemory";
import type { AgentMemoryShareEntry, WorkflowListItem } from "@/types/workflow";

const AGENT_MEMORY_FLOW_ID = "agent-memory-flow";

interface UndoOpNodeCreated {
  kind: "node_created";
  workflowId: string;
  memoryNodeId: string;
}

interface UndoOpNodeDeleted {
  kind: "node_deleted";
  workflowId: string;
  canvasNodeId: string;
  node: AgentMemoryNodeDTO;
  incidentEdges: Array<{
    source_entity_name: string;
    target_entity_name: string;
    relationship_type: string;
    properties: Record<string, unknown>;
    confidence: number;
  }>;
}

interface UndoOpEdgeCreated {
  kind: "edge_created";
  workflowId: string;
  memoryEdgeId: string;
}

interface UndoOpEdgeDeleted {
  kind: "edge_deleted";
  workflowId: string;
  canvasNodeId: string;
  source_entity_name: string;
  target_entity_name: string;
  relationship_type: string;
  properties: Record<string, unknown>;
  confidence: number;
}

interface UndoOpNodeUpdated {
  kind: "node_updated";
  workflowId: string;
  memoryNodeId: string;
  prevEntityName: string;
  prevEntityType: string;
  prevProperties: Record<string, unknown>;
}

type AgentMemoryUndoOp =
  | UndoOpNodeCreated
  | UndoOpNodeDeleted
  | UndoOpEdgeCreated
  | UndoOpEdgeDeleted
  | UndoOpNodeUpdated;

const UNDO_STACK_CAP = 40;

function isTypingInField(target: EventTarget | null): boolean {
  if (!target || !(target instanceof HTMLElement)) {
    return false;
  }
  const inFormControl = target.closest(
    "input, textarea, select, [contenteditable='true'], [contenteditable='']",
  );
  return inFormControl !== null;
}

function incidentEdgesForNode(
  g: AgentMemoryGraphResponse,
  memoryNodeId: string,
): UndoOpNodeDeleted["incidentEdges"] {
  const byId = new Map(g.nodes.map((n) => [n.id, n] as const));
  return g.edges
    .filter((e) => e.source_node_id === memoryNodeId || e.target_node_id === memoryNodeId)
    .map((e) => {
      const s = byId.get(e.source_node_id);
      const t = byId.get(e.target_node_id);
      if (!s || !t) {
        return null;
      }
      return {
        source_entity_name: s.entity_name,
        target_entity_name: t.entity_name,
        relationship_type: e.relationship_type,
        properties: { ...e.properties },
        confidence: e.confidence,
      };
    })
    .filter((x): x is NonNullable<typeof x> => x !== null);
}

import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";

interface Props {
  open: boolean;
  workflowId: string | undefined;
  canvasNodeId: string | undefined;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "close"): void;
}>();

const { showToast } = useToast();
const workflowStore = useWorkflowStore();

const flowPaneRef = ref<InstanceType<typeof AgentMemoryGraphFlowPane> | null>(null);
const dialogContentRef = ref<HTMLElement | null>(null);
/** Vue Flow canvas subtree (layout ref only; undo uses document capture scoped to dialog body). */
const graphAreaRef = ref<HTMLElement | null>(null);
const graphCanvasFullscreen = ref(false);
/** Bumps to remount Vue Flow so node positions snap back to the auto layout. */
const flowLayoutEpoch = ref(0);

function syncGraphCanvasFullscreen(): void {
  const el = graphAreaRef.value;
  graphCanvasFullscreen.value = Boolean(
    el && document.fullscreenElement && document.fullscreenElement === el,
  );
}

async function toggleGraphCanvasFullscreen(): Promise<void> {
  const el = graphAreaRef.value;
  if (!el) {
    return;
  }
  try {
    if (document.fullscreenElement === el) {
      await document.exitFullscreen();
    } else {
      await el.requestFullscreen();
    }
  } catch {
    showToast("Fullscreen is not available in this browser", "error");
  }
}

const loading = ref(false);
const graph = ref<AgentMemoryGraphResponse | null>(null);
const selectedNodeId = ref<string | null>(null);
const undoStack = ref<AgentMemoryUndoOp[]>([]);
const labelsHidden = ref(false);
const needleAnimating = ref(false);
const tooltipState = ref<{ text: string; x: number; y: number } | null>(null);
const COMPACT_MODE_ANIMATION_MS = 1000;
let compactModeAnimationTimer: ReturnType<typeof setTimeout> | null = null;

function clearCompactModeAnimationTimer(): void {
  if (compactModeAnimationTimer === null) {
    return;
  }
  clearTimeout(compactModeAnimationTimer);
  compactModeAnimationTimer = null;
}

function pushUndo(op: AgentMemoryUndoOp): void {
  const next = [...undoStack.value, op];
  undoStack.value =
    next.length > UNDO_STACK_CAP ? next.slice(next.length - UNDO_STACK_CAP) : next;
}

async function tryFitView(): Promise<void> {
  await nextTick();
  await flowPaneRef.value?.fitViewAfterLoad();
}

async function fitGraphViewportAfterLayoutChange(): Promise<void> {
  await nextTick();
  await nextTick();
  await new Promise<void>((resolve) => {
    requestAnimationFrame(() => resolve());
  });
  await flowPaneRef.value?.fitViewAfterLoad({ padding: 0.2, duration: 250 });
}

function tidyMemoryGraphLayout(): void {
  if (!flowNodes.value.length) {
    return;
  }
  flowLayoutEpoch.value += 1;
  void fitGraphViewportAfterLayoutChange();
}

function toggleLabels(): void {
  const enteringCompactMode = !labelsHidden.value;
  clearCompactModeAnimationTimer();
  labelsHidden.value = enteringCompactMode;
  tooltipState.value = null;
  flowLayoutEpoch.value += 1;

  if (!enteringCompactMode) {
    needleAnimating.value = false;
    void fitGraphViewportAfterLayoutChange();
    return;
  }

  needleAnimating.value = true;
  compactModeAnimationTimer = setTimeout(() => {
    needleAnimating.value = false;
    compactModeAnimationTimer = null;
    void fitGraphViewportAfterLayoutChange();
  }, COMPACT_MODE_ANIMATION_MS);
}

function nodeTooltipText(data: Record<string, unknown> | undefined): string {
  const title = flowNodeTitle(data);
  const rows = flowNodePropertyRows(data);
  if (!rows.length) return title;
  return [title, ...rows.map((r) => `${r.key}: ${r.value}`)].join("\n");
}

function onNodePinEnter(data: Record<string, unknown> | undefined, e: MouseEvent): void {
  const text = nodeTooltipText(data);
  if (!text) return;
  tooltipState.value = { text, x: e.clientX + 14, y: e.clientY - 8 };
}

function onNodePinLeave(): void {
  tooltipState.value = null;
}

function propertyRowsFromRecord(
  properties: Record<string, unknown> | undefined,
): Array<{ key: string; value: string }> {
  if (!properties || typeof properties !== "object") {
    return [];
  }
  return Object.entries(properties)
    .filter(([k]) => k.length > 0)
    .map(([key, val]) => ({
      key,
      value:
        val === null || val === undefined
          ? ""
          : typeof val === "object"
            ? JSON.stringify(val)
            : String(val),
    }));
}

function cloneJsonRecord(r: Record<string, unknown>): Record<string, unknown> {
  try {
    return structuredClone(r) as Record<string, unknown>;
  } catch {
    return { ...r };
  }
}

function coalesceEditRowsToProperties(
  rows: Array<{ key: string; value: string }>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const row of rows) {
    const k = row.key.trim();
    if (!k) {
      continue;
    }
    const v = row.value.trim();
    if (v === "") {
      out[k] = "";
      continue;
    }
    if (v === "true") {
      out[k] = true;
      continue;
    }
    if (v === "false") {
      out[k] = false;
      continue;
    }
    const num = Number(v);
    if (!Number.isNaN(num) && String(num) === v) {
      out[k] = num;
      continue;
    }
    try {
      out[k] = JSON.parse(v) as unknown;
      continue;
    } catch {
      out[k] = v;
    }
  }
  return out;
}

function edgePrimaryStatus(edge: AgentMemoryEdgeDTO): string | null {
  const raw = edge.properties?.status;
  return typeof raw === "string" && raw.trim().length > 0 ? raw.trim() : null;
}

function formatMemoryStatusLabel(status: string): string {
  return status.replace(/_/g, " ");
}

function memoryStatusBadgeClass(slug: string): string {
  const s = slug.toLowerCase().replace(/\s+/g, "_");
  const base =
    "inline-flex max-w-full rounded border px-1.5 py-0.5 text-[10px] font-medium leading-snug break-words";
  if (s.includes("proposed") || s.includes("pending") || s.includes("draft")) {
    return `${base} border-amber-500/45 bg-amber-500/12 text-amber-900 dark:text-amber-100`;
  }
  if (s.includes("reject") || s.includes("invalid") || s.includes("revoked")) {
    return `${base} border-destructive/45 bg-destructive/12 text-destructive`;
  }
  if (
    s.includes("confirm") ||
    s.includes("active") ||
    s.includes("accept") ||
    s.includes("verified")
  ) {
    return `${base} border-emerald-500/45 bg-emerald-500/12 text-emerald-900 dark:text-emerald-100`;
  }
  return `${base} border-border bg-muted/80 text-muted-foreground`;
}

function flowNodeTitle(data: Record<string, unknown> | undefined): string {
  const t = data?.title;
  return typeof t === "string" ? t : "";
}

function flowNodePropertyRows(
  data: Record<string, unknown> | undefined,
): Array<{ key: string; value: string }> {
  const rows = data?.propertyRows;
  if (!Array.isArray(rows)) {
    return [];
  }
  return rows.filter(
    (item): item is { key: string; value: string } =>
      typeof item === "object" &&
      item !== null &&
      "key" in item &&
      "value" in item &&
      typeof (item as { key: unknown }).key === "string" &&
      typeof (item as { value: unknown }).value === "string",
  );
}

/** Stable slight Bezier curvature per edge so similar routes do not stack (labels stay on-path). */
function edgePathCurvature(edgeId: string): number {
  let h = 0;
  for (let i = 0; i < edgeId.length; i++) {
    h = (h * 31 + edgeId.charCodeAt(i)) | 0;
  }
  const steps = [0.2, 0.22, 0.24, 0.26, 0.28, 0.3];
  return steps[Math.abs(h) % steps.length] ?? 0.25;
}

/** Longest-path layering from roots (incoming degree 0), tree-like top → down. */
function layoutMemoryGraphDownward(
  nodes: AgentMemoryNodeDTO[],
  edges: AgentMemoryEdgeDTO[],
  opts?: { hDist?: number; vGap?: number; cx?: number },
): Map<string, { x: number; y: number }> {
  const idSet = new Set(nodes.map((n) => n.id));
  const inCount = new Map<string, number>();

  for (const n of nodes) {
    inCount.set(n.id, 0);
  }
  for (const e of edges) {
    if (!idSet.has(e.source_node_id) || !idSet.has(e.target_node_id)) {
      continue;
    }
    inCount.set(e.target_node_id, (inCount.get(e.target_node_id) ?? 0) + 1);
  }

  const rootIds = nodes.filter((n) => (inCount.get(n.id) ?? 0) === 0).map((n) => n.id);
  const seeds =
    rootIds.length > 0
      ? rootIds
      : [nodes.find((n) => n.entity_type.trim().toLowerCase() === "person")?.id ?? nodes[0]!.id];

  const depth = new Map<string, number>();
  for (const n of nodes) {
    depth.set(n.id, seeds.includes(n.id) ? 0 : -1);
  }

  const validEdges = edges.filter(
    (e) => idSet.has(e.source_node_id) && idSet.has(e.target_node_id),
  );
  const relaxIters = Math.max(nodes.length, 1);
  for (let i = 0; i < relaxIters; i++) {
    for (const e of validEdges) {
      const du = depth.get(e.source_node_id) ?? -1;
      if (du < 0) {
        continue;
      }
      const dv = depth.get(e.target_node_id) ?? -1;
      const next = du + 1;
      if (next > dv) {
        depth.set(e.target_node_id, next);
      }
    }
  }

  let maxD = 0;
  for (const n of nodes) {
    const d = depth.get(n.id) ?? -1;
    if (d > maxD) {
      maxD = d;
    }
  }
  const orphanLayer = maxD + 1;
  for (const n of nodes) {
    if ((depth.get(n.id) ?? -1) < 0) {
      depth.set(n.id, orphanLayer);
    }
  }

  const byLayer = new Map<number, string[]>();
  for (const n of nodes) {
    const d = depth.get(n.id) ?? 0;
    if (!byLayer.has(d)) {
      byLayer.set(d, []);
    }
    byLayer.get(d)!.push(n.id);
  }
  for (const ids of byLayer.values()) {
    ids.sort((a, b) => a.localeCompare(b));
  }

  // max-w ~220px nodes: center distance must exceed box width + margin
  const hCenterDist = opts?.hDist ?? 280;
  const vGap = opts?.vGap ?? 205;
  const topPad = 28;
  const centerX = opts?.cx ?? 440;
  const pos = new Map<string, { x: number; y: number }>();

  const sortedLayers = [...byLayer.keys()].sort((a, b) => a - b);

  for (const layer of sortedLayers) {
    const ids = [...byLayer.get(layer)!];
    const y = topPad + layer * vGap;

    if (layer === 0) {
      const count = ids.length;
      for (let i = 0; i < count; i++) {
        const x = centerX + (i - (count - 1) / 2) * hCenterDist;
        pos.set(ids[i]!, { x, y });
      }
      continue;
    }

    const idealX = new Map<string, number>();
    for (const id of ids) {
      const xsImmediate: number[] = [];
      const xsAnyLower: number[] = [];
      for (const e of validEdges) {
        if (e.target_node_id !== id) {
          continue;
        }
        const ps = depth.get(e.source_node_id) ?? -1;
        const pp = pos.get(e.source_node_id);
        if (pp === undefined || ps < 0 || ps >= layer) {
          continue;
        }
        if (ps === layer - 1) {
          xsImmediate.push(pp.x);
        }
        xsAnyLower.push(pp.x);
      }
      let ix: number;
      if (xsImmediate.length > 0) {
        ix = xsImmediate.reduce((s, x) => s + x, 0) / xsImmediate.length;
      } else if (xsAnyLower.length > 0) {
        ix = xsAnyLower.reduce((s, x) => s + x, 0) / xsAnyLower.length;
      } else {
        ix = centerX;
      }
      idealX.set(id, ix);
    }

    const order = ids.sort((a, b) => {
      const da = idealX.get(a) ?? 0;
      const db = idealX.get(b) ?? 0;
      if (da !== db) {
        return da - db;
      }
      return a.localeCompare(b);
    });

    const ideals = order.map((id) => idealX.get(id)!);
    const packed: number[] = [];
    if (order.length === 1) {
      packed.push(ideals[0]!);
    } else {
      const allSame = ideals.every((v) => Math.abs(v - ideals[0]!) < 0.01);
      if (allSame) {
        const ref = ideals[0]!;
        for (let i = 0; i < order.length; i++) {
          packed.push(ref + (i - (order.length - 1) / 2) * hCenterDist);
        }
      } else {
        packed.push(ideals[0]!);
        for (let i = 1; i < order.length; i++) {
          packed.push(Math.max(ideals[i]!, packed[i - 1]! + hCenterDist));
        }
      }
    }

    const mid = (Math.min(...packed) + Math.max(...packed)) / 2;
    // Single-node rows: do not recenter on centerX — shift would erase barycentric x and
    // stack the node under the root column (edges cut through siblings on the row above).
    const shift = order.length === 1 ? 0 : centerX - mid;
    for (let i = 0; i < order.length; i++) {
      pos.set(order[i]!, { x: packed[i]! + shift, y });
    }
  }

  return pos;
}

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

const edgesForSidebarList = computed(() => {
  const g = graph.value;
  if (!g?.edges.length) {
    return [];
  }
  return g.edges.map((edge) => ({ edge, status: edgePrimaryStatus(edge) }));
});

const selectedNode = computed<AgentMemoryNodeDTO | null>(() => {
  if (!selectedNodeId.value || !graph.value) {
    return null;
  }
  return graph.value.nodes.find((n) => n.id === selectedNodeId.value) ?? null;
});

const editName = ref("");
const editType = ref("");
const editPropertyRows = ref<Array<{ key: string; value: string }>>([]);

watch(selectedNode, (n) => {
  if (n) {
    editName.value = n.entity_name;
    editType.value = n.entity_type;
    editPropertyRows.value = propertyRowsFromRecord(n.properties).map((r) => ({ ...r }));
  } else {
    editName.value = "";
    editType.value = "";
    editPropertyRows.value = [];
  }
});

function addEditPropertyRow(): void {
  editPropertyRows.value = [...editPropertyRows.value, { key: "", value: "" }];
}

function removeEditPropertyRow(index: number): void {
  editPropertyRows.value = editPropertyRows.value.filter((_, i) => i !== index);
}

const newName = ref("");
const newType = ref("topic");
const edgeSource = ref("");
const edgeTarget = ref("");
const edgeRel = ref("related");

interface LoadGraphOptions {
  silent?: boolean;
  preserveSelection?: boolean;
  refit?: boolean;
}

async function refreshGraph(): Promise<void> {
  await loadGraph({ refit: true, preserveSelection: true });
}

async function loadGraph(opts?: LoadGraphOptions): Promise<void> {
  if (!props.workflowId || !props.canvasNodeId) {
    return;
  }
  const silent = Boolean(opts?.silent);
  if (!silent) {
    loading.value = true;
    undoStack.value = [];
  }
  const prevCount = graph.value?.nodes.length ?? 0;
  try {
    const data = await workflowApi.getAgentMemoryGraph(props.workflowId, props.canvasNodeId);
    graph.value = {
      nodes: data.nodes.map((n) => ({ ...n })),
      edges: data.edges.map((e) => ({ ...e })),
    };
    if (!silent && !opts?.preserveSelection) {
      selectedNodeId.value = null;
    }
    const shouldRefit =
      Boolean(opts?.refit) || (silent && (graph.value.nodes.length !== prevCount || prevCount === 0));
    if (shouldRefit && graph.value.nodes.length > 0) {
      await tryFitView();
    }
  } catch {
    showToast("Failed to load memory graph", "error");
    if (!silent) {
      graph.value = { nodes: [], edges: [] };
    }
  } finally {
    if (!silent) {
      loading.value = false;
    }
  }
}

watch(
  () => [props.open, props.workflowId, props.canvasNodeId] as const,
  ([open]) => {
    if (open && props.workflowId && props.canvasNodeId) {
      void loadGraph({ refit: true });
    }
  },
);

async function performUndo(): Promise<void> {
  if (!props.workflowId || !props.canvasNodeId) {
    return;
  }
  const op = undoStack.value[undoStack.value.length - 1];
  if (!op) {
    return;
  }
  try {
    switch (op.kind) {
      case "node_created":
        await workflowApi.deleteAgentMemoryNode(op.workflowId, op.memoryNodeId);
        break;
      case "node_deleted": {
        await workflowApi.createAgentMemoryNode(op.workflowId, op.canvasNodeId, {
          entity_name: op.node.entity_name,
          entity_type: op.node.entity_type,
          properties: { ...op.node.properties },
          confidence: op.node.confidence,
        });
        for (const e of op.incidentEdges) {
          await workflowApi.createAgentMemoryEdge(op.workflowId, op.canvasNodeId, {
            source_entity_name: e.source_entity_name,
            target_entity_name: e.target_entity_name,
            relationship_type: e.relationship_type,
            properties: { ...e.properties },
            confidence: e.confidence,
          });
        }
        break;
      }
      case "edge_created":
        await workflowApi.deleteAgentMemoryEdge(op.workflowId, op.memoryEdgeId);
        break;
      case "edge_deleted":
        await workflowApi.createAgentMemoryEdge(op.workflowId, op.canvasNodeId, {
          source_entity_name: op.source_entity_name,
          target_entity_name: op.target_entity_name,
          relationship_type: op.relationship_type,
          properties: { ...op.properties },
          confidence: op.confidence,
        });
        break;
      case "node_updated":
        await workflowApi.updateAgentMemoryNode(op.workflowId, op.memoryNodeId, {
          entity_name: op.prevEntityName,
          entity_type: op.prevEntityType,
          properties: cloneJsonRecord(op.prevProperties),
        });
        break;
    }
    undoStack.value = undoStack.value.slice(0, -1);
    await loadGraph({ silent: true, refit: true });
    showToast("Undone", "success");
  } catch {
    showToast("Undo failed", "error");
  }
}

function applyUndoShortcut(ev: KeyboardEvent): boolean {
  if (!props.open) {
    return false;
  }
  if (!(ev.ctrlKey || ev.metaKey) || ev.key.toLowerCase() !== "z" || ev.shiftKey) {
    return false;
  }
  if (isTypingInField(ev.target)) {
    return false;
  }
  if (undoStack.value.length === 0) {
    return false;
  }
  ev.preventDefault();
  ev.stopPropagation();
  void performUndo();
  return true;
}

function onDocumentUndoCapture(ev: KeyboardEvent): void {
  const t = ev.target;
  if (!(t instanceof Node) || !dialogContentRef.value?.contains(t)) {
    return;
  }
  applyUndoShortcut(ev);
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      document.addEventListener("keydown", onDocumentUndoCapture, true);
      document.addEventListener("fullscreenchange", syncGraphCanvasFullscreen);
      await nextTick();
      dialogContentRef.value?.focus({ preventScroll: true });
      requestAnimationFrame(() => {
        dialogContentRef.value?.focus({ preventScroll: true });
      });
    } else {
      clearCompactModeAnimationTimer();
      document.removeEventListener("keydown", onDocumentUndoCapture, true);
      document.removeEventListener("fullscreenchange", syncGraphCanvasFullscreen);
      const gEl = graphAreaRef.value;
      if (gEl && document.fullscreenElement === gEl) {
        try {
          await document.exitFullscreen();
        } catch {
          /* ignore */
        }
      }
      graphCanvasFullscreen.value = false;
      needleAnimating.value = false;
      tooltipState.value = null;
      undoStack.value = [];
    }
  },
  { immediate: true },
);

onUnmounted(() => {
  clearCompactModeAnimationTimer();
  document.removeEventListener("keydown", onDocumentUndoCapture, true);
  document.removeEventListener("fullscreenchange", syncGraphCanvasFullscreen);
});

watch(graphCanvasFullscreen, (fs, wasFs) => {
  if (fs) {
    void fitGraphViewportAfterLayoutChange();
    return;
  }
  if (wasFs) {
    void fitGraphViewportAfterLayoutChange();
  }
});

function onNodeClick(ev: { node: Node }): void {
  selectedNodeId.value = ev.node.id;
}

function onPaneClick(): void {
  selectedNodeId.value = null;
}

async function saveNodeEdit(): Promise<void> {
  if (!props.workflowId || !selectedNode.value) {
    return;
  }
  const name = editName.value.trim();
  const typ = editType.value.trim();
  if (!name || !typ) {
    showToast("Name and type are required", "error");
    return;
  }
  const prev = selectedNode.value;
  const nextProperties = coalesceEditRowsToProperties(editPropertyRows.value);
  try {
    await workflowApi.updateAgentMemoryNode(props.workflowId, prev.id, {
      entity_name: name,
      entity_type: typ,
      properties: nextProperties,
    });
    pushUndo({
      kind: "node_updated",
      workflowId: props.workflowId,
      memoryNodeId: prev.id,
      prevEntityName: prev.entity_name,
      prevEntityType: prev.entity_type,
      prevProperties: cloneJsonRecord(prev.properties),
    });
    showToast("Node updated", "success");
    await loadGraph({ silent: true });
  } catch {
    showToast("Update failed", "error");
  }
}

async function deleteMemoryEdgeById(
  edgeId: string,
  options?: { toast?: boolean },
): Promise<boolean> {
  const showEdgeToast = options?.toast ?? true;
  if (!props.workflowId || !props.canvasNodeId || !graph.value) {
    return false;
  }
  const edge = graph.value.edges.find((e) => e.id === edgeId);
  if (!edge) {
    return false;
  }
  const byId = new Map(graph.value.nodes.map((n) => [n.id, n] as const));
  const src = byId.get(edge.source_node_id);
  const tgt = byId.get(edge.target_node_id);
  if (!src || !tgt) {
    return false;
  }
  try {
    pushUndo({
      kind: "edge_deleted",
      workflowId: props.workflowId,
      canvasNodeId: props.canvasNodeId,
      source_entity_name: src.entity_name,
      target_entity_name: tgt.entity_name,
      relationship_type: edge.relationship_type,
      properties: { ...edge.properties },
      confidence: edge.confidence,
    });
    await workflowApi.deleteAgentMemoryEdge(props.workflowId, edgeId);
    if (showEdgeToast) {
      showToast("Edge removed", "success");
    }
    await loadGraph({ silent: true, refit: true });
    return true;
  } catch {
    undoStack.value = undoStack.value.slice(0, -1);
    if (showEdgeToast) {
      showToast("Delete failed", "error");
    }
    return false;
  }
}

async function deleteMemoryNodeById(
  memoryNodeId: string,
  options?: { toast?: boolean },
): Promise<boolean> {
  const showNodeToast = options?.toast ?? true;
  if (!props.workflowId || !props.canvasNodeId || !graph.value) {
    return false;
  }
  const node = graph.value.nodes.find((n) => n.id === memoryNodeId);
  if (!node) {
    return false;
  }
  const incident = incidentEdgesForNode(graph.value, node.id);
  try {
    pushUndo({
      kind: "node_deleted",
      workflowId: props.workflowId,
      canvasNodeId: props.canvasNodeId,
      node: { ...node },
      incidentEdges: incident,
    });
    await workflowApi.deleteAgentMemoryNode(props.workflowId, node.id);
    if (selectedNodeId.value === node.id) {
      selectedNodeId.value = null;
    }
    if (showNodeToast) {
      showToast("Node deleted", "success");
    }
    await loadGraph({ silent: true, refit: true });
    return true;
  } catch {
    undoStack.value = undoStack.value.slice(0, -1);
    if (showNodeToast) {
      showToast("Delete failed", "error");
    }
    return false;
  }
}

async function onFlowDeleteSelection(payload: {
  nodeIds: string[];
  edgeIds: string[];
}): Promise<void> {
  let anyOk = false;
  for (const eid of payload.edgeIds) {
    const ok = await deleteMemoryEdgeById(eid, { toast: false });
    anyOk = anyOk || ok;
  }
  for (const nid of payload.nodeIds) {
    const ok = await deleteMemoryNodeById(nid, { toast: false });
    anyOk = anyOk || ok;
  }
  if (anyOk) {
    showToast("Removed", "success");
  }
}

async function deleteSelectedNode(): Promise<void> {
  if (!selectedNode.value) {
    return;
  }
  await deleteMemoryNodeById(selectedNode.value.id);
}

async function addNode(): Promise<void> {
  if (!props.workflowId || !props.canvasNodeId) {
    return;
  }
  const name = newName.value.trim();
  const typ = newType.value.trim() || "topic";
  if (!name) {
    showToast("Entity name is required", "error");
    return;
  }
  try {
    const created = await workflowApi.createAgentMemoryNode(props.workflowId, props.canvasNodeId, {
      entity_name: name,
      entity_type: typ,
    });
    pushUndo({
      kind: "node_created",
      workflowId: props.workflowId,
      memoryNodeId: created.id,
    });
    newName.value = "";
    showToast("Node added", "success");
    await loadGraph({ silent: true, refit: true });
  } catch {
    showToast("Add failed", "error");
  }
}

async function addEdge(): Promise<void> {
  if (!props.workflowId || !props.canvasNodeId) {
    return;
  }
  const s = edgeSource.value.trim();
  const t = edgeTarget.value.trim();
  const r = edgeRel.value.trim() || "related";
  if (!s || !t) {
    showToast("Source and target names are required", "error");
    return;
  }
  try {
    const created = await workflowApi.createAgentMemoryEdge(props.workflowId, props.canvasNodeId, {
      source_entity_name: s,
      target_entity_name: t,
      relationship_type: r,
    });
    pushUndo({
      kind: "edge_created",
      workflowId: props.workflowId,
      memoryEdgeId: created.id,
    });
    showToast("Edge added", "success");
    await loadGraph({ silent: true, refit: true });
  } catch {
    showToast("Edge add failed (check entity names)", "error");
  }
}

async function deleteEdge(edgeId: string): Promise<void> {
  await deleteMemoryEdgeById(edgeId);
}

const entityNames = computed(() => graph.value?.nodes.map((n) => n.entity_name) ?? []);

const workflowListForPicker = ref<WorkflowListItem[]>([]);
const agentsByWorkflowId = ref<Map<string, Array<{ id: string; label: string }>>>(new Map());

const currentWorkflowId = computed(() => workflowStore.currentWorkflow?.id ?? "");

const workflowOptionsForSelect = computed(() =>
  workflowListForPicker.value.map((w) => ({
    value: w.id,
    label: w.name,
  })),
);

const permissionShareOptions: Array<{ value: string; label: string }> = [
  { value: "read", label: "Read only" },
  { value: "write", label: "Read & write" },
];

function workflowOptionsWithFallback(peerWorkflowId: string): Array<{ value: string; label: string }> {
  const base = workflowOptionsForSelect.value;
  const has = base.some((o) => o.value === peerWorkflowId);
  if (!has && peerWorkflowId) {
    return [{ value: peerWorkflowId, label: `${peerWorkflowId} (missing)` }, ...base];
  }
  return base;
}

function agentOptionsForRow(peerWorkflowId: string, peerCanvasNodeId: string): Array<{
  value: string;
  label: string;
}> {
  const agents = agentsByWorkflowId.value.get(peerWorkflowId) ?? [];
  const base = agents.map((a) => ({ value: a.id, label: a.label }));
  const has = base.some((o) => o.value === peerCanvasNodeId);
  if (!has && peerCanvasNodeId) {
    return [{ value: peerCanvasNodeId, label: `${peerCanvasNodeId} (missing)` }, ...base];
  }
  return base;
}

function sharePairKey(s: AgentMemoryShareEntry): string {
  return `${s.peerWorkflowId}\t${s.peerCanvasNodeId}`;
}

const memorySharesForUi = computed((): AgentMemoryShareEntry[] => {
  const selfId = props.canvasNodeId;
  if (!selfId) {
    return [];
  }
  const node = workflowStore.nodes.find((n) => n.id === selfId);
  const raw = node?.data?.memoryShares;
  if (!Array.isArray(raw)) {
    return [];
  }
  const out: AgentMemoryShareEntry[] = [];
  const fallbackWf = currentWorkflowId.value;
  for (const item of raw) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const peer = String((item as { peerCanvasNodeId?: unknown }).peerCanvasNodeId ?? "").trim();
    const permRaw = String((item as { permission?: unknown }).permission ?? "read")
      .trim()
      .toLowerCase();
    const permission: "read" | "write" = permRaw === "write" ? "write" : "read";
    if (!peer) {
      continue;
    }
    const rawWf = String((item as { peerWorkflowId?: unknown }).peerWorkflowId ?? "").trim();
    const peerWorkflowId = rawWf || fallbackWf;
    if (!peerWorkflowId) {
      continue;
    }
    out.push({ peerWorkflowId, peerCanvasNodeId: peer, permission });
  }
  return out;
});

async function loadWorkflowPickerListIfNeeded(): Promise<void> {
  if (workflowListForPicker.value.length > 0) {
    return;
  }
  try {
    const list = await workflowApi.list();
    workflowListForPicker.value = [...list].sort((a, b) => a.name.localeCompare(b.name));
  } catch {
    showToast("Could not load workflows", "error");
  }
}

async function ensureAgentsLoaded(wfId: string): Promise<void> {
  if (!wfId || agentsByWorkflowId.value.has(wfId)) {
    return;
  }
  try {
    const wf = await workflowApi.get(wfId);
    const agents = (wf.nodes || [])
      .filter((n) => n.type === "agent")
      .map((n) => ({ id: n.id, label: String(n.data?.label ?? n.id) }))
      .sort((a, b) => a.label.localeCompare(b.label));
    const next = new Map(agentsByWorkflowId.value);
    next.set(wfId, agents);
    agentsByWorkflowId.value = next;
  } catch {
    showToast("Could not load agents for workflow", "error");
  }
}

function agentsForPeerPick(wfId: string): Array<{ id: string; label: string }> {
  const agents = agentsByWorkflowId.value.get(wfId) ?? [];
  if (wfId === currentWorkflowId.value && props.canvasNodeId) {
    return agents.filter((a) => a.id !== props.canvasNodeId);
  }
  return agents;
}

function persistMemoryShares(next: AgentMemoryShareEntry[]): void {
  const selfId = props.canvasNodeId;
  if (!selfId) {
    return;
  }
  workflowStore.updateNode(selfId, { memoryShares: next });
}

async function onShareWorkflowChange(index: number, peerWorkflowId: string): Promise<void> {
  if (!peerWorkflowId) {
    return;
  }
  await ensureAgentsLoaded(peerWorkflowId);
  const agents = agentsForPeerPick(peerWorkflowId);
  if (!agents.length) {
    showToast("No other agents in this workflow", "error");
    return;
  }
  const prev = memorySharesForUi.value;
  const next = [...prev];
  const cur = next[index];
  if (!cur) {
    return;
  }
  const used = new Set(
    next.map((s, i) => (i === index ? null : sharePairKey(s))).filter((x): x is string =>
      Boolean(x),
    ),
  );
  let pick = agents[0]!.id;
  for (const a of agents) {
    const k = `${peerWorkflowId}\t${a.id}`;
    if (!used.has(k)) {
      pick = a.id;
      break;
    }
  }
  if (used.has(`${peerWorkflowId}\t${pick}`)) {
    showToast("That agent is already listed", "error");
    return;
  }
  next[index] = { ...cur, peerWorkflowId, peerCanvasNodeId: pick };
  persistMemoryShares(next);
}

function onShareAgentChange(index: number, peerWorkflowId: string, peerCanvasNodeId: string): void {
  const prev = memorySharesForUi.value;
  const next = [...prev];
  if (!next[index]) {
    return;
  }
  const k = `${peerWorkflowId}\t${peerCanvasNodeId}`;
  const dup = next.some((s, i) => i !== index && sharePairKey(s) === k);
  if (dup) {
    showToast("That agent is already listed", "error");
    return;
  }
  next[index] = { ...next[index], peerWorkflowId, peerCanvasNodeId };
  persistMemoryShares(next);
}

function onSharePermissionChange(index: number, permission: "read" | "write"): void {
  const prev = memorySharesForUi.value;
  const next = [...prev];
  if (!next[index]) {
    return;
  }
  next[index] = { ...next[index], permission };
  persistMemoryShares(next);
}

async function addMemoryShareRow(): Promise<void> {
  await loadWorkflowPickerListIfNeeded();
  if (!workflowListForPicker.value.length) {
    showToast("No workflows available", "error");
    return;
  }
  const used = new Set(memorySharesForUi.value.map((s) => sharePairKey(s)));
  for (const wf of workflowListForPicker.value) {
    await ensureAgentsLoaded(wf.id);
    const candidates = agentsForPeerPick(wf.id);
    const pick = candidates.find((a) => !used.has(`${wf.id}\t${a.id}`));
    if (pick) {
      persistMemoryShares([
        ...memorySharesForUi.value,
        {
          peerWorkflowId: wf.id,
          peerCanvasNodeId: pick.id,
          permission: "read",
        },
      ]);
      return;
    }
  }
  showToast("No workflow with an available agent to add", "error");
}

function removeMemoryShareRow(index: number): void {
  const prev = memorySharesForUi.value;
  persistMemoryShares(prev.filter((_, i) => i !== index));
}

watch(
  () => props.open,
  async (open) => {
    if (!open || !props.workflowId) {
      return;
    }
    await loadWorkflowPickerListIfNeeded();
    for (const s of memorySharesForUi.value) {
      await ensureAgentsLoaded(s.peerWorkflowId);
    }
  },
);

function handleDialogEscape(event: KeyboardEvent): void {
  if (event.key !== "Escape" || !props.open) {
    return;
  }
  event.preventDefault();
  event.stopImmediatePropagation();
  emit("close");
}
</script>

<template>
  <Dialog
    :open="open"
    title="Agent memory graph"
    size="4xl"
    @escape="handleDialogEscape"
    @close="emit('close')"
  >
    <template #header-trailing>
      <button
        type="button"
        class="dialog-header-icon-btn flex items-center justify-center w-11 h-11 min-h-[44px] min-w-[44px] md:w-8 md:h-8 rounded-xl text-muted-foreground hover:text-foreground transition-all duration-200 disabled:opacity-40 disabled:pointer-events-none"
        :disabled="loading || !workflowId || !canvasNodeId"
        title="Reload graph from server"
        aria-label="Reload memory graph"
        @click="refreshGraph"
      >
        <RefreshCw
          class="w-4 h-4"
          :class="{ 'animate-spin': loading }"
        />
      </button>
    </template>
    <div
      ref="dialogContentRef"
      tabindex="-1"
      class="flex flex-col gap-3 min-h-0 w-full overflow-hidden max-h-[min(70vh,calc(100dvh-10rem))] outline-none focus:outline-none"
    >
      <p class="text-xs text-muted-foreground shrink-0">
        Graph updates in the background after each successful agent run (including sub-agents).
        Drag nodes to rearrange; click a node to edit or delete. Backspace or Delete removes the
        current selection on the canvas (saved immediately). Ctrl+Z undoes the last change
        (not while typing in a field).
      </p>

      <div
        v-if="workflowId && canvasNodeId"
        class="shrink-0 rounded-lg border bg-muted/30 p-3 space-y-2"
      >
        <div class="font-medium text-xs uppercase text-muted-foreground tracking-wide">
          Share memory with other agents
        </div>
        <p class="text-[10px] text-muted-foreground leading-snug">
          Read only: peer agents receive this graph in their system prompt. Read &amp; write: peers
          may also merge new facts into this graph after a successful run (same credential as the
          peer agent).
        </p>
        <div
          v-if="memorySharesForUi.length"
          class="space-y-2"
        >
          <div
            v-for="(share, idx) in memorySharesForUi"
            :key="'share-row-' + String(idx)"
            class="grid w-full grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-center sm:gap-2"
          >
            <div class="min-w-0 w-full">
              <Select
                :model-value="share.peerWorkflowId"
                placeholder="Workflow"
                :options="workflowOptionsWithFallback(share.peerWorkflowId)"
                class="w-full"
                @update:model-value="(v) => v && void onShareWorkflowChange(idx, v)"
              />
            </div>
            <div class="min-w-0 w-full">
              <Select
                :model-value="share.peerCanvasNodeId"
                placeholder="Agent"
                :options="agentOptionsForRow(share.peerWorkflowId, share.peerCanvasNodeId)"
                class="w-full"
                @update:model-value="(v) => v && onShareAgentChange(idx, share.peerWorkflowId, v)"
              />
            </div>
            <div class="min-w-0 w-full">
              <Select
                :model-value="share.permission"
                placeholder="Access"
                :options="permissionShareOptions"
                class="w-full"
                @update:model-value="
                  (v) => v && onSharePermissionChange(idx, v === 'write' ? 'write' : 'read')
                "
              />
            </div>
            <div class="flex shrink-0 items-center justify-end sm:justify-center">
              <button
                type="button"
                class="inline-flex h-11 min-h-[44px] w-11 min-w-[44px] shrink-0 items-center justify-center rounded-xl border border-border bg-background text-destructive shadow-sm hover:bg-destructive/10 md:h-10 md:min-h-0 md:w-10 md:min-w-[40px]"
                title="Remove share"
                aria-label="Remove share"
                @click="removeMemoryShareRow(idx)"
              >
                <Trash2 class="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          class="h-9 w-full"
          @click="addMemoryShareRow"
        >
          Add agent
        </Button>
      </div>

      <div
        v-if="loading"
        class="text-sm text-muted-foreground py-8 text-center shrink-0"
      >
        Loading…
      </div>

      <div
        v-else
        class="grid grid-cols-1 lg:grid-cols-[1fr_minmax(17.5rem,21rem)] gap-3 flex-1 min-h-0 overflow-hidden items-stretch"
      >
        <div
          ref="graphAreaRef"
          class="agent-memory-graph-flow relative flex flex-col border border-border rounded-lg overflow-hidden bg-muted/30 min-h-[220px] h-[min(42vh,360px)] max-h-[50vh] lg:h-full lg:max-h-none lg:min-h-0"
          :class="{ 'agent-memory-graph-canvas-fs': graphCanvasFullscreen, 'needles-spinning': needleAnimating, 'compact-mode': labelsHidden }"
        >
          <AgentMemoryGraphFlowPane
            v-if="flowNodes.length"
            :key="flowLayoutEpoch"
            ref="flowPaneRef"
            :flow-id="AGENT_MEMORY_FLOW_ID"
            :nodes="flowNodes"
            :edges="flowEdges"
            :hotkeys-enabled="open"
            @node-click="onNodeClick"
            @pane-click="onPaneClick"
            @delete-selection="onFlowDeleteSelection"
          >
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
          </AgentMemoryGraphFlowPane>
          <div
            v-else
            class="flex-1 min-h-[200px] flex items-center justify-center text-sm text-muted-foreground"
          >
            No memory entities yet. Run the workflow or add nodes in the sidebar.
          </div>

          <!-- Whirl animation: hub orbits 8 dots around canvas centre -->
          <div
            v-if="needleAnimating"
            class="absolute inset-0 z-10 pointer-events-none overflow-hidden"
          >
            <div class="whirl-hub">
              <div
                class="whirl-dot"
                style="--angle: 0deg;   --r: 55px; --s: 5px; --a: 0.90; --d: 0.00s"
              />
              <div
                class="whirl-dot"
                style="--angle: 45deg;  --r: 30px; --s: 3px; --a: 0.65; --d: 0.05s"
              />
              <div
                class="whirl-dot"
                style="--angle: 90deg;  --r: 58px; --s: 5px; --a: 0.85; --d: 0.03s"
              />
              <div
                class="whirl-dot"
                style="--angle: 135deg; --r: 28px; --s: 3px; --a: 0.65; --d: 0.08s"
              />
              <div
                class="whirl-dot"
                style="--angle: 180deg; --r: 52px; --s: 4px; --a: 0.80; --d: 0.06s"
              />
              <div
                class="whirl-dot"
                style="--angle: 225deg; --r: 32px; --s: 3px; --a: 0.65; --d: 0.04s"
              />
              <div
                class="whirl-dot"
                style="--angle: 270deg; --r: 56px; --s: 5px; --a: 0.90; --d: 0.07s"
              />
              <div
                class="whirl-dot"
                style="--angle: 315deg; --r: 26px; --s: 3px; --a: 0.60; --d: 0.02s"
              />
            </div>
          </div>

          <Button
            type="button"
            variant="secondary"
            size="icon"
            class="absolute bottom-14 left-2 z-[5] h-9 w-9 min-h-[36px] min-w-[36px] shadow-md border border-border bg-card/95 backdrop-blur-sm md:h-8 md:w-8"
            :title="labelsHidden ? 'Show labels' : 'Hide labels'"
            :aria-label="labelsHidden ? 'Show labels' : 'Hide labels'"
            :disabled="!flowNodes.length"
            @click="toggleLabels"
          >
            <EyeOff
              v-if="labelsHidden"
              class="w-4 h-4"
            />
            <Eye
              v-else
              class="w-4 h-4"
            />
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="icon"
            class="absolute bottom-2 left-2 z-[5] h-9 w-9 min-h-[36px] min-w-[36px] shadow-md border border-border bg-card/95 backdrop-blur-sm md:h-8 md:w-8"
            title="Tidy layout"
            aria-label="Tidy layout"
            :disabled="!flowNodes.length"
            @click="tidyMemoryGraphLayout"
          >
            <Wand2 class="w-4 h-4" />
          </Button>
          <!-- Tooltip: position:fixed escapes overflow:hidden AND stays inside the
               browser-fullscreen element's subtree (unlike Teleport to body) -->
          <div
            v-if="tooltipState"
            class="fixed z-[9999] pointer-events-none max-w-[240px] rounded-md border border-border/60 bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-lg whitespace-pre-wrap break-words leading-relaxed"
            :style="{ left: `${tooltipState.x}px`, top: `${tooltipState.y}px` }"
          >
            {{ tooltipState.text }}
          </div>
          <Button
            type="button"
            variant="secondary"
            size="icon"
            class="absolute bottom-2 right-2 z-[5] h-9 w-9 min-h-[36px] min-w-[36px] shadow-md border border-border bg-card/95 backdrop-blur-sm md:h-8 md:w-8"
            :title="graphCanvasFullscreen ? 'Exit graph fullscreen' : 'Fullscreen graph'"
            :aria-label="graphCanvasFullscreen ? 'Exit graph fullscreen' : 'Fullscreen graph'"
            @click="toggleGraphCanvasFullscreen"
          >
            <Minimize2
              v-if="graphCanvasFullscreen"
              class="w-4 h-4"
            />
            <Maximize2
              v-else
              class="w-4 h-4"
            />
          </Button>
        </div>

        <div
          class="agent-memory-sidebar flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden text-sm lg:min-h-0"
        >
          <div
            class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overflow-x-hidden py-0.5 pr-1"
          >
            <div
              class="flex shrink-0 flex-col rounded-lg border bg-muted/20 p-3 w-full min-w-0"
            >
              <div
                v-if="selectedNode"
                class="space-y-3"
              >
                <div class="font-medium text-xs uppercase text-muted-foreground tracking-wide">
                  Edit node
                </div>
                <Input
                  v-model="editName"
                  placeholder="Entity name"
                  class="h-9 text-sm w-full"
                  aria-label="Entity name"
                />
                <Input
                  v-model="editType"
                  placeholder="Type (e.g. person)"
                  class="h-9 text-sm w-full"
                  aria-label="Entity type"
                />
                <div class="font-medium text-[10px] uppercase text-muted-foreground tracking-wide pt-0.5">
                  Attributes
                </div>
                <div class="space-y-3">
                  <div
                    v-for="(row, idx) in editPropertyRows"
                    :key="`attr-${idx}`"
                    class="rounded-lg border border-border bg-background/90 p-3 space-y-2.5 shadow-sm"
                  >
                    <div class="flex items-center justify-between gap-2">
                      <span class="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                        {{
                          editPropertyRows.length > 1 ? `Attribute ${String(idx + 1)}` : "Attribute"
                        }}
                      </span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        class="h-7 shrink-0 px-2 text-destructive hover:bg-destructive/10 hover:text-destructive"
                        title="Remove attribute"
                        @click="removeEditPropertyRow(idx)"
                      >
                        <Trash2 class="w-3.5 h-3.5" />
                      </Button>
                    </div>
                    <div class="space-y-1">
                      <span class="text-[10px] text-muted-foreground">Key</span>
                      <Input
                        v-model="row.key"
                        placeholder="e.g. serving_style"
                        class="h-9 text-sm w-full"
                        aria-label="Attribute key"
                      />
                    </div>
                    <div class="space-y-1">
                      <span class="text-[10px] text-muted-foreground">Value</span>
                      <Input
                        v-model="row.value"
                        placeholder="e.g. küllah"
                        class="h-9 text-sm w-full"
                        aria-label="Attribute value"
                      />
                    </div>
                  </div>
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
                  <Button
                    size="sm"
                    class="h-9 flex-1 min-w-0"
                    @click="saveNodeEdit"
                  >
                    Save
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    class="h-9 shrink-0"
                    @click="deleteSelectedNode"
                  >
                    <Trash2 class="w-4 h-4" />
                  </Button>
                </div>
              </div>
              <div
                v-else
                class="space-y-3"
              >
                <div class="font-medium text-xs uppercase text-muted-foreground tracking-wide">
                  New entity
                </div>
                <Input
                  v-model="newName"
                  placeholder="Entity name"
                  class="h-9 text-sm w-full"
                />
                <Input
                  v-model="newType"
                  placeholder="Type (e.g. person)"
                  class="h-9 text-sm w-full"
                />
                <Button
                  size="sm"
                  class="h-9 w-full"
                  @click="addNode"
                >
                  Add node
                </Button>
              </div>
            </div>

            <div class="shrink-0 space-y-2 p-3 rounded-lg border w-full min-w-0">
              <div class="font-medium text-xs uppercase text-muted-foreground tracking-wide">
                New relationship
              </div>
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
              <Input
                v-model="edgeRel"
                placeholder="Relationship (e.g. works for)"
                class="h-9 text-sm w-full"
              />
              <Button
                size="sm"
                class="h-9 w-full"
                @click="addEdge"
              >
                Add edge
              </Button>
            </div>

            <div
              v-if="edgesForSidebarList.length"
              class="shrink-0 rounded-lg border w-full min-w-0 pb-1"
            >
              <div class="space-y-0 p-3">
                <div class="font-medium text-xs uppercase text-muted-foreground tracking-wide mb-2">
                  All edges
                </div>
                <div
                  v-for="{ edge: e, status } in edgesForSidebarList"
                  :key="e.id"
                  class="flex items-start justify-between gap-2 border-b border-border/50 py-2 text-xs last:border-b-0"
                >
                  <span
                    class="min-w-0 flex-1 block"
                    :title="
                      (graph?.nodes.find((n) => n.id === e.source_node_id)?.entity_name ?? '?') +
                        ' → ' +
                        (graph?.nodes.find((n) => n.id === e.target_node_id)?.entity_name ?? '?') +
                        ' (' +
                        e.relationship_type +
                        ')' +
                        (status ? ' [' + status + ']' : '')
                    "
                  >
                    <span class="block break-words leading-snug">
                      {{ graph?.nodes.find((n) => n.id === e.source_node_id)?.entity_name ?? "?" }}
                      →
                      {{ graph?.nodes.find((n) => n.id === e.target_node_id)?.entity_name ?? "?" }}
                    </span>
                    <span class="text-muted-foreground">({{ e.relationship_type }})</span>
                    <span
                      v-if="status"
                      class="mt-1 block w-fit max-w-full"
                    >
                      <span :class="memoryStatusBadgeClass(status)">
                        {{ formatMemoryStatusLabel(status) }}
                      </span>
                    </span>
                  </span>
                  <button
                    type="button"
                    class="mt-0.5 shrink-0 rounded p-1.5 hover:bg-destructive/10 text-destructive"
                    title="Remove edge"
                    @click="deleteEdge(e.id)"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Dialog>
</template>

<style scoped>
/* Vue Flow theme-default uses light-only #fff node shells and label backgrounds. */
.agent-memory-graph-flow {
  --vf-node-bg: hsl(var(--card));
  --vf-node-text: hsl(var(--foreground));
}

.agent-memory-graph-flow.agent-memory-graph-canvas-fs {
  height: 100vh !important;
  min-height: 100vh !important;
  max-height: 100vh !important;
  border-radius: 0;
}

.agent-memory-graph-canvas-fs :deep(.agent-memory-vue-flow) {
  flex: 1 1 0;
  min-height: 0;
  height: 100%;
}

.agent-memory-graph-flow :deep(.vue-flow) {
  background: hsl(var(--background)) !important;
}

.agent-memory-graph-flow :deep(.vue-flow__renderer),
.agent-memory-graph-flow :deep(.vue-flow__container) {
  background: transparent !important;
}

.agent-memory-graph-flow :deep(.vue-flow__pane) {
  background: hsl(var(--muted) / 0.2) !important;
}

.agent-memory-graph-flow :deep(.vue-flow__node-default) {
  padding: 0 !important;
  width: auto !important;
  min-width: 0 !important;
  max-width: none !important;
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  text-align: left;
  color: inherit;
}

.agent-memory-graph-flow :deep(.vue-flow__node-default.selectable:hover) {
  box-shadow: none !important;
}

.agent-memory-graph-flow :deep(.vue-flow__node-default.selected),
.agent-memory-graph-flow :deep(.vue-flow__node-default:focus),
.agent-memory-graph-flow :deep(.vue-flow__node-default:focus-visible) {
  border: none !important;
  box-shadow: none !important;
  outline: none !important;
}

.agent-memory-graph-flow :deep(.vue-flow__edge-textbg) {
  fill: hsl(var(--card)) !important;
}

.agent-memory-graph-flow :deep(.vue-flow__edge-text) {
  fill: hsl(var(--foreground)) !important;
}

.agent-memory-graph-flow :deep(.vue-flow__attribution) {
  opacity: 0.5;
  font-size: 10px;
}

.agent-memory-graph-flow :deep(.vue-flow__attribution a) {
  color: hsl(var(--muted-foreground));
}

.dialog-header-icon-btn {
  background: hsl(var(--muted) / 0.5);
}

.dialog-header-icon-btn:hover:not(:disabled) {
  background: hsl(var(--muted));
}

/* Whirl overlay: hub rotates, child dots orbit → esinti/vortex effect */
.whirl-hub {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 0;
  height: 0;
  transform-origin: 0 0;
  animation: whirl-hub-spin 1s cubic-bezier(0.1, 0.55, 0.35, 1) forwards;
}

@keyframes whirl-hub-spin {
  0%   { transform: rotate(0deg);    opacity: 0; }
  8%   {                             opacity: 1; }
  75%  {                             opacity: 1; }
  100% { transform: rotate(-720deg); opacity: 0; }
}

/* Dots are positioned statically via CSS vars (vars in transform DO work outside keyframes) */
.whirl-dot {
  position: absolute;
  border-radius: 50%;
  background: hsl(var(--primary) / var(--a, 0.8));
  width: var(--s, 4px);
  height: var(--s, 4px);
  margin: calc(var(--s, 4px) / -2);
  /* static positioning: rotate to orbit angle, then move radially outward */
  transform: rotate(var(--angle, 0deg)) translateY(calc(-1 * var(--r, 40px)));
  /* individual pop-in/pop-out via CSS independent 'scale' (doesn't affect transform above) */
  animation: whirl-dot-pop 1s ease-out forwards;
  animation-delay: var(--d, 0s);
}

@keyframes whirl-dot-pop {
  0%   { scale: 0;   opacity: 0; }
  18%  { scale: 1.4; opacity: 1; }
  75%  { scale: 1;   opacity: 1; }
  100% { scale: 0.2; opacity: 0; }
}

/* Keep relationship lines visible in compact mode after the opening animation ends. */
.compact-mode :deep(.vue-flow__edge-labels) {
  display: none !important;
}

.needles-spinning.compact-mode :deep(.vue-flow__edges),
.needles-spinning.compact-mode :deep(.vue-flow__edge) {
  opacity: 0;
  pointer-events: none;
}

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
</style>
