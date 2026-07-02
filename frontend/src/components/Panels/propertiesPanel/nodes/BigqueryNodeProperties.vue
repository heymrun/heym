<script setup lang="ts">
import { AlertTriangle, Minus, Plus } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  isWorkflowOwner,
  bqProjectIdExpressionInputRef,
  bqQueryExpressionInputRef,
  bqDatasetIdExpressionInputRef,
  bqTableIdExpressionInputRef,
  bqRowsExpressionInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  bigQueryExpressionFieldCount,
  handleBigQueryExpressionFieldNavigate,
  onBigQueryRegisterExpressionFieldIndex,
  bqMappingInputRef,
  bigQueryCredentialOptions,
  bigQueryOperationOptions,
  updateNodeData,
  bqMappings,
  addBqMapping,
  updateBqMapping,
  removeBqMapping,
  switchBqToRaw,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>BigQuery Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="bigQueryCredentialOptions"
        :disabled="!isWorkflowOwner"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <div v-if="!selectedNode.data.credentialId">
        <p class="text-xs text-amber-500 flex items-center gap-1">
          <AlertTriangle class="h-3 w-3" />
          Credential is required.
        </p>
        <p class="text-xs text-muted-foreground mt-1">
          <a
            href="/?tab=credentials"
            class="text-primary hover:underline"
            @click.prevent="$router.push('/?tab=credentials')"
          >Add credentials</a> in Dashboard
        </p>
      </div>
    </div>

    <div class="space-y-2">
      <Label>Operation</Label>
      <Select
        :model-value="selectedNode.data.bqOperation || ''"
        :options="bigQueryOperationOptions"
        @update:model-value="updateNodeData('bqOperation', $event)"
      />
    </div>

    <template v-if="selectedNode.data.bqOperation">
      <div class="space-y-2">
        <Label>Project ID</Label>
        <ExpressionInput
          ref="bqProjectIdExpressionInputRef"
          :model-value="selectedNode.data.bqProjectId || ''"
          placeholder="my-gcp-project"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="bigQueryExpressionFieldCount > 1"
          :navigation-index="0"
          :navigation-total="bigQueryExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Project ID"
          @update:model-value="updateNodeData('bqProjectId', $event)"
          @navigate="handleBigQueryExpressionFieldNavigate"
          @register-field-index="onBigQueryRegisterExpressionFieldIndex"
        />
      </div>

      <!-- query operation fields -->
      <template v-if="selectedNode.data.bqOperation === 'query'">
        <div class="space-y-2">
          <Label>SQL Query</Label>
          <ExpressionInput
            ref="bqQueryExpressionInputRef"
            :model-value="selectedNode.data.bqQuery || ''"
            placeholder="SELECT * FROM `dataset.table` LIMIT 10"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :navigation-enabled="bigQueryExpressionFieldCount > 1"
            :navigation-index="1"
            :navigation-total="bigQueryExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="SQL Query"
            field-key="bqQuery"
            @update:model-value="updateNodeData('bqQuery', $event)"
            @navigate="handleBigQueryExpressionFieldNavigate"
            @register-field-index="onBigQueryRegisterExpressionFieldIndex"
          />
        </div>
        <div class="space-y-2">
          <Label>Max Results <span class="text-muted-foreground font-normal">(0 = unlimited)</span></Label>
          <input
            type="number"
            min="0"
            :value="selectedNode.data.bqMaxResults ?? '1000'"
            placeholder="1000"
            class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            @input="updateNodeData('bqMaxResults', String(($event.target as HTMLInputElement).value))"
          >
        </div>
      </template>

      <!-- insertRows operation fields -->
      <template v-if="selectedNode.data.bqOperation === 'insertRows'">
        <div class="space-y-2">
          <Label>Dataset ID</Label>
          <ExpressionInput
            ref="bqDatasetIdExpressionInputRef"
            :model-value="selectedNode.data.bqDatasetId || ''"
            placeholder="my_dataset"
            single-line
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :navigation-enabled="bigQueryExpressionFieldCount > 1"
            :navigation-index="1"
            :navigation-total="bigQueryExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Dataset ID"
            @update:model-value="updateNodeData('bqDatasetId', $event)"
            @navigate="handleBigQueryExpressionFieldNavigate"
            @register-field-index="onBigQueryRegisterExpressionFieldIndex"
          />
        </div>
        <div class="space-y-2">
          <Label>Table ID</Label>
          <ExpressionInput
            ref="bqTableIdExpressionInputRef"
            :model-value="selectedNode.data.bqTableId || ''"
            placeholder="my_table"
            single-line
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :navigation-enabled="bigQueryExpressionFieldCount > 1"
            :navigation-index="2"
            :navigation-total="bigQueryExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Table ID"
            @update:model-value="updateNodeData('bqTableId', $event)"
            @navigate="handleBigQueryExpressionFieldNavigate"
            @register-field-index="onBigQueryRegisterExpressionFieldIndex"
          />
        </div>

        <!-- Row input mode toggle -->
        <div class="flex items-center gap-2 rounded-md border border-input p-1">
          <button
            :class="[
              'flex-1 rounded text-xs py-1 transition-colors',
              (selectedNode.data.bqRowsInputMode || 'raw') === 'raw'
                ? 'bg-primary text-primary-foreground font-medium'
                : 'text-muted-foreground hover:text-foreground'
            ]"
            @click="switchBqToRaw()"
          >
            JSON array
          </button>
          <button
            :class="[
              'flex-1 rounded text-xs py-1 transition-colors',
              selectedNode.data.bqRowsInputMode === 'selective'
                ? 'bg-primary text-primary-foreground font-medium'
                : 'text-muted-foreground hover:text-foreground'
            ]"
            @click="updateNodeData('bqRowsInputMode', 'selective')"
          >
            Key-value
          </button>
        </div>

        <!-- Raw JSON array mode -->
        <div
          v-if="(selectedNode.data.bqRowsInputMode || 'raw') === 'raw'"
          class="space-y-2"
        >
          <Label>Rows (JSON array)</Label>
          <ExpressionInput
            ref="bqRowsExpressionInputRef"
            :model-value="selectedNode.data.bqRows || '[]'"
            placeholder="[{&quot;col&quot;: &quot;$input.value&quot;}]"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :navigation-enabled="bigQueryExpressionFieldCount > 1"
            :navigation-index="3"
            :navigation-total="bigQueryExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Rows"
            field-key="bqRows"
            @update:model-value="updateNodeData('bqRows', $event)"
            @navigate="handleBigQueryExpressionFieldNavigate"
            @register-field-index="onBigQueryRegisterExpressionFieldIndex"
          />
          <p class="text-xs text-muted-foreground">
            JSON array of row objects; each key must match a column name in the table.
          </p>
        </div>

        <!-- Selective key-value mode -->
        <div
          v-else
          class="space-y-3"
        >
          <div class="flex items-center justify-between">
            <Label>Row fields</Label>
            <Button
              variant="ghost"
              size="sm"
              class="h-11 min-h-[44px] md:h-7 px-2"
              @click="addBqMapping"
            >
              <Plus class="w-3 h-3 mr-1" />
              Add
            </Button>
          </div>
          <div
            v-for="(mapping, index) in bqMappings"
            :key="index"
            class="flex gap-1 items-center"
          >
            <Input
              :model-value="mapping.key"
              placeholder="column"
              class="w-24 shrink-0 font-mono text-xs"
              @update:model-value="updateBqMapping(index, 'key', $event)"
            />
            <span class="text-muted-foreground text-xs">=</span>
            <ExpressionInput
              :ref="(el: any) => bqMappingInputRef(index, el)"
              :model-value="mapping.value"
              :placeholder="exampleRef"
              single-line
              class="flex-1 text-xs"
              :nodes="workflowStore.nodes"
              :node-results="workflowStore.nodeResults"
              :edges="workflowStore.edges"
              :current-node-id="selectedNode.id"
              :navigation-enabled="bigQueryExpressionFieldCount > 1"
              :navigation-index="index + 3"
              :navigation-total="bigQueryExpressionFieldCount"
              :dialog-node-label="selectedNodeEvaluateDialogLabel"
              :dialog-key-label="mapping.key || `field ${index + 1}`"
              @update:model-value="updateBqMapping(index, 'value', $event)"
              @navigate="handleBigQueryExpressionFieldNavigate"
              @register-field-index="onBigQueryRegisterExpressionFieldIndex"
            />
            <Button
              variant="ghost"
              size="icon"
              class="h-10 w-7 text-destructive shrink-0"
              @click="removeBqMapping(index)"
            >
              <Minus class="w-3 h-3" />
            </Button>
          </div>
          <p class="text-xs text-muted-foreground">
            One row is inserted per execution. Add a field for each column.
          </p>
        </div>
      </template>
    </template>

    <div class="rounded-md bg-muted/40 border p-3 space-y-1">
      <p class="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        Output
      </p>
      <div class="text-xs font-mono space-y-0.5">
        <template v-if="selectedNode.data.bqOperation === 'query'">
          <div>${{ selectedNode.data.label }}.rows - Array of row objects</div>
          <div>${{ selectedNode.data.label }}.total - Number of rows returned</div>
          <div>${{ selectedNode.data.label }}.schema - Table schema fields</div>
        </template>
        <template v-else-if="selectedNode.data.bqOperation === 'insertRows'">
          <div>${{ selectedNode.data.label }}.insertedCount - Number of rows inserted</div>
          <div>${{ selectedNode.data.label }}.errors - Array of insertion errors (empty on success)</div>
        </template>
        <template v-else>
          <div>Select an operation to see output fields</div>
        </template>
      </div>
    </div>
  </template>
</template>
