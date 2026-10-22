<script setup lang="ts">
import { computed } from "vue";
import { List, Timer } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";

interface Props {
  modelValue: "logs" | "timeline";
}

const props = defineProps<Props>();
const emit = defineEmits<{
  "update:modelValue": [value: "logs" | "timeline"];
}>();

/** The button names the view it switches to: Timeline from the logs, Logs from the timeline. */
const showsTimeline = computed<boolean>(() => props.modelValue === "timeline");

function toggle(): void {
  emit("update:modelValue", showsTimeline.value ? "logs" : "timeline");
}
</script>

<template>
  <Button
    variant="ghost"
    size="sm"
    class="text-xs h-6 px-2 gap-1"
    :title="showsTimeline ? 'Show node logs' : 'Show execution timeline'"
    data-testid="execution-history-timeline-toggle"
    @click="toggle"
  >
    <component
      :is="showsTimeline ? List : Timer"
      class="w-3 h-3"
    />
    {{ showsTimeline ? "Logs" : "Timeline" }}
  </Button>
</template>
