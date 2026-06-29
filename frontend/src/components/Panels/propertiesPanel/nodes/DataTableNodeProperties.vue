<script setup lang="ts">
import { AlertTriangle, ExternalLink } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  dataTableColumns,
  dataTableSelectiveValues,
  dataTableRowIdExpressionInputRef,
  dataTableDataExpressionInputRef,
  dataTableFilterExpressionInputRef,
  dataTableSortExpressionInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  setDataTableSelectiveExpressionInputRef,
  switchDataTableRowDataToSelectiveMode,
  handleDataTableIdChangedForSelect,
  handleDataTableSelectiveColumnInput,
  dataTableExpressionFieldCount,
  handleDataTableExpressionFieldNavigate,
  onDataTableRegisterExpressionFieldIndex,
  dataTableOperationOptions,
  dataTableOptions,
  openDataTableInNewTab,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>DataTable</Label>
      <div class="group relative">
        <Select
          :model-value="selectedNode.data.dataTableId || ''"
          :options="dataTableOptions"
          :select-class="selectedNode.data.dataTableId ? 'pr-16' : undefined"
          @update:model-value="handleDataTableIdChangedForSelect"
        />
        <button
          v-if="selectedNode.data.dataTableId"
          type="button"
          class="absolute inset-y-0 right-9 z-10 flex items-center justify-center w-7 opacity-0 group-hover:opacity-100 transition-opacity duration-200 text-muted-foreground hover:text-foreground"
          title="Open in new tab"
          @click.stop="openDataTableInNewTab(selectedNode.data.dataTableId || '')"
        >
          <ExternalLink :size="14" />
        </button>
      </div>
      <p
        v-if="!selectedNode.data.dataTableId"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        DataTable is required.
      </p>
      <p class="text-xs text-muted-foreground mt-1">
        <a
          href="/?tab=datatable"
          class="font-medium text-violet-600 hover:underline dark:text-violet-400"
          @click.prevent="$router.push('/?tab=datatable')"
        >Manage DataTables</a> in Dashboard
      </p>
    </div>

    <div class="space-y-2">
      <Label>Operation</Label>
      <Select
        :model-value="selectedNode.data.dataTableOperation || ''"
        :options="dataTableOperationOptions"
        @update:model-value="updateNodeData('dataTableOperation', $event)"
      />
      <p
        v-if="!selectedNode.data.dataTableOperation"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Operation is required
      </p>
    </div>

    <!-- Row ID — for getById, update, remove -->
    <div
      v-if="['getById', 'update', 'remove'].includes(selectedNode.data.dataTableOperation || '')"
      class="space-y-2"
    >
      <Label>Row ID <span class="text-destructive">*</span></Label>
      <ExpressionInput
        ref="dataTableRowIdExpressionInputRef"
        :model-value="selectedNode.data.dataTableRowId || ''"
        placeholder="row-uuid"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :navigation-enabled="dataTableExpressionFieldCount > 1"
        :navigation-index="0"
        :navigation-total="dataTableExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Row ID"
        @navigate="handleDataTableExpressionFieldNavigate"
        @register-field-index="onDataTableRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('dataTableRowId', $event)"
      />
    </div>

    <!-- Row Data — for insert, update, upsert -->
    <div
      v-if="['insert', 'update', 'upsert'].includes(selectedNode.data.dataTableOperation || '')"
      class="space-y-2"
    >
      <div class="flex items-center justify-between">
        <Label>Row Data <span class="text-destructive">*</span></Label>
        <div
          v-if="dataTableColumns.length > 0"
          class="flex rounded border text-xs overflow-hidden"
        >
          <button
            class="px-2 py-0.5 transition-colors"
            :class="(selectedNode.data.dataTableInputMode || 'raw') === 'raw' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'"
            @click="updateNodeData('dataTableInputMode', 'raw')"
          >
            Raw
          </button>
          <button
            class="px-2 py-0.5 transition-colors"
            :class="selectedNode.data.dataTableInputMode === 'selective' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'"
            @click="switchDataTableRowDataToSelectiveMode"
          >
            Selective
          </button>
        </div>
      </div>

      <!-- Raw mode -->
      <template v-if="(selectedNode.data.dataTableInputMode || 'raw') === 'raw'">
        <ExpressionInput
          ref="dataTableDataExpressionInputRef"
          :model-value="selectedNode.data.dataTableData || '{}'"
          placeholder="{&#10;  &quot;column_name&quot;: &quot;value&quot;&#10;}"
          :rows="4"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          class="font-mono text-xs"
          :navigation-enabled="dataTableExpressionFieldCount > 1 && (selectedNode.data.dataTableInputMode || 'raw') === 'raw'"
          :navigation-index="selectedNode.data.dataTableOperation === 'upsert' ? 0 : 1"
          :navigation-total="dataTableExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Row data"
          @navigate="handleDataTableExpressionFieldNavigate"
          @register-field-index="onDataTableRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('dataTableData', $event)"
        />
        <div class="flex items-center justify-between">
          <p class="text-xs text-muted-foreground">
            JSON object mapping column names to values
          </p>
          <button
            class="text-xs text-primary hover:underline"
            @click="() => { try { const parsed = JSON.parse(selectedNode?.data.dataTableData || '{}'); updateNodeData('dataTableData', JSON.stringify(parsed, null, 2)); } catch {} }"
          >
            Format
          </button>
        </div>
      </template>

      <!-- Selective mode -->
      <template v-else>
        <div class="space-y-2">
          <div
            v-for="(col, colIdx) in dataTableColumns"
            :key="col.id"
            class="space-y-1"
          >
            <label class="text-xs text-muted-foreground flex items-center gap-1">
              {{ col.name }}
              <span class="text-[10px] text-muted-foreground/60">({{ col.type }})</span>
              <span
                v-if="col.required"
                class="text-destructive"
              >*</span>
            </label>
            <ExpressionInput
              :ref="(el) => setDataTableSelectiveExpressionInputRef(col.name, el)"
              :model-value="dataTableSelectiveValues[col.name] || ''"
              :placeholder="col.type === 'boolean' ? 'true / false' : col.type === 'number' ? '0' : col.type === 'json' ? '{}' : ''"
              :rows="col.type === 'json' ? 2 : 1"
              :nodes="workflowStore.nodes"
              :node-results="workflowStore.nodeResults"
              :edges="workflowStore.edges"
              :current-node-id="selectedNode.id"
              :navigation-enabled="dataTableExpressionFieldCount > 1"
              :navigation-index="
                selectedNode.data.dataTableOperation === 'update'
                  ? 1 + colIdx
                  : colIdx
              "
              :navigation-total="dataTableExpressionFieldCount"
              :dialog-node-label="selectedNodeEvaluateDialogLabel"
              :dialog-key-label="`Row data: ${col.name}`"
              @navigate="handleDataTableExpressionFieldNavigate"
              @register-field-index="onDataTableRegisterExpressionFieldIndex"
              @update:model-value="handleDataTableSelectiveColumnInput(col.name, $event)"
            />
          </div>
        </div>
      </template>
    </div>

    <!-- Filter — for find, upsert, count -->
    <div
      v-if="['find', 'upsert', 'count'].includes(selectedNode.data.dataTableOperation || '')"
      class="space-y-2"
    >
      <div class="flex items-center justify-between">
        <Label>Filter (JSON)</Label>
        <button
          class="text-xs font-medium text-violet-600 hover:underline dark:text-violet-400"
          @click="() => { try { const parsed = JSON.parse(selectedNode?.data.dataTableFilter || '{}'); updateNodeData('dataTableFilter', JSON.stringify(parsed, null, 2)); } catch {} }"
        >
          Format
        </button>
      </div>
      <ExpressionInput
        ref="dataTableFilterExpressionInputRef"
        :model-value="selectedNode.data.dataTableFilter || '{}'"
        placeholder="{&#10;  &quot;column_name&quot;: &quot;value&quot;&#10;}"
        :rows="3"
        class="font-mono text-xs"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :navigation-enabled="dataTableExpressionFieldCount > 1"
        :navigation-index="
          ['find', 'count'].includes(selectedNode.data.dataTableOperation || '')
            ? 0
            : (selectedNode.data.dataTableInputMode || 'raw') === 'raw'
              ? 1
              : dataTableColumns.length
        "
        :navigation-total="dataTableExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Filter"
        @navigate="handleDataTableExpressionFieldNavigate"
        @register-field-index="onDataTableRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('dataTableFilter', $event)"
      />
      <p class="text-xs text-muted-foreground">
        <template v-if="['find', 'count'].includes(selectedNode.data.dataTableOperation || '')">
          Plain value = equals. Use operators like
          <code>{"age": {"$gt": 18}}</code>
          or
          <code>{"created_at": {"$contains": "2026-06"}}</code>.
        </template>
        <template v-else>
          Exact-match lookup for upsert:
          <code>{"column": "$input.value"}</code>
        </template>
      </p>
    </div>

    <!-- Sort — for find, getAll -->
    <div
      v-if="['find', 'getAll'].includes(selectedNode.data.dataTableOperation || '')"
      class="space-y-2"
    >
      <Label>Sort</Label>
      <ExpressionInput
        ref="dataTableSortExpressionInputRef"
        :model-value="selectedNode.data.dataTableSort || ''"
        placeholder="column_name or -column_name"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :navigation-enabled="dataTableExpressionFieldCount > 1"
        :navigation-index="selectedNode.data.dataTableOperation === 'find' ? 1 : 0"
        :navigation-total="dataTableExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Sort"
        @navigate="handleDataTableExpressionFieldNavigate"
        @register-field-index="onDataTableRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('dataTableSort', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Prefix with - for descending (e.g. -created_at)
      </p>
    </div>

    <!-- Limit — for find, getAll -->
    <div
      v-if="['find', 'getAll'].includes(selectedNode.data.dataTableOperation || '')"
      class="space-y-2"
    >
      <Label>Limit</Label>
      <Input
        type="number"
        :model-value="selectedNode.data.dataTableLimit ?? ''"
        placeholder="No limit"
        min="0"
        @update:model-value="updateNodeData('dataTableLimit', $event ? parseInt(String($event)) : null)"
      />
      <p class="text-xs text-muted-foreground">
        Leave empty for no limit
      </p>
    </div>

    <!-- Output schema -->
    <div class="space-y-2 mt-3">
      <Label class="text-xs font-medium text-muted-foreground">Output Schema</Label>
      <div class="text-xs font-mono text-muted-foreground space-y-0.5 bg-muted/30 p-2 rounded">
        <template v-if="selectedNode.data.dataTableOperation === 'find'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.rows - Array of rows</div>
          <div>${{ selectedNode.data.label }}.count - Number of rows</div>
        </template>
        <template v-else-if="selectedNode.data.dataTableOperation === 'getAll'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.rows - Array of rows</div>
          <div>${{ selectedNode.data.label }}.count - Number of rows</div>
        </template>
        <template v-else-if="selectedNode.data.dataTableOperation === 'getById'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.row - Row object</div>
          <div>${{ selectedNode.data.label }}.found - Boolean</div>
        </template>
        <template v-else-if="selectedNode.data.dataTableOperation === 'insert'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.row - Created row</div>
          <div>${{ selectedNode.data.label }}.id - New row ID</div>
        </template>
        <template v-else-if="selectedNode.data.dataTableOperation === 'update'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.row - Updated row</div>
          <div>${{ selectedNode.data.label }}.id - Row ID</div>
        </template>
        <template v-else-if="selectedNode.data.dataTableOperation === 'remove'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.id - Deleted row ID</div>
        </template>
        <template v-else-if="selectedNode.data.dataTableOperation === 'upsert'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.row - Row object</div>
          <div>${{ selectedNode.data.label }}.operation - "insert" or "update"</div>
        </template>
        <template v-else>
          <div>Select an operation to see output fields</div>
        </template>
      </div>
    </div>
  </template>
</template>
