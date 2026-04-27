<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";

import type { NodeData } from "@/types/workflow";

import { cn } from "@/lib/utils";
import { useWorkflowStore } from "@/stores/workflow";

interface Props {
  id: string;
  data: NodeData;
  selected?: boolean;
}

const props = defineProps<Props>();
const workflowStore = useWorkflowStore();

const isEditing = ref(false);
const localNote = ref(props.data.note || "");
const textareaRef = ref<HTMLTextAreaElement | null>(null);

watch(
  () => props.data.note,
  (value) => {
    if (!isEditing.value) {
      localNote.value = value || "";
    }
  }
);

function escapeHtml(input: string): string {
  return input
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function sanitizeUrl(url: string): string {
  if (url.startsWith("http://") || url.startsWith("https://")) {
    return url;
  }
  return "#";
}

function renderMarkdown(raw: string): string {
  const safe = escapeHtml(raw);
  const lines = safe.split("\n");
  const result: string[] = [];
  let currentParagraph: string[] = [];

  function flushParagraph(): void {
    if (currentParagraph.length > 0) {
      result.push(`<p>${currentParagraph.join("<br />")}</p>`);
      currentParagraph = [];
    }
  }

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed === "") {
      flushParagraph();
      continue;
    }

    if (trimmed.startsWith("### ")) {
      flushParagraph();
      result.push(`<h3 class="text-base font-bold mt-2 mb-1">${trimmed.slice(4)}</h3>`);
    } else if (trimmed.startsWith("## ")) {
      flushParagraph();
      result.push(`<h2 class="text-lg font-bold mt-2 mb-1">${trimmed.slice(3)}</h2>`);
    } else if (trimmed.startsWith("# ")) {
      flushParagraph();
      result.push(`<h1 class="text-xl font-bold mt-2 mb-1">${trimmed.slice(2)}</h1>`);
    } else {
      let processed = line
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.+?)\*/g, "<em>$1</em>")
        .replace(/`(.+?)`/g, "<code class=\"px-1 py-0.5 rounded bg-black/10 dark:bg-white/10 font-mono text-xs\">$1</code>")
        .replace(/\[([^\]]+)]\(([^)]+)\)/g, (_match, text, url) => {
          const safeUrl = sanitizeUrl(url);
          return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer" class="text-blue-600 dark:text-blue-400 underline">${text}</a>`;
        });
      currentParagraph.push(processed);
    }
  }

  flushParagraph();
  return result.join("");
}

const renderedNote = computed(() => {
  const value = (props.data.note || "").trim();
  const content = value.length > 0 ? value : "Double click to edit";
  return renderMarkdown(content);
});

function startEditing(): void {
  isEditing.value = true;
  localNote.value = props.data.note || "";
  nextTick(() => textareaRef.value?.focus());
}

function stopEditing(): void {
  isEditing.value = false;
  workflowStore.updateNode(props.id, { note: localNote.value });
}
</script>

<template>
  <!-- eslint-disable vue/no-v-html -->
  <div
    :class="cn(
      'min-w-[200px] max-w-[320px] rounded-lg border-2 bg-yellow-100/80 dark:bg-yellow-900/30 border-yellow-300 dark:border-yellow-700 px-4 py-3 shadow-md text-sm text-yellow-900 dark:text-yellow-100',
      selected && 'ring-2 ring-primary ring-offset-2 ring-offset-background'
    )
    "
    @dblclick.stop="startEditing"
  >
    <div class="text-xs font-semibold uppercase tracking-wide text-yellow-800/80 dark:text-yellow-200/80">
      Sticky Note
    </div>
    <div class="mt-2">
      <textarea
        v-if="isEditing"
        ref="textareaRef"
        v-model="localNote"
        class="w-full min-h-[120px] bg-transparent border border-yellow-300/60 dark:border-yellow-700/60 rounded-md p-2 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-400"
        @blur="stopEditing"
      />
      <div
        v-else
        class="space-y-1 leading-relaxed"
        v-html="renderedNote"
      />
    </div>
  </div>
</template>