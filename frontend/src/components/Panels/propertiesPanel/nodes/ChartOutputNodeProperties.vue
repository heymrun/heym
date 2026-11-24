<script setup lang="ts">
import { computed } from "vue";

import type { ChartOutputExpressionFieldKey } from "@/lib/chartOutputExpressionFields";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { getChartOutputExpressionFields } from "@/lib/chartOutputExpressionFields";
import { CHART_TYPE_EXAMPLES } from "@/lib/chartTypeExamples";
import { CHART_ACTION_RESULT_OUTGOING_ERROR, CHART_ACTION_RESULT_TYPE_ERROR } from "@/lib/workflowEdges";
import ChartOutputHitlFields from "./ChartOutputHitlFields.vue";
import ChartOutputLinkFields from "./ChartOutputLinkFields.vue";
import ChartOutputStatusFields from "./ChartOutputStatusFields.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore, selectedNode, selectedNodeEvaluateDialogLabel,
  chartOutputExpressionFieldCount, chartOutputExpressionFieldIndex,
  setChartOutputExpressionInputRef, handleChartOutputExpressionFieldNavigate,
  onChartOutputRegisterExpressionFieldIndex, updateNodeData,
} = usePropertiesPanelContext();

const isActionResult = computed(() => workflowStore.chartActionResultIds.has(selectedNode.value?.id ?? ""));
const outgoingResultEdges = computed(() => isActionResult.value
  ? workflowStore.edges.filter((edge) => edge.source === selectedNode.value?.id)
  : []);
const options = computed(() => CHART_TYPE_EXAMPLES.map(({ value, label }) => ({
  value, label, disabled: isActionResult.value && value !== "html",
})));
const fields = computed(() => selectedNode.value?.data.chartType === "hitl" ? [] :
  getChartOutputExpressionFields(selectedNode.value?.data.chartType)
    .filter(({ key }) => !["statusColumn", "linkColumn", "linkLabel"].includes(key)));
const structuredHint = computed((): string => {
  if (selectedNode.value?.data.chartType === "gantt") {
    return "Data path selects task rows: id, label, start, end (ISO dates), optional progress (0–100) and dependencies (task ids). Timezone-free dates use UTC.";
  }
  if (selectedNode.value?.data.chartType === "erDiagram") {
    return "Data path selects an object with entities [{id, label, fields: [{name, type, key}]}] and relations [{source, target, sourceField, targetField, cardinality}]. Keys: PK, FK, PK/FK. Cardinality: one-to-one, one-to-many, many-to-one, many-to-many.";
  }
  return "";
});

const multiLine = new Set<ChartOutputExpressionFieldKey>(["text", "html"]);

const placeholders: Partial<Record<ChartOutputExpressionFieldKey, string>> = {
  dataPath: "e.g. rows, tasks or graph",
  labelField: "row key used as category label",
  valueField: "row key holding the value",
  text: "e.g. **Last execution** at `19:47`",
  html: "e.g. <h2>$stats.open</h2><p>open tickets</p>",
  xField: "row key for the X axis (numeric)",
  yField: "row key for the Y axis (numeric)",
  unit: "e.g. USD, %, ms",
  title: "optional chart title",
  url: "https://… (optional)",
  min: "0",
  max: "defaults to the largest row value",
};

function fieldValue(key: ChartOutputExpressionFieldKey): string {
  const value = selectedNode.value?.data[key];
  if (value !== undefined && value !== null) return String(value);
  if (selectedNode.value?.data.chartType === "gauge" && key === "max") return "100";
  return key === "min" ? "0" : "";
}

function removeOutgoingResultEdges(): void {
  for (const edge of outgoingResultEdges.value) workflowStore.removeEdge(edge.id);
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Chart type</Label>
      <Select
        data-testid="chart-output-type"
        :model-value="selectedNode.data.chartType || 'bar'"
        :options="options"
        @update:model-value="updateNodeData('chartType', $event)"
      />
      <p
        v-if="isActionResult && selectedNode.data.chartType !== 'html'"
        role="alert"
        class="text-xs text-destructive"
      >
        {{ CHART_ACTION_RESULT_TYPE_ERROR }}
      </p>
      <div
        v-if="outgoingResultEdges.length"
        class="space-y-1.5"
      >
        <p
          role="alert"
          class="text-xs text-destructive"
        >
          {{ CHART_ACTION_RESULT_OUTGOING_ERROR }}
        </p>
        <Button
          variant="outline"
          size="sm"
          :disabled="workflowStore.isReadOnly"
          @click="removeOutgoingResultEdges"
        >
          Remove outgoing connections
        </Button>
      </div>
    </div>
    <div
      v-if="selectedNode.data.chartType === 'bar'"
      class="space-y-2"
    >
      <Label>Orientation</Label>
      <Select
        :model-value="selectedNode.data.orientation || 'vertical'"
        :options="[{ value: 'vertical', label: 'Vertical' }, { value: 'horizontal', label: 'Horizontal' }]"
        @update:model-value="updateNodeData('orientation', $event)"
      />
    </div>
    <p
      v-if="structuredHint"
      class="text-xs text-muted-foreground"
    >
      {{ structuredHint }}
    </p>
    <template v-if="selectedNode.data.chartType === 'hitl'">
      <p class="text-xs text-muted-foreground">
        Shows your pending human reviews. The header reads 1/n pending. The name opens that run on the canvas.
        Approve, request changes, or reject from the card. The history icon beside the title opens that run.
      </p>
      <ChartOutputHitlFields />
    </template>
    <template v-if="selectedNode.data.chartType === 'table'">
      <ChartOutputStatusFields />
      <ChartOutputLinkFields />
    </template>
    <div
      v-for="field in fields"
      :key="field.key"
      class="space-y-2"
    >
      <Label>{{ field.label }}</Label>
      <ExpressionInput
        :ref="(el: unknown) => setChartOutputExpressionInputRef(field.key, el)"
        :model-value="fieldValue(field.key)"
        :placeholder="placeholders[field.key]"
        :rows="field.key === 'html' ? 8 : field.key === 'text' ? 5 : undefined"
        :single-line="!multiLine.has(field.key)"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        :dialog-key-label="field.label"
        :field-key="field.key"
        :navigation-enabled="chartOutputExpressionFieldCount > 1"
        :navigation-index="chartOutputExpressionFieldIndex(field.key)"
        :navigation-total="chartOutputExpressionFieldCount"
        @navigate="handleChartOutputExpressionFieldNavigate"
        @register-field-index="onChartOutputRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData(field.key, $event)"
      />
      <p
        v-if="field.key === 'text'"
        class="text-xs text-muted-foreground"
      >
        Markdown is supported. Leave empty and set a Value field to pull the message from upstream data.
      </p>
      <p
        v-if="field.key === 'html'"
        class="text-xs text-muted-foreground"
      >
        Runs in a sandboxed frame. Call <code>heym.action(message, data)</code> to send an event to the
        widget's Action branch. Leave empty and set a Value field to show HTML built upstream.
      </p>
      <p
        v-if="field.key === 'dataPath'"
        class="text-xs text-muted-foreground"
      >
        Dot path to the upstream rows, or the graph object for entity relationships. Leave empty to auto-detect.
      </p>
    </div>
  </template>
</template>
