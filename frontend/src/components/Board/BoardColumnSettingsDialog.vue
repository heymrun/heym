<script setup lang="ts">
import Dialog from "@/components/ui/Dialog.vue";

defineProps<{ open: boolean; columnId: string | null }>();
const emit = defineEmits<{ (e: "close"): void }>();
</script>

<template>
  <Dialog
    :open="open"
    title="Column settings"
    @close="emit('close')"
  />
</template>
