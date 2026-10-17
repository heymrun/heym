<script setup lang="ts">
import { computed } from "vue";
import { AlertTriangle } from "lucide-vue-next";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { SHEETS_EVENT_OPTIONS, selectedEvents, toggleEvent } from "@/lib/googleTriggerConfig";
import type { GoogleTriggerEvent } from "@/types/workflow";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const { selectedNode, isWorkflowOwner, googleSheetsCredentialOptions, updateNodeData } =
  usePropertiesPanelContext();

const events = computed<GoogleTriggerEvent[]>(() => selectedEvents(selectedNode.value?.data.gstEvents));
const hasHeader = computed<boolean>(() => selectedNode.value?.data.gstHasHeader !== false);

function setEvent(event: GoogleTriggerEvent, enabled: boolean): void {
  updateNodeData("gstEvents", toggleEvent(events.value, event, enabled));
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div
        class="space-y-2"
        data-testid="gst-credential-field"
      >
        <Label>Google Sheets Credential</Label>
        <Select
          :model-value="selectedNode.data.credentialId || ''"
          :options="googleSheetsCredentialOptions"
          :disabled="!isWorkflowOwner"
          @update:model-value="updateNodeData('credentialId', $event)"
        />
        <p
          v-if="!selectedNode.data.credentialId"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          No Google Sheets credential set: polling is off
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="gst-spreadsheet-field"
      >
        <Label for="gst-spreadsheet-id">Spreadsheet ID or URL</Label>
        <Input
          id="gst-spreadsheet-id"
          :model-value="selectedNode.data.gstSpreadsheetId || ''"
          @update:model-value="updateNodeData('gstSpreadsheetId', $event)"
        />
      </div>

      <div
        class="space-y-2"
        data-testid="gst-sheet-name-field"
      >
        <Label for="gst-sheet-name">Sheet Name</Label>
        <Input
          id="gst-sheet-name"
          :model-value="selectedNode.data.gstSheetName ?? 'Sheet1'"
          @update:model-value="updateNodeData('gstSheetName', $event)"
        />
      </div>

      <div
        class="flex items-center gap-2"
        data-testid="gst-has-header-field"
      >
        <input
          id="gst-has-header"
          type="checkbox"
          class="rounded border-border"
          :checked="hasHeader"
          @change="updateNodeData('gstHasHeader', ($event.target as HTMLInputElement).checked)"
        >
        <label
          for="gst-has-header"
          class="text-xs cursor-pointer select-none"
        >First row is header</label>
      </div>

      <div
        class="space-y-2"
        data-testid="gst-key-column-field"
      >
        <Label for="gst-key-column">Key Column (recommended)</Label>
        <Input
          id="gst-key-column"
          :model-value="selectedNode.data.gstKeyColumn || ''"
          :placeholder="hasHeader ? 'e.g. Email' : 'e.g. B'"
          @update:model-value="updateNodeData('gstKeyColumn', $event)"
        />
        <p class="text-xs text-muted-foreground">
          A column whose value is unique per row. With it, inserting, deleting, or sorting rows is
          detected correctly. Without it, rows are matched by row number.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="gst-events-field"
      >
        <Label>Start a run when</Label>
        <div
          v-for="option in SHEETS_EVENT_OPTIONS"
          :key="option.value"
          class="flex items-center gap-2"
        >
          <input
            :id="`gst-event-${option.value}`"
            type="checkbox"
            class="rounded border-border"
            :checked="events.includes(option.value)"
            @change="setEvent(option.value, ($event.target as HTMLInputElement).checked)"
          >
          <label
            :for="`gst-event-${option.value}`"
            class="text-xs cursor-pointer select-none"
          >{{ option.label }}</label>
        </div>
        <p
          class="text-xs text-amber-500 flex items-start gap-1"
          data-testid="gst-write-back-warning"
        >
          <AlertTriangle class="h-3 w-3 mt-0.5 shrink-0" />
          If this workflow writes to the same sheet, keep only "Row added" on, or its own writes
          start new runs.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="gst-poll-field"
      >
        <Label for="gst-poll-interval">Poll Interval (Minutes)</Label>
        <Input
          id="gst-poll-interval"
          :model-value="String(selectedNode.data.pollIntervalMinutes ?? 1)"
          type="number"
          min="1"
          step="1"
          @update:model-value="updateNodeData('pollIntervalMinutes', Number.parseInt($event, 10) || 1)"
        />
        <p class="text-xs text-muted-foreground">
          The first poll records the sheet as it is. Heym keeps only fingerprints of cells, never
          their values.
        </p>
      </div>

      <div
        class="space-y-2 pt-2 border-t"
        data-testid="gst-output-fields"
      >
        <Label class="text-xs text-muted-foreground">Available output fields</Label>
        <div class="text-xs text-muted-foreground space-y-1 font-mono">
          <div>${{ selectedNode.data.label }}.event: created, updated, or deleted</div>
          <div>${{ selectedNode.data.label }}.row: current cells by column name</div>
          <div>${{ selectedNode.data.label }}.row.rowIndex: sheet row number</div>
          <div>${{ selectedNode.data.label }}.changed_columns: columns that changed</div>
          <div>${{ selectedNode.data.label }}.key: key column value</div>
          <div>${{ selectedNode.data.label }}.triggered_at: when the change was seen</div>
        </div>
      </div>
    </div>
  </template>
</template>
