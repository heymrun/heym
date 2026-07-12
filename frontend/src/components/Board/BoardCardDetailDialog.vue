<script setup lang="ts">
import Dialog from "@/components/ui/Dialog.vue";

defineProps<{ open: boolean; cardId: string | null }>();
const emit = defineEmits<{ (e: "close"): void }>();
</script>

<template>
  <Dialog
    :open="open"
    title="Card"
    @close="emit('close')"
  />
</template>
