<script setup lang="ts">
import type { StatusTone } from "@/types/dashboard";
import {
  STATUS_TONE_CLASSES,
  cellText,
  statusTone,
  tableRowRecord,
  type TableRecord,
  type TableRowLink,
} from "@/components/Dashboards/chartTable";

const props = defineProps<{
  columns: string[];
  rows: unknown[][];
  statusColumn?: string;
  statusTones?: Record<string, StatusTone>;
  /** Set when the widget links rows to a detail page the viewer can open. */
  rowLink?: TableRowLink | null;
}>();

const emit = defineEmits<{
  (e: "row-open", record: TableRecord): void;
}>();

function recordOf(row: unknown[]): TableRecord | null {
  return tableRowRecord(props.columns, row, props.rowLink);
}

function open(row: unknown[]): void {
  const record = recordOf(row);
  if (record) emit("row-open", record);
}

function chipClass(cell: unknown): string {
  return STATUS_TONE_CLASSES[statusTone(cell, props.statusTones)];
}
</script>

<template>
  <table class="w-full text-sm text-foreground">
    <thead class="sticky top-0 bg-card">
      <tr class="border-b border-border">
        <th
          v-for="col in columns"
          :key="col"
          class="px-2 py-1 text-left font-medium text-muted-foreground"
        >
          {{ col }}
        </th>
      </tr>
    </thead>
    <tbody>
      <tr
        v-for="(row, rowIndex) in rows"
        :key="rowIndex"
        class="border-b border-border/50"
        :class="recordOf(row) ? 'cursor-pointer hover:bg-accent/50 focus:bg-accent/50 focus:outline-none' : ''"
        :role="recordOf(row) ? 'link' : undefined"
        :tabindex="recordOf(row) ? 0 : undefined"
        :data-record="recordOf(row)?.record"
        @click="open(row)"
        @keydown.enter="open(row)"
      >
        <td
          v-for="(cell, cellIndex) in row"
          :key="cellIndex"
          class="px-2 py-1"
        >
          <span
            v-if="statusColumn && columns[cellIndex] === statusColumn && cellText(cell)"
            class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium"
            :class="chipClass(cell)"
            :data-tone="statusTone(cell, statusTones)"
          >
            {{ cellText(cell) }}
          </span>
          <template v-else>
            {{ cell }}
          </template>
        </td>
      </tr>
    </tbody>
  </table>
</template>
