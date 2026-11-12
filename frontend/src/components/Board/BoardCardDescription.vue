<script setup lang="ts">
import { computed, ref, useId } from "vue";

import Textarea from "@/components/ui/Textarea.vue";
import { renderMarkdown } from "@/lib/markdown";

const content = defineModel<string>({ required: true });
const preview = ref(false);
const descriptionId = useId();
const contentId = useId();
const renderedContent = computed<string>(() => renderMarkdown(content.value));
</script>

<template>
  <section>
    <div class="mb-1 flex items-center gap-2">
      <h3
        :id="descriptionId"
        class="text-xs font-semibold uppercase text-muted-foreground"
      >
        Description
      </h3>
      <button
        type="button"
        class="rounded px-1.5 py-0.5 text-xs font-medium text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :aria-pressed="preview"
        :aria-controls="contentId"
        @click="preview = !preview"
      >
        {{ preview ? "Edit" : "Preview" }}
      </button>
    </div>
    <div :id="contentId">
      <div
        v-if="preview"
        class="board-description-md min-h-[96px] overflow-x-auto rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground [overflow-wrap:anywhere]"
        role="region"
        :aria-labelledby="descriptionId"
        data-testid="card-description-preview"
      >
        <!-- eslint-disable-next-line vue/no-v-html -- Sanitized by the shared Markdown renderer. -->
        <div v-html="renderedContent" />
        <p
          v-if="!content.trim()"
          class="text-muted-foreground"
        >
          No description yet.
        </p>
      </div>
      <Textarea
        v-else
        v-model="content"
        :aria-labelledby="descriptionId"
        :rows="3"
        placeholder="Describe the job for this card"
      />
    </div>
    <slot />
  </section>
</template>

<style scoped>
.board-description-md :deep(p),
.board-description-md :deep(ul),
.board-description-md :deep(ol),
.board-description-md :deep(pre),
.board-description-md :deep(blockquote),
.board-description-md :deep(table) {
  margin: 0 0 0.6rem;
}

.board-description-md :deep(:last-child) {
  margin-bottom: 0;
}

.board-description-md :deep(:is(h1, h2, h3, h4, h5, h6)) {
  margin: 0.6rem 0 0.4rem;
  font-weight: 600;
  line-height: 1.3;
}

.board-description-md :deep(h1) {
  font-size: 1.4rem;
}

.board-description-md :deep(h2) {
  font-size: 1.2rem;
}

.board-description-md :deep(h3) {
  font-size: 1.05rem;
}

.board-description-md :deep(ul) {
  list-style: disc;
  padding-left: 1.5rem;
}

.board-description-md :deep(ol) {
  list-style: decimal;
  padding-left: 1.5rem;
}

.board-description-md :deep(a) {
  color: hsl(var(--primary));
  text-decoration: underline;
}

.dark .board-description-md :deep(a) {
  color: hsl(var(--primary-soft));
}

.board-description-md :deep(code),
.board-description-md :deep(pre) {
  border-radius: 0.25rem;
  background: hsl(var(--muted));
}

.board-description-md :deep(code) {
  padding: 0.1rem 0.25rem;
  font-size: 0.85em;
}

.board-description-md :deep(pre) {
  overflow-x: auto;
  padding: 0.75rem;
}

.board-description-md :deep(pre code) {
  padding: 0;
  background: transparent;
}

.board-description-md :deep(blockquote) {
  border-left: 3px solid hsl(var(--border));
  padding-left: 0.75rem;
  color: hsl(var(--muted-foreground));
}

.board-description-md :deep(table) {
  border-collapse: collapse;
}

.board-description-md :deep(th),
.board-description-md :deep(td) {
  border: 1px solid hsl(var(--border));
  padding: 0.4rem 0.6rem;
}

.board-description-md :deep(th) {
  background: hsl(var(--muted));
}

.board-description-md :deep(img) {
  max-width: 100%;
  height: auto;
}

.board-description-md :deep(hr) {
  margin: 0.75rem 0;
  border-color: hsl(var(--border));
}
</style>
