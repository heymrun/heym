<script setup lang="ts">
import { storeToRefs } from "pinia";

import QuickWorkflowRunView from "@/components/Layout/QuickWorkflowRunView.vue";
import { useQuickDrawerStore } from "@/stores/quickDrawer";

interface Props {
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
}>();

const quickDrawerStore = useQuickDrawerStore();
const { currentInputValues, runState, selectedWorkflow } = storeToRefs(quickDrawerStore);
</script>

<template>
  <QuickWorkflowRunView
    v-if="selectedWorkflow"
    :workflow="selectedWorkflow"
    :input-values="currentInputValues"
    :run-state="runState"
    :show-close="showClose"
    :show-pin="showPin"
    :show-eyebrow="showEyebrow"
    :compact="compact"
    :back-label="backLabel"
    @back="emit('back')"
    @close="emit('close')"
    @go-to-workflow="(event) => emit('goToWorkflow', event)"
    @toggle-pin="quickDrawerStore.togglePin(selectedWorkflow.id)"
    @update-input="(key, value) => quickDrawerStore.updateInputValue(key, value)"
    @run="quickDrawerStore.runSelectedWorkflow()"
    @stop="quickDrawerStore.stopSelectedWorkflowExecution()"
  />
</template>
