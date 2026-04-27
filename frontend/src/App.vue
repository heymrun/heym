<script setup lang="ts">
import { RouterView } from "vue-router";

import { useOverlayBackHandler } from "@/composables/useOverlayBackHandler";
import ToastNotification from "@/components/ui/ToastNotification.vue";

useOverlayBackHandler();
</script>

<template>
  <div class="overflow-x-hidden">
    <RouterView />
    <ToastNotification />
  </div>
</template>