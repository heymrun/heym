<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { BaseEdge, EdgeLabelRenderer, getBezierPath } from "@vue-flow/core";
import type { EdgeProps } from "@vue-flow/core";
import { Plus } from "lucide-vue-next";

import { useWorkflowStore } from "@/stores/workflow";

const props = defineProps<EdgeProps>();

const workflowStore = useWorkflowStore();
const isHovered = ref(false);

const path = computed(() => {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
  });

  return { edgePath, labelX, labelY };
});

function handleInsertClick(event: MouseEvent): void {
  event.stopPropagation();

  workflowStore.setPendingInsertEdge({
    edgeId: props.id,
    sourceId: props.source,
    targetId: props.target,
    sourceHandle: props.sourceHandleId || undefined,
    targetHandle: props.targetHandleId || undefined,
  });

  workflowStore.clearNodeSearchQuery();
}

function onEdgeMouseEnter(): void {
  isHovered.value = true;
}

function onEdgeMouseLeave(): void {
  isHovered.value = false;
}

onMounted(() => {
  const edgeEl = document.querySelector(`[data-id="${props.id}"]`);
  if (edgeEl) {
    edgeEl.addEventListener("mouseenter", onEdgeMouseEnter);
    edgeEl.addEventListener("mouseleave", onEdgeMouseLeave);
  }
});

onUnmounted(() => {
  const edgeEl = document.querySelector(`[data-id="${props.id}"]`);
  if (edgeEl) {
    edgeEl.removeEventListener("mouseenter", onEdgeMouseEnter);
    edgeEl.removeEventListener("mouseleave", onEdgeMouseLeave);
  }
});
</script>

<template>
  <BaseEdge
    :id="id"
    :style="style"
    :path="path.edgePath"
    :marker-end="markerEnd"
    :interaction-width="20"
  />
  <EdgeLabelRenderer>
    <div
      class="insert-button-wrapper nodrag nopan"
      :class="{ 'is-visible': isHovered }"
      :style="{
        transform: `translate(-50%, -50%) translate(${path.labelX}px, ${path.labelY}px)`,
        pointerEvents: 'all',
      }"
      @mouseenter="isHovered = true"
      @mouseleave="isHovered = false"
    >
      <button
        class="insert-button"
        @click="handleInsertClick"
      >
        <Plus class="w-3 h-3" />
      </button>
    </div>
  </EdgeLabelRenderer>
</template>

<style scoped>
.insert-button-wrapper {
  position: absolute;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.insert-button-wrapper.is-visible {
  opacity: 1;
}

.insert-button {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  border: 2px solid hsl(var(--background));
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.insert-button:hover {
  transform: scale(1.2);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
}
</style>
