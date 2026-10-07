<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import type { ChartPayload } from "@/types/dashboard";
import ChartMarkdown from "@/components/Dashboards/ChartMarkdown.vue";
import ChartTable from "@/components/Dashboards/ChartTable.vue";
import HitlCarousel from "@/components/Dashboards/HitlCarousel.vue";
import MarkdownTextContent from "@/components/Dashboards/MarkdownTextContent.vue";
import {
  buildApexOptions,
  formatNumericValue,
  isChartEmpty,
  normalizeChartPayload,
  toApexSeries,
  toApexType,
  toBarGaugeRows,
  toProportionSegments,
} from "@/components/Dashboards/chartModel";
import type { TableRecord, TableRowLink } from "@/components/Dashboards/chartTable";
import { hasTaskItems } from "@/lib/markdownTaskList";

const props = defineProps<{
  payload: ChartPayload | Record<string, unknown> | null;
  markdownTaskSaving?: boolean;
  /** Dark palette for ApexCharts, which does not follow the page's CSS theme. */
  dark: boolean;
  /** Table rows open this detail page when set (see chartTable.ts). */
  rowLink?: TableRowLink | null;
}>();

const emit = defineEmits<{
  (e: "markdown-task-toggle", lineIndex: number): void;
  (e: "markdown-task-update", payload: { lineIndex: number; text: string }): void;
  (e: "row-open", record: TableRecord): void;
}>();

const chartPayload = computed((): ChartPayload | null => normalizeChartPayload(props.payload));
const proportionSegments = computed(() => toProportionSegments(chartPayload.value));
const barGaugeRows = computed(() => toBarGaugeRows(chartPayload.value));

// ApexCharts pie/radialBar derive their radius from the resolved pixel height.
// height="100%" can resolve to 0 on first mount inside a flex card, leaving the
// chart invisible (the original pie-not-rendering bug). Track the real height and
// pass it as a number instead.
const containerRef = ref<HTMLElement | null>(null);
const chartHeight = ref(220);
const chartWidth = ref(220);
let resizeObserver: ResizeObserver | null = null;

onMounted(() => {
  if (!containerRef.value) return;
  resizeObserver = new ResizeObserver((entries) => {
    const rect = entries[0]?.contentRect;
    if (rect && rect.height > 0) chartHeight.value = Math.round(rect.height);
    if (rect && rect.width > 0) chartWidth.value = Math.round(rect.width);
  });
  resizeObserver.observe(containerRef.value);
});

// Pie / radial charts derive their radius from the smaller dimension, so in a tall,
// narrow widget the chart canvas should stay square and be centered vertically —
// otherwise ApexCharts pins the circle to the top and leaves dead space below.
const radialHeight = computed((): number => {
  return Math.max(120, Math.min(chartHeight.value, chartWidth.value));
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
});

const isEmpty = computed((): boolean => isChartEmpty(chartPayload.value));

const usesTaskListRenderer = computed((): boolean => {
  const p = chartPayload.value;
  if (!p || p.type !== "text" || !p.text) return false;
  return hasTaskItems(p.text);
});

function onMarkdownTaskToggle(lineIndex: number): void {
  emit("markdown-task-toggle", lineIndex);
}

function onMarkdownTaskUpdate(payload: { lineIndex: number; text: string }): void {
  emit("markdown-task-update", payload);
}

const numericValue = computed((): string => formatNumericValue(chartPayload.value));
const apexType = computed(() => toApexType(chartPayload.value));
const apexSeries = computed(() => toApexSeries(chartPayload.value));
const apexOptions = computed(() =>
  buildApexOptions(chartPayload.value, { dark: props.dark, radialHeight: radialHeight.value }),
);
</script>


<template>
  <div
    ref="containerRef"
    class="h-full w-full text-foreground"
  >
    <div
      v-if="isEmpty"
      class="flex h-full min-h-[120px] items-center justify-center text-sm text-muted-foreground"
    >
      No data
    </div>

    <HitlCarousel
      v-else-if="chartPayload && chartPayload.type === 'hitl'"
      :seed-items="chartPayload.items"
      :seed-total="chartPayload.pending_total"
    />

    <div
      v-else-if="chartPayload && chartPayload.type === 'numeric'"
      class="flex h-full min-h-[120px] flex-col items-center justify-center"
    >
      <div class="text-4xl font-semibold tabular-nums text-foreground">
        {{ numericValue }}
      </div>
      <div
        v-if="chartPayload.unit"
        class="mt-1 text-sm text-muted-foreground"
      >
        {{ chartPayload.unit }}
      </div>
    </div>

    <MarkdownTextContent
      v-else-if="chartPayload && chartPayload.type === 'text' && usesTaskListRenderer"
      :text="chartPayload.text || ''"
      :interactive="!!chartPayload.text_interactive"
      :saving="markdownTaskSaving"
      @toggle="onMarkdownTaskToggle"
      @update="onMarkdownTaskUpdate"
    />
    <ChartMarkdown
      v-else-if="chartPayload && chartPayload.type === 'text'"
      :text="chartPayload.text || ''"
    />

    <div
      v-else-if="chartPayload && chartPayload.type === 'table'"
      class="h-full overflow-auto pb-3"
    >
      <ChartTable
        :columns="chartPayload.columns ?? []"
        :rows="chartPayload.rows ?? []"
        :status-column="chartPayload.statusColumn"
        :status-tones="chartPayload.statusTones"
        :row-link="rowLink"
        @row-open="(record) => emit('row-open', record)"
      />
    </div>

    <div
      v-else-if="chartPayload && chartPayload.type === 'proportion'"
      class="flex h-full flex-col justify-center gap-4 px-1"
    >
      <div class="flex h-3 w-full overflow-hidden rounded-full bg-muted">
        <div
          v-for="(seg, i) in proportionSegments"
          :key="i"
          class="h-full first:rounded-l-full last:rounded-r-full"
          :style="{ width: seg.pct + '%', backgroundColor: seg.color }"
          :title="`${seg.label} ${seg.pct.toFixed(2)}%`"
        />
      </div>
      <div class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm text-foreground">
        <div
          v-for="(seg, i) in proportionSegments"
          :key="i"
          class="flex items-center gap-2"
        >
          <span
            class="h-2.5 w-2.5 shrink-0 rounded-full"
            :style="{ backgroundColor: seg.color }"
          />
          <span class="truncate">{{ seg.label }} {{ seg.pct.toFixed(2) }}%</span>
        </div>
      </div>
    </div>

    <div
      v-else-if="chartPayload && chartPayload.type === 'barGauge'"
      class="flex h-full flex-col justify-center gap-2 overflow-auto px-1 py-1"
    >
      <div
        v-for="(row, i) in barGaugeRows"
        :key="i"
        class="flex items-center gap-2 text-sm"
      >
        <span class="w-14 shrink-0 truncate text-muted-foreground">{{ row.label }}</span>
        <div class="relative h-4 flex-1 overflow-hidden rounded bg-muted">
          <div
            class="h-full rounded"
            :style="{
              width: row.pct + '%',
              backgroundImage: 'linear-gradient(to right, #ef4444, #f59e0b, #22c55e)',
              backgroundSize: row.gradientSize,
              backgroundRepeat: 'no-repeat',
            }"
          />
        </div>
        <span
          class="w-20 shrink-0 text-right font-semibold tabular-nums"
          :style="{ color: row.valueColor }"
        >
          {{ row.value }}<span
            v-if="chartPayload.unit"
            class="ml-1 text-xs font-normal text-muted-foreground"
          >{{ chartPayload.unit }}</span>
        </span>
      </div>
    </div>

    <!-- Pie / gauge: keep the canvas square and centered in tall, narrow widgets. -->
    <div
      v-else-if="apexType === 'pie' || apexType === 'radialBar'"
      class="flex h-full w-full items-center justify-center"
    >
      <apexchart
        :key="apexType"
        :type="apexType"
        :height="radialHeight"
        :options="apexOptions"
        :series="apexSeries"
      />
    </div>

    <apexchart
      v-else
      :key="apexType"
      :type="apexType"
      :height="chartHeight"
      :options="apexOptions"
      :series="apexSeries"
    />
  </div>
</template>
