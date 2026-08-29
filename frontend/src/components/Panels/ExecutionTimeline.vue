<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ExternalLink, Eye, EyeOff } from "lucide-vue-next";

import type {
  SpanItem,
  SpanRow,
  TimelineEntry,
  TimelineSelectPayload,
} from "@/components/Panels/executionTimeline";
import {
  buildTimelineModel,
  formatTimelineMs,
  getTimelineRowKey,
  getServerAlignedNowMs,
  LIVE_TIMELINE_REFRESH_INTERVAL_MS,
  summarizeTimelineModel,
} from "@/components/Panels/executionTimeline";
import ExecutionSpanDetails from "@/components/Panels/ExecutionSpanDetails.vue";

interface Props {
  nodeResults: TimelineEntry[];
  totalTimeMs: number;
  subAgentLabelToParentId: Map<string, string>;
  serverClockOffsetMs?: number;
}

const props = defineProps<Props>();
const router = useRouter();

const emit = defineEmits<{
  selectNode: [payload: TimelineSelectPayload];
}>();

const selectedSpan = ref<SpanItem | null>(null);
const detailsOpen = ref(false);

function emitSelectNode(payload: TimelineSelectPayload, event: MouseEvent): void {
  event.stopPropagation();
  emit("selectNode", payload);
}

function onSpanClick(span: SpanItem, event: MouseEvent): void {
  // Clicking swaps the rows out for the details panel, so the span unmounts and
  // mouseleave never fires — clear the hover state or the tooltip stays stuck.
  hoveredSpan.value = null;
  selectedSpan.value = span;
  detailsOpen.value = true;
  emitSelectNode({ nodeId: span.nodeId, resultListIndex: span.resultListIndex }, event);
}

function onSpanKeydown(span: SpanItem, event: KeyboardEvent): void {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  onSpanClick(span, event as unknown as MouseEvent);
}

function closeDetails(): void {
  detailsOpen.value = false;
  selectedSpan.value = null;
}

function isTraceableSpan(span: SpanItem): boolean {
  return Boolean(span.traceId) && (span.nodeType === "llm" || span.nodeType === "agent");
}

function openTraceInNewTab(span: SpanItem, event: MouseEvent): void {
  event.stopPropagation();
  if (!isTraceableSpan(span) || !span.traceId) {
    return;
  }
  const href = router.resolve({
    path: "/",
    query: { tab: "traces", traceId: span.traceId },
  }).href;
  window.open(href, "_blank", "noopener,noreferrer");
}

function onRowLabelClick(row: SpanRow, event: MouseEvent): void {
  emitSelectNode({ nodeId: row.nodeId, resultListIndex: null }, event);
}

let timelineClockOffsetMs = props.serverClockOffsetMs ?? 0;
let timelineClockAnchorMs = getServerAlignedNowMs(Date.now(), timelineClockOffsetMs);
let timelineClockMonotonicAnchorMs = performance.now();

function synchronizeTimelineClock(): void {
  timelineClockOffsetMs = props.serverClockOffsetMs ?? 0;
  timelineClockAnchorMs = getServerAlignedNowMs(Date.now(), timelineClockOffsetMs);
  timelineClockMonotonicAnchorMs = performance.now();
}

function getTimelineNowMs(): number {
  if (timelineClockOffsetMs !== (props.serverClockOffsetMs ?? 0)) {
    synchronizeTimelineClock();
  }
  return timelineClockAnchorMs + (performance.now() - timelineClockMonotonicAnchorMs);
}

const timelineNowMs = ref(getTimelineNowMs());
let timelineNowTimer: ReturnType<typeof setInterval> | null = null;

const hasLiveHitlWait = computed(() =>
  props.nodeResults.some(
    (result) =>
      result.status === "pending" &&
      (result.node_type === "agent" ||
        result.node_type === "codex" ||
        Boolean(result.metadata?.hitl) ||
        Boolean(result.metadata?.codex)),
  ),
);
const hasLiveRunningSpan = computed(() =>
  props.nodeResults.some((result) => result.status === "running"),
);
const hasLiveTimelineSpan = computed(
  () => hasLiveHitlWait.value || hasLiveRunningSpan.value,
);

function syncTimelineNowTimer(): void {
  if (hasLiveTimelineSpan.value) {
    timelineNowMs.value = getTimelineNowMs();
    if (timelineNowTimer === null) {
      timelineNowTimer = setInterval(() => {
        timelineNowMs.value = getTimelineNowMs();
      }, LIVE_TIMELINE_REFRESH_INTERVAL_MS);
    }
    return;
  }
  if (timelineNowTimer !== null) {
    clearInterval(timelineNowTimer);
    timelineNowTimer = null;
  }
}

onMounted(() => {
  syncTimelineNowTimer();
});

onBeforeUnmount(() => {
  if (timelineNowTimer !== null) {
    clearInterval(timelineNowTimer);
    timelineNowTimer = null;
  }
});

watch(hasLiveTimelineSpan, () => {
  syncTimelineNowTimer();
});
watch(
  () => props.serverClockOffsetMs,
  () => {
    synchronizeTimelineClock();
    timelineNowMs.value = getTimelineNowMs();
  },
);

const fullTimelineModel = computed(() =>
  buildTimelineModel(
    props.nodeResults,
    props.totalTimeMs,
    props.subAgentLabelToParentId,
    { nowMs: timelineNowMs.value },
  ),
);
const timelineSummary = computed(() =>
  summarizeTimelineModel(fullTimelineModel.value.rows, fullTimelineModel.value.timeWindow),
);

const rows = computed(() => fullTimelineModel.value.rows);
const hiddenRowKeys = ref<Set<string>>(new Set());
const visibleNodeResults = computed(() =>
  props.nodeResults.filter(
    (result) =>
      !hiddenRowKeys.value.has(getTimelineRowKey(result, props.subAgentLabelToParentId)),
  ),
);
const shouldZoomVisibleRange = computed(
  () => hiddenRowKeys.value.size > 0 && visibleNodeResults.value.length > 0,
);
const timelineModel = computed(() =>
  buildTimelineModel(
    visibleNodeResults.value,
    props.totalTimeMs,
    props.subAgentLabelToParentId,
    {
      preserveTotalTime: !shouldZoomVisibleRange.value,
      nowMs: timelineNowMs.value,
    },
  ),
);
const visibleRows = computed(() => timelineModel.value.rows);
const hiddenRows = computed(() =>
  rows.value.filter((row) => hiddenRowKeys.value.has(row.key)),
);

watch(
  rows,
  (nextRows) => {
    const validKeys = new Set(nextRows.map((row) => row.key));
    hiddenRowKeys.value = new Set(
      [...hiddenRowKeys.value].filter((rowKey) => validKeys.has(rowKey)),
    );
  },
  { flush: "sync" },
);

// selectedSpan is a snapshot of a span from the previous rows computation. When
// rows recomputes (new results arrive, rows hidden/shown), the old object is stale,
// so re-resolve it by key against the fresh rows — or close if it no longer exists.
watch(
  rows,
  (nextRows) => {
    if (!selectedSpan.value) return;
    const replacement = nextRows
      .flatMap((row) => row.spans)
      .find((span) => span.key === selectedSpan.value?.key);
    if (replacement) {
      selectedSpan.value = replacement;
    } else {
      closeDetails();
    }
  },
  { flush: "sync" },
);

const timeMarkers = computed(() => {
  const totalMs = timelineModel.value.timeWindow.totalMs;
  if (totalMs <= 0) return [];
  return [0, 25, 50, 75, 100].map((pct) => ({
    pct,
    label: formatTimelineMs((totalMs * pct) / 100),
  }));
});
const rowHeightPx = computed(() => {
  const count = visibleRows.value.length;
  if (count <= 0) return 26;
  return Math.min(Math.max(Math.floor(220 / count), 26), 44);
});
const topLevelBarHeightPx = computed(() =>
  Math.min(Math.max(rowHeightPx.value - 10, 15), 24),
);
const childBarHeightPx = computed(() =>
  Math.min(Math.max(rowHeightPx.value - 14, 11), 20),
);

const hoveredSpan = ref<SpanItem | null>(null);
const tooltipX = ref(0);
const tooltipY = ref(0);

function onBarEnter(span: SpanItem, event: MouseEvent): void {
  hoveredSpan.value = span;
  tooltipX.value = event.clientX;
  tooltipY.value = event.clientY;
}

function onBarMove(event: MouseEvent): void {
  tooltipX.value = event.clientX;
  tooltipY.value = event.clientY;
}

function onBarLeave(): void {
  hoveredSpan.value = null;
}

function retrySummaryText(span: SpanItem): string | null {
  if (span.retryFailedAttempts <= 0 || span.retryFinalAttempt === null) {
    return null;
  }

  const maxAttemptsSuffix =
    span.retryMaxAttempts !== null ? `/${span.retryMaxAttempts}` : "";
  const retryLabel =
    span.retryFailedAttempts === 1
      ? "1 retry"
      : `${span.retryFailedAttempts} retries`;
  return `attempt ${span.retryFinalAttempt}${maxAttemptsSuffix} · ${retryLabel}`;
}

function toggleRowVisibility(rowKey: string): void {
  const next = new Set(hiddenRowKeys.value);
  if (next.has(rowKey)) {
    next.delete(rowKey);
  } else {
    next.add(rowKey);
  }
  hiddenRowKeys.value = next;
}

function showAllRows(): void {
  hiddenRowKeys.value = new Set();
}
</script>

<template>
  <div class="flex flex-col border-t bg-muted/5 select-none overflow-hidden">
    <div
      v-show="!detailsOpen"
      class="flex items-center gap-3 px-2 py-1.5 border-b border-border/20 bg-background/40 text-[10px] text-muted-foreground"
    >
      <span class="font-medium text-foreground/80">Execution summary</span>
      <span>{{ formatTimelineMs(timelineSummary.totalDurationMs) }}</span>
      <span>{{ timelineSummary.spanCount }} spans</span>
      <span
        v-if="timelineSummary.failedSpanCount > 0"
        class="text-destructive"
      >
        {{ timelineSummary.failedSpanCount }} failed
      </span>
      <span
        v-if="timelineSummary.retryCount > 0"
        class="text-amber-600"
      >
        {{ timelineSummary.retryCount }} retries
      </span>
      <span
        v-if="timelineSummary.failedSpanCount === 0 && timelineSummary.retryCount === 0"
        class="text-emerald-600"
      >
        Healthy
      </span>
    </div>
    <div
      v-show="!detailsOpen"
      class="flex h-5 border-b border-border/30 overflow-hidden"
    >
      <div class="w-[176px] shrink-0 border-r border-border/20" />
      <div class="flex-1 relative overflow-hidden">
        <template
          v-for="marker in timeMarkers"
          :key="marker.pct"
        >
          <div
            class="absolute top-0 h-full flex items-center pointer-events-none"
            :style="{
              left: `${marker.pct}%`,
              transform: marker.pct === 100 ? 'translateX(-100%)' : marker.pct > 0 ? 'translateX(-50%)' : 'none',
            }"
          >
            <span class="text-[9px] text-muted-foreground/40 leading-none px-0.5 font-mono">
              {{ marker.label }}
            </span>
          </div>
          <div
            class="absolute top-0 h-full w-px bg-border/25 pointer-events-none"
            :style="{ left: `${marker.pct}%` }"
          />
        </template>
      </div>
    </div>

    <div
      v-if="hiddenRows.length > 0"
      v-show="!detailsOpen"
      class="flex items-center gap-2 px-2 py-1.5 border-b border-border/20 bg-muted/10 overflow-x-auto"
    >
      <span class="text-[10px] uppercase tracking-wide text-muted-foreground shrink-0">
        Hidden
      </span>
      <button
        v-for="row in hiddenRows"
        :key="`hidden-${row.key}`"
        type="button"
        class="inline-flex items-center gap-1.5 h-6 px-2 rounded-md border border-border/40 bg-background/60 text-[11px] text-muted-foreground hover:text-foreground hover:border-border transition-colors shrink-0"
        :title="`Show ${row.nodeLabel}`"
        @click="toggleRowVisibility(row.key)"
      >
        <EyeOff class="w-3 h-3" />
        <span class="truncate max-w-[140px]">{{ row.nodeLabel }}</span>
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 h-6 px-2 rounded-md border border-border/40 bg-background/60 text-[11px] text-muted-foreground hover:text-foreground hover:border-border transition-colors shrink-0"
        @click="showAllRows"
      >
        Show all
      </button>
    </div>

    <template v-if="detailsOpen && selectedSpan">
      <ExecutionSpanDetails
        class="flex-1 min-h-0 overflow-y-auto"
        :span="selectedSpan"
        @close="closeDetails"
        @open-trace="openTraceInNewTab(selectedSpan, $event)"
      />
    </template>
    <div
      v-else
      class="flex-1 min-h-0 overflow-y-auto"
    >
      <div
        v-for="row in visibleRows"
        :key="row.key"
        :data-testid="`execution-timeline-row-${row.nodeId}`"
        class="flex items-center hover:bg-muted/20 group"
        :style="{ height: `${rowHeightPx}px` }"
      >
        <div
          class="w-[176px] shrink-0 text-[11px] text-muted-foreground/70 group-hover:text-foreground/80 transition-colors border-r border-border/20 font-mono flex items-center gap-1.5 cursor-pointer pr-1"
          :title="row.nodeLabel"
          @click="onRowLabelClick(row, $event)"
        >
          <span
            v-if="row.depth === 1"
            class="text-border/60 shrink-0 pl-2 pr-1 text-[10px]"
          >└</span>
          <span
            v-else
            class="pl-2 pr-1"
          />
          <span class="truncate flex-1 min-w-0">{{ row.nodeLabel }}</span>
          <button
            type="button"
            class="inline-flex h-5 w-5 items-center justify-center rounded-sm text-muted-foreground/60 hover:text-foreground hover:bg-muted/50 transition-colors shrink-0"
            :title="`Hide ${row.nodeLabel}`"
            @click.stop="toggleRowVisibility(row.key)"
          >
            <Eye class="w-3.5 h-3.5" />
          </button>
        </div>

        <div class="flex-1 relative h-full flex items-center overflow-hidden">
          <div
            v-for="marker in timeMarkers"
            :key="`tl-${row.key}-${marker.pct}`"
            class="absolute top-0 h-full w-px bg-border/10 pointer-events-none"
            :style="{ left: `${marker.pct}%` }"
          />

          <template
            v-for="span in row.spans"
            :key="span.key"
          >
            <div
              class="trace-span absolute rounded-sm border cursor-pointer transition-opacity overflow-hidden"
              :data-testid="`execution-timeline-span-${span.nodeId}-${span.resultListIndex}`"
              role="button"
              tabindex="0"
              :aria-label="`Open details for ${span.nodeLabel}`"
              :aria-pressed="selectedSpan?.key === span.key"
              :class="[
                selectedSpan?.key === span.key
                  ? 'ring-2 ring-primary ring-offset-1 ring-offset-background'
                  : '',
                span.status === 'running' ? 'trace-span-running' : '',
                span.isHitlWait
                  ? 'opacity-80 group-hover:opacity-95 hitl-wait-span'
                  : span.status === 'error'
                    ? 'opacity-90'
                    : 'opacity-70 group-hover:opacity-95',
              ]"
              :style="{
                left: `${span.leftPct}%`,
                width: `${span.widthPct}%`,
                minWidth: '3px',
                height: `${row.depth === 1 ? childBarHeightPx : topLevelBarHeightPx}px`,
                backgroundColor: span.isHitlWait
                  ? undefined
                  : `hsl(var(--${span.colorVar}) / 0.55)`,
                borderColor: `hsl(var(--${span.colorVar}))`,
                borderWidth: span.status === 'error' ? '1.5px' : '1px',
                borderStyle: span.isHitlWait ? 'dashed' : 'solid',
                top: '50%',
                transform: 'translateY(-50%)',
              }"
              @click="onSpanClick(span, $event)"
              @keydown="onSpanKeydown(span, $event)"
              @mouseenter="onBarEnter(span, $event)"
              @mousemove="onBarMove"
              @mouseleave="onBarLeave"
            >
              <button
                v-if="isTraceableSpan(span)"
                type="button"
                class="trace-span-action"
                title="Open trace in new tab"
                @click="openTraceInNewTab(span, $event)"
              >
                <ExternalLink class="w-3 h-3" />
              </button>
              <div
                v-for="(gcSegment, segmentIndex) in span.gcPauseSegments"
                :key="`${span.key}-gc-${segmentIndex}`"
                class="absolute inset-y-0 pointer-events-none"
                :style="{
                  left: `${gcSegment.leftPct}%`,
                  width: `${gcSegment.widthPct}%`,
                  minWidth: '2px',
                  background:
                    'repeating-linear-gradient(135deg, rgb(245 158 11 / 0.9) 0px, rgb(245 158 11 / 0.9) 3px, rgb(251 191 36 / 0.9) 3px, rgb(251 191 36 / 0.9) 6px)',
                  boxShadow: 'inset 0 0 0 1px rgb(120 53 15 / 0.35)',
                }"
              />
              <span
                v-if="span.widthPct > 8 && row.depth === 0"
                class="trace-span-duration"
              >
                {{ span.durationMs >= 1000
                  ? `${(span.durationMs / 1000).toFixed(1)}s`
                  : `${Math.round(span.durationMs)}ms` }}
              </span>
            </div>
          </template>
        </div>
      </div>

      <div
        v-if="visibleRows.length === 0 && hiddenRows.length > 0"
        class="px-3 py-5 text-xs text-muted-foreground flex items-center justify-between gap-3"
      >
        <span>All timeline rows are hidden.</span>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 h-7 px-2 rounded-md border border-border/40 bg-background/60 text-[11px] hover:text-foreground hover:border-border transition-colors shrink-0"
          @click="showAllRows"
        >
          <EyeOff class="w-3.5 h-3.5" />
          Show all rows
        </button>
      </div>
    </div>
  </div>

  <Teleport to="body">
    <div
      v-if="hoveredSpan"
      class="fixed z-[9999] pointer-events-none px-2.5 py-1.5 rounded-md text-xs bg-popover border border-border shadow-lg flex items-center gap-2"
      :style="{ left: `${tooltipX + 14}px`, top: `${tooltipY - 36}px` }"
    >
      <div
        class="w-2 h-2 rounded-full shrink-0"
        :style="{ backgroundColor: `hsl(var(--${hoveredSpan.colorVar}))` }"
      />
      <span class="font-medium text-foreground">
        <template v-if="hoveredSpan.isHitlWait">HITL wait · </template>{{ hoveredSpan.nodeLabel }}<template v-if="!hoveredSpan.isHitlWait && hoveredSpan.occurrenceCount > 1"> #{{ hoveredSpan.occurrence }}</template>
      </span>
      <span class="text-muted-foreground font-mono">
        {{ hoveredSpan.durationMs >= 1000
          ? `${(hoveredSpan.durationMs / 1000).toFixed(2)}s`
          : `${hoveredSpan.durationMs.toFixed(1)}ms` }}
      </span>
      <span class="text-muted-foreground/80 font-mono">
        at {{ hoveredSpan.startOffsetMs >= 1000
          ? `${(hoveredSpan.startOffsetMs / 1000).toFixed(2)}s`
          : `${hoveredSpan.startOffsetMs.toFixed(1)}ms` }}
        <template v-if="hoveredSpan.endOffsetMs > hoveredSpan.startOffsetMs">
          → {{ hoveredSpan.endOffsetMs >= 1000
            ? `${(hoveredSpan.endOffsetMs / 1000).toFixed(2)}s`
            : `${hoveredSpan.endOffsetMs.toFixed(1)}ms` }}
        </template>
      </span>
      <span
        v-if="hoveredSpan.gcPauseMs > 0"
        class="text-amber-600 font-mono"
      >
        GC {{ hoveredSpan.gcPauseMs >= 1000
          ? `${(hoveredSpan.gcPauseMs / 1000).toFixed(2)}s`
          : `${hoveredSpan.gcPauseMs.toFixed(1)}ms` }}
        <template v-if="hoveredSpan.gcPauseCount > 1">·{{ hoveredSpan.gcPauseCount }}x</template>
      </span>
      <span
        v-if="retrySummaryText(hoveredSpan)"
        class="text-sky-600 font-mono"
      >
        {{ retrySummaryText(hoveredSpan) }}
      </span>
    </div>
  </Teleport>
</template>

<style scoped>
.trace-span {
  overflow: visible;
}

.trace-span-running {
  animation: trace-span-running-heartbeat 1.2s ease-in-out infinite;
}

@keyframes trace-span-running-heartbeat {
  0%,
  100% {
    opacity: 0.55;
    box-shadow: 0 0 0 0 hsl(var(--success) / 0.45);
  }
  50% {
    opacity: 1;
    box-shadow: 0 0 0 4px hsl(var(--success) / 0);
  }
}

.trace-span-duration {
  position: absolute;
  left: 4px;
  top: 50%;
  z-index: 1;
  transform: translateY(-50%);
  padding: 0 3px;
  border-radius: 2px;
  background: hsl(var(--background) / 0.55);
  color: hsl(var(--foreground) / 0.88);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 9px;
  line-height: 1.2;
  font-weight: 500;
  pointer-events: none;
  user-select: none;
  white-space: nowrap;
}

.hitl-wait-span {
  background: repeating-linear-gradient(
    135deg,
    hsl(var(--warning) / 0.55) 0px,
    hsl(var(--warning) / 0.55) 3px,
    hsl(var(--warning) / 0.28) 3px,
    hsl(var(--warning) / 0.28) 6px
  );
}

.trace-span-action {
  position: absolute;
  right: 2px;
  top: 50%;
  z-index: 2;
  display: inline-flex;
  height: 18px;
  width: 18px;
  transform: translateY(-50%);
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  background: hsl(var(--background) / 0.92);
  color: hsl(var(--foreground));
  opacity: 0;
  box-shadow: 0 0 0 1px hsl(var(--border) / 0.8);
  transition: opacity 120ms ease, background-color 120ms ease;
}

.trace-span:hover .trace-span-action,
.trace-span-action:focus-visible {
  opacity: 1;
}

.trace-span-action:hover {
  background: hsl(var(--primary) / 0.16);
}

@media (prefers-reduced-motion: reduce) {
  .trace-span-running {
    animation: none;
  }
}
</style>
