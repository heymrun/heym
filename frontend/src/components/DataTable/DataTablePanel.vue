<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import {
  ArrowLeft,
  ArrowDown,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Coins,
  Copy,
  Download,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Share2,
  Table2,
  Trash2,
  Upload,
  X,
} from "lucide-vue-next";

import type { DataTable, DataTableColumn, DataTableListItem, DataTableRow } from "@/types/dataTable";
import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { formatDate } from "@/lib/utils";
import { dataTablesApi } from "@/services/api";

import DataTableShareDialog from "./DataTableShareDialog.vue";
import DataTableColumnEditor from "./DataTableColumnEditor.vue";
import DataTableImportDialog from "./DataTableImportDialog.vue";
import LLMPricingPanel from "./LLMPricingPanel.vue";

const LLM_PRICING_ROUTE_ID = "llm-pricing";

const props = defineProps<{ initialTableId?: string | null }>();
const emit = defineEmits<{ navigate: [id: string | null] }>();
const route = useRoute();

type RowSortField = "created_at" | "updated_at";
type RowSortDirection = "asc" | "desc";
type RowPageSize = 25 | 50 | 100 | "all";

function parseDataTableRoute(tab: unknown): { kind: "list" } | { kind: "detail"; id: string } {
  const raw = Array.isArray(tab) ? tab[0] : tab;
  if (typeof raw !== "string") return { kind: "list" };
  if (raw === "datatable") return { kind: "list" };
  if (raw.startsWith("datatable/")) return { kind: "detail", id: raw.slice("datatable/".length) };
  return { kind: "list" };
}

// ── List state ──
const tables = ref<DataTableListItem[]>([]);
const loading = ref(true);
const error = ref("");
const searchQuery = ref("");

// ── Detail state ──
const selectedTable = ref<DataTable | null>(null);
const rows = ref<DataTableRow[]>([]);
const rowsLoading = ref(false);
const detailLoading = ref(
  Boolean(props.initialTableId) && props.initialTableId !== LLM_PRICING_ROUTE_ID,
);
const rowPage = ref(0);
const rowPageSize = ref<RowPageSize>(25);
const rowTotal = ref(0);
const rowSortField = ref<RowSortField>("created_at");
const rowSortDirection = ref<RowSortDirection>("desc");
const rowPageSizeOptions: Array<{ value: RowPageSize; label: string }> = [
  { value: 25, label: "25" },
  { value: 50, label: "50" },
  { value: 100, label: "100" },
  { value: "all", label: "All" },
];
const DATA_GRID_COLUMN_WIDTH_REM = 12;
const DATA_GRID_META_WIDTH_REM = 33;

// ── Create dialog ──
const showCreateDialog = ref(false);
const newName = ref("");
const newDescription = ref("");
const creating = ref(false);

// ── Share dialog ──
const showShareDialog = ref(false);

// ── Column editor ──
const showColumnEditor = ref(false);
const editingColumn = ref<DataTableColumn | null>(null);

// ── Import dialog ──
const showImportDialog = ref(false);

// ── Inline edit ──
const editingCell = ref<{ rowId: string; colName: string } | null>(null);
const editingValue = ref("");

// ── Add row ──
const addingRow = ref(false);
const newRowData = ref<Record<string, string>>({});

// ── Rename in list ──
const renamingTableId = ref<string | null>(null);
const renameValue = ref("");
const renameInputRef = ref<HTMLInputElement | null>(null);

// ── Copied ID feedback ──
const copiedRowId = ref<string | null>(null);

const filtered = computed(() => {
  if (!searchQuery.value) return tables.value;
  const q = searchQuery.value.toLowerCase();
  return tables.value.filter(
    (t) => t.name.toLowerCase().includes(q) || (t.description || "").toLowerCase().includes(q),
  );
});

async function loadTables() {
  loading.value = true;
  error.value = "";
  try {
    tables.value = await dataTablesApi.list();
  } catch {
    error.value = "Failed to load data tables";
  } finally {
    loading.value = false;
  }
}

async function openTable(id: string): Promise<void> {
  try {
    selectedTable.value = await dataTablesApi.get(id);
    rowPage.value = 0;
    await loadRows();
    const tabRaw = route.query.tab;
    const tab = Array.isArray(tabRaw) ? tabRaw[0] : tabRaw;
    if (typeof tab === "string" && tab === `datatable/${id}`) {
      return;
    }
    emit("navigate", id);
  } catch {
    error.value = "Failed to load data table";
  }
}

async function loadRows() {
  if (!selectedTable.value) return;
  rowsLoading.value = true;
  try {
    const limit = rowPageSize.value === "all" ? 0 : rowPageSize.value;
    const offset = rowPageSize.value === "all" ? 0 : rowPage.value * rowPageSize.value;
    const allRows = await dataTablesApi.listRows(
      selectedTable.value.id,
      limit,
      offset,
      rowSortField.value,
      rowSortDirection.value,
    );
    rows.value = allRows;
    rowTotal.value = selectedTable.value.row_count;
  } catch {
    error.value = "Failed to load rows";
  } finally {
    rowsLoading.value = false;
  }
}

async function refreshSelectedTable(): Promise<void> {
  if (!selectedTable.value) return;
  try {
    selectedTable.value = await dataTablesApi.get(selectedTable.value.id);
    await loadRows();
  } catch {
    error.value = "Failed to refresh data table";
  }
}

function goBack() {
  selectedTable.value = null;
  rows.value = [];
  editingCell.value = null;
  addingRow.value = false;
  emit("navigate", null);
  loadTables();
}

async function handleCreate() {
  if (!newName.value.trim()) return;
  creating.value = true;
  try {
    const created = await dataTablesApi.create({
      name: newName.value.trim(),
      description: newDescription.value.trim() || undefined,
    });
    showCreateDialog.value = false;
    newName.value = "";
    newDescription.value = "";
    await openTable(created.id);
    await loadTables();
  } catch {
    error.value = "Failed to create data table";
  } finally {
    creating.value = false;
  }
}

async function handleDelete(id: string) {
  if (!confirm("Delete this data table? This cannot be undone.")) return;
  try {
    await dataTablesApi.delete(id);
    if (selectedTable.value?.id === id) {
      selectedTable.value = null;
      rows.value = [];
    }
    await loadTables();
  } catch {
    error.value = "Failed to delete data table";
  }
}

async function handleClearRows() {
  if (!selectedTable.value) return;
  if (!confirm("Delete all rows? This cannot be undone.")) return;
  try {
    await dataTablesApi.clearRows(selectedTable.value.id);
    selectedTable.value = await dataTablesApi.get(selectedTable.value.id);
    await loadRows();
  } catch {
    error.value = "Failed to clear rows";
  }
}

function startRename(table: DataTableListItem) {
  renamingTableId.value = table.id;
  renameValue.value = table.name;
  nextTick(() => renameInputRef.value?.focus());
}

async function saveRename() {
  if (!renamingTableId.value || !renameValue.value.trim()) {
    renamingTableId.value = null;
    return;
  }
  try {
    await dataTablesApi.update(renamingTableId.value, { name: renameValue.value.trim() });
    await loadTables();
  } catch {
    error.value = "Failed to rename table";
  } finally {
    renamingTableId.value = null;
  }
}

function cancelRename() {
  renamingTableId.value = null;
}

function copyRowId(id: string) {
  navigator.clipboard.writeText(id);
  copiedRowId.value = id;
  setTimeout(() => { copiedRowId.value = null; }, 1500);
}

// ── Column management ──

function openAddColumn() {
  editingColumn.value = null;
  showColumnEditor.value = true;
}

async function handleColumnSave(column: DataTableColumn) {
  if (!selectedTable.value) return;
  const existing = selectedTable.value.columns || [];
  const idx = existing.findIndex((c) => c.id === column.id);
  let updatedColumns: DataTableColumn[];
  if (idx >= 0) {
    updatedColumns = [...existing];
    updatedColumns[idx] = column;
  } else {
    updatedColumns = [...existing, { ...column, order: existing.length }];
  }
  try {
    selectedTable.value = await dataTablesApi.update(selectedTable.value.id, { columns: updatedColumns });
    showColumnEditor.value = false;
    editingColumn.value = null;
  } catch {
    error.value = "Failed to update columns";
  }
}

async function handleColumnDelete(colId: string) {
  if (!selectedTable.value) return;
  if (!confirm("Remove this column?")) return;
  const updatedColumns = (selectedTable.value.columns || []).filter((c) => c.id !== colId);
  try {
    selectedTable.value = await dataTablesApi.update(selectedTable.value.id, { columns: updatedColumns });
  } catch {
    error.value = "Failed to remove column";
  }
}

// ── Row management ──

function startAddRow() {
  if (!selectedTable.value) return;
  addingRow.value = true;
  newRowData.value = {};
  for (const col of selectedTable.value.columns || []) {
    newRowData.value[col.name] = col.defaultValue != null ? String(col.defaultValue) : "";
  }
}

async function handleAddRow() {
  if (!selectedTable.value) return;

  const validationErr = validateAllRowData();
  if (validationErr) {
    error.value = validationErr;
    return;
  }

  const coercedData: Record<string, unknown> = {};
  for (const col of selectedTable.value.columns || []) {
    const raw = newRowData.value[col.name] ?? "";
    if (raw || col.required) {
      coercedData[col.name] = coerceValue(raw, col);
    }
  }

  try {
    await dataTablesApi.createRow(selectedTable.value.id, coercedData);
    addingRow.value = false;
    newRowData.value = {};
    selectedTable.value = await dataTablesApi.get(selectedTable.value.id);
    await loadRows();
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Failed to add row";
    error.value = msg;
  }
}

async function handleDeleteRow(rowId: string) {
  if (!selectedTable.value) return;
  try {
    await dataTablesApi.deleteRow(selectedTable.value.id, rowId);
    selectedTable.value = await dataTablesApi.get(selectedTable.value.id);
    await loadRows();
  } catch {
    error.value = "Failed to delete row";
  }
}

// ── Type validation ──

function validateValue(value: string, col: DataTableColumn): string | null {
  if (!value && !col.required) return null;
  if (!value && col.required) return `${col.name} is required`;
  switch (col.type) {
    case "number":
      if (isNaN(Number(value))) return `${col.name} must be a number`;
      break;
    case "boolean":
      if (!["true", "false", "1", "0"].includes(value.toLowerCase()))
        return `${col.name} must be true/false`;
      break;
    case "date":
      if (isNaN(Date.parse(value))) return `${col.name} must be a valid date`;
      break;
    case "json":
      try { JSON.parse(value); } catch { return `${col.name} must be valid JSON`; }
      break;
  }
  return null;
}

function coerceValue(value: string, col: DataTableColumn): unknown {
  if (!value) return col.type === "boolean" ? false : value;
  switch (col.type) {
    case "number": return Number(value);
    case "boolean": return ["true", "1"].includes(value.toLowerCase());
    case "json": try { return JSON.parse(value); } catch { return value; }
    default: return value;
  }
}

function validateAllRowData(): string | null {
  if (!selectedTable.value) return null;
  for (const col of selectedTable.value.columns || []) {
    const val = newRowData.value[col.name] ?? "";
    const err = validateValue(val, col);
    if (err) return err;
  }
  return null;
}

const cellValidationError = ref("");

// ── Inline edit ──

function startEdit(rowId: string, colName: string, value: unknown) {
  editingCell.value = { rowId, colName };
  editingValue.value = value != null ? String(value) : "";
  cellValidationError.value = "";
}

async function saveEdit() {
  if (!editingCell.value || !selectedTable.value) return;
  const { rowId, colName } = editingCell.value;

  const col = (selectedTable.value.columns || []).find((c) => c.name === colName);
  if (col) {
    const err = validateValue(editingValue.value, col);
    if (err) {
      cellValidationError.value = err;
      return;
    }
  }

  const coerced = col ? coerceValue(editingValue.value, col) : editingValue.value;
  try {
    await dataTablesApi.updateRow(selectedTable.value.id, rowId, { [colName]: coerced });
    await loadRows();
  } catch {
    error.value = "Failed to update row";
  } finally {
    editingCell.value = null;
    cellValidationError.value = "";
  }
}

function cancelEdit() {
  editingCell.value = null;
  cellValidationError.value = "";
}

// ── CSV ──

async function handleExport() {
  if (!selectedTable.value) return;
  try {
    const blob = await dataTablesApi.exportCsv(selectedTable.value.id);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${selectedTable.value.name.replace(/\s+/g, "_")}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  } catch {
    error.value = "Failed to export CSV";
  }
}

async function handleImportComplete() {
  showImportDialog.value = false;
  if (selectedTable.value) {
    selectedTable.value = await dataTablesApi.get(selectedTable.value.id);
    await loadRows();
  }
}

// ── Pagination ──
const totalPages = computed(() => {
  if (rowPageSize.value === "all") return 1;
  return Math.max(1, Math.ceil(rowTotal.value / rowPageSize.value));
});

function prevPage(): void {
  if (rowPage.value > 0) {
    rowPage.value--;
    loadRows();
  }
}

function nextPage(): void {
  if (rowPage.value < totalPages.value - 1) {
    rowPage.value++;
    loadRows();
  }
}

function setRowPageSize(value: string): void {
  rowPageSize.value = value === "all" ? "all" : (Number(value) as 25 | 50 | 100);
  rowPage.value = 0;
  loadRows();
}

function handleRowPageSizeChange(event: Event): void {
  setRowPageSize((event.target as HTMLSelectElement).value);
}

function toggleRowSort(field: RowSortField): void {
  if (rowSortField.value === field) {
    rowSortDirection.value = rowSortDirection.value === "asc" ? "desc" : "asc";
  } else {
    rowSortField.value = field;
    rowSortDirection.value = "desc";
  }
  rowPage.value = 0;
  loadRows();
}

const sortedColumns = computed(() => {
  if (!selectedTable.value) return [];
  return [...(selectedTable.value.columns || [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
});

const dataGridMinWidth = computed(
  () => `${sortedColumns.value.length * DATA_GRID_COLUMN_WIDTH_REM + DATA_GRID_META_WIDTH_REM}rem`,
);

const isLLMPricingSelected = computed(() => {
  const parsed = parseDataTableRoute(route.query.tab);
  return parsed.kind === "detail" && parsed.id === LLM_PRICING_ROUTE_ID;
});

watch(
  () => route.query.tab,
  async (tab) => {
    const parsed = parseDataTableRoute(tab);
    if (parsed.kind === "list") {
      if (selectedTable.value) {
        selectedTable.value = null;
        rows.value = [];
        editingCell.value = null;
        addingRow.value = false;
      }
      return;
    }
    if (parsed.id === LLM_PRICING_ROUTE_ID) {
      selectedTable.value = null;
      rows.value = [];
      editingCell.value = null;
      addingRow.value = false;
      return;
    }
    if (selectedTable.value?.id === parsed.id) {
      return;
    }
    detailLoading.value = true;
    try {
      selectedTable.value = await dataTablesApi.get(parsed.id);
      rowPage.value = 0;
      await loadRows();
    } catch {
      error.value = "Failed to load data table";
    } finally {
      detailLoading.value = false;
    }
  },
);

onMounted(async () => {
  const tablesPromise = loadTables();
  if (props.initialTableId && props.initialTableId !== LLM_PRICING_ROUTE_ID) {
    detailLoading.value = true;
    try {
      await Promise.all([tablesPromise, openTable(props.initialTableId)]);
    } finally {
      detailLoading.value = false;
    }
    return;
  }
  await tablesPromise;
});
</script>

<template>
  <div class="flex flex-col gap-4 px-1">
    <!-- Error banner -->
    <div
      v-if="error"
      class="rounded-lg border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
    >
      {{ error }}
      <button
        class="ml-2 underline"
        @click="error = ''"
      >
        dismiss
      </button>
    </div>

    <!-- ════════ LIST VIEW ════════ -->
    <template v-if="detailLoading" />

    <template v-else-if="isLLMPricingSelected">
      <LLMPricingPanel />
    </template>

    <template v-else-if="!selectedTable">
      <div class="flex items-center justify-between gap-3">
        <div class="relative flex-1">
          <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            v-model="searchQuery"
            placeholder="Search data tables..."
            class="pl-9"
          />
        </div>
        <Button
          size="sm"
          @click="showCreateDialog = true"
        >
          <Plus class="mr-1 h-4 w-4" /> New DataTable
        </Button>
        <Button
          size="sm"
          variant="ghost"
          @click="loadTables"
        >
          <RefreshCw
            class="h-4 w-4"
            :class="{ 'animate-spin': loading }"
          />
        </Button>
      </div>

      <div class="space-y-2">
        <div class="text-xs uppercase tracking-wide text-muted-foreground">
          System tables
        </div>
        <div
          class="group relative cursor-pointer rounded-lg border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/30"
          @click="$router.push({ query: { ...$route.query, tab: 'datatable/llm-pricing' } })"
        >
          <div class="flex items-start gap-3">
            <Coins class="w-5 h-5 text-primary mt-0.5" />
            <div>
              <div class="font-medium">
                LLM Cost Table
              </div>
              <div class="text-xs text-muted-foreground">
                Per-model pricing used by the Traces cost charts
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Loading -->
      <div
        v-if="loading"
        class="flex items-center justify-center py-20"
      >
        <RefreshCw class="h-6 w-6 animate-spin text-muted-foreground" />
      </div>

      <!-- Empty state -->
      <div
        v-else-if="filtered.length === 0"
        class="flex flex-col items-center justify-center gap-4 py-20 text-center"
      >
        <Table2 class="h-12 w-12 text-muted-foreground/50" />
        <div>
          <p class="text-lg font-medium">
            No data tables yet
          </p>
          <p class="text-sm text-muted-foreground">
            Create a data table to store and manage structured data.
          </p>
        </div>
        <Button @click="showCreateDialog = true">
          <Plus class="mr-1 h-4 w-4" /> Create DataTable
        </Button>
      </div>

      <!-- Table list -->
      <div
        v-else
        class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
      >
        <div
          v-for="table in filtered"
          :key="table.id"
          class="group relative cursor-pointer rounded-lg border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/30"
          @click="openTable(table.id)"
        >
          <div class="flex items-start justify-between">
            <div class="min-w-0 flex-1">
              <template v-if="renamingTableId === table.id">
                <input
                  ref="renameInputRef"
                  v-model="renameValue"
                  class="w-full truncate rounded border bg-background px-2 py-0.5 font-medium focus:outline-none focus:ring-1 focus:ring-primary"
                  @click.stop
                  @keydown.enter.stop="saveRename"
                  @keydown.escape.stop="cancelRename"
                  @blur="saveRename"
                >
              </template>
              <h3
                v-else
                class="truncate font-medium"
              >
                {{ table.name }}
              </h3>
              <p
                v-if="table.description"
                class="mt-1 truncate text-sm text-muted-foreground"
              >
                {{ table.description }}
              </p>
            </div>
            <div class="ml-2 flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
              <button
                class="rounded p-1 hover:bg-accent"
                @click.stop="startRename(table)"
              >
                <Pencil class="h-3.5 w-3.5 text-muted-foreground" />
              </button>
              <button
                class="rounded p-1 hover:bg-destructive/10"
                @click.stop="handleDelete(table.id)"
              >
                <Trash2 class="h-4 w-4 text-destructive" />
              </button>
            </div>
          </div>
          <div class="mt-3 flex items-center gap-3 text-xs text-muted-foreground">
            <span>{{ table.column_count }} cols</span>
            <span>{{ table.row_count }} rows</span>
            <span
              v-if="table.is_shared"
              class="text-blue-500"
            >
              shared{{ table.shared_by ? ` by ${table.shared_by}` : "" }}{{ table.shared_by_team ? ` via ${table.shared_by_team}` : "" }}
            </span>
          </div>
          <div class="mt-1 text-xs text-muted-foreground">
            {{ formatDate(table.updated_at) }}
          </div>
        </div>
      </div>
    </template>

    <!-- ════════ DETAIL VIEW ════════ -->
    <template v-else>
      <!-- Header -->
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div class="flex min-w-0 items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            class="shrink-0"
            @click="goBack"
          >
            <ArrowLeft class="h-4 w-4" />
          </Button>
          <h2 class="min-w-0 text-lg font-semibold leading-tight">
            {{ selectedTable.name }}
          </h2>
          <span class="shrink-0 rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
            {{ rowTotal }} rows
          </span>
          <span
            v-if="selectedTable.description"
            class="hidden min-w-0 truncate text-sm text-muted-foreground md:inline"
          >{{ selectedTable.description }}</span>
        </div>
        <div class="flex max-w-full items-center gap-2 overflow-x-auto pb-1 [-webkit-overflow-scrolling:touch] sm:overflow-visible sm:pb-0">
          <Button
            size="sm"
            variant="outline"
            class="shrink-0"
            :disabled="rowsLoading"
            @click="refreshSelectedTable"
          >
            <RefreshCw
              class="mr-1 h-4 w-4"
              :class="{ 'animate-spin': rowsLoading }"
            /> Refresh
          </Button>
          <Button
            size="sm"
            variant="outline"
            class="shrink-0"
            @click="showShareDialog = true"
          >
            <Share2 class="mr-1 h-4 w-4" /> Share
          </Button>
          <Button
            size="sm"
            variant="outline"
            class="shrink-0"
            @click="showImportDialog = true"
          >
            <Upload class="mr-1 h-4 w-4" /> Import
          </Button>
          <Button
            size="sm"
            variant="outline"
            class="shrink-0"
            @click="handleExport"
          >
            <Download class="mr-1 h-4 w-4" /> Export
          </Button>
          <Button
            v-if="rowTotal > 0"
            size="sm"
            variant="outline"
            class="shrink-0 text-destructive hover:bg-destructive/10"
            @click="handleClearRows"
          >
            <Trash2 class="mr-1 h-4 w-4" /> Clear
          </Button>
        </div>
      </div>

      <!-- Column management -->
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-sm font-medium">Columns:</span>
        <div
          v-for="col in sortedColumns"
          :key="col.id"
          class="group/col flex items-center gap-1 rounded-md border bg-muted/50 px-2 py-1 text-xs"
        >
          <span class="font-medium">{{ col.name }}</span>
          <span class="text-muted-foreground">({{ col.type }})</span>
          <span
            v-if="col.required"
            class="text-red-500"
          >*</span>
          <button
            class="ml-1 hidden rounded p-0.5 hover:bg-destructive/10 group-hover/col:inline-flex"
            @click="handleColumnDelete(col.id)"
          >
            <X class="h-3 w-3 text-destructive" />
          </button>
        </div>
        <Button
          size="sm"
          variant="outline"
          class="h-7 text-xs"
          @click="openAddColumn"
        >
          <Plus class="mr-1 h-3 w-3" /> Column
        </Button>
      </div>

      <!-- Data grid -->
      <div class="max-w-full overflow-x-auto rounded-lg border overscroll-x-contain [-webkit-overflow-scrolling:touch]">
        <table
          class="w-full table-fixed text-sm"
          :style="{ minWidth: dataGridMinWidth }"
        >
          <colgroup>
            <col
              v-for="col in sortedColumns"
              :key="`width-${col.id}`"
              class="w-48"
            >
            <col class="w-40">
            <col class="w-40">
            <col class="w-28">
            <col class="w-24">
          </colgroup>
          <thead>
            <tr class="border-b bg-muted/50">
              <th
                v-for="col in sortedColumns"
                :key="col.id"
                class="w-48 min-w-48 max-w-48 px-3 py-2 text-left font-medium"
              >
                <span
                  class="block truncate"
                  :title="col.name"
                >
                  {{ col.name }}
                </span>
              </th>
              <th class="w-40 min-w-40 px-3 py-2 text-right text-xs font-medium text-muted-foreground">
                <button
                  class="inline-flex items-center justify-end gap-1 rounded px-1 py-0.5 whitespace-nowrap hover:bg-accent hover:text-foreground"
                  @click="toggleRowSort('created_at')"
                >
                  Created
                  <ArrowUp
                    v-if="rowSortField === 'created_at' && rowSortDirection === 'asc'"
                    class="h-3.5 w-3.5"
                  />
                  <ArrowDown
                    v-else-if="rowSortField === 'created_at'"
                    class="h-3.5 w-3.5"
                  />
                </button>
              </th>
              <th class="w-40 min-w-40 px-3 py-2 text-right text-xs font-medium text-muted-foreground">
                <button
                  class="inline-flex items-center justify-end gap-1 rounded px-1 py-0.5 whitespace-nowrap hover:bg-accent hover:text-foreground"
                  @click="toggleRowSort('updated_at')"
                >
                  Updated
                  <ArrowUp
                    v-if="rowSortField === 'updated_at' && rowSortDirection === 'asc'"
                    class="h-3.5 w-3.5"
                  />
                  <ArrowDown
                    v-else-if="rowSortField === 'updated_at'"
                    class="h-3.5 w-3.5"
                  />
                </button>
              </th>
              <th class="w-28 min-w-28 px-3 py-2 text-right font-medium text-muted-foreground">
                ID
              </th>
              <th class="w-24 min-w-24 px-3 py-2 text-right font-medium">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            <!-- Existing rows -->
            <tr
              v-for="row in rows"
              :key="row.id"
              class="group border-b last:border-0 hover:bg-accent/30"
            >
              <td
                v-for="col in sortedColumns"
                :key="col.id"
                class="w-48 min-w-48 max-w-48 px-3 py-2"
                @dblclick="startEdit(row.id, col.name, row.data[col.name])"
              >
                <!-- Inline editing -->
                <template v-if="editingCell?.rowId === row.id && editingCell?.colName === col.name">
                  <div class="flex flex-col gap-0.5">
                    <div
                      v-if="col.type === 'boolean'"
                      class="relative"
                    >
                      <select
                        v-model="editingValue"
                        class="w-full appearance-none rounded border bg-background pl-2 pr-7 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                        autofocus
                        @change="saveEdit"
                        @keydown.escape="cancelEdit"
                      >
                        <option value="true">
                          true
                        </option>
                        <option value="false">
                          false
                        </option>
                      </select>
                      <ChevronDown class="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                    </div>
                    <textarea
                      v-else-if="col.type === 'string' || col.type === 'json'"
                      v-model="editingValue"
                      class="w-full resize-y rounded border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-1"
                      :class="cellValidationError ? 'border-red-400 focus:ring-red-400' : 'focus:ring-primary'"
                      :rows="Math.min(Math.max(String(editingValue).split('\n').length, Math.ceil(String(editingValue).length / 40)), 6)"
                      autofocus
                      @keydown.escape="cancelEdit"
                      @blur="saveEdit"
                      @keydown.ctrl.enter="saveEdit"
                      @keydown.meta.enter="saveEdit"
                    />
                    <input
                      v-else
                      v-model="editingValue"
                      :type="col.type === 'number' ? 'number' : col.type === 'date' ? 'date' : 'text'"
                      :step="col.type === 'number' ? 'any' : undefined"
                      class="w-full rounded border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-1"
                      :class="cellValidationError ? 'border-red-400 focus:ring-red-400' : 'focus:ring-primary'"
                      autofocus
                      @keydown.enter="saveEdit"
                      @keydown.escape="cancelEdit"
                      @blur="saveEdit"
                    >
                    <span
                      v-if="cellValidationError"
                      class="text-xs text-red-500"
                    >{{ cellValidationError }}</span>
                  </div>
                </template>
                <template v-else>
                  <span
                    class="cursor-default block truncate"
                    :title="String(row.data[col.name] ?? '')"
                  >{{ row.data[col.name] ?? "" }}</span>
                </template>
              </td>
              <td class="w-40 min-w-40 px-3 py-2 text-right text-xs text-muted-foreground whitespace-nowrap">
                {{ formatDate(row.created_at) }}
              </td>
              <td class="w-40 min-w-40 px-3 py-2 text-right text-xs text-muted-foreground whitespace-nowrap">
                {{ formatDate(row.updated_at) }}
              </td>
              <td class="w-28 min-w-28 px-3 py-2 text-right">
                <button
                  class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-mono text-muted-foreground opacity-0 transition-opacity hover:bg-accent group-hover:opacity-100"
                  :title="row.id"
                  @click="copyRowId(row.id)"
                >
                  <template v-if="copiedRowId === row.id">
                    <Check class="h-3 w-3 text-green-500" />
                  </template>
                  <template v-else>
                    <Copy class="h-3 w-3" />
                  </template>
                  {{ row.id.slice(0, 8) }}
                </button>
              </td>
              <td class="w-24 min-w-24 px-3 py-2 text-right">
                <button
                  class="rounded p-1 opacity-0 hover:bg-destructive/10 group-hover:opacity-100"
                  @click="handleDeleteRow(row.id)"
                >
                  <Trash2 class="h-3.5 w-3.5 text-destructive" />
                </button>
              </td>
            </tr>

            <!-- Add row inline -->
            <tr
              v-if="addingRow"
              class="border-b bg-accent/20"
            >
              <td
                v-for="col in sortedColumns"
                :key="col.id"
                class="w-48 min-w-48 max-w-48 px-3 py-2"
              >
                <div
                  v-if="col.type === 'boolean'"
                  class="relative"
                >
                  <select
                    v-model="newRowData[col.name]"
                    class="w-full appearance-none rounded border bg-background pl-2 pr-7 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    <option value="">
                      --
                    </option>
                    <option value="true">
                      true
                    </option>
                    <option value="false">
                      false
                    </option>
                  </select>
                  <ChevronDown class="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                </div>
                <input
                  v-else
                  v-model="newRowData[col.name]"
                  :type="col.type === 'number' ? 'number' : col.type === 'date' ? 'date' : 'text'"
                  :step="col.type === 'number' ? 'any' : undefined"
                  :placeholder="col.name + (col.type !== 'string' ? ` (${col.type})` : '')"
                  class="w-full rounded border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                  @keydown.enter="handleAddRow"
                >
              </td>
              <td />
              <td />
              <td />
              <td class="px-3 py-2 text-right">
                <div class="flex items-center justify-end gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    class="h-7 text-xs"
                    @click="handleAddRow"
                  >
                    Save
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    class="h-7 text-xs"
                    @click="addingRow = false"
                  >
                    <X class="h-3 w-3" />
                  </Button>
                </div>
              </td>
            </tr>

            <!-- Empty state -->
            <tr v-if="rows.length === 0 && !addingRow && !rowsLoading">
              <td
                :colspan="sortedColumns.length + 4"
                class="px-3 py-8 text-center text-muted-foreground"
              >
                No rows yet. Click "Add Row" to get started.
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Footer: add row + pagination -->
      <div class="flex items-center justify-between">
        <Button
          size="sm"
          variant="outline"
          :disabled="sortedColumns.length === 0"
          @click="startAddRow"
        >
          <Plus class="mr-1 h-4 w-4" /> Add Row
        </Button>
        <div class="flex items-center gap-3 text-sm text-muted-foreground">
          <span>{{ rowTotal }} rows</span>
          <label class="flex items-center">
            <span class="relative inline-flex">
              <select
                :value="String(rowPageSize)"
                class="h-8 min-w-24 appearance-none rounded-md border bg-background pl-3 pr-9 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                @change="handleRowPageSizeChange"
              >
                <option
                  v-for="option in rowPageSizeOptions"
                  :key="option.label"
                  :value="String(option.value)"
                >
                  {{ option.label }}
                </option>
              </select>
              <ChevronDown class="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            </span>
          </label>
          <Button
            size="sm"
            variant="ghost"
            :disabled="rowPageSize === 'all' || rowPage === 0"
            @click="prevPage"
          >
            <ChevronLeft class="h-4 w-4" />
          </Button>
          <span>{{ rowPage + 1 }} / {{ totalPages }}</span>
          <Button
            size="sm"
            variant="ghost"
            :disabled="rowPageSize === 'all' || rowPage >= totalPages - 1"
            @click="nextPage"
          >
            <ChevronRight class="h-4 w-4" />
          </Button>
        </div>
      </div>
    </template>

    <!-- ════════ CREATE DIALOG ════════ -->
    <Dialog
      :open="showCreateDialog"
      title="New DataTable"
      @close="showCreateDialog = false"
    >
      <div class="flex flex-col gap-4 p-4">
        <div>
          <Label>Name</Label>
          <Input
            v-model="newName"
            placeholder="My Table"
            class="mt-1"
            @keydown.enter="handleCreate"
          />
        </div>
        <div>
          <Label>Description (optional)</Label>
          <Textarea
            v-model="newDescription"
            placeholder="What is this table for?"
            class="mt-1"
            :rows="2"
          />
        </div>
        <div class="flex justify-end">
          <Button
            :disabled="!newName.trim() || creating"
            @click="handleCreate"
          >
            {{ creating ? "Creating..." : "Create" }}
          </Button>
        </div>
      </div>
    </Dialog>

    <!-- ════════ SHARE DIALOG ════════ -->
    <DataTableShareDialog
      v-if="showShareDialog && selectedTable"
      :table-id="selectedTable.id"
      @close="showShareDialog = false"
    />

    <!-- ════════ COLUMN EDITOR ════════ -->
    <DataTableColumnEditor
      v-if="showColumnEditor"
      :column="editingColumn"
      @save="handleColumnSave"
      @close="showColumnEditor = false"
    />

    <!-- ════════ IMPORT DIALOG ════════ -->
    <DataTableImportDialog
      v-if="showImportDialog && selectedTable"
      :table-id="selectedTable.id"
      :columns="selectedTable.columns"
      @close="showImportDialog = false"
      @imported="handleImportComplete"
    />
  </div>
</template>
