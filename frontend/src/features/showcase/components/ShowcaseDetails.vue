<script setup lang="ts">
import { ChevronDown } from "lucide-vue-next";

import type { ShowcaseDefinition } from "@/features/showcase/showcase.types";
import { cn } from "@/lib/utils";

const props = defineProps<{
  definition: ShowcaseDefinition;
  expandedDetailId: string | null;
}>();

const emit = defineEmits<{
  (e: "toggle", detailId: string): void;
}>();

function isExpanded(detailId: string): boolean {
  return props.expandedDetailId === detailId;
}
</script>

<template>
  <section class="space-y-3">
    <div class="flex items-center justify-between gap-3">
      <h3 class="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        More Detail
      </h3>
      <div class="h-px flex-1 bg-gradient-to-r from-primary/25 via-border/70 to-transparent" />
    </div>

    <div class="space-y-2">
      <article
        v-for="detail in definition.details"
        :key="detail.id"
        class="rounded-2xl border border-border/70 bg-background/70"
      >
        <button
          type="button"
          class="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
          @click="emit('toggle', detail.id)"
        >
          <span class="text-sm font-medium text-foreground">
            {{ detail.title }}
          </span>
          <ChevronDown
            :class="cn(
              'h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-300',
              isExpanded(detail.id) && 'rotate-180'
            )"
          />
        </button>

        <div
          :class="cn(
            'showcase-detail-content grid transition-[grid-template-rows] duration-300 ease-out',
            isExpanded(detail.id) ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
          )"
        >
          <div class="min-h-0 overflow-hidden">
            <p class="border-t border-border/60 px-4 py-3 text-sm leading-6 text-muted-foreground">
              {{ detail.content }}
            </p>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
@media (prefers-reduced-motion: reduce) {
  .showcase-detail-content,
  .showcase-detail-content :deep(svg) {
    transition: none !important;
  }
}
</style>
