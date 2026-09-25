<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import { Copy, X } from "lucide-vue-next";
import type { SpanInput } from "@/components/Panels/executionSpanInput";
import type { SpanItem } from "@/components/Panels/executionTimeline";
import {
  formatModelRoutingLabel,
  formatSpanCost,
  formatTimelineMs,
  isSpanSettled,
  splitSpanOutput,
} from "@/components/Panels/executionTimeline";
import ExecutionSpanImages from "@/components/Panels/ExecutionSpanImages.vue";
import ExecutionSpanNavigator from "@/components/Panels/ExecutionSpanNavigator.vue";
import JsonTree from "@/components/ui/JsonTree.vue";
import { getOutputImageSrcs, maskImageDataForDisplay } from "@/lib/executionImages";

const props = defineProps<{
  span: SpanItem;
  /** Null until the input has arrived; the section stays hidden meanwhile. */
  input: SpanInput | null;
  /** Every image of the run in execution order, for the lightbox gallery. */
  runImageSrcs: string[];
  /** Node labels of the timeline's spans in start order, for the jump menu. */
  spanLabels: string[];
  /** Position of this span in `spanLabels`; -1 when not listed. */
  spanIndex: number;
  /** USD cost of the span's trace when its model is priced. */
  costUsd: string | null;
}>();
const emit = defineEmits<{
  close: [];
  openTrace: [event: MouseEvent];
  previous: [event: MouseEvent];
  next: [event: MouseEvent];
  jump: [index: number];
}>();
const traceIdCopied = ref(false);
// Live ticks replace `span` every frame but keep its output reference, so the scans below stay cached.
const settledOutput = computed((): unknown => (isSpanSettled(props.span) ? props.span.output : null));
const outputParts = computed(() => {
  const parts = splitSpanOutput(settledOutput.value);
  return { message: parts.message, details: maskImageDataForDisplay(parts.details) };
});
const outputImageSrcs = computed(() => getOutputImageSrcs(settledOutput.value));
const inputValue = computed(() =>
  props.input?.value ? maskImageDataForDisplay(props.input.value) : null,
);
const hasJsonColumn = computed(() => props.input !== null || outputParts.value.details !== null);
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
      <div class="flex shrink-0 items-center gap-0.5">
        <ExecutionSpanNavigator
          :labels="spanLabels"
          :index="spanIndex"
          @previous="emit('previous', $event)"
          @next="emit('next', $event)"
          @jump="emit('jump', $event)"
        />
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
    </div>
    <div class="grid grid-cols-2 gap-x-4 gap-y-1 px-2 py-2 text-[10px] sm:grid-cols-3 lg:grid-cols-6">
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
      <div v-if="span.tokenUsage">
        <span class="text-muted-foreground">Tokens</span><div
          class="font-mono"
          data-testid="span-token-usage"
        >
          {{ span.tokenUsage.total.toLocaleString() }}<span
            v-if="span.tokenUsage.prompt !== null && span.tokenUsage.completion !== null"
            class="text-muted-foreground"
          > · {{ span.tokenUsage.prompt.toLocaleString() }} in / {{ span.tokenUsage.completion.toLocaleString() }} out</span>
        </div>
      </div>
      <div v-if="costUsd !== null">
        <span class="text-muted-foreground">Cost</span><div
          class="font-mono"
          data-testid="span-cost"
        >
          {{ formatSpanCost(costUsd) }}
        </div>
      </div>
      <div v-if="span.modelRouting">
        <span class="text-muted-foreground">Model</span><div
          class="font-medium"
          data-testid="span-model-routing"
        >
          {{ formatModelRoutingLabel(span.modelRouting) }}
        </div>
      </div>
    </div>
    <div
      v-if="span.modelRouting && span.modelRouting.calls.length > 1"
      class="mx-2 mb-2 space-y-0.5 rounded border border-border/40 px-2 py-1.5 text-[10px]"
    >
      <div class="text-muted-foreground">
        Routed per turn
      </div>
      <div
        v-for="(call, index) in span.modelRouting.calls"
        :key="index"
        class="flex items-center gap-2 font-mono"
      >
        <span class="text-muted-foreground">{{ index + 1 }}.</span><span>{{ call.model }}</span><span
          v-if="call.option"
          class="text-muted-foreground"
        >{{ call.option }}</span><span
          v-if="call.fallback"
          class="text-amber-600"
        >fallback</span>
      </div>
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
        type="button"
        class="text-primary hover:underline"
        @click="emit('openTrace', $event)"
      >
        Open trace
      </button>
    </div>
    <!-- JSON always sits in the left column; a reply text reads as the message on the right. -->
    <div
      v-if="hasJsonColumn || outputParts.message !== null"
      class="grid gap-x-4 gap-y-3 border-t border-border/20 px-2 py-2"
      :class="{ 'md:grid-cols-2': hasJsonColumn && outputParts.message !== null }"
    >
      <div
        v-if="hasJsonColumn"
        class="min-w-0 space-y-3"
      >
        <section
          v-if="input"
          data-testid="execution-span-input"
        >
          <div class="mb-1 text-[10px] font-medium text-muted-foreground">
            Input
          </div>
          <div
            v-if="input.note"
            class="mb-1 text-[10px] text-muted-foreground"
          >
            {{ input.note }}
          </div>
          <div
            v-if="inputValue"
            class="select-text text-[10px] font-mono"
          >
            <JsonTree
              :data="inputValue"
              :root-expanded="true"
              :auto-expand-depth="1"
            />
          </div>
        </section>
        <section
          v-if="outputParts.details !== null"
          data-testid="execution-span-output"
        >
          <div class="mb-1 text-[10px] font-medium text-muted-foreground">
            Output
          </div>
          <ExecutionSpanImages
            v-if="outputImageSrcs.length > 0"
            :srcs="outputImageSrcs"
            :gallery="runImageSrcs"
          />
          <div class="select-text">
            <div
              v-if="typeof outputParts.details === 'object'"
              class="text-[10px] font-mono"
            >
              <JsonTree
                :data="outputParts.details"
                :root-expanded="true"
                :auto-expand-depth="1"
              />
            </div>
            <pre
              v-else
              class="whitespace-pre-wrap break-words text-[10px] font-mono"
            >{{ String(outputParts.details) }}</pre>
          </div>
        </section>
      </div>
      <section
        v-if="outputParts.message !== null"
        class="min-w-0"
        :class="{ 'md:border-l md:border-border/20 md:pl-4': hasJsonColumn }"
        data-testid="execution-span-message"
      >
        <div class="mb-1 text-[10px] font-medium text-muted-foreground">
          Message
        </div>
        <div
          v-if="outputParts.message"
          class="select-text whitespace-pre-wrap break-words text-[11px] leading-relaxed"
        >
          {{ outputParts.message }}
        </div>
        <div
          v-else
          class="text-[10px] text-muted-foreground"
        >
          Empty reply.
        </div>
      </section>
    </div>
  </div>
</template>
