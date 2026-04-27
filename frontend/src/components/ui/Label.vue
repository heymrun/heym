<script setup lang="ts">
import { cn } from "@/lib/utils";

interface Props {
  for?: string;
  error?: boolean;
}

const props = defineProps<Props>();
</script>

<template>
  <label
    :for="props.for"
    :class="
      cn(
        'text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70',
        props.error && 'text-destructive'
      )
    "
  >
    <slot />
  </label>
</template>