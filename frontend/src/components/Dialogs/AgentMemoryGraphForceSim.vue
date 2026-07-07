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
