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
    targetY: props.targetY,
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
        class="rounded border border-border bg-card px-2 py-1 text-[10px] font-medium text-foreground shadow-sm"
      >
        {{ relationshipLabel }}
      </span>
    </div>
  </EdgeLabelRenderer>
</template>
