<script setup lang="ts">
import { X } from "lucide-vue-next";

defineProps<{
  dashboardName: string;
  label: string;
}>();

const emit = defineEmits<{
  (e: "clear"): void;
}>();
</script>

<template>
  <div
    class="mb-3 flex min-w-0 items-center gap-1.5 text-sm"
    data-testid="dashboard-record-bar"
  >
    <span class="shrink-0 text-muted-foreground">{{ dashboardName }} /</span>
    <span class="truncate font-medium">{{ label }}</span>
    <button
      class="shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
      aria-label="Clear record"
      title="Clear record"
      @click="emit('clear')"
    >
      <X class="h-3.5 w-3.5" />
    </button>
  </div>
</template>
