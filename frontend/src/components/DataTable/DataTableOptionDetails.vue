<script setup lang="ts">
import { computed } from "vue";
import { Table2 } from "lucide-vue-next";

import type { ClarifyOption, ClarifyTableState } from "@/types/clarify";

const props = defineProps<{
  option: ClarifyOption;
  // The existing table a `table` option points at: undefined while it loads, null when unavailable.
  table?: ClarifyTableState;
  error?: string;
}>();

interface ColumnChip {
  name: string;
  type: string;
  unique: boolean;
}

const heading = computed((): string => {
  if (props.option.createTable) return `New table: ${props.option.createTable.name}`;
  return props.table?.name ?? props.option.label;
});

const description = computed(
  (): string => props.option.createTable?.description ?? props.table?.description ?? "",
);

const columns = computed((): ColumnChip[] => {
  if (props.option.createTable) {
    return props.option.createTable.columns.map((column) => ({
      name: column.name,
      type: column.type,
      unique: column.unique === true,
    }));
  }
  return [...(props.table?.columns ?? [])]
    .sort((left, right) => left.order - right.order)
    .map((column) => ({ name: column.name, type: column.type, unique: column.unique }));
});

const unavailable = computed((): boolean => !props.option.createTable && props.table === null);
const loading = computed((): boolean => !props.option.createTable && props.table === undefined);
</script>

<template>
  <div
    class="flex flex-col gap-1.5 rounded-md border border-border bg-background px-2.5 py-2 text-xs"
    data-testid="clarify-data-table-details"
  >
    <div class="flex items-center gap-1.5 font-medium text-foreground">
      <Table2 class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span class="truncate">{{ heading }}</span>
    </div>
    <p
      v-if="unavailable"
      class="text-muted-foreground"
    >
      This table is not available.
    </p>
    <p
      v-else-if="loading"
      class="text-muted-foreground"
    >
      Loading columns…
    </p>
    <template v-else>
      <p
        v-if="description"
        class="text-muted-foreground"
      >
        {{ description }}
      </p>
      <div class="flex flex-wrap gap-1">
        <span
          v-for="column in columns"
          :key="column.name"
          class="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground"
        >{{ column.name }} · {{ column.type }}{{ column.unique ? " · unique" : "" }}</span>
      </div>
    </template>
    <p
      v-if="error"
      class="text-destructive"
    >
      {{ error }}
    </p>
  </div>
</template>
