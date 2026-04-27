<script setup lang="ts">
import { computed } from "vue";

import type { ShowcaseDefinition } from "@/features/showcase/showcase.types";
import { cn } from "@/lib/utils";

const props = defineProps<{
  definition: ShowcaseDefinition;
}>();

const toneClasses = computed<Record<string, string>>(() => ({
  primary: "border-primary/20 bg-primary/[0.08]",
  blue: "border-sky-500/20 bg-sky-500/[0.08]",
  green: "border-emerald-500/20 bg-emerald-500/[0.08]",
  amber: "border-amber-500/20 bg-amber-500/[0.08]",
}));

function highlightClass(tone: string | undefined): string {
  return toneClasses.value[tone ?? "primary"] ?? toneClasses.value.primary;
}
</script>

<template>
  <section class="space-y-3">
    <div class="flex items-center justify-between gap-3">
      <h3 class="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        Highlights
      </h3>
      <div class="h-px flex-1 bg-gradient-to-r from-primary/25 via-border/70 to-transparent" />
    </div>

    <div class="grid gap-3">
      <article
        v-for="(highlight, index) in props.definition.highlights"
        :key="highlight.title"
        :class="cn(
          'showcase-highlight rounded-3xl border px-4 py-4 shadow-sm transition-transform duration-300',
          highlightClass(highlight.tone)
        )"
        :style="{ animationDelay: `${index * 90}ms` }"
      >
        <p
          v-if="highlight.eyebrow"
          class="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground"
        >
          {{ highlight.eyebrow }}
        </p>
        <h4 class="mt-2 text-base font-semibold text-foreground">
          {{ highlight.title }}
        </h4>
        <p class="mt-1.5 text-sm leading-6 text-muted-foreground">
          {{ highlight.description }}
        </p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.showcase-highlight {
  animation: showcase-highlight-in 0.45s cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes showcase-highlight-in {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .showcase-highlight {
    animation: none;
  }
}
</style>
