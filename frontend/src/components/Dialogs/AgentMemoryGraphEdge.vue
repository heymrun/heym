<script lang="ts">
// Genuine module scope (unlike anything declared inside <script setup>, which runs fresh
// inside setup() on every component instantiation) — this must survive Vue Flow remounting
// this component on every selection change, so a deselect can still find where the fill
// animation left off instead of restarting from a fresh, always-zero ref.
export const revealProgressByEdgeId = new Map<string, number>();

/** Exported so AgentMemoryGraphDialog.vue can keep the "restore other entities' color" delay
 * on deselect in sync with how long this component's own drain animation actually takes. */
export const REVEAL_DURATION_MS = 450;
</script>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { BaseEdge, EdgeLabelRenderer, useVueFlow } from "@vue-flow/core";
import type { EdgeProps } from "@vue-flow/core";

const props = defineProps<EdgeProps>();

const { findNode } = useVueFlow();

function pathCurvatureFromData(): number {
  const d = props.data;
  if (!d || typeof d !== "object") {
    return 0.06;
  }
  const v = (d as Record<string, unknown>).pathCurvature;
  if (typeof v === "number" && Number.isFinite(v)) {
    return Math.min(0.15, Math.max(0.02, v));
  }
  return 0.06;
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

/** Vue Flow's computedPosition is the node box's top-left corner, not its center. Since
 * flowNodes now sets each node's width/height to exactly its circle's diameter (see
 * AgentMemoryGraphDialog.vue), the circle's true center is always top-left + radius on both
 * axes — this no longer drifts with caption text width the way the old flex-centered layout
 * did (that made the box wider than the circle, so computedPosition-as-center pointed at the
 * box's center, not the circle's). */
function circleCenterOf(nodeComputedPosition: { x: number; y: number }, radius: number): { x: number; y: number } {
  return { x: nodeComputedPosition.x + radius, y: nodeComputedPosition.y + radius };
}

const path = computed(() => {
  const sourceNode = findNode(props.source);
  const targetNode = findNode(props.target);
  if (!sourceNode || !targetNode) {
    return { edgePath: "", labelX: props.sourceX, labelY: props.sourceY };
  }
  const sourceRadius = radiusOf(props.source);
  const targetRadius = radiusOf(props.target);
  return circleToCirclePath(
    circleCenterOf(sourceNode.computedPosition, sourceRadius),
    sourceRadius,
    circleCenterOf(targetNode.computedPosition, targetRadius),
    targetRadius,
    pathCurvatureFromData(),
  );
});

function isDimmed(): boolean {
  const d = props.data;
  return Boolean(d && typeof d === "object" && (d as { dimmed?: unknown }).dimmed === true);
}

/** True when a sibling active edge (same selected hub) is hovered instead of this one — hides
 * only this edge's relationship-label chip (the lines themselves stay put) so the hovered
 * relation's label can be read without overlapping text from its siblings. */
function isHoveredOut(): boolean {
  const d = props.data;
  return Boolean(d && typeof d === "object" && (d as { hoveredOut?: unknown }).hoveredOut === true);
}

/** True when this edge is directly incident to the selected node — the only state in which its
 * relationship label is shown and its chain-fill overlay is revealed. */
function isActive(): boolean {
  const d = props.data;
  return Boolean(d && typeof d === "object" && (d as { active?: unknown }).active === true);
}

function growsFromEnd(): boolean {
  const d = props.data;
  return Boolean(d && typeof d === "object" && (d as { growFromEnd?: unknown }).growFromEnd === true);
}

/** Always-visible base line: thin, solid, subtle — a plain network hairline rather than a
 * dashed/colored one, so an unfocused graph reads as a coherent web instead of a scatter of
 * disconnected dashes. */
const basePathStyle = computed(() => ({
  ...((props.style as Record<string, string> | undefined) ?? {}),
  stroke: "hsl(215 20% 70% / 0.35)",
  strokeWidth: 1,
  opacity: isDimmed() ? 0.06 : 1,
  transition: "opacity 0.2s ease",
}));

// --- Chain-fill overlay: a purple line that draws itself in (from the selected node outward)
// when this edge becomes active, and drains back out the same way on deselect. ---
//
// Vue Flow remounts this component (confirmed via instrumentation: onUnmounted immediately
// followed by a fresh onMounted with a new instance) on every selection change, since its
// slot-based custom-edge render path has early `return null` branches that transiently produce
// a null render. A plain component-local `ref(0)` would therefore always restart from 0 on
// both select AND deselect, animating the fill-in (0 -> 1, so it looked correct by accident)
// but never the drain (0 -> 0 is a no-op, which read as an instant snap with no animation).
// revealProgressByEdgeId (module-level, declared in the sibling plain <script> block above)
// survives the remount so a deselect still finds start=1 and animates down to 0.
const revealPathEl = ref<SVGPathElement | null>(null);
const revealProgress = ref(revealProgressByEdgeId.get(props.id) ?? 0); // 0 = drained, 1 = drawn
let revealRafId: number | null = null;

watch(revealProgress, (v) => {
  revealProgressByEdgeId.set(props.id, v);
});

function animateReveal(target: number): void {
  if (revealRafId !== null) {
    cancelAnimationFrame(revealRafId);
  }
  const start = revealProgress.value;
  if (start === target) {
    return;
  }
  const startTime = performance.now();
  function tick(now: number): void {
    const t = Math.min(1, (now - startTime) / REVEAL_DURATION_MS);
    const eased = 1 - (1 - t) * (1 - t);
    revealProgress.value = start + (target - start) * eased;
    revealRafId = t < 1 ? requestAnimationFrame(tick) : null;
  }
  revealRafId = requestAnimationFrame(tick);
}

watch(
  () => isActive(),
  (active) => animateReveal(active ? 1 : 0),
  { immediate: true },
);

onUnmounted(() => {
  if (revealRafId !== null) {
    cancelAnimationFrame(revealRafId);
  }
});

const revealPathLength = computed(() => {
  void path.value.edgePath;
  return revealPathEl.value?.getTotalLength() ?? 0;
});

const revealStyle = computed(() => {
  const len = revealPathLength.value;
  if (!len || revealProgress.value <= 0.001) {
    return { opacity: 0 };
  }
  const magnitude = len * (1 - revealProgress.value);
  const offset = growsFromEnd() ? -magnitude : magnitude;
  return {
    strokeDasharray: `${len} ${len}`,
    strokeDashoffset: offset,
    opacity: 1,
  };
});

function relationshipTypeLabel(): string {
  const d = props.data;
  if (d && typeof d === "object" && typeof (d as { relationshipType?: unknown }).relationshipType === "string") {
    return (d as { relationshipType: string }).relationshipType;
  }
  return typeof props.label === "string" ? props.label : "";
}

const relationshipLabel = computed(() => relationshipTypeLabel());
</script>

<template>
  <BaseEdge
    :id="id"
    :style="basePathStyle"
    :path="path.edgePath"
    :marker-end="markerEnd"
    :interaction-width="16"
  />
  <path
    ref="revealPathEl"
    :d="path.edgePath"
    fill="none"
    class="agent-memory-edge-reveal"
    :style="revealStyle"
  />
  <EdgeLabelRenderer>
    <div
      v-if="relationshipLabel && isActive() && !isHoveredOut()"
      class="agent-memory-edge-label nodrag nopan pointer-events-none max-w-[220px] text-center transition-opacity duration-150"
      :style="{
        position: 'absolute',
        left: 0,
        top: 0,
        transform: `translate(-50%, -50%) translate(${path.labelX}px, ${path.labelY}px)`,
        opacity: revealProgress >= 0.98 ? 1 : 0,
      }"
    >
      <span
        class="rounded border border-primary/40 bg-card/90 px-1.5 py-0.5 text-[11px] font-semibold text-foreground shadow-sm backdrop-blur-sm"
      >
        {{ relationshipLabel }}
      </span>
    </div>
  </EdgeLabelRenderer>
</template>

<style scoped>
.agent-memory-edge-reveal {
  stroke: hsl(var(--primary));
  stroke-width: 2;
  pointer-events: none;
}
</style>
