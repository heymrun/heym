<script setup lang="ts">
import { computed } from "vue";

import type { NodeTypeAnalytics } from "@/types/analytics";
import Card from "@/components/ui/Card.vue";
import {
  buildNodeTypeChart,
  formatDurationMs,
  NODE_TYPE_CHART_COLORS,
  NODE_TYPE_EMPTY_MESSAGE,
  NODE_TYPE_METRICS,
  type ChartBaseOptions,
  type NodeTypeChartModel,
} from "@/components/Analytics/nodeTypeCharts";
import { resolveNodeDisplay } from "@/lib/nodeDisplay";

const props = defineProps<{
  analytics: NodeTypeAnalytics | null;
  baseOptions: ChartBaseOptions;
  scopeKey: string;
}>();

function labelFor(nodeType: string): string {
  return resolveNodeDisplay(nodeType).typeLabel;
}

const charts = computed<NodeTypeChartModel[]>(() =>
  NODE_TYPE_METRICS.map((metric) => buildNodeTypeChart(metric, props.analytics, labelFor)),
);

function formatValue(model: NodeTypeChartModel, value: number | null): string {
  if (value === null) return "No calls";
  return model.metric === "duration" ? formatDurationMs(value) : Math.round(value).toString();
}

function optionsFor(model: NodeTypeChartModel): Record<string, unknown> {
  return {
    ...props.baseOptions,
    chart: { ...props.baseOptions.chart, type: "area", stacked: model.stacked },
    colors: NODE_TYPE_CHART_COLORS,
    dataLabels: { enabled: false },
    fill: { type: "solid", opacity: model.stacked ? 0.45 : 0.15 },
    legend: { position: "bottom" },
    tooltip: {
      ...props.baseOptions.tooltip,
      y: { formatter: (value: number | null) => formatValue(model, value) },
    },
    yaxis: {
      ...props.baseOptions.yaxis,
      min: 0,
      labels: { formatter: (value: number) => formatValue(model, value) },
    },
  };
}
</script>

<template>
  <section
    class="space-y-4"
    data-testid="analytics-node-types"
  >
    <h3 class="text-lg font-semibold">
      Node Types
    </h3>
    <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <Card
        v-for="(chart, index) in charts"
        :key="chart.metric"
        class="min-w-0 p-4"
        :class="index === charts.length - 1 ? 'lg:col-span-2' : ''"
        :data-testid="`analytics-node-chart-${chart.metric}`"
      >
        <div class="mb-2 space-y-0.5">
          <h4 class="text-base font-semibold">
            {{ chart.title }}
          </h4>
          <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <p class="text-xs text-muted-foreground">
              {{ chart.subtitle }}
            </p>
            <p
              v-if="chart.leader"
              class="truncate text-sm font-medium"
              :title="chart.leader"
            >
              {{ chart.leader }}
            </p>
          </div>
        </div>
        <div
          v-if="chart.series.length === 0"
          class="flex h-[300px] items-center justify-center px-6 text-center text-sm text-muted-foreground"
        >
          {{ NODE_TYPE_EMPTY_MESSAGE }}
        </div>
        <apexchart
          v-else
          :key="`${scopeKey}-node-${chart.metric}`"
          type="area"
          height="300"
          :options="optionsFor(chart)"
          :series="chart.series"
        />
      </Card>
    </div>
  </section>
</template>
