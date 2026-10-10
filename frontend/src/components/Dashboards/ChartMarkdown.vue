<script setup lang="ts">
import { computed } from "vue";

import { renderChartMarkdown } from "@/lib/markdown";

const props = defineProps<{ text: string }>();

// Render the markdown body of a `text` chart to sanitized HTML.
const html = computed((): string => renderChartMarkdown(props.text));
</script>

<template>
  <!-- eslint-disable vue/no-v-html -- Sanitized via DOMPurify in renderChartMarkdown -->
  <div
    class="chart-markdown h-full overflow-auto break-words px-1 py-1 text-sm text-foreground"
    v-html="html"
  />
</template>

<style scoped>
.chart-markdown :deep(p) {
  margin: 0 0 0.5rem;
}

.chart-markdown :deep(p:last-child) {
  margin-bottom: 0;
}

.chart-markdown :deep(h1),
.chart-markdown :deep(h2),
.chart-markdown :deep(h3) {
  margin: 0.5rem 0 0.35rem;
  font-weight: 700;
  line-height: 1.2;
}

.chart-markdown :deep(h1) {
  font-size: 1.5rem;
}

.chart-markdown :deep(h2) {
  font-size: 1.25rem;
}

.chart-markdown :deep(h3) {
  font-size: 1.05rem;
}

.chart-markdown :deep(ul),
.chart-markdown :deep(ol) {
  margin: 0 0 0.5rem;
  padding-left: 1.25rem;
}

.chart-markdown :deep(ul) {
  list-style: disc;
}

.chart-markdown :deep(ol) {
  list-style: decimal;
}

.chart-markdown :deep(a) {
  color: rgb(37 99 235);
  text-decoration: underline;
}

.chart-markdown :deep(code) {
  border-radius: 0.25rem;
  background: rgb(0 0 0 / 0.08);
  padding: 0.1rem 0.3rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 0.85em;
}

.chart-markdown :deep(pre) {
  margin: 0 0 0.5rem;
  overflow-x: auto;
  border-radius: 0.375rem;
  background: rgb(0 0 0 / 0.06);
  padding: 0.5rem 0.75rem;
}

.chart-markdown :deep(pre code) {
  background: transparent;
  padding: 0;
}

.chart-markdown :deep(strong) {
  font-weight: 700;
}

.chart-markdown :deep(em) {
  font-style: italic;
}

.chart-markdown :deep(blockquote) {
  margin: 0 0 0.5rem;
  border-left: 3px solid rgb(0 0 0 / 0.15);
  padding-left: 0.75rem;
  color: hsl(var(--muted-foreground));
}

.chart-markdown :deep(hr) {
  margin: 0.75rem 0;
  border: none;
  border-top: 1px solid hsl(var(--border));
}

:global(.dark) .chart-markdown :deep(a) {
  color: rgb(96 165 250);
}

:global(.dark) .chart-markdown :deep(code),
:global(.dark) .chart-markdown :deep(pre) {
  background: rgb(255 255 255 / 0.1);
}
</style>
