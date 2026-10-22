<script setup lang="ts">
import { computed } from "vue";
import { Sparkles } from "lucide-vue-next";

import { useWorkflowStore } from "@/stores/workflow";

const props = defineProps<{ nodeId: string; label: string; raised?: boolean }>();
const workflowStore = useWorkflowStore();
const isFocused = computed<boolean>(() => workflowStore.aiFocusNodeId === props.nodeId);

function openAssistant(): void {
  workflowStore.focusAssistantOnNode(props.nodeId);
}
</script>

<template>
  <div
    class="canvas-node-ai nodrag nopan absolute bottom-full left-1/2 -translate-x-1/2"
    :class="[raised ? 'pb-6' : 'pb-4', isFocused && 'canvas-node-ai-focused']"
    @pointerdown.stop
    @mousedown.stop
    @click.stop
    @dblclick.stop
    @keydown.stop
  >
    <button
      type="button"
      class="inline-flex h-6 items-center gap-1 rounded-md border px-2 text-[11px] font-medium leading-none shadow-[0_0_12px_hsl(var(--primary)/0.35)] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/40"
      :class="isFocused
        ? 'border-primary bg-primary/15 text-primary dark:text-brand-primary-soft'
        : 'border-primary/50 bg-background text-primary hover:bg-primary/10 dark:text-brand-primary-soft'"
      :aria-label="`Edit ${label} with AI`"
      title="Change or fix this node with the AI Assistant"
      data-testid="canvas-node-ai-button"
      @click="openAssistant"
    >
      <Sparkles class="h-3 w-3" />
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
</style>
