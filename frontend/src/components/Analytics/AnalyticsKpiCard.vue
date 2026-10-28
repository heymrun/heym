<script setup lang="ts">
import type { Component } from "vue";

import Card from "@/components/ui/Card.vue";

defineProps<{
  label: string;
  value: string;
  caption: string;
  icon: Component;
  iconClass: string;
}>();
</script>

<template>
  <!-- The icon sits on the value row so the caption gets the full card width. -->
  <Card
    class="min-w-0 p-4"
    data-testid="analytics-kpi-card"
  >
    <p class="text-sm text-muted-foreground">
      {{ label }}
    </p>
    <div class="flex items-center justify-between gap-3">
      <p
        class="truncate text-2xl font-bold"
        data-testid="analytics-kpi-value"
      >
        {{ value }}
      </p>
      <component
        :is="icon"
        class="h-8 w-8 shrink-0"
        :class="iconClass"
        data-testid="analytics-kpi-icon"
      />
    </div>
    <p
      class="mt-1 truncate text-xs text-muted-foreground"
      :title="caption"
    >
      {{ caption }}
    </p>
  </Card>
</template>
