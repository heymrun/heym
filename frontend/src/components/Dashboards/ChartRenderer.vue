<script setup lang="ts">
import type { ChartPayload } from "@/types/dashboard";
import ChartView from "@/components/Dashboards/ChartView.vue";
import { useThemeStore } from "@/stores/theme";

defineProps<{
  payload: ChartPayload | Record<string, unknown> | null;
  markdownTaskSaving?: boolean;
}>();

const emit = defineEmits<{
  (e: "markdown-task-toggle", lineIndex: number): void;
  (e: "markdown-task-update", payload: { lineIndex: number; text: string }): void;
}>();

const themeStore = useThemeStore();
</script>

<template>
  <ChartView
    :payload="payload"
    :markdown-task-saving="markdownTaskSaving"
    :dark="themeStore.isDark"
    @markdown-task-toggle="(lineIndex) => emit('markdown-task-toggle', lineIndex)"
    @markdown-task-update="(payload) => emit('markdown-task-update', payload)"
  />
</template>
