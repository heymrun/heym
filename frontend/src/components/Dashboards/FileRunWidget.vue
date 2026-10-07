<script setup lang="ts">
import { ref } from "vue";

import type { FileRunPayload } from "@/types/dashboard";
import type { QuickDrawerRunState } from "@/types/quickDrawer";
import FileRunWidgetView from "@/components/Dashboards/FileRunWidgetView.vue";
import { fileRunState } from "@/components/Layout/quickWorkflowRun";
import { dashboardApi, fileIntakeApi, getErrorDetail } from "@/services/api";

const props = defineProps<{
  widgetId: string;
  payload: FileRunPayload;
}>();

function idle(): QuickDrawerRunState {
  return {
    status: "idle",
    executionId: null,
    outputs: null,
    executionTimeMs: null,
    executionHistoryId: null,
    errorMessage: null,
    nodeResults: [],
    startedAt: null,
  };
}

const file = ref<File | null>(null);
// The last result stays in this page view; other viewers do not see it.
const runState = ref<QuickDrawerRunState>(idle());

async function onDrop(dropped: File): Promise<void> {
  file.value = dropped;
  const startedAt = Date.now();
  runState.value = { ...idle(), status: "running", startedAt };
  try {
    const slot = await dashboardApi.createFileRunSlot(props.widgetId);
    runState.value = fileRunState(await fileIntakeApi.upload(slot.upload_url, dropped), startedAt);
  } catch (error) {
    runState.value = {
      ...runState.value,
      status: "error",
      errorMessage: getErrorDetail(error, "The file could not be run"),
    };
  }
}

</script>

<template>
  <FileRunWidgetView
    :payload="payload"
    :file="file"
    :run-state="runState"
    @drop="onDrop"
  />
</template>
