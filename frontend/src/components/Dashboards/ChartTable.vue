<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-vue-next";

import type { StatusTone } from "@/types/dashboard";
import {
  STATUS_TONE_CLASSES,
  cellText,
  sortTableRows,
  statusTone,
  tableRowRecord,
  type TableRecord,
  type TableRowLink,
  type TableSort,
  type TableSortDirection,
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

const sort = ref<TableSort | null>(null);

const sortedRows = computed((): unknown[][] => {
  if (!sort.value) return props.rows;
  return sortTableRows(props.rows, sort.value.column, sort.value.direction);
});

watch(
  () => props.columns.join("\0"),
  () => {
    sort.value = null;
  },
);

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

function toggleSort(column: number): void {
  const next: TableSortDirection =
    sort.value?.column === column && sort.value.direction === "asc" ? "desc" : "asc";
  sort.value = { column, direction: next };
}

function ariaSort(column: number): "ascending" | "descending" | "none" {
  if (sort.value?.column !== column) return "none";
  return sort.value.direction === "asc" ? "ascending" : "descending";
}
</script>

<template>
  <table class="w-full text-sm text-foreground">
    <thead class="chart-table-head sticky top-0 z-[1]">
      <tr class="border-b border-border">
        <th
          v-for="(col, index) in columns"
          :key="`${index}-${col}`"
          class="p-0 text-left font-medium"
          :aria-sort="ariaSort(index)"
        >
          <button
            type="button"
            class="flex w-full items-center gap-1 px-2 py-2 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground hover:text-foreground"
            :aria-label="`Sort by ${col}`"
            @click="toggleSort(index)"
          >
            <span class="truncate">{{ col }}</span>
            <ArrowUp
              v-if="sort?.column === index && sort.direction === 'asc'"
              class="h-3 w-3 shrink-0"
              aria-hidden="true"
            />
            <ArrowDown
              v-else-if="sort?.column === index && sort.direction === 'desc'"
              class="h-3 w-3 shrink-0"
              aria-hidden="true"
            />
            <ArrowUpDown
              v-else
              class="h-3 w-3 shrink-0 opacity-40"
              aria-hidden="true"
            />
          </button>
        </th>
      </tr>
    </thead>
    <tbody>
      <tr
        v-for="(row, rowIndex) in sortedRows"
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
          class="px-2 py-1.5"
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

<style scoped>
/* Match the card the table sits on: Heym's card, or Work's widget when that token exists. */
.chart-table-head {
  background-color: hsl(var(--widget, var(--card)));
}
</style>
