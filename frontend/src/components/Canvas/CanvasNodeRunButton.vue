<script setup lang="ts">
import { ref } from "vue";
import axios from "axios";
import { Play } from "lucide-vue-next";

import { useToast } from "@/composables/useToast";
import { useWorkflowStore } from "@/stores/workflow";

const props = defineProps<{ nodeId: string; label: string }>();
const workflowStore = useWorkflowStore();
const { showToast } = useToast();
const preparing = ref(false);

async function run(): Promise<void> {
  if (preparing.value || workflowStore.isExecuting || workflowStore.isSaving) return;
  if (!workflowStore.prepareNodeRun(props.nodeId)) return;
  preparing.value = true;
  try {
    const validation = workflowStore.validateWorkflow(props.nodeId);
    const targets = validation.isValid
      ? await workflowStore.validateExecuteTargetsExist(props.nodeId) : validation;
    if (!targets.isValid) {
      showToast(targets.errors.map((error) => `${error.nodeLabel}: ${error.message}`).join("\n"), "error");
      return;
    }
    await workflowStore.executeWorkflow(workflowStore.buildExecutionRequestBody(props.nodeId), props.nodeId);
  } catch (error: unknown) {
    const message = axios.isAxiosError(error) ? error.response?.data?.detail : undefined;
    showToast(typeof message === "string" ? message : error instanceof Error ? error.message : "Unable to run node", "error");
  } finally {
    preparing.value = false;
  }
}
</script>

<template>
  <div
    class="canvas-node-run nodrag nopan absolute top-full left-1/2 -translate-x-1/2 pt-1"
    @pointerdown.stop
    @mousedown.stop
    @click.stop
    @dblclick.stop
    @keydown.stop
  >
    <button
      type="button"
      class="inline-flex h-5 items-center gap-1 rounded-md border border-border bg-background px-1.5 text-[10px] font-medium leading-none text-foreground shadow-sm transition-colors hover:border-primary/40 hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/40 disabled:pointer-events-none disabled:opacity-50"
      :aria-label="`Run to ${label}`"
      title="Run this node and its upstream dependencies"
      :disabled="preparing || workflowStore.isExecuting || workflowStore.isSaving"
      @click="run"
    >
      <Play class="h-2.5 w-2.5" />
      Run
    </button>
  </div>
</template>

<style>
.canvas-node-run {
  opacity: 0;
  pointer-events: none;
  transition: opacity 120ms ease;
}
.vue-flow__node:hover .canvas-node-run,
.canvas-node-run:focus-within {
  opacity: 1;
  pointer-events: auto;
}
</style>
