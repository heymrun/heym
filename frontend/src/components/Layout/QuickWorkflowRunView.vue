<script setup lang="ts">
import type { QuickDrawerRunState, QuickDrawerWorkflowViewModel } from "@/types/quickDrawer";
import QuickWorkflowRunHeader from "@/components/Layout/QuickWorkflowRunHeader.vue";
import QuickWorkflowRunInputs from "@/components/Layout/QuickWorkflowRunInputs.vue";
import QuickWorkflowRunResult from "@/components/Layout/QuickWorkflowRunResult.vue";

interface Props {
  workflow: QuickDrawerWorkflowViewModel;
  inputValues: Record<string, string>;
  runState: QuickDrawerRunState;
  showClose?: boolean;
  showPin?: boolean;
  showEyebrow?: boolean;
  /** Tighter header for the preview bottom sheet. */
  compact?: boolean;
  backLabel?: string;
}

withDefaults(defineProps<Props>(), {
  showClose: true,
  showPin: true,
  showEyebrow: true,
  compact: false,
  backLabel: "Back to workflow list",
});

const emit = defineEmits<{
  back: [];
  close: [];
  goToWorkflow: [event: MouseEvent];
  togglePin: [];
  updateInput: [key: string, value: string];
  run: [];
  stop: [];
}>();
</script>

<template>
  <div
    class="flex h-full min-h-0 flex-1 flex-col bg-card"
    data-testid="quick-workflow-run-panel"
  >
    <QuickWorkflowRunHeader
      :workflow="workflow"
      :show-close="showClose"
      :show-pin="showPin"
      :show-eyebrow="showEyebrow"
      :compact="compact"
      :back-label="backLabel"
      @back="emit('back')"
      @close="emit('close')"
      @go-to-workflow="(event) => emit('goToWorkflow', event)"
      @toggle-pin="emit('togglePin')"
    />

    <div class="min-h-0 flex-1 overflow-y-auto px-5 py-4">
      <div class="space-y-5">
        <QuickWorkflowRunInputs
          :fields="workflow.inputFields"
          :values="inputValues"
          :running="runState.status === 'running'"
          @update-input="(key, value) => emit('updateInput', key, value)"
          @run="emit('run')"
          @stop="emit('stop')"
        />
        <QuickWorkflowRunResult :run-state="runState" />
      </div>
    </div>
  </div>
</template>
