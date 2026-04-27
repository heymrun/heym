<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ArrowDown, ArrowUp, ArrowUpDown, BarChart3, ExternalLink, TrendingDown, TrendingUp, Zap } from "lucide-vue-next";
import type {
  AnalyticsDateRange,
  AnalyticsQueryOptions,
  AnalyticsStats,
  BucketSize,
  TimeSeriesMetrics,
  TimeRange,
  WorkflowBreakdownItem,
} from "@/types/analytics";
import type { WorkflowListItem } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import Select from "@/components/ui/Select.vue";
import { analyticsApi, workflowApi } from "@/services/api";

const emit = defineEmits<{
  (e: "openErrorHistory", workflowId: string): void;
}>();

const stats = ref<AnalyticsStats | null>(null);
const metrics = ref<TimeSeriesMetrics | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const timeRange = ref<TimeRange>("7d");
const selectedDateRange = ref<AnalyticsDateRange | null>(null);
const workflowId = ref<string | undefined>(undefined);
const workflows = ref<WorkflowListItem[]>([]);
const autoRefresh = ref(false);
const refreshInterval = ref<number | null>(null);
const workflowBreakdown = ref<WorkflowBreakdownItem[] | null>(null);
const route = useRoute();
const router = useRouter();
const SELECTION_START_QUERY_KEY = "selectionStart";
const SELECTION_END_QUERY_KEY = "selectionEnd";
let pendingSelectedDateRange: AnalyticsDateRange | null = null;

interface ChartSelectionBounds {
  min?: number;
  max?: number;
}

interface ChartSelectionEventConfig {
  xaxis?: ChartSelectionBounds;
}

const HOUR_IN_MS = 60 * 60 * 1000;
const DAY_IN_MS = 24 * HOUR_IN_MS;

const isSelectionActive = computed<boolean>(() => selectedDateRange.value !== null);

const activeBucketSize = computed<BucketSize>(() => {
  if (!selectedDateRange.value) {
    return timeRange.value === "all" ? "1d" : "1h";
  }

  const rangeMs = new Date(selectedDateRange.value.endAt).getTime() -
    new Date(selectedDateRange.value.startAt).getTime();
  if (rangeMs <= 2 * DAY_IN_MS) {
    return "1h";
  }
  if (rangeMs <= 14 * DAY_IN_MS) {
    return "6h";
  }
  return "1d";
});

const activeAnalyticsQuery = computed<AnalyticsQueryOptions>(() => ({
  timeRange: timeRange.value,
  bucketSize: activeBucketSize.value,
  dateRange: selectedDateRange.value,
}));

const chartScopeKey = computed<string>(() => [
  workflowId.value ?? "all",
  timeRange.value,
  selectedDateRange.value?.startAt ?? "preset",
  selectedDateRange.value?.endAt ?? "preset",
  activeBucketSize.value,
].join(":"));

const selectedRangeLabel = computed<string | null>(() => {
  if (!selectedDateRange.value) {
    return null;
  }
  return formatDateRangeLabel(selectedDateRange.value);
});

function getBucketSizeMs(bucketSize: BucketSize): number {
  if (bucketSize === "6h") {
    return 6 * HOUR_IN_MS;
  }
  if (bucketSize === "1d") {
    return DAY_IN_MS;
  }
  return HOUR_IN_MS;
}

function findClosestBucket(target: number, buckets: number[]): number {
  return buckets.reduce((closest, current) => {
    return Math.abs(current - target) < Math.abs(closest - target) ? current : closest;
  }, buckets[0]);
}

function buildSelectedDateRange(min: number, max: number): AnalyticsDateRange | null {
  if (!metrics.value) {
    return null;
  }

  const buckets = metrics.value.time_buckets
    .map((bucket) => new Date(bucket).getTime())
    .filter((bucket) => Number.isFinite(bucket));
  if (buckets.length === 0) {
    return null;
  }

  const lowerBound = Math.min(min, max);
  const upperBound = Math.max(min, max);
  const selectedBuckets = buckets.filter((bucket) => bucket >= lowerBound && bucket <= upperBound);
  const alignedBuckets = selectedBuckets.length > 0
    ? selectedBuckets
    : [findClosestBucket(lowerBound, buckets), findClosestBucket(upperBound, buckets)];

  const startMs = Math.min(...alignedBuckets);
  const endMs = Math.max(...alignedBuckets) + getBucketSizeMs(activeBucketSize.value);
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {
    return null;
  }

  return {
    startAt: new Date(startMs).toISOString(),
    endAt: new Date(endMs).toISOString(),
  };
}

function applyChartSelection(bounds?: ChartSelectionBounds): void {
  if (typeof bounds?.min !== "number" || typeof bounds?.max !== "number") {
    return;
  }

  const nextRange = buildSelectedDateRange(bounds.min, bounds.max);
  if (!nextRange) {
    return;
  }
  pendingSelectedDateRange = nextRange;
}

function clearSelectedDateRange(): void {
  selectedDateRange.value = null;
}

function areDateRangesEqual(
  left: AnalyticsDateRange | null,
  right: AnalyticsDateRange | null,
): boolean {
  if (left === right) {
    return true;
  }
  if (!left || !right) {
    return false;
  }
  return left.startAt === right.startAt && left.endAt === right.endAt;
}

function parseSelectionDateRange(
  startValue: unknown,
  endValue: unknown,
): AnalyticsDateRange | null {
  if (typeof startValue !== "string" || typeof endValue !== "string") {
    return null;
  }

  const startMs = new Date(startValue).getTime();
  const endMs = new Date(endValue).getTime();
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {
    return null;
  }

  return {
    startAt: new Date(startMs).toISOString(),
    endAt: new Date(endMs).toISOString(),
  };
}

function syncAnalyticsQueryState(): void {
  const currentWorkflowId = typeof route.query.workflowId === "string"
    ? route.query.workflowId
    : undefined;
  const currentSelectionStart = typeof route.query[SELECTION_START_QUERY_KEY] === "string"
    ? route.query[SELECTION_START_QUERY_KEY]
    : undefined;
  const currentSelectionEnd = typeof route.query[SELECTION_END_QUERY_KEY] === "string"
    ? route.query[SELECTION_END_QUERY_KEY]
    : undefined;
  const nextSelectionStart = selectedDateRange.value?.startAt;
  const nextSelectionEnd = selectedDateRange.value?.endAt;

  if (
    currentWorkflowId === workflowId.value &&
    currentSelectionStart === nextSelectionStart &&
    currentSelectionEnd === nextSelectionEnd
  ) {
    return;
  }

  const nextQuery = { ...route.query };
  if (workflowId.value) {
    nextQuery.workflowId = workflowId.value;
  } else {
    delete nextQuery.workflowId;
  }
  if (nextSelectionStart && nextSelectionEnd) {
    nextQuery[SELECTION_START_QUERY_KEY] = nextSelectionStart;
    nextQuery[SELECTION_END_QUERY_KEY] = nextSelectionEnd;
  } else {
    delete nextQuery[SELECTION_START_QUERY_KEY];
    delete nextQuery[SELECTION_END_QUERY_KEY];
  }

  router.push({ query: nextQuery }).catch(() => {});
}

function commitPendingChartSelection(): void {
  if (!pendingSelectedDateRange) {
    return;
  }

  const nextRange = pendingSelectedDateRange;
  pendingSelectedDateRange = null;
  if (areDateRangesEqual(nextRange, selectedDateRange.value)) {
    return;
  }
  selectedDateRange.value = nextRange;
}

function clearPendingChartSelection(): void {
  pendingSelectedDateRange = null;
}

const chartOptions = computed(() => ({
  chart: {
    type: "line",
    height: 300,
    toolbar: {
      show: false,
      autoSelected: "selection",
    },
    selection: {
      enabled: true,
      type: "x",
      fill: {
        color: "#3b82f6",
        opacity: 0.12,
      },
      stroke: {
        color: "#3b82f6",
        opacity: 0.35,
        width: 1,
      },
    },
    zoom: {
      enabled: false,
      type: "x",
      autoScaleYaxis: true,
      allowMouseWheelZoom: false,
    },
    events: {
      selection: (_chartContext: unknown, config: ChartSelectionEventConfig) => {
        applyChartSelection(config.xaxis);
      },
    },
  },
  stroke: {
    curve: "smooth",
    width: 2,
  },
  xaxis: {
    type: "datetime",
    labels: {
      datetimeUTC: false,
    },
  },
  yaxis: {
    labels: {
      formatter: (val: number) => Math.round(val).toString(),
    },
  },
  tooltip: {
    x: {
      format: "dd MMM yyyy HH:mm",
    },
  },
  theme: {
    mode: document.documentElement.classList.contains("dark") ? "dark" : "light",
  },
}));

const executionVolumeChart = computed(() => {
  if (!metrics.value) {
    return null;
  }
  const maxExecutions = Math.max(...metrics.value.executions, 0);
  const hasData = metrics.value.executions.some((val) => val > 0);

  const chartData = metrics.value.time_buckets.map((bucket, i) => ({
    x: new Date(bucket).getTime(),
    y: metrics.value!.executions[i],
  }));

  return {
    series: [
      {
        name: "Executions",
        data: chartData,
      },
    ],
    options: {
      ...chartOptions.value,
      colors: ["#3b82f6"],
      title: {
        text: "Execution Volume Over Time",
        style: { fontSize: "16px", fontWeight: 600 },
      },
      yaxis: {
        ...chartOptions.value.yaxis,
        min: 0,
        max: hasData && maxExecutions > 0 ? Math.max(maxExecutions * 1.1, 5) : 5,
      },
    },
  };
});

const successErrorChart = computed(() => {
  if (!metrics.value) return null;
  const maxValue = Math.max(
    ...metrics.value.successes,
    ...metrics.value.errors,
    0
  );
  const hasData = metrics.value.successes.some((val) => val > 0) ||
    metrics.value.errors.some((val) => val > 0);

  const chartData = {
    successes: metrics.value.time_buckets.map((bucket, i) => ({
      x: new Date(bucket).getTime(),
      y: metrics.value!.successes[i],
    })),
    errors: metrics.value.time_buckets.map((bucket, i) => ({
      x: new Date(bucket).getTime(),
      y: metrics.value!.errors[i],
    })),
  };

  return {
    series: [
      {
        name: "Successes",
        data: chartData.successes,
      },
      {
        name: "Errors",
        data: chartData.errors,
      },
    ],
    options: {
      ...chartOptions.value,
      chart: { ...chartOptions.value.chart, type: "area", stacked: true },
      colors: ["#10b981", "#ef4444"],
      title: {
        text: "Success vs Error Rate",
        style: { fontSize: "16px", fontWeight: 600 },
      },
      yaxis: {
        ...chartOptions.value.yaxis,
        min: 0,
        max: hasData && maxValue > 0 ? Math.max(maxValue * 1.1, 5) : 5,
      },
    },
  };
});

const latencyChart = computed(() => {
  if (!metrics.value) return null;
  const maxLatency = Math.max(...metrics.value.avg_latency_ms, 0);
  const hasData = metrics.value.avg_latency_ms.some((val) => val > 0);

  const chartData = metrics.value.time_buckets.map((bucket, i) => {
    const dateTime = new Date(bucket).getTime();
    const latency = Math.round(metrics.value!.avg_latency_ms[i]);
    return { x: dateTime, y: latency };
  });

  return {
    series: [
      {
        name: "Avg Latency (ms)",
        data: chartData,
      },
    ],
    options: {
      ...chartOptions.value,
      colors: ["#f59e0b"],
      title: {
        text: "Average Latency Over Time",
        style: { fontSize: "16px", fontWeight: 600 },
      },
      yaxis: {
        ...chartOptions.value.yaxis,
        min: 0,
        max: hasData && maxLatency > 0 ? Math.max(maxLatency * 1.1, 100) : 100,
        labels: {
          formatter: (val: number) => `${Math.round(val)}ms`,
        },
      },
    },
  };
});

type SortKey = "workflow_name" | "execution_count" | "success_rate" | "error_count" | "avg_latency_ms" | "error_rate";
type SortDir = "asc" | "desc";

const usedSortKey = ref<SortKey>("execution_count");
const usedSortDir = ref<SortDir>("desc");
const failedSortKey = ref<SortKey>("error_count");
const failedSortDir = ref<SortDir>("desc");

function toggleUsedSort(key: SortKey): void {
  if (usedSortKey.value === key) {
    usedSortDir.value = usedSortDir.value === "desc" ? "asc" : "desc";
  } else {
    usedSortKey.value = key;
    usedSortDir.value = "desc";
  }
}

function toggleFailedSort(key: SortKey): void {
  if (failedSortKey.value === key) {
    failedSortDir.value = failedSortDir.value === "desc" ? "asc" : "desc";
  } else {
    failedSortKey.value = key;
    failedSortDir.value = "desc";
  }
}

function sortItems(items: WorkflowBreakdownItem[], key: SortKey, dir: SortDir): WorkflowBreakdownItem[] {
  return [...items].sort((a, b) => {
    const aVal = a[key] as number | string;
    const bVal = b[key] as number | string;
    if (typeof aVal === "string" && typeof bVal === "string") {
      return dir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    }
    return dir === "asc" ? (aVal as number) - (bVal as number) : (bVal as number) - (aVal as number);
  });
}

const mostUsedWorkflows = computed<WorkflowBreakdownItem[]>(() => {
  if (!workflowBreakdown.value || workflowId.value) {
    return [];
  }
  return sortItems(workflowBreakdown.value, usedSortKey.value, usedSortDir.value);
});

const mostFailedWorkflows = computed<WorkflowBreakdownItem[]>(() => {
  if (!workflowBreakdown.value || workflowId.value) {
    return [];
  }
  return sortItems(
    workflowBreakdown.value.filter((item) => item.error_count > 0),
    failedSortKey.value,
    failedSortDir.value,
  );
});

async function loadData(): Promise<void> {
  try {
    loading.value = true;
    error.value = null;
    const baseRequests = [
      analyticsApi.getStats(workflowId.value, activeAnalyticsQuery.value),
      analyticsApi.getMetrics(workflowId.value, activeAnalyticsQuery.value),
    ] as const;
    const breakdownRequest =
      workflowId.value === undefined
        ? analyticsApi.getWorkflowBreakdown(activeAnalyticsQuery.value, 10)
        : Promise.resolve<WorkflowBreakdownItem[] | null>(null);

    const [statsData, metricsData, breakdownData] = await Promise.all([
      ...baseRequests,
      breakdownRequest,
    ]);
    stats.value = statsData;
    metrics.value = metricsData;
    workflowBreakdown.value = breakdownData;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load analytics";
  } finally {
    loading.value = false;
  }
}

async function loadWorkflows(): Promise<void> {
  try {
    workflows.value = await workflowApi.list();
  } catch (err) {
    console.error("Failed to load workflows", err);
  }
}

watch(
  [timeRange, workflowId],
  ([nextTimeRange], [previousTimeRange]) => {
    if (nextTimeRange !== previousTimeRange && selectedDateRange.value) {
      selectedDateRange.value = null;
      return;
    }

    void loadData();
  },
);

watch(
  [workflowId, selectedDateRange],
  () => {
    syncAnalyticsQueryState();
  },
  { deep: true },
);

watch(
  selectedDateRange,
  () => {
    void loadData();
  },
  { deep: true },
);

watch(
  () => [
    route.query.workflowId,
    route.query[SELECTION_START_QUERY_KEY],
    route.query[SELECTION_END_QUERY_KEY],
  ] as const,
  ([workflowQuery, selectionStartQuery, selectionEndQuery]) => {
    const nextId = typeof workflowQuery === "string" ? workflowQuery : undefined;
    if (nextId !== workflowId.value) {
      workflowId.value = nextId;
    }
    const nextRange = parseSelectionDateRange(selectionStartQuery, selectionEndQuery);
    if (!areDateRangesEqual(nextRange, selectedDateRange.value)) {
      selectedDateRange.value = nextRange;
    }
  },
  { immediate: true },
);

watch(autoRefresh, (enabled) => {
  if (enabled) {
    refreshInterval.value = window.setInterval(() => {
      void loadData();
    }, 30000);
  } else if (refreshInterval.value !== null) {
    clearInterval(refreshInterval.value);
    refreshInterval.value = null;
  }
});

onMounted(() => {
  window.addEventListener("mouseup", commitPendingChartSelection);
  window.addEventListener("touchend", commitPendingChartSelection);
  window.addEventListener("mousedown", clearPendingChartSelection);
  window.addEventListener("touchstart", clearPendingChartSelection);
  void loadWorkflows();
  void loadData();
});

onUnmounted(() => {
  window.removeEventListener("mouseup", commitPendingChartSelection);
  window.removeEventListener("touchend", commitPendingChartSelection);
  window.removeEventListener("mousedown", clearPendingChartSelection);
  window.removeEventListener("touchstart", clearPendingChartSelection);
  if (refreshInterval.value !== null) {
    clearInterval(refreshInterval.value);
  }
});

function formatNumber(num: number): string {
  return new Intl.NumberFormat("en-US").format(num);
}

function formatLatency(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function formatDateRangeLabel(range: AnalyticsDateRange): string {
  const start = new Date(range.startAt);
  const end = new Date(Math.max(new Date(range.endAt).getTime() - 1, start.getTime()));
  const sameDay = start.toDateString() === end.toDateString();
  const startFormatter = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  const endFormatter = new Intl.DateTimeFormat("en-US", sameDay
    ? { hour: "2-digit", minute: "2-digit" }
    : { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  return `${startFormatter.format(start)} - ${endFormatter.format(end)}`;
}

function selectWorkflow(id: string): void {
  workflowId.value = id;
}

function isKnownWorkflowRow(id: string): boolean {
  return workflows.value.some((w) => w.id === id);
}

function goToWorkflow(): void {
  if (!workflowId.value) return;
  router.push({ name: "editor", params: { id: workflowId.value } }).catch(() => {});
}
</script>

<template>
  <div class="space-y-6 overflow-x-hidden">
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
      <h2 class="text-2xl font-bold">
        Analytics Dashboard
      </h2>
      <div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 flex-wrap">
        <Select
          v-model="workflowId"
          :options="[
            { value: undefined, label: 'All Workflows' },
            ...workflows.map((w) => ({ value: w.id, label: w.name })),
          ]"
          placeholder="Filter by workflow"
          class="w-full sm:w-48 min-w-0"
        />
        <Select
          v-model="timeRange"
          :options="[
            { value: '24h', label: 'Last 24 Hours' },
            { value: '7d', label: 'Last 7 Days' },
            { value: '30d', label: 'Last 30 Days' },
            { value: 'all', label: 'All Time' },
          ]"
          class="w-full sm:w-40 min-w-0"
        />
        <div class="flex items-center gap-2 flex-shrink-0">
          <Button
            :variant="autoRefresh ? 'default' : 'outline'"
            size="sm"
            class="text-xs sm:text-sm"
            @click="autoRefresh = !autoRefresh"
          >
            <span class="hidden sm:inline">Auto Refresh</span>
            <span class="sm:hidden">Auto</span>
          </Button>
          <Button
            variant="outline"
            size="sm"
            :disabled="loading"
            @click="loadData"
          >
            Refresh
          </Button>
          <Button
            v-if="workflowId"
            variant="outline"
            size="sm"
            @click="goToWorkflow"
          >
            Go to Workflow
          </Button>
          <Button
            v-if="isSelectionActive"
            variant="outline"
            size="sm"
            @click="clearSelectedDateRange"
          >
            Clear Selection
          </Button>
        </div>
      </div>
    </div>

    <Card class="px-4 py-3">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div class="space-y-1">
          <p class="text-sm font-medium">
            {{ isSelectionActive ? "Selection mode is active" : "Chart selection is ready" }}
          </p>
          <p class="text-sm text-muted-foreground">
            {{
              selectedRangeLabel
                ? `Selected range: ${selectedRangeLabel}. Drag on any chart again to refine it.`
                : "Drag across any chart to focus a custom time slice without changing the preset time filter."
            }}
          </p>
        </div>
        <p class="text-xs text-muted-foreground">
          Base window: {{ timeRange }}
        </p>
      </div>
    </Card>

    <div
      v-if="error"
      class="rounded-lg bg-destructive/10 p-4 text-destructive"
    >
      {{ error }}
    </div>

    <div
      v-if="loading && !stats"
      class="space-y-4"
    >
      <div class="h-32 animate-pulse rounded-lg bg-muted" />
      <div class="h-64 animate-pulse rounded-lg bg-muted" />
    </div>

    <div
      v-else-if="stats"
      class="space-y-6"
    >
      <div class="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card class="p-4">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm text-muted-foreground">
                Total Executions
              </p>
              <p class="text-2xl font-bold">
                {{ formatNumber(stats.total_executions) }}
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                {{ selectedRangeLabel ?? `Last 24h: ${formatNumber(stats.total_executions_24h)}` }}
              </p>
            </div>
            <BarChart3 class="h-8 w-8 text-muted-foreground" />
          </div>
        </Card>

        <Card class="p-4">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm text-muted-foreground">
                Success Rate
              </p>
              <p class="text-2xl font-bold">
                {{ stats.success_rate.toFixed(1) }}%
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                {{ formatNumber(stats.success_count) }} / {{ formatNumber(stats.total_executions) }}
              </p>
            </div>
            <TrendingUp class="h-8 w-8 text-green-500" />
          </div>
        </Card>

        <Card class="p-4">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm text-muted-foreground">
                Error Rate
              </p>
              <p class="text-2xl font-bold">
                {{ stats.error_rate.toFixed(1) }}%
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                {{ formatNumber(stats.error_count) }} errors
              </p>
            </div>
            <TrendingDown class="h-8 w-8 text-red-500" />
          </div>
        </Card>

        <Card class="p-4">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm text-muted-foreground">
                Avg Latency
              </p>
              <p class="text-2xl font-bold">
                {{ formatLatency(stats.avg_latency_ms) }}
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                P95: {{ formatLatency(stats.p95_latency_ms) }}
              </p>
            </div>
            <Zap class="h-8 w-8 text-yellow-500" />
          </div>
        </Card>
      </div>

      <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card class="p-4">
          <div
            v-if="!executionVolumeChart || !metrics || !metrics.time_buckets || metrics.time_buckets.length === 0"
            class="flex items-center justify-center h-[300px] text-sm text-muted-foreground"
          >
            No execution data available for this time period
          </div>
          <apexchart
            v-else
            :key="`${chartScopeKey}-volume`"
            type="line"
            height="300"
            :options="executionVolumeChart.options"
            :series="executionVolumeChart.series"
          />
        </Card>

        <Card class="p-4">
          <div
            v-if="!successErrorChart || !metrics || !metrics.time_buckets || metrics.time_buckets.length === 0"
            class="flex items-center justify-center h-[300px] text-sm text-muted-foreground"
          >
            No success/error data available for this time period
          </div>
          <apexchart
            v-else
            :key="`${chartScopeKey}-success`"
            type="area"
            height="300"
            :options="successErrorChart.options"
            :series="successErrorChart.series"
          />
        </Card>

        <Card class="p-4 lg:col-span-2">
          <div
            v-if="!latencyChart || !metrics || !metrics.time_buckets || metrics.time_buckets.length === 0"
            class="flex items-center justify-center h-[300px] text-sm text-muted-foreground"
          >
            No latency data available for this time period
          </div>
          <apexchart
            v-else
            :key="`${chartScopeKey}-latency`"
            type="line"
            height="300"
            :options="latencyChart.options"
            :series="latencyChart.series"
          />
        </Card>
      </div>

      <Card class="p-4">
        <h3 class="mb-4 text-lg font-semibold">
          Latency Percentiles
        </h3>
        <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <p class="text-sm text-muted-foreground">
              P50 (Median)
            </p>
            <p class="text-xl font-bold">
              {{ formatLatency(stats.p50_latency_ms) }}
            </p>
          </div>
          <div>
            <p class="text-sm text-muted-foreground">
              P95
            </p>
            <p class="text-xl font-bold">
              {{ formatLatency(stats.p95_latency_ms) }}
            </p>
          </div>
          <div>
            <p class="text-sm text-muted-foreground">
              P99
            </p>
            <p class="text-xl font-bold">
              {{ formatLatency(stats.p99_latency_ms) }}
            </p>
          </div>
        </div>
      </Card>

      <div
        v-if="!workflowId && workflowBreakdown && workflowBreakdown.length > 0"
        class="grid grid-cols-1 gap-6 lg:grid-cols-2"
      >
        <Card class="p-4">
          <h3 class="mb-4 text-lg font-semibold">
            Most Used Workflows
          </h3>
          <div class="overflow-x-auto -mx-1">
            <table class="w-full text-xs sm:text-sm min-w-[340px]">
              <thead>
                <tr class="border-b border-border">
                  <th
                    class="p-1.5 sm:p-2 text-left font-medium cursor-pointer select-none hover:text-foreground group"
                    @click="toggleUsedSort('workflow_name')"
                  >
                    <span class="flex items-center gap-1">
                      <span>Workflow</span>
                      <component
                        :is="usedSortKey === 'workflow_name' ? (usedSortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown"
                        :class="['w-3 h-3 shrink-0', usedSortKey === 'workflow_name' ? 'text-primary' : 'text-muted-foreground/40 group-hover:text-muted-foreground']"
                      />
                    </span>
                  </th>
                  <th
                    class="p-1.5 sm:p-2 text-right font-medium cursor-pointer select-none hover:text-foreground group"
                    @click="toggleUsedSort('execution_count')"
                  >
                    <span class="flex items-center justify-end gap-1">
                      <component
                        :is="usedSortKey === 'execution_count' ? (usedSortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown"
                        :class="['w-3 h-3 shrink-0', usedSortKey === 'execution_count' ? 'text-primary' : 'text-muted-foreground/40 group-hover:text-muted-foreground']"
                      />
                      <span class="hidden sm:inline">Executions</span>
                      <span class="sm:hidden">Runs</span>
                    </span>
                  </th>
                  <th
                    class="p-1.5 sm:p-2 text-right font-medium cursor-pointer select-none hover:text-foreground group"
                    @click="toggleUsedSort('success_rate')"
                  >
                    <span class="flex items-center justify-end gap-1">
                      <component
                        :is="usedSortKey === 'success_rate' ? (usedSortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown"
                        :class="['w-3 h-3 shrink-0', usedSortKey === 'success_rate' ? 'text-primary' : 'text-muted-foreground/40 group-hover:text-muted-foreground']"
                      />
                      <span class="hidden sm:inline">Success %</span>
                      <span class="sm:hidden">OK%</span>
                    </span>
                  </th>
                  <th
                    class="p-1.5 sm:p-2 text-right font-medium cursor-pointer select-none hover:text-foreground group"
                    @click="toggleUsedSort('error_count')"
                  >
                    <span class="flex items-center justify-end gap-1">
                      <component
                        :is="usedSortKey === 'error_count' ? (usedSortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown"
                        :class="['w-3 h-3 shrink-0', usedSortKey === 'error_count' ? 'text-primary' : 'text-muted-foreground/40 group-hover:text-muted-foreground']"
                      />
                      <span>Err</span>
                    </span>
                  </th>
                  <th
                    class="p-1.5 sm:p-2 text-right font-medium cursor-pointer select-none hover:text-foreground group"
                    @click="toggleUsedSort('avg_latency_ms')"
                  >
                    <span class="flex items-center justify-end gap-1">
                      <component
                        :is="usedSortKey === 'avg_latency_ms' ? (usedSortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown"
                        :class="['w-3 h-3 shrink-0', usedSortKey === 'avg_latency_ms' ? 'text-primary' : 'text-muted-foreground/40 group-hover:text-muted-foreground']"
                      />
                      <span class="hidden sm:inline">Avg Latency</span>
                      <span class="sm:hidden">Lat.</span>
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in mostUsedWorkflows"
                  :key="item.workflow_id"
                  class="border-b border-border/50 transition-colors"
                  :class="
                    isKnownWorkflowRow(item.workflow_id)
                      ? 'hover:bg-muted/30 cursor-pointer'
                      : 'cursor-default opacity-90'
                  "
                  @click="isKnownWorkflowRow(item.workflow_id) ? selectWorkflow(item.workflow_id) : undefined"
                >
                  <td class="p-1.5 sm:p-2 font-medium max-w-[100px] sm:max-w-none truncate">
                    {{ item.workflow_name }}
                  </td>
                  <td class="p-1.5 sm:p-2 text-right tabular-nums">
                    {{ formatNumber(item.execution_count) }}
                  </td>
                  <td class="p-1.5 sm:p-2 text-right tabular-nums">
                    {{ item.success_rate.toFixed(1) }}%
                  </td>
                  <td class="p-1.5 sm:p-2 text-right tabular-nums">
                    {{ formatNumber(item.error_count) }}
                  </td>
                  <td class="p-1.5 sm:p-2 text-right tabular-nums">
                    {{ formatLatency(item.avg_latency_ms) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </Card>

        <Card class="p-4">
          <h3 class="mb-4 text-lg font-semibold">
            Most Failed Workflows
          </h3>
          <div class="overflow-x-auto -mx-1">
            <table class="w-full text-xs sm:text-sm min-w-[340px]">
              <thead>
                <tr class="border-b border-border">
                  <th
                    class="p-1.5 sm:p-2 text-left font-medium cursor-pointer select-none hover:text-foreground group"
                    @click="toggleFailedSort('workflow_name')"
                  >
                    <span class="flex items-center gap-1">
                      <span>Workflow</span>
                      <component
                        :is="failedSortKey === 'workflow_name' ? (failedSortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown"
                        :class="['w-3 h-3 shrink-0', failedSortKey === 'workflow_name' ? 'text-primary' : 'text-muted-foreground/40 group-hover:text-muted-foreground']"
                      />
                    </span>
                  </th>
                  <th
                    class="p-1.5 sm:p-2 text-right font-medium cursor-pointer select-none hover:text-foreground group"
                    @click="toggleFailedSort('execution_count')"
                  >
                    <span class="flex items-center justify-end gap-1">
                      <component
                        :is="failedSortKey === 'execution_count' ? (failedSortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown"
                        :class="['w-3 h-3 shrink-0', failedSortKey === 'execution_count' ? 'text-primary' : 'text-muted-foreground/40 group-hover:text-muted-foreground']"
                      />
                      <span class="hidden sm:inline">Executions</span>
                      <span class="sm:hidden">Runs</span>
                    </span>
                  </th>
                  <th
                    class="p-1.5 sm:p-2 text-right font-medium cursor-pointer select-none hover:text-foreground group"
                    @click="toggleFailedSort('error_rate')"
                  >
                    <span class="flex items-center justify-end gap-1">
                      <component
                        :is="failedSortKey === 'error_rate' ? (failedSortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown"
                        :class="['w-3 h-3 shrink-0', failedSortKey === 'error_rate' ? 'text-primary' : 'text-muted-foreground/40 group-hover:text-muted-foreground']"
                      />
                      <span class="hidden sm:inline">Error %</span>
                      <span class="sm:hidden">Err%</span>
                    </span>
                  </th>
                  <th
                    class="p-1.5 sm:p-2 text-right font-medium cursor-pointer select-none hover:text-foreground group"
                    @click="toggleFailedSort('error_count')"
                  >
                    <span class="flex items-center justify-end gap-1">
                      <component
                        :is="failedSortKey === 'error_count' ? (failedSortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown"
                        :class="['w-3 h-3 shrink-0', failedSortKey === 'error_count' ? 'text-primary' : 'text-muted-foreground/40 group-hover:text-muted-foreground']"
                      />
                      <span>Err</span>
                    </span>
                  </th>
                  <th
                    class="p-1.5 sm:p-2 text-right font-medium cursor-pointer select-none hover:text-foreground group"
                    @click="toggleFailedSort('avg_latency_ms')"
                  >
                    <span class="flex items-center justify-end gap-1">
                      <component
                        :is="failedSortKey === 'avg_latency_ms' ? (failedSortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown"
                        :class="['w-3 h-3 shrink-0', failedSortKey === 'avg_latency_ms' ? 'text-primary' : 'text-muted-foreground/40 group-hover:text-muted-foreground']"
                      />
                      <span class="hidden sm:inline">Avg Latency</span>
                      <span class="sm:hidden">Lat.</span>
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in mostFailedWorkflows"
                  :key="`failed-${item.workflow_id}`"
                  class="border-b border-border/50 transition-colors"
                  :class="
                    isKnownWorkflowRow(item.workflow_id)
                      ? 'hover:bg-muted/30 cursor-pointer'
                      : 'cursor-default opacity-90'
                  "
                  @click="isKnownWorkflowRow(item.workflow_id) ? selectWorkflow(item.workflow_id) : undefined"
                >
                  <td class="p-1.5 sm:p-2 font-medium max-w-[100px] sm:max-w-none truncate">
                    {{ item.workflow_name }}
                  </td>
                  <td class="p-1.5 sm:p-2 text-right tabular-nums">
                    {{ formatNumber(item.execution_count) }}
                  </td>
                  <td class="p-1.5 sm:p-2 text-right tabular-nums">
                    {{ item.error_rate.toFixed(1) }}%
                  </td>
                  <td class="p-1.5 sm:p-2 text-right tabular-nums">
                    <span
                      class="inline-flex items-center justify-end gap-0.5 underline decoration-dotted cursor-pointer text-destructive hover:text-destructive/70 transition-colors"
                      @click.stop="emit('openErrorHistory', item.workflow_id)"
                    >
                      {{ formatNumber(item.error_count) }}
                      <ExternalLink class="w-3 h-3 shrink-0" />
                    </span>
                  </td>
                  <td class="p-1.5 sm:p-2 text-right tabular-nums">
                    {{ formatLatency(item.avg_latency_ms) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  </div>
</template>
