<script setup lang="ts">
import type { FileRunPayload } from "@/types/dashboard";
import type { QuickDrawerRunState } from "@/types/quickDrawer";
import QuickWorkflowRunResult from "@/components/Layout/QuickWorkflowRunResult.vue";
import FileDropInput from "@/components/ui/FileDropInput.vue";

defineProps<{
  payload: FileRunPayload;
  /** The file of the last drop, while it runs and after. */
  file: File | null;
  runState: QuickDrawerRunState;
}>();

const emit = defineEmits<{
  drop: [file: File];
}>();
</script>

<template>
  <div
    class="h-full space-y-3 overflow-auto"
    data-testid="file-run-widget"
  >
    <FileDropInput
      :label="payload.file_label"
      :file="file"
      :allowed-types="payload.allowed_types"
      :max-size-mb="payload.max_size_mb"
      :disabled="runState.status === 'running'"
      @select="(selected) => selected && emit('drop', selected)"
    />
    <QuickWorkflowRunResult
      v-if="runState.status !== 'idle'"
      :run-state="runState"
    />
  </div>
</template>
