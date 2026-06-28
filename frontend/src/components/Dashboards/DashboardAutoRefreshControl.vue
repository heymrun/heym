<script setup lang="ts">
import AutoRefreshControl from "@/components/ui/AutoRefreshControl.vue";

const emit = defineEmits<{
  (e: "refresh"): void;
}>();
</script>

<template>
  <AutoRefreshControl @refresh="emit('refresh')" />
</template>
