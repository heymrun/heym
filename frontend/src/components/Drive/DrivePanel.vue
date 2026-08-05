<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  Check,
  ChevronDown,
  Copy,
  Download,
  FileText,
  HardDrive,
  Image,
  RefreshCw,
  Search,
  Settings,
  Share2,
  Sheet,
  Trash2,
  Upload,
  Users,
} from "lucide-vue-next";

import type { GeneratedFile } from "@/types/file";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import { formatDate, formatFileSize } from "@/lib/utils";
import { filesApi } from "@/services/api";

import BulkFileShareDialog from "./BulkFileShareDialog.vue";
import FileShareDialog from "./FileShareDialog.vue";

const files = ref<GeneratedFile[]>([]);
const total = ref(0);
const loading = ref(true);
const clearing = ref(false);
const error = ref("");
const searchQuery = ref("");
const page = ref(0);

const PAGE_SIZE_OPTIONS = [25, 50, 100, "All"] as const;
const ALL_PAGE_SIZE = 1000;
const pageSizeChoice = ref<(typeof PAGE_SIZE_OPTIONS)[number]>(25);
const pageSize = computed(() =>
  pageSizeChoice.value === "All" ? ALL_PAGE_SIZE : pageSizeChoice.value,
);

const showShare = ref(false);
const shareFileId = ref("");
const shareFilename = ref("");

const showBulk = ref(false);
const downloadingBulk = ref(false);
const deletingBulk = ref(false);
const selectedIds = ref<Set<string>>(new Set());
const lastSelectedIndex = ref<number | null>(null);

const filtered = computed(() => {
  if (!searchQuery.value) return files.value;
  const q = searchQuery.value.toLowerCase();
  return files.value.filter(
    (f) =>
      f.filename.toLowerCase().includes(q) ||
      f.mime_type.toLowerCase().includes(q) ||
      (f.source_node_label || "").toLowerCase().includes(q),
  );
});
const hasOwnedFilesOnPage = computed(() => files.value.some((file) => !file.is_shared));

// Only owned files can be team-shared or given share links, so only they are selectable.
const selectableFiles = computed(() => filtered.value.filter((f) => !f.is_shared));
const selectedFileIds = computed(() => Array.from(selectedIds.value));
const allSelectableSelected = computed(
  () =>
    selectableFiles.value.length > 0 &&
    selectableFiles.value.every((f) => selectedIds.value.has(f.id)),
);
const someSelectableSelected = computed(
  () => selectableFiles.value.some((f) => selectedIds.value.has(f.id)) && !allSelectableSelected.value,
);

function clearSelection(): void {
  selectedIds.value = new Set();
  lastSelectedIndex.value = null;
}

function toggleRow(file: GeneratedFile, index: number, shiftKey: boolean): void {
  const next = new Set(selectedIds.value);
  if (shiftKey && lastSelectedIndex.value !== null) {
    const [start, end] = [lastSelectedIndex.value, index].sort((a, b) => a - b);
    const select = !next.has(file.id);
    for (let i = start; i <= end; i++) {
      const target = selectableFiles.value[i];
      if (!target) continue;
      if (select) next.add(target.id);
      else next.delete(target.id);
    }
  } else if (next.has(file.id)) {
    next.delete(file.id);
  } else {
    next.add(file.id);
  }
  selectedIds.value = next;
  lastSelectedIndex.value = index;
}

function toggleSelectAll(): void {
  if (allSelectableSelected.value) {
    clearSelection();
  } else {
    selectedIds.value = new Set(selectableFiles.value.map((f) => f.id));
    lastSelectedIndex.value = null;
  }
}

async function loadFiles() {
  loading.value = true;
  error.value = "";
  try {
    const res = await filesApi.list({
      limit: pageSize.value,
      offset: page.value * pageSize.value,
    });
    files.value = res.files;
    total.value = res.total;
    clearSelection();
  } catch {
    error.value = "Failed to load files";
  } finally {
    loading.value = false;
  }
}

async function deleteFile(file: GeneratedFile) {
  if (!window.confirm(`Delete "${file.filename}"? This cannot be undone.`)) return;
  try {
    await filesApi.delete(file.id);
    await loadFiles();
  } catch {
    error.value = "Failed to delete file";
  }
}

async function clearAllFiles() {
  if (total.value === 0) return;
  if (!window.confirm("Delete all files in Drive? This action cannot be undone.")) return;
  clearing.value = true;
  error.value = "";
  try {
    await filesApi.clearAll();
    page.value = 0;
    await loadFiles();
  } catch {
    error.value = "Failed to clear Drive files";
  } finally {
    clearing.value = false;
  }
}

const isDragging = ref(false);
const uploading = ref(false);
const uploadError = ref("");
const dragDepth = ref(0);

function isFileDrag(e: DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes("Files");
}

function handleWindowDragEnter(e: DragEvent): void {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth.value++;
  isDragging.value = true;
  if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
}

function handleWindowDragOver(e: DragEvent): void {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
  isDragging.value = true;
}

function handleWindowDragLeave(e: DragEvent): void {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth.value = Math.max(0, dragDepth.value - 1);
  if (dragDepth.value === 0) {
    isDragging.value = false;
  }
}

async function handleDrop(e: DragEvent): Promise<void> {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth.value = 0;
  isDragging.value = false;
  const droppedFiles = Array.from(e.dataTransfer?.files ?? []);
  if (!droppedFiles.length) return;
  uploading.value = true;
  uploadError.value = "";
  try {
    for (const f of droppedFiles) {
      await filesApi.upload(f);
    }
    await loadFiles();
  } catch {
    uploadError.value = "Upload failed";
  } finally {
    uploading.value = false;
  }
}

function openShare(file: GeneratedFile) {
  shareFileId.value = file.id;
  shareFilename.value = file.filename;
  showShare.value = true;
}

function downloadFile(file: GeneratedFile): void {
  const url = file.authenticated_download_url || file.download_url;
  if (!url) return;
  window.open(url, "_blank", "noopener");
}

// The file UUID is what Drive and Converter nodes take, so make it one click to grab.
const copiedFileId = ref("");
let copiedResetTimer: ReturnType<typeof setTimeout> | undefined;

async function copyFileId(file: GeneratedFile): Promise<void> {
  if (typeof navigator === "undefined" || !navigator.clipboard) return;
  try {
    await navigator.clipboard.writeText(file.id);
    copiedFileId.value = file.id;
    clearTimeout(copiedResetTimer);
    copiedResetTimer = setTimeout(() => {
      copiedFileId.value = "";
    }, 1500);
  } catch {
    // Clipboard access can be denied; there is nothing useful to report here.
  }
}

async function downloadSelected(): Promise<void> {
  const ids = selectedFileIds.value;
  if (ids.length === 0 || downloadingBulk.value) return;
  downloadingBulk.value = true;
  error.value = "";
  try {
    const blob = await filesApi.bulkDownload(ids);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "heym-drive-files.zip";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch {
    error.value = "Failed to download selected files";
  } finally {
    downloadingBulk.value = false;
  }
}

async function deleteSelected(): Promise<void> {
  const ids = selectedFileIds.value;
  if (ids.length === 0 || deletingBulk.value) return;
  if (
    !window.confirm(
      `Delete ${ids.length} selected file${ids.length === 1 ? "" : "s"}? This cannot be undone.`,
    )
  ) {
    return;
  }
  deletingBulk.value = true;
  error.value = "";
  try {
    await filesApi.bulkDelete(ids);
    await loadFiles();
  } catch {
    error.value = "Failed to delete selected files";
  } finally {
    deletingBulk.value = false;
  }
}

function mimeIcon(mime: string) {
  if (mime.startsWith("image/")) return Image;
  if (mime === "application/pdf") return FileText;
  if (mime.includes("csv") || mime.includes("spreadsheet")) return Sheet;
  return FileText;
}

function mimeColor(mime: string) {
  if (mime.startsWith("image/")) return "text-blue-400";
  if (mime === "application/pdf") return "text-red-400";
  if (mime.includes("csv") || mime.includes("spreadsheet")) return "text-green-400";
  if (mime.includes("word") || mime.includes("docx")) return "text-indigo-400";
  return "text-muted-foreground";
}

const totalPages = computed(() => Math.ceil(total.value / pageSize.value));

watch(page, () => {
  if (!clearing.value) void loadFiles();
});

watch(pageSizeChoice, () => {
  if (page.value === 0) void loadFiles();
  else page.value = 0;
});

// A search only filters the rows currently loaded on the page, so as soon as the
// user types we switch to "All" to search across every accessible file. The prior
// page-size choice is restored when the search is cleared.
const pageSizeBeforeSearch = ref<(typeof PAGE_SIZE_OPTIONS)[number] | null>(null);
watch(searchQuery, (query, previous) => {
  const hasQuery = query.trim().length > 0;
  const hadQuery = previous.trim().length > 0;
  if (hasQuery && !hadQuery && pageSizeChoice.value !== "All") {
    pageSizeBeforeSearch.value = pageSizeChoice.value;
    pageSizeChoice.value = "All";
  } else if (!hasQuery && hadQuery && pageSizeBeforeSearch.value !== null) {
    pageSizeChoice.value = pageSizeBeforeSearch.value;
    pageSizeBeforeSearch.value = null;
  }
});

onMounted(() => {
  void loadFiles();
  window.addEventListener("dragenter", handleWindowDragEnter);
  window.addEventListener("dragover", handleWindowDragOver);
  window.addEventListener("dragleave", handleWindowDragLeave);
  window.addEventListener("drop", handleDrop);
});

onBeforeUnmount(() => {
  window.removeEventListener("dragenter", handleWindowDragEnter);
  window.removeEventListener("dragover", handleWindowDragOver);
  window.removeEventListener("dragleave", handleWindowDragLeave);
  window.removeEventListener("drop", handleDrop);
  clearTimeout(copiedResetTimer);
});
</script>

<template>
  <div class="space-y-4 relative min-h-[calc(100vh-220px)]">
    <!-- Drag overlay -->
    <div
      v-if="isDragging"
      class="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-primary bg-primary/10 pointer-events-none"
    >
      <Upload class="w-8 h-8 text-primary mb-2" />
      <p class="text-sm font-medium text-primary">
        Drop to upload
      </p>
    </div>

    <!-- Upload progress -->
    <div
      v-if="uploading"
      class="text-sm text-muted-foreground bg-muted/50 p-2 rounded-lg flex items-center gap-2"
    >
      <RefreshCw class="w-3.5 h-3.5 animate-spin" />
      Uploading...
    </div>

    <!-- Upload error -->
    <div
      v-if="uploadError"
      class="text-sm text-destructive bg-destructive/10 p-3 rounded-lg"
    >
      {{ uploadError }}
    </div>

    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
      <div class="flex items-center gap-2 shrink-0">
        <HardDrive class="w-5 h-5 text-muted-foreground" />
        <h2 class="text-lg font-semibold">
          Drive
        </h2>
        <span class="text-xs text-muted-foreground whitespace-nowrap">({{ total }} files)</span>
      </div>
      <div class="grid grid-cols-[1fr_auto_auto] items-center gap-2 sm:flex sm:flex-wrap sm:justify-end">
        <div class="relative min-w-0">
          <Search class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            v-model="searchQuery"
            placeholder="Search files..."
            class="pl-8 h-8 text-xs w-full sm:w-48"
          />
        </div>
        <Button
          size="sm"
          variant="ghost"
          :disabled="loading"
          class="px-2 sm:px-4"
          @click="loadFiles"
        >
          <RefreshCw
            class="w-3.5 h-3.5"
            :class="loading && 'animate-spin'"
          />
        </Button>
        <Button
          v-if="hasOwnedFilesOnPage"
          size="sm"
          variant="destructive"
          :loading="clearing"
          :disabled="loading || clearing"
          class="px-2 sm:px-4"
          @click="clearAllFiles"
        >
          <Trash2 class="w-3.5 h-3.5" />
          Clear All
        </Button>
      </div>
    </div>

    <!-- Error -->
    <div
      v-if="error"
      class="text-sm text-destructive bg-destructive/10 p-3 rounded-lg"
    >
      {{ error }}
    </div>

    <!-- Loading -->
    <div
      v-if="loading && files.length === 0"
      class="text-center py-12 text-muted-foreground"
    >
      <RefreshCw class="w-6 h-6 mx-auto mb-2 animate-spin" />
      <p class="text-sm">
        Loading files...
      </p>
    </div>

    <!-- Empty state -->
    <div
      v-else-if="files.length === 0"
      class="text-center py-16 text-muted-foreground"
    >
      <HardDrive class="w-10 h-10 mx-auto mb-3 opacity-40" />
      <p class="text-sm font-medium">
        No files yet
      </p>
      <p class="text-xs mt-1">
        Files generated by skills will appear here
      </p>
    </div>

    <!-- Bulk action bar -->
    <div
      v-if="selectedIds.size > 0"
      class="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm"
    >
      <span class="font-medium">{{ selectedIds.size }} selected</span>
      <Button
        size="sm"
        :loading="downloadingBulk"
        :disabled="downloadingBulk"
        @click="downloadSelected"
      >
        <Download class="w-3.5 h-3.5 mr-1" />
        Download ZIP
      </Button>
      <Button
        size="sm"
        @click="showBulk = true"
      >
        <Settings class="w-3.5 h-3.5 mr-1" />
        Actions
      </Button>
      <Button
        size="sm"
        variant="destructive"
        :loading="deletingBulk"
        :disabled="deletingBulk"
        @click="deleteSelected"
      >
        <Trash2 class="w-3.5 h-3.5 mr-1" />
        Delete
      </Button>
      <Button
        size="sm"
        variant="ghost"
        @click="clearSelection"
      >
        Clear selection
      </Button>
    </div>

    <!-- File list -->
    <div
      v-if="files.length > 0"
      class="rounded-lg border border-border overflow-hidden"
    >
      <!-- Below ~320px even the truncated layout runs out of room, so scroll rather than clip. -->
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-muted/50 text-xs text-muted-foreground">
            <tr>
              <th class="w-9 px-3 py-2">
                <input
                  v-if="selectableFiles.length > 0"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background align-middle"
                  title="Select all"
                  :checked="allSelectableSelected"
                  :indeterminate="someSelectableSelected"
                  @change="toggleSelectAll"
                >
              </th>
              <th class="text-left px-3 py-2 font-medium">
                Name
              </th>
              <th class="text-left px-3 py-2 font-medium hidden sm:table-cell">
                Type
              </th>
              <th class="text-left px-3 py-2 font-medium hidden md:table-cell">
                Size
              </th>
              <th class="text-left px-3 py-2 font-medium hidden lg:table-cell">
                Source
              </th>
              <th class="text-left px-3 py-2 font-medium hidden sm:table-cell">
                Date
              </th>
              <th class="text-right px-3 py-2 font-medium w-px whitespace-nowrap">
                Actions
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr
              v-for="file in filtered"
              :key="file.id"
              class="transition-colors"
              :class="selectedIds.has(file.id) ? 'bg-primary/5' : 'hover:bg-muted/30'"
            >
              <td class="w-9 px-3 py-2.5 align-top">
                <input
                  v-if="!file.is_shared"
                  type="checkbox"
                  class="mt-0.5 h-4 w-4 rounded border-input bg-background"
                  :checked="selectedIds.has(file.id)"
                  @click="toggleRow(file, selectableFiles.indexOf(file), ($event as MouseEvent).shiftKey)"
                >
              </td>
              <td class="px-3 py-2.5">
                <div class="flex items-center gap-2 min-w-0">
                  <component
                    :is="mimeIcon(file.mime_type)"
                    class="w-4 h-4 shrink-0"
                    :class="mimeColor(file.mime_type)"
                  />
                  <span class="truncate max-w-[40vw] sm:max-w-[300px]">{{ file.filename }}</span>
                  <span
                    v-if="file.shared_with_my_teams && !file.is_shared"
                    class="inline-flex shrink-0 items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary dark:bg-violet-400/15 dark:text-violet-200"
                  >
                    <Users class="w-3 h-3" />
                    Teams
                  </span>
                  <span
                    v-if="file.is_shared"
                    class="inline-flex shrink-0 items-center gap-1 rounded bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-medium text-blue-500"
                  >
                    <Users class="w-3 h-3" />
                    Shared
                  </span>
                </div>
                <p
                  v-if="file.is_shared && (file.shared_by || file.shared_by_team)"
                  class="mt-1 text-[11px] text-muted-foreground"
                >
                  Shared{{ file.shared_by ? ` by ${file.shared_by}` : "" }}{{ file.shared_by_team ? ` via ${file.shared_by_team}` : "" }}
                </p>
              </td>
              <td class="px-3 py-2.5 text-xs text-muted-foreground hidden sm:table-cell">
                {{ file.mime_type.split("/").pop() }}
              </td>
              <td class="px-3 py-2.5 text-xs text-muted-foreground hidden md:table-cell whitespace-nowrap">
                {{ formatFileSize(file.size_bytes) }}
              </td>
              <td class="px-3 py-2.5 text-xs text-muted-foreground hidden lg:table-cell whitespace-nowrap">
                {{ file.source_node_label || "-" }}
              </td>
              <td class="px-3 py-2.5 text-xs text-muted-foreground hidden sm:table-cell whitespace-nowrap">
                {{ formatDate(file.created_at) }}
              </td>
              <td class="px-3 py-2.5 w-px whitespace-nowrap">
                <div
                  class="flex items-center justify-end gap-0.5 sm:gap-1"
                  @click.stop
                >
                  <button
                    class="p-1 rounded hover:bg-muted"
                    :title="copiedFileId === file.id ? 'File ID copied' : 'Copy file ID'"
                    @click="copyFileId(file)"
                  >
                    <Check
                      v-if="copiedFileId === file.id"
                      class="w-3.5 h-3.5 text-emerald-500"
                    />
                    <Copy
                      v-else
                      class="w-3.5 h-3.5"
                    />
                  </button>
                  <button
                    class="p-1 rounded hover:bg-muted"
                    title="Download"
                    @click="downloadFile(file)"
                  >
                    <Download class="w-3.5 h-3.5" />
                  </button>
                  <button
                    v-if="!file.is_shared"
                    class="p-1 rounded hover:bg-muted"
                    title="Share"
                    @click="openShare(file)"
                  >
                    <Share2 class="w-3.5 h-3.5" />
                  </button>
                  <button
                    v-if="!file.is_shared"
                    class="p-1 rounded hover:bg-destructive/10 text-destructive"
                    title="Delete"
                    @click="deleteFile(file)"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Pagination + page size -->
    <div
      v-if="files.length > 0"
      class="flex items-center justify-between gap-2 text-xs"
    >
      <label class="flex items-center gap-1.5 text-muted-foreground">
        Rows per page
        <span class="relative inline-flex">
          <select
            v-model="pageSizeChoice"
            class="h-8 min-w-24 appearance-none rounded-md border border-border bg-background pl-3 pr-9 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option
              v-for="opt in PAGE_SIZE_OPTIONS"
              :key="opt"
              :value="opt"
            >
              {{ opt }}
            </option>
          </select>
          <ChevronDown class="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        </span>
      </label>
      <div
        v-if="totalPages > 1"
        class="flex items-center gap-2"
      >
        <Button
          size="sm"
          variant="ghost"
          :disabled="page === 0"
          @click="page--"
        >
          Previous
        </Button>
        <span class="text-muted-foreground">
          Page {{ page + 1 }} of {{ totalPages }}
        </span>
        <Button
          size="sm"
          variant="ghost"
          :disabled="page >= totalPages - 1"
          @click="page++"
        >
          Next
        </Button>
      </div>
    </div>

    <!-- Share dialog -->
    <FileShareDialog
      :open="showShare"
      :file-id="shareFileId"
      :filename="shareFilename"
      :shared-with-my-teams="files.find((f) => f.id === shareFileId)?.shared_with_my_teams ?? false"
      @close="showShare = false"
      @updated="loadFiles"
    />

    <!-- Bulk actions dialog -->
    <BulkFileShareDialog
      :open="showBulk"
      :file-ids="selectedFileIds"
      @close="showBulk = false"
      @updated="loadFiles"
    />
  </div>
</template>
