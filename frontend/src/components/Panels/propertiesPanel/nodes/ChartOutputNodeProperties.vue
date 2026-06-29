<script setup lang="ts">
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  chartOutputExpressionFieldCount,
  chartOutputExpressionFieldIndex,
  setChartOutputExpressionInputRef,
  handleChartOutputExpressionFieldNavigate,
  onChartOutputRegisterExpressionFieldIndex,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Chart type</Label>
      <Select
        :model-value="selectedNode.data.chartType || 'bar'"
        :options="[
          { value: 'bar', label: 'Bar' },
          { value: 'line', label: 'Line' },
          { value: 'area', label: 'Area' },
          { value: 'pie', label: 'Pie' },
          { value: 'table', label: 'Table' },
          { value: 'numeric', label: 'Numeric' },
          { value: 'gauge', label: 'Gauge' },
          { value: 'scatter', label: 'Scatter' },
          { value: 'proportion', label: 'Proportion' },
          { value: 'barGauge', label: 'Bar gauge' },
          { value: 'text', label: 'Text' },
        ]"
        @update:model-value="updateNodeData('chartType', $event)"
      />
    </div>

    <div
      v-if="selectedNode.data.chartType === 'text'"
      class="space-y-2"
    >
      <Label>Text (markdown)</Label>
      <ExpressionInput
        :ref="(el: unknown) => setChartOutputExpressionInputRef('text', el)"
        :model-value="selectedNode.data.text || ''"
        :rows="5"
        placeholder="e.g. **Last execution** at `19:47`"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Text (markdown)"
        field-key="text"
        :navigation-enabled="chartOutputExpressionFieldCount > 1"
        :navigation-index="chartOutputExpressionFieldIndex('text')"
        :navigation-total="chartOutputExpressionFieldCount"
        @navigate="handleChartOutputExpressionFieldNavigate"
        @register-field-index="onChartOutputRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('text', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Markdown is supported. Leave empty and set a Value field below to pull the message
        from upstream data instead.
      </p>
    </div>

    <div
      v-if="selectedNode.data.chartType === 'text'"
      class="space-y-2"
    >
      <Label>Value field (optional)</Label>
      <ExpressionInput
        :ref="(el: unknown) => setChartOutputExpressionInputRef('valueField', el)"
        :model-value="selectedNode.data.valueField || ''"
        placeholder="row key holding the markdown string"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Value field"
        field-key="valueField"
        :navigation-enabled="chartOutputExpressionFieldCount > 1"
        :navigation-index="chartOutputExpressionFieldIndex('valueField')"
        :navigation-total="chartOutputExpressionFieldCount"
        @navigate="handleChartOutputExpressionFieldNavigate"
        @register-field-index="onChartOutputRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('valueField', $event)"
      />
    </div>

    <div
      v-if="selectedNode.data.chartType === 'bar'"
      class="space-y-2"
    >
      <Label>Orientation</Label>
      <Select
        :model-value="selectedNode.data.orientation || 'vertical'"
        :options="[
          { value: 'vertical', label: 'Vertical' },
          { value: 'horizontal', label: 'Horizontal' },
        ]"
        @update:model-value="updateNodeData('orientation', $event)"
      />
    </div>

    <div class="space-y-2">
      <Label>Data path</Label>
      <ExpressionInput
        :ref="(el: unknown) => setChartOutputExpressionInputRef('dataPath', el)"
        :model-value="selectedNode.data.dataPath || ''"
        placeholder="e.g. data or result.items"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Data path"
        field-key="dataPath"
        :navigation-enabled="chartOutputExpressionFieldCount > 1"
        :navigation-index="chartOutputExpressionFieldIndex('dataPath')"
        :navigation-total="chartOutputExpressionFieldCount"
        @navigate="handleChartOutputExpressionFieldNavigate"
        @register-field-index="onChartOutputRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('dataPath', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Dot path to the rows array inside the upstream output. Leave empty to auto-detect.
      </p>
    </div>

    <template
      v-if="['bar', 'line', 'area', 'pie', 'numeric', 'gauge', 'proportion', 'barGauge'].includes(selectedNode.data.chartType || 'bar')"
    >
      <div
        v-if="['bar', 'line', 'area', 'pie', 'proportion', 'barGauge'].includes(selectedNode.data.chartType || 'bar')"
        class="space-y-2"
      >
        <Label>Label field</Label>
        <ExpressionInput
          :ref="(el: unknown) => setChartOutputExpressionInputRef('labelField', el)"
          :model-value="selectedNode.data.labelField || ''"
          placeholder="row key used as category label"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Label field"
          field-key="labelField"
          :navigation-enabled="chartOutputExpressionFieldCount > 1"
          :navigation-index="chartOutputExpressionFieldIndex('labelField')"
          :navigation-total="chartOutputExpressionFieldCount"
          @navigate="handleChartOutputExpressionFieldNavigate"
          @register-field-index="onChartOutputRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('labelField', $event)"
        />
      </div>

      <div class="space-y-2">
        <Label>Value field</Label>
        <ExpressionInput
          :ref="(el: unknown) => setChartOutputExpressionInputRef('valueField', el)"
          :model-value="selectedNode.data.valueField || ''"
          placeholder="row key used as numeric value"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Value field"
          field-key="valueField"
          :navigation-enabled="chartOutputExpressionFieldCount > 1"
          :navigation-index="chartOutputExpressionFieldIndex('valueField')"
          :navigation-total="chartOutputExpressionFieldCount"
          @navigate="handleChartOutputExpressionFieldNavigate"
          @register-field-index="onChartOutputRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('valueField', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.chartType === 'scatter'">
      <div class="space-y-2">
        <Label>X field</Label>
        <ExpressionInput
          :ref="(el: unknown) => setChartOutputExpressionInputRef('xField', el)"
          :model-value="selectedNode.data.xField || ''"
          placeholder="row key for the X axis (numeric)"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="X field"
          field-key="xField"
          :navigation-enabled="chartOutputExpressionFieldCount > 1"
          :navigation-index="chartOutputExpressionFieldIndex('xField')"
          :navigation-total="chartOutputExpressionFieldCount"
          @navigate="handleChartOutputExpressionFieldNavigate"
          @register-field-index="onChartOutputRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('xField', $event)"
        />
      </div>
      <div class="space-y-2">
        <Label>Y field</Label>
        <ExpressionInput
          :ref="(el: unknown) => setChartOutputExpressionInputRef('yField', el)"
          :model-value="selectedNode.data.yField || ''"
          placeholder="row key for the Y axis (numeric)"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Y field"
          field-key="yField"
          :navigation-enabled="chartOutputExpressionFieldCount > 1"
          :navigation-index="chartOutputExpressionFieldIndex('yField')"
          :navigation-total="chartOutputExpressionFieldCount"
          @navigate="handleChartOutputExpressionFieldNavigate"
          @register-field-index="onChartOutputRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('yField', $event)"
        />
      </div>
    </template>

    <div
      v-if="selectedNode.data.chartType === 'gauge'"
      class="grid grid-cols-2 gap-2"
    >
      <div class="space-y-2">
        <Label>Min</Label>
        <ExpressionInput
          :ref="(el: unknown) => setChartOutputExpressionInputRef('min', el)"
          :model-value="String(selectedNode.data.min ?? 0)"
          placeholder="0"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Min"
          field-key="min"
          :navigation-enabled="chartOutputExpressionFieldCount > 1"
          :navigation-index="chartOutputExpressionFieldIndex('min')"
          :navigation-total="chartOutputExpressionFieldCount"
          @navigate="handleChartOutputExpressionFieldNavigate"
          @register-field-index="onChartOutputRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('min', $event)"
        />
      </div>
      <div class="space-y-2">
        <Label>Max</Label>
        <ExpressionInput
          :ref="(el: unknown) => setChartOutputExpressionInputRef('max', el)"
          :model-value="String(selectedNode.data.max ?? 100)"
          placeholder="100"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Max"
          field-key="max"
          :navigation-enabled="chartOutputExpressionFieldCount > 1"
          :navigation-index="chartOutputExpressionFieldIndex('max')"
          :navigation-total="chartOutputExpressionFieldCount"
          @navigate="handleChartOutputExpressionFieldNavigate"
          @register-field-index="onChartOutputRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('max', $event)"
        />
      </div>
    </div>

    <div
      v-if="selectedNode.data.chartType === 'barGauge'"
      class="space-y-2"
    >
      <Label>Max (optional)</Label>
      <ExpressionInput
        :ref="(el: unknown) => setChartOutputExpressionInputRef('max', el)"
        :model-value="selectedNode.data.max === undefined || selectedNode.data.max === null ? '' : String(selectedNode.data.max)"
        placeholder="defaults to the largest row value"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Max"
        field-key="max"
        :navigation-enabled="chartOutputExpressionFieldCount > 1"
        :navigation-index="chartOutputExpressionFieldIndex('max')"
        :navigation-total="chartOutputExpressionFieldCount"
        @navigate="handleChartOutputExpressionFieldNavigate"
        @register-field-index="onChartOutputRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('max', $event)"
      />
    </div>

    <div
      v-if="['numeric', 'gauge', 'barGauge'].includes(selectedNode.data.chartType || 'bar')"
      class="space-y-2"
    >
      <Label>Unit</Label>
      <ExpressionInput
        :ref="(el: unknown) => setChartOutputExpressionInputRef('unit', el)"
        :model-value="selectedNode.data.unit || ''"
        placeholder="e.g. USD, %, ms"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Unit"
        field-key="unit"
        :navigation-enabled="chartOutputExpressionFieldCount > 1"
        :navigation-index="chartOutputExpressionFieldIndex('unit')"
        :navigation-total="chartOutputExpressionFieldCount"
        @navigate="handleChartOutputExpressionFieldNavigate"
        @register-field-index="onChartOutputRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('unit', $event)"
      />
    </div>

    <div class="space-y-2">
      <Label>Title</Label>
      <ExpressionInput
        :ref="(el: unknown) => setChartOutputExpressionInputRef('title', el)"
        :model-value="selectedNode.data.title || ''"
        placeholder="optional chart title"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Title"
        field-key="title"
        :navigation-enabled="chartOutputExpressionFieldCount > 1"
        :navigation-index="chartOutputExpressionFieldIndex('title')"
        :navigation-total="chartOutputExpressionFieldCount"
        @navigate="handleChartOutputExpressionFieldNavigate"
        @register-field-index="onChartOutputRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('title', $event)"
      />
    </div>

    <div class="space-y-2">
      <Label>Website URL</Label>
      <ExpressionInput
        :ref="(el: unknown) => setChartOutputExpressionInputRef('url', el)"
        :model-value="selectedNode.data.url || ''"
        placeholder="https://… (optional)"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Website URL"
        field-key="url"
        :navigation-enabled="chartOutputExpressionFieldCount > 1"
        :navigation-index="chartOutputExpressionFieldIndex('url')"
        :navigation-total="chartOutputExpressionFieldCount"
        @navigate="handleChartOutputExpressionFieldNavigate"
        @register-field-index="onChartOutputRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('url', $event)"
      />
    </div>
  </template>
</template>
