<script setup lang="ts">
import { onMounted, ref } from "vue";
import { AlertTriangle, Loader2, X } from "lucide-vue-next";

import type { RagIngestJob } from "@/types/ragIngest";

import Button from "@/components/ui/Button.vue";
import { useIngestJobPolling } from "@/lib/ragIngestJobs";
import { formatFileSize } from "@/lib/utils";
import { vectorStoresApi } from "@/services/api";

/** A store's uploads Heym is still reading in the background, or failed to read. */
const props = defineProps<{ storeId: string }>();
const emit = defineEmits<{ finished: [] }>();

const polling = useIngestJobPolling(
  async () => (await vectorStoresApi.listIngestJobs(props.storeId)).jobs,
  () => emit("finished"),
);
const { jobs } = polling;
const dismissing = ref<string | null>(null);
const dismissError = ref("");

function label(job: RagIngestJob): string {
  if (job.status === "failed") return job.error ?? "Heym could not read this file.";
  if (job.status === "queued") return "Waiting its turn";
  return job.kind === "audio" ? "Transcribing" : "Reading scanned pages";
}

async function dismiss(job: RagIngestJob): Promise<void> {
  dismissing.value = job.id;
  dismissError.value = "";
  try {
    await vectorStoresApi.dismissIngestJob(props.storeId, job.id);
    jobs.value = jobs.value.filter((item) => item.id !== job.id);
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    dismissError.value = err.response?.data?.detail || "Could not dismiss this file";
  } finally {
    dismissing.value = null;
  }
}

defineExpose({ refresh: polling.refresh });
onMounted(() => void polling.refresh());
</script>

<template>
  <div
    v-if="jobs.length > 0"
    class="space-y-1"
    data-testid="vector-store-ingest-jobs"
  >
    <div
      v-for="job in jobs"
      :key="job.id"
      class="flex items-center gap-2 rounded-lg border p-3 text-sm"
      :class="job.status === 'failed' ? 'border-destructive/40 bg-destructive/5' : 'bg-muted/30'"
    >
      <AlertTriangle
        v-if="job.status === 'failed'"
        class="h-4 w-4 flex-shrink-0 text-destructive"
      />
      <Loader2
        v-else
        class="h-4 w-4 flex-shrink-0 animate-spin text-muted-foreground"
      />
      <span class="truncate font-medium">{{ job.filename }}</span>
      <span class="flex-shrink-0 text-xs text-muted-foreground">{{ formatFileSize(job.file_size) }}</span>
      <span
        class="min-w-0 flex-1 truncate text-xs"
        :class="job.status === 'failed' ? 'text-destructive' : 'text-muted-foreground'"
        :title="label(job)"
      >{{ label(job) }}</span>
      <Button
        v-if="job.status === 'failed'"
        variant="ghost"
        size="icon"
        class="h-6 w-6 flex-shrink-0 text-muted-foreground"
        :loading="dismissing === job.id"
        title="Dismiss"
        @click="dismiss(job)"
      >
        <X class="h-3 w-3" />
      </Button>
    </div>
    <p
      v-if="dismissError"
      class="text-xs text-destructive"
    >
      {{ dismissError }}
    </p>
  </div>
</template>
