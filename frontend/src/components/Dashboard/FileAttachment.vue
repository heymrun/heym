<script setup lang="ts">
import { Download, FileText, Image, Sheet } from "lucide-vue-next";

import { formatFileSize } from "@/lib/utils";

export interface FileLink {
  filename: string;
  mime_type: string;
  size_bytes: number;
  download_url: string;
}

defineProps<{
  files: FileLink[];
}>();

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
</script>

<template>
  <div
    v-if="files.length"
    class="flex flex-wrap gap-2 mt-2"
  >
    <a
      v-for="(file, idx) in files"
      :key="idx"
      :href="file.download_url"
      target="_blank"
      rel="noopener"
      class="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border bg-card hover:bg-muted/60 transition-colors text-xs group"
    >
      <component
        :is="mimeIcon(file.mime_type)"
        class="w-3.5 h-3.5 shrink-0"
        :class="mimeColor(file.mime_type)"
      />
      <span class="truncate max-w-[160px]">{{ file.filename }}</span>
      <span class="text-muted-foreground">{{ formatFileSize(file.size_bytes) }}</span>
      <Download class="w-3 h-3 text-muted-foreground group-hover:text-foreground transition-colors" />
    </a>
  </div>
</template>
