<script setup lang="ts">
import { computed } from "vue";
import { Sparkles } from "lucide-vue-next";

import { useWorkflowStore } from "@/stores/workflow";

const props = defineProps<{ nodeId: string; label: string }>();
const workflowStore = useWorkflowStore();
const isFocused = computed<boolean>(() => workflowStore.aiFocusNodeId === props.nodeId);

function openAssistant(): void {
  workflowStore.focusAssistantOnNode(props.nodeId);
}
</script>

<template>
  <div
    class="canvas-node-ai nodrag nopan absolute bottom-full left-1/2 -translate-x-1/2 flex pb-1.5"
    :class="isFocused && 'canvas-node-ai-focused'"
    @pointerdown.stop
    @mousedown.stop
    @click.stop
    @dblclick.stop
    @keydown.stop
  >
    <button
      type="button"
      class="canvas-node-ai-button inline-flex h-5 items-center gap-1 rounded-md border px-1.5 text-[10px] font-medium leading-none text-primary shadow-[0_0_12px_hsl(var(--primary)/0.35)] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/40 dark:text-brand-primary-soft"
      :class="isFocused ? 'border-primary' : 'border-primary/50'"
      :aria-label="`Edit ${label} with AI`"
      title="Change or fix this node with the AI Assistant"
      data-testid="canvas-node-ai-button"
      @click="openAssistant"
    >
      <Sparkles class="h-2.5 w-2.5" />
      AI
    </button>
  </div>
</template>

<style>
.canvas-node-ai {
  opacity: 0;
  pointer-events: none;
  transition: opacity 120ms ease;
}
.vue-flow__node:hover .canvas-node-ai,
.canvas-node-ai:focus-within,
.canvas-node-ai.canvas-node-ai-focused {
  opacity: 1;
  pointer-events: auto;
}
/* Opaque like the Run button, so an edge behind it never shows through; the
   primary tint is a layer on top of the background colour, not a see-through fill. */
.canvas-node-ai-button {
  background-color: hsl(var(--background));
}
.canvas-node-ai-button:hover {
  background-image: linear-gradient(hsl(var(--primary) / 0.1), hsl(var(--primary) / 0.1));
}
.canvas-node-ai-focused .canvas-node-ai-button {
  background-image: linear-gradient(hsl(var(--primary) / 0.15), hsl(var(--primary) / 0.15));
}
</style>
