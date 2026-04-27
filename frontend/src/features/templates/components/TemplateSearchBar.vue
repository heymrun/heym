<script setup lang="ts">
import { ref, watch } from "vue";
import { Search, X } from "lucide-vue-next";

interface Props {
  modelValue: string;
  placeholder?: string;
}

const props = withDefaults(defineProps<Props>(), {
  placeholder: "Search templates…",
});

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

const inputRef = ref<HTMLInputElement | null>(null);

function clear(): void {
  emit("update:modelValue", "");
  inputRef.value?.focus();
}

watch(
  () => props.modelValue,
  (val) => {
    if (inputRef.value && inputRef.value.value !== val) {
      inputRef.value.value = val;
    }
  },
);
</script>

<template>
  <div class="relative flex-1 max-w-sm">
    <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
    <input
      ref="inputRef"
      type="text"
      :value="modelValue"
      :placeholder="placeholder"
      class="w-full pl-9 pr-8 py-2 text-sm rounded-lg border border-border/50 bg-muted/30 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    >
    <button
      v-if="modelValue"
      class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
      type="button"
      @click="clear"
    >
      <X class="w-4 h-4" />
    </button>
  </div>
</template>
