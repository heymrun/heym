<script setup lang="ts">
const props = defineProps<{
  id: string;
  modelValue: boolean;
  label: string;
  disabled?: boolean;
}>();

const emit = defineEmits<{ "update:modelValue": [value: boolean] }>();

function toggle(): void {
  if (props.disabled) return;
  emit("update:modelValue", !props.modelValue);
}
</script>

<template>
  <div class="flex items-center gap-3">
    <button
      :id="props.id"
      type="button"
      role="switch"
      :aria-checked="props.modelValue"
      :disabled="props.disabled"
      class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
      :class="props.modelValue ? 'bg-primary border-primary' : 'bg-muted border-border'"
      @click="toggle"
    >
      <span
        class="inline-block h-3.5 w-3.5 rounded-full bg-background shadow-sm transition-transform duration-200"
        :class="props.modelValue ? 'translate-x-[18px]' : 'translate-x-[3px]'"
      />
    </button>
    <span
      class="text-sm font-normal select-none"
      :class="props.disabled ? 'text-muted-foreground' : 'text-foreground cursor-pointer'"
      @click="toggle"
    >
      {{ props.label }}
    </span>
  </div>
</template>
