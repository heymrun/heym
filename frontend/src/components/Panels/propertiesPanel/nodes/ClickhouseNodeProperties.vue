<script setup lang="ts">
import { AlertTriangle, Loader2 } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  isWorkflowOwner,
  clickhouseDiscoveredColumns,
  loadingClickhouseColumns,
  clickhouseQueryExpressionInputRef,
  clickhouseTableExpressionInputRef,
  clickhouseFilterExpressionInputRef,
  clickhouseSortExpressionInputRef,
  clickhouseRowIdExpressionInputRef,
  clickhouseDataExpressionInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  clickhouseExpressionFieldCount,
  handleClickhouseExpressionFieldNavigate,
  onClickhouseRegisterExpressionFieldIndex,
  clickhouseMappingInputRef,
  clickhouseMappings,
  updateClickhouseMappingValue,
  switchClickhouseToRaw,
  clickhouseCredentialOptions,
  clickhouseOperationGroups,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>ClickHouse Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="clickhouseCredentialOptions"
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
      <SearchableSelect
        :model-value="selectedNode.data.clickhouseOperation || ''"
        :groups="clickhouseOperationGroups"
        search-placeholder="Search ClickHouse operations..."
        @update:model-value="updateNodeData('clickhouseOperation', $event)"
      />
    </div>

    <template v-if="selectedNode.data.clickhouseOperation === 'query'">
      <div class="space-y-2">
        <Label>SQL Query</Label>
        <ExpressionInput
          ref="clickhouseQueryExpressionInputRef"
          :model-value="selectedNode.data.clickhouseQuery || ''"
          placeholder="SELECT * FROM events LIMIT 10"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="clickhouseQuery"
          :navigation-enabled="clickhouseExpressionFieldCount > 1"
          :navigation-index="0"
          :navigation-total="clickhouseExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="SQL Query"
          @update:model-value="updateNodeData('clickhouseQuery', $event)"
          @navigate="handleClickhouseExpressionFieldNavigate"
          @register-field-index="onClickhouseRegisterExpressionFieldIndex"
        />
        <p class="text-xs text-muted-foreground">
          SELECT/SHOW return rows; other statements (INSERT, ALTER, DELETE) run as commands.
        </p>
      </div>
    </template>

    <template v-else-if="selectedNode.data.clickhouseOperation">
      <div class="space-y-2">
        <Label>Table</Label>
        <ExpressionInput
          ref="clickhouseTableExpressionInputRef"
          :model-value="selectedNode.data.clickhouseTable || ''"
          placeholder="events"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="clickhouseTable"
          :navigation-enabled="clickhouseExpressionFieldCount > 1"
          :navigation-index="0"
          :navigation-total="clickhouseExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Table"
          @update:model-value="updateNodeData('clickhouseTable', $event)"
          @navigate="handleClickhouseExpressionFieldNavigate"
          @register-field-index="onClickhouseRegisterExpressionFieldIndex"
        />
      </div>

      <div
        v-if="['find', 'count', 'update', 'remove'].includes(String(selectedNode.data.clickhouseOperation))"
        class="space-y-2"
      >
        <Label>Filter (JSON object)</Label>
        <ExpressionInput
          ref="clickhouseFilterExpressionInputRef"
          :model-value="selectedNode.data.clickhouseFilter || '{}'"
          placeholder="{&quot;status&quot;:&quot;active&quot;}"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="clickhouseFilter"
          :navigation-enabled="clickhouseExpressionFieldCount > 1"
          :navigation-index="selectedNode.data.clickhouseOperation === 'update' ? 2 : 1"
          :navigation-total="clickhouseExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Filter"
          @update:model-value="updateNodeData('clickhouseFilter', $event)"
          @navigate="handleClickhouseExpressionFieldNavigate"
          @register-field-index="onClickhouseRegisterExpressionFieldIndex"
        />
        <p
          v-if="['update', 'remove'].includes(String(selectedNode.data.clickhouseOperation))"
          class="text-xs text-amber-500"
        >
          Required. ClickHouse {{ selectedNode.data.clickhouseOperation }} runs as an
          asynchronous mutation; a filter prevents a full-table change.
        </p>
      </div>

      <div
        v-if="selectedNode.data.clickhouseOperation === 'getById'"
        class="space-y-2"
      >
        <Label>Row ID</Label>
        <ExpressionInput
          ref="clickhouseRowIdExpressionInputRef"
          :model-value="selectedNode.data.clickhouseRowId || ''"
          placeholder="$input.id"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="clickhouseRowId"
          :navigation-enabled="clickhouseExpressionFieldCount > 1"
          :navigation-index="1"
          :navigation-total="clickhouseExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Row ID"
          @update:model-value="updateNodeData('clickhouseRowId', $event)"
          @navigate="handleClickhouseExpressionFieldNavigate"
          @register-field-index="onClickhouseRegisterExpressionFieldIndex"
        />
        <p class="text-xs text-muted-foreground">
          Matched against the table's `id` column.
        </p>
      </div>

      <div
        v-if="selectedNode.data.clickhouseOperation === 'find'"
        class="space-y-2"
      >
        <Label>Sort</Label>
        <ExpressionInput
          ref="clickhouseSortExpressionInputRef"
          :model-value="selectedNode.data.clickhouseSort || ''"
          placeholder="created_at DESC"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="clickhouseSort"
          :navigation-enabled="clickhouseExpressionFieldCount > 1"
          :navigation-index="2"
          :navigation-total="clickhouseExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Sort"
          @update:model-value="updateNodeData('clickhouseSort', $event)"
          @navigate="handleClickhouseExpressionFieldNavigate"
          @register-field-index="onClickhouseRegisterExpressionFieldIndex"
        />
      </div>

      <div
        v-if="['find', 'getAll'].includes(String(selectedNode.data.clickhouseOperation))"
        class="space-y-2"
      >
        <Label>Limit <span class="text-muted-foreground font-normal">(0 = unlimited)</span></Label>
        <input
          type="number"
          min="0"
          :value="selectedNode.data.clickhouseLimit ?? '100'"
          placeholder="100"
          class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          @input="updateNodeData('clickhouseLimit', String(($event.target as HTMLInputElement).value))"
        >
      </div>

      <template v-if="selectedNode.data.clickhouseOperation === 'update'">
        <div class="space-y-2">
          <Label>Data (JSON object)</Label>
          <ExpressionInput
            ref="clickhouseDataExpressionInputRef"
            :model-value="selectedNode.data.clickhouseData || '{}'"
            placeholder="{&quot;status&quot;:&quot;archived&quot;}"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="clickhouseData"
            :navigation-enabled="clickhouseExpressionFieldCount > 1"
            :navigation-index="1"
            :navigation-total="clickhouseExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Data"
            @update:model-value="updateNodeData('clickhouseData', $event)"
            @navigate="handleClickhouseExpressionFieldNavigate"
            @register-field-index="onClickhouseRegisterExpressionFieldIndex"
          />
          <p class="text-xs text-muted-foreground">
            JSON object of column values to set on matching rows.
          </p>
        </div>
      </template>

      <template
        v-if="['insert', 'upsert'].includes(String(selectedNode.data.clickhouseOperation))"
      >
        <div class="flex items-center gap-2 rounded-md border border-input p-1">
          <button
            :class="[
              'flex-1 rounded text-xs py-1 transition-colors',
              (selectedNode.data.clickhouseInputMode || 'raw') === 'raw'
                ? 'bg-primary text-primary-foreground font-medium'
                : 'text-muted-foreground hover:text-foreground'
            ]"
            @click="switchClickhouseToRaw()"
          >
            JSON array
          </button>
          <button
            :class="[
              'flex-1 rounded text-xs py-1 transition-colors',
              selectedNode.data.clickhouseInputMode === 'selective'
                ? 'bg-primary text-primary-foreground font-medium'
                : 'text-muted-foreground hover:text-foreground'
            ]"
            @click="updateNodeData('clickhouseInputMode', 'selective')"
          >
            Key-value
          </button>
        </div>

        <div
          v-if="(selectedNode.data.clickhouseInputMode || 'raw') === 'raw'"
          class="space-y-2"
        >
          <Label>Rows (JSON array)</Label>
          <ExpressionInput
            ref="clickhouseDataExpressionInputRef"
            :model-value="selectedNode.data.clickhouseData || '[]'"
            placeholder="[{&quot;id&quot;: &quot;$input.id&quot;, &quot;event&quot;: &quot;signup&quot;}]"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="clickhouseData"
            :navigation-enabled="clickhouseExpressionFieldCount > 1"
            :navigation-index="1"
            :navigation-total="clickhouseExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Rows"
            @update:model-value="updateNodeData('clickhouseData', $event)"
            @navigate="handleClickhouseExpressionFieldNavigate"
            @register-field-index="onClickhouseRegisterExpressionFieldIndex"
          />
          <p class="text-xs text-muted-foreground">
            JSON array of row objects; each key must match a column in the table.
          </p>
        </div>

        <div
          v-else
          class="space-y-3"
        >
          <div
            v-if="loadingClickhouseColumns && clickhouseMappings.length === 0"
            class="flex h-9 items-center"
            title="Loading ClickHouse columns"
          >
            <Loader2 class="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
          <template v-else>
            <div
              v-for="(mapping, index) in clickhouseMappings"
              :key="mapping.key"
              class="flex gap-2 items-center"
            >
              <div
                class="h-9 w-28 shrink-0 truncate rounded-md border border-input bg-muted/40 px-2 py-2 font-mono text-xs"
                :title="clickhouseDiscoveredColumns.find((col) => col.name === mapping.key)?.type || mapping.key"
              >
                {{ mapping.key }}
              </div>
              <span class="text-muted-foreground text-xs">=</span>
              <ExpressionInput
                :ref="(el: any) => clickhouseMappingInputRef(mapping.key, el)"
                :model-value="mapping.value"
                :placeholder="exampleRef"
                single-line
                class="flex-1 text-xs"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :navigation-enabled="clickhouseExpressionFieldCount > 1"
                :navigation-index="index + 1"
                :navigation-total="clickhouseExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                :dialog-key-label="mapping.key"
                @update:model-value="updateClickhouseMappingValue(index, $event)"
                @navigate="handleClickhouseExpressionFieldNavigate"
                @register-field-index="onClickhouseRegisterExpressionFieldIndex"
              />
            </div>
          </template>
        </div>
      </template>
    </template>

    <div class="rounded-md bg-muted/40 border p-3 space-y-1">
      <p class="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        Output
      </p>
      <div class="text-xs font-mono space-y-0.5">
        <div>${{ selectedNode.data.label }}.rows - Returned row objects (read ops)</div>
        <div>${{ selectedNode.data.label }}.count - Row count (find/getAll/count/insert)</div>
        <div>${{ selectedNode.data.label }}.row - Single row (getById)</div>
        <div>${{ selectedNode.data.label }}.success - Boolean success flag</div>
      </div>
    </div>
  </template>
</template>
