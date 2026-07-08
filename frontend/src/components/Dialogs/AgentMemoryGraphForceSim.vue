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
  /** Node whose incident links should rest at FOCUS_LINK_DISTANCE instead of LINK_DISTANCE, so
   * selecting a hub physically pushes its neighbors apart to make room for the edge labels and
   * captions that only appear while it's selected (see AgentMemoryGraphDialog.vue). */
  focusNodeId?: string | null;
}>();

const { getNodes, findNode, updateNode, viewport, dimensions } = useVueFlow();

const LINK_DISTANCE = 140;
const FOCUS_LINK_DISTANCE = 240;
const LINK_STRENGTH = 0.06;
const REPULSION_STRENGTH = 2600;
const CENTER_STRENGTH = 0.02;
const CLUSTER_STRENGTH = 0.015;
const COLLISION_PADDING = 6;
const VELOCITY_DAMPING = 0.7;
const ALPHA_DECAY = 0.985;
const ALPHA_MIN = 0.006;
/** Keep every node's center within this fraction of the visible canvas inset from each of the
 * four edges, so nodes (especially ones pushed outward by FOCUS_LINK_DISTANCE) can't drift under
 * the canvas toolbar buttons or off-screen. */
const SAFE_AREA_MARGIN_RATIO = 0.1;

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

interface FlowSpaceBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

/** Converts the visible viewport rect (screen space) into flow-space coordinates, inset by
 * SAFE_AREA_MARGIN_RATIO on each side. Returns null while the pane hasn't measured yet. */
function safeAreaBounds(): FlowSpaceBounds | null {
  const { width, height } = dimensions.value;
  if (width <= 0 || height <= 0) {
    return null;
  }
  const { x: vx, y: vy, zoom } = viewport.value;
  const marginX = (width * SAFE_AREA_MARGIN_RATIO) / zoom;
  const marginY = (height * SAFE_AREA_MARGIN_RATIO) / zoom;
  return {
    minX: -vx / zoom + marginX,
    maxX: (width - vx) / zoom - marginX,
    minY: -vy / zoom + marginY,
    maxY: (height - vy) / zoom - marginY,
  };
}

function clamp(value: number, lo: number, hi: number): number {
  if (lo > hi) {
    return (lo + hi) / 2;
  }
  return Math.min(hi, Math.max(lo, value));
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

  // Link springs pull connected nodes toward LINK_DISTANCE apart (or FOCUS_LINK_DISTANCE for
  // links touching the focused/selected node, so its neighbors spread out to make room).
  const focusId = props.focusNodeId;
  for (const link of props.links) {
    const a = findNode(link.source);
    const b = findNode(link.target);
    if (!a || !b) {
      continue;
    }
    const restLength =
      focusId != null && (link.source === focusId || link.target === focusId)
        ? FOCUS_LINK_DISTANCE
        : LINK_DISTANCE;
    const dx = b.position.x - a.position.x;
    const dy = b.position.y - a.position.y;
    const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
    const displacement = (dist - restLength) * LINK_STRENGTH;
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
  const bounds = safeAreaBounds();
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

    let nextX = n.position.x + v.vx;
    let nextY = n.position.y + v.vy;
    if (bounds) {
      const r = nodeRadiusOf(n.id);
      nextX = clamp(nextX, bounds.minX + r, bounds.maxX - r);
      nextY = clamp(nextY, bounds.minY + r, bounds.maxY - r);
    }

    updateNode(n.id, {
      position: { x: nextX, y: nextY },
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

// Re-settle the layout whenever the focused node changes (select, deselect, or switch), so the
// spacing-out/closing-back-up motion is visibly animated rather than snapping instantly.
watch(() => props.focusNodeId, () => reheat());

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
