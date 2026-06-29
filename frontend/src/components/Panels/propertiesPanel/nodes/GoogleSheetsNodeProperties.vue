<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import GoogleSheetsValuesInputPanel from "@/components/ui/GoogleSheetsValuesInputPanel.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  isWorkflowOwner,
  googleSheetsSpreadsheetIdExpressionInputRef,
  googleSheetsSheetNameExpressionInputRef,
  googleSheetsValuesInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  googleSheetsExpressionFieldCount,
  handleGoogleSheetsExpressionFieldNavigate,
  onGoogleSheetsRegisterExpressionFieldIndex,
  googleSheetsCredentialOptions,
  googleSheetsOperationOptions,
  googleSheetsAppendPlacementOptions,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Google Sheets Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="googleSheetsCredentialOptions"
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
        :model-value="selectedNode.data.gsOperation || ''"
        :options="googleSheetsOperationOptions"
        @update:model-value="updateNodeData('gsOperation', $event)"
      />
    </div>

    <template v-if="selectedNode.data.gsOperation">
      <div class="space-y-2">
        <Label>Spreadsheet ID or URL</Label>
        <ExpressionInput
          ref="googleSheetsSpreadsheetIdExpressionInputRef"
          :model-value="selectedNode.data.gsSpreadsheetId || ''"
          placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms or full URL"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="googleSheetsExpressionFieldCount > 1"
          :navigation-index="0"
          :navigation-total="googleSheetsExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Spreadsheet ID or URL"
          field-key="gsSpreadsheetId"
          @navigate="handleGoogleSheetsExpressionFieldNavigate"
          @register-field-index="onGoogleSheetsRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('gsSpreadsheetId', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Accepts a full Google Sheets URL or bare spreadsheet ID
        </p>
      </div>

      <div
        v-if="selectedNode.data.gsOperation !== 'getSheetInfo'"
        class="space-y-2"
      >
        <Label>Sheet Name</Label>
        <ExpressionInput
          ref="googleSheetsSheetNameExpressionInputRef"
          :model-value="selectedNode.data.gsSheetName || 'Sheet1'"
          placeholder="Sheet1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="googleSheetsExpressionFieldCount > 1"
          :navigation-index="1"
          :navigation-total="googleSheetsExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Sheet name"
          field-key="gsSheetName"
          @navigate="handleGoogleSheetsExpressionFieldNavigate"
          @register-field-index="onGoogleSheetsRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('gsSheetName', $event)"
        />
      </div>

      <!-- Read: declarative row/header controls -->
      <template v-if="selectedNode.data.gsOperation === 'readRange'">
        <div class="grid grid-cols-2 gap-2">
          <div class="space-y-1">
            <Label class="text-xs">Start row</Label>
            <input
              type="number"
              min="1"
              :value="selectedNode.data.gsStartRow ?? '1'"
              placeholder="1"
              class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              @input="updateNodeData('gsStartRow', String(($event.target as HTMLInputElement).value))"
            >
          </div>
          <div class="space-y-1">
            <Label class="text-xs">Max rows (0 = all)</Label>
            <input
              type="number"
              min="0"
              :value="selectedNode.data.gsMaxRows ?? '0'"
              placeholder="0"
              class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              @input="updateNodeData('gsMaxRows', String(($event.target as HTMLInputElement).value))"
            >
          </div>
        </div>
        <div class="flex items-center gap-2 pt-1">
          <input
            id="gs-has-header"
            type="checkbox"
            :checked="selectedNode.data.gsHasHeader !== false"
            class="rounded border-border"
            @change="updateNodeData('gsHasHeader', ($event.target as HTMLInputElement).checked)"
          >
          <label
            for="gs-has-header"
            class="text-xs cursor-pointer select-none"
          >First row is header (returns objects with column names as keys)</label>
        </div>
      </template>

      <!-- Update: target sheet row + values (single values PUT, not batchUpdate) -->
      <template v-if="selectedNode.data.gsOperation === 'updateRange'">
        <div class="space-y-1">
          <Label class="text-xs">Row number</Label>
          <input
            type="number"
            min="1"
            :value="selectedNode.data.gsUpdateRow ?? selectedNode.data.gsStartRow ?? '1'"
            placeholder="1"
            class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            @input="updateNodeData('gsUpdateRow', String(($event.target as HTMLInputElement).value))"
          >
          <p class="text-xs text-muted-foreground">
            Sheet row number to update (1-based).
          </p>
        </div>
      </template>

      <!-- Clear: full sheet (columns A–Z); optional first row preserved -->
      <template v-if="selectedNode.data.gsOperation === 'clearRange'">
        <p class="text-xs text-muted-foreground">
          Clears all values in columns A through Z for this tab (same width as read/update).
        </p>
        <div class="flex items-center gap-2 pt-1">
          <input
            id="gs-keep-header-clear"
            type="checkbox"
            :checked="selectedNode.data.gsKeepHeader === true"
            class="rounded border-border"
            @change="updateNodeData('gsKeepHeader', ($event.target as HTMLInputElement).checked)"
          >
          <label
            for="gs-keep-header-clear"
            class="text-xs cursor-pointer select-none"
          >Keep header row (preserve row 1, clear rows below)</label>
        </div>
      </template>

      <template v-if="selectedNode.data.gsOperation === 'appendRows'">
        <div class="space-y-2">
          <Label class="text-xs">Insert rows</Label>
          <Select
            :model-value="selectedNode.data.gsAppendPlacement || 'append'"
            :options="googleSheetsAppendPlacementOptions"
            @update:model-value="updateNodeData('gsAppendPlacement', $event)"
          />
          <p class="text-xs text-muted-foreground">
            Bottom appends after the last row with data. Top inserts directly under row 1 and shifts existing rows down.
          </p>
        </div>
      </template>

      <!-- Values: append + update -->
      <div
        v-if="selectedNode.data.gsOperation === 'appendRows' || selectedNode.data.gsOperation === 'updateRange'"
        class="space-y-2"
      >
        <Label>Values (JSON array of rows)</Label>
        <GoogleSheetsValuesInputPanel
          ref="googleSheetsValuesInputRef"
          :model-value="selectedNode.data.gsValues || '[]'"
          :input-mode="selectedNode.data.gsValuesInputMode === 'selective' ? 'selective' : 'raw'"
          :selective-cols="selectedNode.data.gsValuesSelectiveCols || '3'"
          :selective-single-row="true"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="googleSheetsExpressionFieldCount > 1"
          :navigation-index="2"
          :navigation-total="googleSheetsExpressionFieldCount"
          :selective-navigation-base-index="2"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          @update:model-value="updateNodeData('gsValues', $event)"
          @update:input-mode="updateNodeData('gsValuesInputMode', $event)"
          @update:selective-cols="updateNodeData('gsValuesSelectiveCols', $event)"
          @navigate="handleGoogleSheetsExpressionFieldNavigate"
          @register-field-index="onGoogleSheetsRegisterExpressionFieldIndex"
        />
      </div>
    </template>

    <div class="rounded-md bg-muted/40 border p-3 space-y-1">
      <p class="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        Output
      </p>
      <div class="text-xs font-mono space-y-0.5">
        <template v-if="selectedNode.data.gsOperation === 'readRange'">
          <div>${{ selectedNode.data.label }}.rows - Array of row objects</div>
          <div>${{ selectedNode.data.label }}.total - Number of rows returned</div>
        </template>
        <template v-else-if="selectedNode.data.gsOperation === 'appendRows'">
          <div>${{ selectedNode.data.label }}.updatedRange - Range that was updated</div>
          <div>${{ selectedNode.data.label }}.updatedRows - Number of rows appended</div>
        </template>
        <template v-else-if="selectedNode.data.gsOperation === 'updateRange'">
          <div>${{ selectedNode.data.label }}.updatedRange - Range that was updated</div>
          <div>${{ selectedNode.data.label }}.updatedCells - Number of cells updated</div>
        </template>
        <template v-else-if="selectedNode.data.gsOperation === 'clearRange'">
          <div>${{ selectedNode.data.label }}.clearedRange - Range that was cleared</div>
        </template>
        <template v-else-if="selectedNode.data.gsOperation === 'getSheetInfo'">
          <div>${{ selectedNode.data.label }}.sheets - Array of {title, sheetId, index}</div>
        </template>
        <template v-else>
          <div>Select an operation to see output fields</div>
        </template>
      </div>
    </div>
  </template>
</template>
