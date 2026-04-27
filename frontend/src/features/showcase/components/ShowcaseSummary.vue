<script setup lang="ts">
import type { ShowcaseDefinition } from "@/features/showcase/showcase.types";

defineProps<{
  definition: ShowcaseDefinition;
}>();
</script>

<template>
  <section class="space-y-4">
    <div class="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">
      Page Guide
    </div>

    <div class="space-y-3">
      <h2 class="text-2xl font-semibold text-foreground">
        {{ definition.title }}
      </h2>
      <p class="text-sm leading-6 text-muted-foreground">
        {{ definition.summary }}
      </p>
    </div>

    <ul class="space-y-2">
      <li
        v-for="bullet in definition.bullets"
        :key="bullet"
        class="flex items-start gap-3 rounded-2xl border border-border/60 bg-background/65 px-4 py-3 text-sm text-muted-foreground"
      >
        <span class="mt-1 h-2 w-2 shrink-0 rounded-full bg-primary/75" />
        <span>{{ bullet }}</span>
      </li>
    </ul>
  </section>
</template>
