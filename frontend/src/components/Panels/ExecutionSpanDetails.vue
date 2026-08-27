<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import { Copy, X } from "lucide-vue-next";
import type { SpanItem } from "@/components/Panels/executionTimeline";
import { formatTimelineMs } from "@/components/Panels/executionTimeline";
import JsonTree from "@/components/ui/JsonTree.vue";

const props = defineProps<{ span: SpanItem }>();
const emit = defineEmits<{ close: []; openTrace: [event: MouseEvent] }>();
const traceIdCopied = ref(false);
// Objects/arrays render through JsonTree below; this is only the scalar fallback.
const outputText = computed(() => String(props.span.output));
let traceIdCopiedTimer: ReturnType<typeof setTimeout> | null = null;

async function copyTraceId(): Promise<void> {
  if (!props.span.traceId) return;
  try {
    await navigator.clipboard.writeText(props.span.traceId);
    traceIdCopied.value = true;
    if (traceIdCopiedTimer !== null) clearTimeout(traceIdCopiedTimer);
    traceIdCopiedTimer = setTimeout(() => { traceIdCopied.value = false; }, 1500);
  } catch { traceIdCopied.value = false; }
}

onBeforeUnmount(() => {
  if (traceIdCopiedTimer !== null) {
    clearTimeout(traceIdCopiedTimer);
    traceIdCopiedTimer = null;
  }
});
</script>

<template>
  <div
    class="border-t border-border/30 bg-background/60"
    data-testid="execution-span-details"
  >
    <div class="flex items-center justify-between gap-2 px-2 py-1.5 border-b border-border/20">
      <div class="flex min-w-0 items-center gap-2">
        <span class="truncate text-xs font-medium">{{ span.nodeLabel }}</span><span class="text-[10px] text-muted-foreground">{{ span.nodeType }}</span>
      </div>
      <button
        type="button"
        class="inline-flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-muted"
        title="Close span details"
        aria-label="Close span details"
        @click="emit('close')"
      >
        <X class="h-3.5 w-3.5" />
      </button>
    </div>
    <div class="grid grid-cols-2 gap-x-4 gap-y-1 px-2 py-2 text-[10px] sm:grid-cols-3">
      <div>
        <span class="text-muted-foreground">Status</span><div class="font-medium capitalize">
          {{ span.status }}
        </div>
      </div>
      <div>
        <span class="text-muted-foreground">Duration</span><div class="font-mono">
          {{ formatTimelineMs(span.durationMs) }}
        </div>
      </div>
      <div><span class="text-muted-foreground">Attempts</span><div>{{ span.retryFinalAttempt ?? 1 }}<span v-if="span.retryMaxAttempts"> / {{ span.retryMaxAttempts }}</span></div></div>
    </div>
    <div
      v-if="span.error"
      class="mx-2 mb-2 rounded border border-destructive/30 bg-destructive/5 px-2 py-1.5 text-[10px] text-destructive"
    >
      <span class="font-medium">Error:</span> {{ span.error }}
    </div>
    <div
      v-else-if="span.retryLastError"
      class="mx-2 mb-2 rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1.5 text-[10px] text-amber-700"
    >
      <span class="font-medium">Previous attempt error:</span> {{ span.retryLastError }}
    </div>
    <div
      v-if="span.traceId"
      class="flex items-center gap-1 px-2 pb-2 text-[10px]"
    >
      <span class="text-muted-foreground">Trace</span><code class="min-w-0 truncate font-mono">{{ span.traceId }}</code><button
        type="button"
        class="inline-flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:bg-muted"
        :title="traceIdCopied ? 'Copied' : 'Copy trace ID'"
        @click="copyTraceId"
      >
        <Copy class="h-3 w-3" />
      </button><button
        v-if="span.nodeType === 'llm' || span.nodeType === 'agent'"
        type="button"
        class="text-primary hover:underline"
        @click="emit('openTrace', $event)"
      >
        Open trace
      </button>
    </div>
    <div class="flex-1 min-h-0 overflow-auto border-t border-border/20 px-2 py-2">
      <div class="mb-1 text-[10px] font-medium text-muted-foreground">
        Output
      </div><div
        v-if="span.isHitlWait"
        class="text-[10px] text-muted-foreground"
      >
        Output is available after this wait completes.
      </div><div
        v-else-if="span.output !== null && typeof span.output === 'object'"
        class="text-[10px] font-mono"
      >
        <JsonTree
          :data="span.output"
          :root-expanded="true"
          :auto-expand-depth="1"
        />
      </div><pre
        v-else
        class="whitespace-pre-wrap break-words text-[10px] font-mono"
      >{{ outputText }}</pre>
    </div>
  </div>
</template>
