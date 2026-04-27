<script setup lang="ts">
import { ref, watch } from "vue";

import type { WorkflowVersion } from "@/types/workflow";
import ReadonlyCanvasPreview from "@/components/Canvas/ReadonlyCanvasPreview.vue";
import Dialog from "@/components/ui/Dialog.vue";

interface Props {
  open: boolean;
  version: WorkflowVersion | null;
  selectedNode: Record<string, unknown> | null;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "update:selectedNode", value: Record<string, unknown> | null): void;
}>();

const flowKey = ref(0);

watch(
  () => props.open,
  (open) => {
    if (open) {
      flowKey.value += 1;
    }
  },
);
</script>

<template>
  <Dialog
    :open="open"
    :title="version ? `Version ${version.version_number} Preview` : 'Preview'"
    size="4xl"
    :close-on-escape="false"
    @close="emit('close')"
  >
    <div class="h-[65vh]">
      <ReadonlyCanvasPreview
        :flow-key="flowKey"
        :nodes="version?.nodes ?? []"
        :edges="version?.edges ?? []"
        :selected-node="selectedNode"
        empty-message="No nodes in this version"
        @update:selected-node="emit('update:selectedNode', $event)"
      />
    </div>
  </Dialog>
</template>
