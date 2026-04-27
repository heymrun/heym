<script setup lang="ts">
import { computed, ref, watch } from "vue";
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
} from "@/components/Panels/executionTimeline";

interface Props {
  nodeResults: TimelineEntry[];
  totalTimeMs: number;
  subAgentLabelToParentId: Map<string, string>;
}

const props = defineProps<Props>();
const router = useRouter();

const emit = defineEmits<{
  selectNode: [payload: TimelineSelectPayload];
}>();

function emitSelectNode(payload: TimelineSelectPayload, event: MouseEvent): void {
  event.stopPropagation();
  emit("selectNode", payload);
}

function onSpanClick(span: SpanItem, event: MouseEvent): void {
  emitSelectNode({ nodeId: span.nodeId, resultListIndex: span.resultListIndex }, event);
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

const fullTimelineModel = computed(() =>
  buildTimelineModel(
    props.nodeResults,
    props.totalTimeMs,
    props.subAgentLabelToParentId,
  ),
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
    { preserveTotalTime: !shouldZoomVisibleRange.value },
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
  <div class="border-t bg-muted/5 select-none overflow-hidden">
    <div class="flex h-5 border-b border-border/30 overflow-hidden">
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

    <div
      class="overflow-y-auto"
      style="max-height: 220px;"
    >
      <div
        v-for="row in visibleRows"
        :key="row.key"
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
              :class="[
                span.status === 'error' ? 'opacity-90' : 'opacity-70 group-hover:opacity-95',
              ]"
              :style="{
                left: `${span.leftPct}%`,
                width: `${span.widthPct}%`,
                minWidth: '3px',
                height: `${row.depth === 1 ? childBarHeightPx : topLevelBarHeightPx}px`,
                backgroundColor: `hsl(var(--${span.colorVar}) / 0.55)`,
                borderColor: `hsl(var(--${span.colorVar}))`,
                borderWidth: span.status === 'error' ? '1.5px' : '1px',
                top: '50%',
                transform: 'translateY(-50%)',
              }"
              @click="onSpanClick(span, $event)"
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
            </div>

            <span
              v-if="span.widthPct > 8 && row.depth === 0"
              class="absolute text-[9px] leading-none pointer-events-none font-mono select-none"
              :style="{
                left: `calc(${span.leftPct}% + 5px)`,
                color: `hsl(var(--${span.colorVar}))`,
                top: '50%',
                transform: 'translateY(-50%)',
              }"
            >
              {{ span.durationMs >= 1000
                ? `${(span.durationMs / 1000).toFixed(1)}s`
                : `${Math.round(span.durationMs)}ms` }}
            </span>
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
        {{ hoveredSpan.nodeLabel }}<template v-if="hoveredSpan.occurrenceCount > 1"> #{{ hoveredSpan.occurrence }}</template>
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
</style>
