<script setup lang="ts">
import { ExternalLink } from "lucide-vue-next";

const props = defineProps<{ authUrl: string }>();

const emit = defineEmits<{ (e: "open"): void }>();
</script>

<template>
  <p class="text-xs text-muted-foreground">
    Popup didn't open?
    <a
      :href="props.authUrl"
      target="_blank"
      rel="opener"
      class="inline-flex items-center gap-1 text-primary underline"
      @click.prevent="emit('open')"
    >
      Open the authorization page
      <ExternalLink class="h-3 w-3" />
    </a>
  </p>
</template>
