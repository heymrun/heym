<script setup lang="ts">
import { ref } from "vue";
import { Upload } from "lucide-vue-next";

import type { DataTableColumn, DataTableImportResult } from "@/types/dataTable";
import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import { dataTablesApi } from "@/services/api";

const props = defineProps<{
  tableId: string;
  columns: DataTableColumn[];
}>();
const emit = defineEmits<{ close: []; imported: [] }>();

const file = ref<File | null>(null);
const preview = ref<string[][]>([]);
const headers = ref<string[]>([]);
const importing = ref(false);
const result = ref<DataTableImportResult | null>(null);
const error = ref("");
const dragging = ref(false);

function processFile(f: File) {
  file.value = f;
  result.value = null;
  error.value = "";

  const reader = new FileReader();
  reader.onload = (e) => {
    const text = e.target?.result as string;
    const lines = text.split("\n").filter((l) => l.trim());
    if (lines.length === 0) return;

    headers.value = lines[0].split(",").map((h) => h.trim().replace(/^"|"$/g, ""));
    preview.value = lines
      .slice(1, 6)
      .map((line) => line.split(",").map((cell) => cell.trim().replace(/^"|"$/g, "")));
  };
  reader.readAsText(f);
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  if (!input.files?.length) return;
  processFile(input.files[0]);
}

function handleDrop(event: DragEvent) {
  dragging.value = false;
  const f = event.dataTransfer?.files?.[0];
  if (f && f.name.endsWith(".csv")) {
    processFile(f);
  }
}

function handleDragOver(event: DragEvent) {
  event.preventDefault();
  dragging.value = true;
}

function handleDragLeave() {
  dragging.value = false;
}

async function handleImport() {
  if (!file.value) return;
  importing.value = true;
  error.value = "";
  try {
    result.value = await dataTablesApi.importCsv(props.tableId, file.value);
    if (result.value.errors.length === 0) {
      emit("imported");
    }
  } catch {
    error.value = "Import failed";
  } finally {
    importing.value = false;
  }
}

const columnNames = props.columns.map((c) => c.name);
</script>

<template>
  <Dialog
    :open="true"
    title="Import CSV"
    @close="emit('close')"
  >
    <div class="flex flex-col gap-4 p-4">
      <div
        class="relative flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors"
        :class="dragging ? 'border-primary bg-primary/5' : 'border-muted-foreground/25 hover:border-muted-foreground/50'"
        @drop.prevent="handleDrop"
        @dragover="handleDragOver"
        @dragleave="handleDragLeave"
      >
        <Upload class="h-8 w-8 text-muted-foreground/50" />
        <p
          v-if="!file"
          class="text-sm text-muted-foreground"
        >
          Drag &amp; drop a CSV file here, or
        </p>
        <p
          v-else
          class="text-sm font-medium"
        >
          {{ file.name }}
        </p>
        <label class="cursor-pointer rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90">
          Browse
          <input
            type="file"
            accept=".csv"
            class="hidden"
            @change="handleFileChange"
          >
        </label>
      </div>

      <!-- Column mapping info -->
      <div
        v-if="headers.length > 0"
        class="text-sm"
      >
        <p class="font-medium">
          CSV Columns:
        </p>
        <div class="mt-1 flex flex-wrap gap-1">
          <span
            v-for="h in headers"
            :key="h"
            class="rounded border px-2 py-0.5 text-xs"
            :class="columnNames.includes(h) ? 'border-green-300 bg-green-50 dark:border-green-800 dark:bg-green-950' : 'border-yellow-300 bg-yellow-50 dark:border-yellow-800 dark:bg-yellow-950'"
          >
            {{ h }}
            <span
              v-if="columnNames.includes(h)"
              class="text-green-600"
            > &#10003;</span>
            <span
              v-else
              class="text-yellow-600"
            > ?</span>
          </span>
        </div>
        <p class="mt-1 text-xs text-muted-foreground">
          Green columns match table schema. Yellow columns will be ignored.
        </p>
      </div>

      <!-- Preview -->
      <div
        v-if="preview.length > 0"
        class="overflow-x-auto rounded border"
      >
        <table class="w-full text-xs">
          <thead>
            <tr class="border-b bg-muted/50">
              <th
                v-for="h in headers"
                :key="h"
                class="px-2 py-1 text-left font-medium"
              >
                {{ h }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, i) in preview"
              :key="i"
              class="border-b last:border-0"
            >
              <td
                v-for="(cell, j) in row"
                :key="j"
                class="px-2 py-1"
              >
                {{ cell }}
              </td>
            </tr>
          </tbody>
        </table>
        <p class="px-2 py-1 text-xs text-muted-foreground">
          Showing first {{ preview.length }} rows
        </p>
      </div>

      <!-- Result -->
      <div
        v-if="result"
        class="rounded border p-3 text-sm"
      >
        <p class="font-medium">
          Imported {{ result.imported }} of {{ result.total }} rows
        </p>
        <div
          v-if="result.errors.length > 0"
          class="mt-2 text-red-500"
        >
          <p class="font-medium">
            Errors:
          </p>
          <ul class="ml-4 list-disc">
            <li
              v-for="(err, i) in result.errors.slice(0, 10)"
              :key="i"
            >
              Row {{ err.row }}: {{ err.errors.join(", ") }}
            </li>
          </ul>
          <p
            v-if="result.errors.length > 10"
            class="mt-1 text-xs"
          >
            ...and {{ result.errors.length - 10 }} more errors
          </p>
        </div>
        <Button
          v-if="result.imported > 0"
          size="sm"
          class="mt-2"
          @click="emit('imported')"
        >
          Done
        </Button>
      </div>

      <div
        v-if="error"
        class="text-sm text-red-500"
      >
        {{ error }}
      </div>

      <div class="flex justify-end">
        <Button
          :disabled="!file || importing"
          @click="handleImport"
        >
          <Upload class="mr-1 h-4 w-4" />
          {{ importing ? "Importing..." : "Import" }}
        </Button>
      </div>
    </div>
  </Dialog>
</template>
