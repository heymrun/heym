<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import JsonInputPanel from "@/components/ui/JsonInputPanel.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  gristColumns,
  gristDocIdExpressionInputRef,
  gristTableIdExpressionInputRef,
  gristRecordIdExpressionInputRef,
  gristRecordIdsExpressionInputRef,
  gristRecordsDataExpressionInputRef,
  gristSortExpressionInputRef,
  gristRecordDataJsonInputRef,
  gristFilterJsonInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  gristExpressionFieldCount,
  handleGristExpressionFieldNavigate,
  onGristRegisterExpressionFieldIndex,
  gristCredentialOptions,
  gristOperationOptions,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="gristCredentialOptions"
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
        :model-value="selectedNode.data.gristOperation || ''"
        :options="gristOperationOptions"
        @update:model-value="updateNodeData('gristOperation', $event)"
      />
      <p
        v-if="!selectedNode.data.gristOperation"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Operation is required
      </p>
    </div>

    <div class="space-y-2">
      <Label>Document ID <span class="text-destructive">*</span></Label>
      <ExpressionInput
        ref="gristDocIdExpressionInputRef"
        :model-value="selectedNode.data.gristDocId || ''"
        placeholder="your-document-id"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :navigation-enabled="gristExpressionFieldCount > 1"
        :navigation-index="0"
        :navigation-total="gristExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Document ID"
        @navigate="handleGristExpressionFieldNavigate"
        @register-field-index="onGristRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('gristDocId', $event)"
      />
      <p
        v-if="!selectedNode.data.gristDocId || selectedNode.data.gristDocId.trim() === ''"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Document ID is required
      </p>
      <p
        v-else
        class="text-xs text-muted-foreground"
      >
        Grist document ID (found in document URL)
      </p>
    </div>

    <template v-if="selectedNode.data.gristOperation && selectedNode.data.gristOperation !== 'listTables'">
      <div class="space-y-2">
        <Label>Table ID <span class="text-destructive">*</span></Label>
        <ExpressionInput
          ref="gristTableIdExpressionInputRef"
          :model-value="selectedNode.data.gristTableId || ''"
          placeholder="Table1"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="gristExpressionFieldCount > 1"
          :navigation-index="1"
          :navigation-total="gristExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Table ID"
          @navigate="handleGristExpressionFieldNavigate"
          @register-field-index="onGristRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('gristTableId', $event)"
        />
        <p
          v-if="!selectedNode.data.gristTableId || selectedNode.data.gristTableId.trim() === ''"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          Table ID is required
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Use listTables operation to discover table IDs
        </p>
      </div>
    </template>

    <template
      v-if="selectedNode.data.gristOperation === 'getRecord' || selectedNode.data.gristOperation === 'updateRecord'"
    >
      <div class="space-y-2">
        <Label>Record ID <span class="text-destructive">*</span></Label>
        <ExpressionInput
          ref="gristRecordIdExpressionInputRef"
          :model-value="selectedNode.data.gristRecordId || ''"
          placeholder="$input.recordId"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="gristExpressionFieldCount > 1"
          :navigation-index="2"
          :navigation-total="gristExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Record ID"
          @navigate="handleGristExpressionFieldNavigate"
          @register-field-index="onGristRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('gristRecordId', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Numeric record ID (supports expressions)
        </p>
      </div>
    </template>

    <template
      v-if="selectedNode.data.gristOperation === 'createRecord' || selectedNode.data.gristOperation === 'updateRecord'"
    >
      <JsonInputPanel
        ref="gristRecordDataJsonInputRef"
        :model-value="selectedNode.data.gristRecordData || '{}'"
        :columns="gristColumns"
        :input-mode="selectedNode.data.gristRecordDataInputMode || 'raw'"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        placeholder="{
    &quot;Name&quot;: &quot;John&quot;,
    &quot;Email&quot;: &quot;john@example.com&quot;
  }"
        :rows="4"
        label="Record Data (JSON)"
        :navigation-enabled="gristExpressionFieldCount > 1"
        :navigation-index="selectedNode.data.gristOperation === 'updateRecord' ? 3 : 2"
        :selective-navigation-base-index="selectedNode.data.gristOperation === 'updateRecord' ? 3 : 2"
        :navigation-total="gristExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Record data (JSON)"
        @update:model-value="updateNodeData('gristRecordData', $event)"
        @update:input-mode="updateNodeData('gristRecordDataInputMode', $event)"
        @navigate="handleGristExpressionFieldNavigate"
        @register-field-index="onGristRegisterExpressionFieldIndex"
      />
    </template>

    <template
      v-if="selectedNode.data.gristOperation === 'createRecords' || selectedNode.data.gristOperation === 'updateRecords'"
    >
      <div class="space-y-2">
        <Label>Records Data (JSON Array)</Label>
        <ExpressionInput
          ref="gristRecordsDataExpressionInputRef"
          :model-value="selectedNode.data.gristRecordsData || '[]'"
          placeholder="[{&quot;Name&quot;: &quot;John&quot;}, {&quot;Name&quot;: &quot;Jane&quot;}]"
          :rows="5"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="gristExpressionFieldCount > 1"
          :navigation-index="2"
          :navigation-total="gristExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Records data"
          @navigate="handleGristExpressionFieldNavigate"
          @register-field-index="onGristRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('gristRecordsData', $event)"
        />
        <div class="flex items-center justify-between">
          <p class="text-xs text-muted-foreground">
            <template v-if="selectedNode.data.gristOperation === 'updateRecords'">
              Array of objects with "id" and "fields" properties
            </template>
            <template v-else>
              Array of record objects (batch create)
            </template>
          </p>
          <button
            class="text-xs text-primary hover:underline"
            @click="() => { try { const parsed = JSON.parse(selectedNode?.data.gristRecordsData || '[]'); updateNodeData('gristRecordsData', JSON.stringify(parsed, null, 2)); } catch {} }"
          >
            Format
          </button>
        </div>
      </div>
    </template>

    <template v-if="selectedNode.data.gristOperation === 'deleteRecord'">
      <div class="space-y-2">
        <Label>Record ID (single)</Label>
        <ExpressionInput
          ref="gristRecordIdExpressionInputRef"
          :model-value="selectedNode.data.gristRecordId || ''"
          placeholder="$input.recordId"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="gristExpressionFieldCount > 1"
          :navigation-index="2"
          :navigation-total="gristExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Record ID (single)"
          @navigate="handleGristExpressionFieldNavigate"
          @register-field-index="onGristRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('gristRecordId', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Single record ID to delete
        </p>
      </div>
      <div class="space-y-2">
        <Label>Record IDs (batch)</Label>
        <ExpressionInput
          ref="gristRecordIdsExpressionInputRef"
          :model-value="selectedNode.data.gristRecordIds || ''"
          placeholder="[1, 2, 3]"
          :rows="2"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="gristExpressionFieldCount > 1"
          :navigation-index="3"
          :navigation-total="gristExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Record IDs (batch)"
          @navigate="handleGristExpressionFieldNavigate"
          @register-field-index="onGristRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('gristRecordIds', $event)"
        />
        <p class="text-xs text-muted-foreground">
          JSON array of record IDs for batch delete (overrides single ID)
        </p>
      </div>
    </template>

    <template v-if="selectedNode.data.gristOperation === 'getRecords'">
      <JsonInputPanel
        ref="gristFilterJsonInputRef"
        :model-value="selectedNode.data.gristFilter || '{}'"
        :columns="gristColumns"
        :input-mode="selectedNode.data.gristFilterInputMode || 'raw'"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        placeholder="{
    &quot;Status&quot;: [&quot;Active&quot;, &quot;Pending&quot;]
  }"
        :rows="3"
        label="Filter (JSON)"
        :navigation-enabled="gristExpressionFieldCount > 1"
        :navigation-index="2"
        :selective-navigation-base-index="2"
        :navigation-total="gristExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Filter (JSON)"
        @update:model-value="updateNodeData('gristFilter', $event)"
        @update:input-mode="updateNodeData('gristFilterInputMode', $event)"
        @navigate="handleGristExpressionFieldNavigate"
        @register-field-index="onGristRegisterExpressionFieldIndex"
      />

      <div class="space-y-2">
        <Label>Sort</Label>
        <ExpressionInput
          ref="gristSortExpressionInputRef"
          :model-value="selectedNode.data.gristSort || ''"
          placeholder="Name,-CreatedAt"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="gristExpressionFieldCount > 1"
          :navigation-index="(selectedNode.data.gristFilterInputMode || 'raw') === 'raw' ? 3 : 3 + gristColumns.length"
          :navigation-total="gristExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Sort"
          @navigate="handleGristExpressionFieldNavigate"
          @register-field-index="onGristRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('gristSort', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Column names to sort by (prefix with - for descending)
        </p>
      </div>

      <div class="space-y-2">
        <Label>Limit (optional)</Label>
        <Input
          type="number"
          :model-value="selectedNode.data.gristLimit || ''"
          placeholder="Leave empty for all records"
          min="1"
          @update:model-value="updateNodeData('gristLimit', $event ? parseInt($event as string) : '')"
        />
        <p class="text-xs text-muted-foreground">
          Maximum number of records to return (leave empty for all)
        </p>
      </div>
    </template>

    <div class="space-y-2 pt-2 border-t">
      <Label class="text-muted-foreground">Output</Label>
      <div class="text-xs font-mono space-y-1 text-muted-foreground">
        <template v-if="selectedNode.data.gristOperation === 'listTables'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.tables - Array of table info</div>
        </template>
        <template v-else-if="selectedNode.data.gristOperation === 'listColumns'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.columns - Array of column info</div>
        </template>
        <template v-else-if="selectedNode.data.gristOperation === 'getRecord'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.record - Record object</div>
          <div>${{ selectedNode.data.label }}.found - Boolean</div>
        </template>
        <template v-else-if="selectedNode.data.gristOperation === 'getRecords'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.records - Array of records</div>
          <div>${{ selectedNode.data.label }}.count - Number of records</div>
        </template>
        <template v-else-if="selectedNode.data.gristOperation === 'createRecord'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.record - Created record</div>
          <div>${{ selectedNode.data.label }}.id - New record ID</div>
        </template>
        <template v-else-if="selectedNode.data.gristOperation === 'createRecords'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.records - Created records</div>
          <div>${{ selectedNode.data.label }}.count - Number created</div>
          <div>${{ selectedNode.data.label }}.ids - Array of new IDs</div>
        </template>
        <template v-else-if="selectedNode.data.gristOperation === 'updateRecord'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.id - Updated record ID</div>
        </template>
        <template v-else-if="selectedNode.data.gristOperation === 'updateRecords'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.count - Number updated</div>
        </template>
        <template v-else-if="selectedNode.data.gristOperation === 'deleteRecord'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.deleted - Array of deleted IDs</div>
          <div>${{ selectedNode.data.label }}.count - Number deleted</div>
        </template>
        <template v-else>
          <div>Select an operation to see output fields</div>
        </template>
      </div>
    </div>
  </template>
</template>
