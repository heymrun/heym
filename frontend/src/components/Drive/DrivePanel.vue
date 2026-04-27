<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  FileText,
  HardDrive,
  Image,
  RefreshCw,
  Search,
  Share2,
  Sheet,
  Trash2,
  Upload,
} from "lucide-vue-next";

import type { GeneratedFile } from "@/types/file";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import { formatDate, formatFileSize } from "@/lib/utils";
import { filesApi } from "@/services/api";

import FileShareDialog from "./FileShareDialog.vue";

const files = ref<GeneratedFile[]>([]);
const total = ref(0);
const loading = ref(true);
const clearing = ref(false);
const error = ref("");
const searchQuery = ref("");
const page = ref(0);
const pageSize = 25;

const showShare = ref(false);
const shareFileId = ref("");
const shareFilename = ref("");

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

async function loadFiles() {
  loading.value = true;
  error.value = "";
  try {
    const res = await filesApi.list({ limit: pageSize, offset: page.value * pageSize });
    files.value = res.files;
    total.value = res.total;
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

function handleDragOver(e: DragEvent): void {
  e.preventDefault();
  isDragging.value = true;
}

function handleDragLeave(e: DragEvent): void {
  if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) {
    isDragging.value = false;
  }
}

async function handleDrop(e: DragEvent): Promise<void> {
  e.preventDefault();
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

const totalPages = computed(() => Math.ceil(total.value / pageSize));

watch(page, () => {
  if (!clearing.value) void loadFiles();
});
onMounted(loadFiles);
</script>

<template>
  <div
    class="space-y-4 relative"
    @dragover="handleDragOver"
    @dragleave="handleDragLeave"
    @drop="handleDrop"
  >
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
    <div class="flex items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <HardDrive class="w-5 h-5 text-muted-foreground" />
        <h2 class="text-lg font-semibold">
          Drive
        </h2>
        <span class="text-xs text-muted-foreground">({{ total }} files)</span>
      </div>
      <div class="flex items-center gap-2">
        <div class="relative">
          <Search class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            v-model="searchQuery"
            placeholder="Search files..."
            class="pl-8 h-8 text-xs w-48"
          />
        </div>
        <Button
          size="sm"
          variant="ghost"
          :disabled="loading"
          @click="loadFiles"
        >
          <RefreshCw
            class="w-3.5 h-3.5"
            :class="loading && 'animate-spin'"
          />
        </Button>
        <Button
          v-if="total > 0"
          size="sm"
          variant="destructive"
          :loading="clearing"
          :disabled="loading || clearing"
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

    <!-- File list -->
    <div
      v-else
      class="rounded-lg border border-border overflow-hidden"
    >
      <table class="w-full text-sm">
        <thead class="bg-muted/50 text-xs text-muted-foreground">
          <tr>
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
            <th class="text-right px-3 py-2 font-medium">
              Actions
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          <tr
            v-for="file in filtered"
            :key="file.id"
            class="hover:bg-muted/30 transition-colors"
          >
            <td class="px-3 py-2.5">
              <div class="flex items-center gap-2">
                <component
                  :is="mimeIcon(file.mime_type)"
                  class="w-4 h-4 shrink-0"
                  :class="mimeColor(file.mime_type)"
                />
                <span class="truncate max-w-[200px] sm:max-w-[300px]">{{ file.filename }}</span>
              </div>
            </td>
            <td class="px-3 py-2.5 text-xs text-muted-foreground hidden sm:table-cell">
              {{ file.mime_type.split("/").pop() }}
            </td>
            <td class="px-3 py-2.5 text-xs text-muted-foreground hidden md:table-cell">
              {{ formatFileSize(file.size_bytes) }}
            </td>
            <td class="px-3 py-2.5 text-xs text-muted-foreground hidden lg:table-cell">
              {{ file.source_node_label || "-" }}
            </td>
            <td class="px-3 py-2.5 text-xs text-muted-foreground hidden sm:table-cell">
              {{ formatDate(file.created_at) }}
            </td>
            <td class="px-3 py-2.5">
              <div
                class="flex items-center justify-end gap-1"
                @click.stop
              >
                <button
                  class="p-1 rounded hover:bg-muted"
                  title="Share"
                  @click="openShare(file)"
                >
                  <Share2 class="w-3.5 h-3.5" />
                </button>
                <button
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

    <!-- Pagination -->
    <div
      v-if="totalPages > 1"
      class="flex items-center justify-center gap-2 text-xs"
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

    <!-- Share dialog -->
    <FileShareDialog
      :open="showShare"
      :file-id="shareFileId"
      :filename="shareFilename"
      @close="showShare = false"
    />
  </div>
</template>
