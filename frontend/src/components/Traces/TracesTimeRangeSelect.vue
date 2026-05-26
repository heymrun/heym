<script setup lang="ts">
import { computed } from "vue";

import type { TraceTimeRange } from "@/types/trace";

import Select from "@/components/ui/Select.vue";

interface Props {
  modelValue: TraceTimeRange;
}
interface Emits {
  (e: "update:modelValue", value: TraceTimeRange): void;
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

const options = computed<Array<{ value: TraceTimeRange; label: string }>>(() => [
  { value: "1h", label: "Last 1 hour" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "all", label: "All time" },
]);

const internal = computed({
  get: () => props.modelValue,
  set: (value: TraceTimeRange) => emit("update:modelValue", value),
});
</script>

<template>
  <Select
    v-model="internal"
    :options="options"
  />
</template>
