<script setup lang="ts">
import { computed, ref } from "vue";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Copy,
  Image as ImageIcon,
  Loader2,
  Workflow,
} from "lucide-vue-next";

import type { QuickDrawerRunState } from "@/types/quickDrawer";
import ImageLightbox from "@/components/ui/ImageLightbox.vue";
import Button from "@/components/ui/Button.vue";
import {
  extractImages,
  formatExecutionTime,
  formatJson,
  latestNodeResults,
  resultToneClasses,
} from "@/components/Layout/quickWorkflowRun";
import { useToast } from "@/composables/useToast";

const props = defineProps<{ runState: QuickDrawerRunState }>();

const { showToast } = useToast();
const selectedImageSrc = ref<string | null>(null);

const resultTone = computed(() => resultToneClasses(props.runState.status));
const outputImages = computed(() =>
  extractImages(props.runState.outputs, props.runState.nodeResults),
);
const visibleNodeResults = computed(() => latestNodeResults(props.runState.nodeResults));

async function copyFinalOutput(): Promise<void> {
  if (!props.runState.outputs) return;

  try {
    await navigator.clipboard.writeText(formatJson(props.runState.outputs));
    showToast("Final output copied", "success");
  } catch {
    showToast("Failed to copy final output", "error");
  }
}
</script>

<template>
  <section class="rounded-3xl border border-border/60 bg-background/80 p-4">
    <div class="flex items-center justify-between gap-3">
      <div>
        <div class="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Progress & Result
        </div>
        <div
          class="mt-2 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium"
          :class="resultTone"
        >
          <Loader2
            v-if="runState.status === 'running'"
            class="h-3.5 w-3.5 animate-spin"
          />
          <CheckCircle2
            v-else-if="runState.status === 'success'"
            class="h-3.5 w-3.5"
          />
          <Clock3
            v-else-if="runState.status === 'pending'"
            class="h-3.5 w-3.5"
          />
          <AlertTriangle
            v-else-if="runState.status === 'error'"
            class="h-3.5 w-3.5"
          />
          <Workflow
            v-else
            class="h-3.5 w-3.5"
          />
          <span class="capitalize">{{ runState.status }}</span>
        </div>
      </div>

      <div
        v-if="runState.executionTimeMs !== null || runState.status === 'pending'"
        class="text-right text-xs text-muted-foreground"
      >
        <div class="font-medium text-foreground">
          {{ formatExecutionTime(runState.executionTimeMs) }}
        </div>
        <div v-if="runState.executionHistoryId">
          History: {{ runState.executionHistoryId }}
        </div>
      </div>
    </div>

    <div
      v-if="runState.status === 'idle'"
      class="mt-4 rounded-2xl border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground"
    >
      Choose a workflow and run it to see progress here.
    </div>

    <div
      v-else
      class="mt-4 space-y-4"
    >
      <div
        v-if="runState.errorMessage"
        class="rounded-2xl border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm text-destructive"
      >
        {{ runState.errorMessage }}
      </div>

      <div
        v-if="visibleNodeResults.length > 0"
        class="space-y-2"
      >
        <div class="text-sm font-medium text-foreground">
          Step Progress
        </div>
        <div class="space-y-2">
          <div
            v-for="nodeResult in visibleNodeResults"
            :key="`${nodeResult.node_id}-${nodeResult.status}`"
            class="rounded-2xl border border-border/60 bg-card/70 px-3 py-3"
          >
            <div class="flex items-center justify-between gap-3">
              <div class="min-w-0">
                <div class="truncate text-sm font-medium text-foreground">
                  {{ nodeResult.node_label }}
                </div>
                <div class="mt-0.5 text-xs text-muted-foreground">
                  {{ nodeResult.node_type }}
                </div>
              </div>
              <div class="text-right">
                <div
                  class="text-xs font-medium capitalize"
                  :class="{
                    'text-success': nodeResult.status === 'success',
                    'text-destructive': nodeResult.status === 'error',
                    'text-warning': nodeResult.status === 'pending',
                    'text-primary': nodeResult.status === 'running',
                    'text-muted-foreground': nodeResult.status === 'skipped',
                  }"
                >
                  {{ nodeResult.status }}
                </div>
                <div class="text-[11px] text-muted-foreground">
                  {{ formatExecutionTime(nodeResult.execution_time_ms) }}
                </div>
              </div>
            </div>
            <div
              v-if="nodeResult.error"
              class="mt-2 rounded-xl bg-destructive/10 px-3 py-2 text-xs text-destructive"
            >
              {{ nodeResult.error }}
            </div>
          </div>
        </div>
      </div>

      <div
        v-if="outputImages.length > 0"
        class="space-y-2"
      >
        <div class="flex items-center gap-2 text-sm font-medium text-foreground">
          <ImageIcon class="h-4 w-4 text-primary" />
          Images
        </div>
        <div class="grid grid-cols-2 gap-3">
          <button
            v-for="imageSrc in outputImages"
            :key="imageSrc"
            type="button"
            class="overflow-hidden rounded-2xl border border-border/60 bg-muted/20 transition-colors hover:border-primary/40"
            @click="selectedImageSrc = imageSrc"
          >
            <img
              :src="imageSrc"
              alt="Workflow output image"
              class="h-32 w-full object-cover"
            >
          </button>
        </div>
      </div>

      <div
        v-if="runState.outputs"
        class="space-y-2"
      >
        <div class="flex items-center justify-between gap-3">
          <div class="text-sm font-medium text-foreground">
            Final Output
          </div>
          <Button
            variant="outline"
            size="sm"
            @click="copyFinalOutput"
          >
            <Copy class="h-4 w-4" />
            Copy
          </Button>
        </div>
        <pre class="max-h-64 overflow-auto rounded-2xl border border-border/60 bg-slate-950 px-4 py-3 text-xs text-slate-100">{{ formatJson(runState.outputs) }}</pre>
      </div>
    </div>

    <ImageLightbox
      :src="selectedImageSrc"
      alt="Quick drawer output image"
      @close="selectedImageSrc = null"
    />
  </section>
</template>
