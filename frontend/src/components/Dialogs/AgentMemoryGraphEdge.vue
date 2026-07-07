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
    :style="dashedPathStyle"
    :path="path.edgePath"
    :marker-end="markerEnd"
    :interaction-width="16"
  />
  <EdgeLabelRenderer>
    <div
      class="agent-memory-edge-label nodrag nopan pointer-events-none max-w-[220px] text-center"
      :style="{
        position: 'absolute',
        left: 0,
        top: 0,
        transform: `translate(-50%, -50%) translate(${path.labelX}px, ${path.labelY}px)`,
      }"
    >
      <span
        v-if="relationshipLabel"
        class="rounded border border-border bg-card/70 px-1.5 py-0.5 text-[9px] font-medium text-foreground shadow-sm backdrop-blur-sm transition-opacity duration-150"
        :style="{ opacity: isDimmed() ? 0.15 : 1 }"
      >
        {{ relationshipLabel }}
      </span>
    </div>
  </EdgeLabelRenderer>
</template>
