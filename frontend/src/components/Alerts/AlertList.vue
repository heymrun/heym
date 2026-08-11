<script setup lang="ts">
import AlertCard from "./AlertCard.vue";

import type { Alert } from "@/types/alerts";

interface Props {
  alerts: Alert[];
  loading: boolean;
}

defineProps<Props>();
const emit = defineEmits<{
  edit: [alert: Alert];
  remove: [alert: Alert];
  share: [alert: Alert];
  toggle: [alert: Alert];
}>();
</script>

<template>
  <div>
    <!-- Skeletons rather than a text line: the cards keep their footprint so the
         firing history below does not jump when the list arrives. -->
    <div
      v-if="loading"
      class="grid gap-3"
    >
      <div
        v-for="index in 2"
        :key="index"
        class="h-[104px] animate-pulse rounded-xl border border-border bg-muted/40"
      />
    </div>

    <div
      v-else-if="alerts.length === 0"
      class="rounded-xl border border-dashed border-border px-6 py-10 text-center"
    >
      <p class="font-medium">
        No alerts yet
      </p>
      <p class="mt-1 text-sm text-muted-foreground">
        Create one to be told when errors, duration, cost, or run count cross a line.
      </p>
    </div>

    <div
      v-else
      class="grid gap-3"
    >
      <AlertCard
        v-for="alert in alerts"
        :key="alert.id"
        :alert="alert"
        @edit="emit('edit', $event)"
        @remove="emit('remove', $event)"
        @share="emit('share', $event)"
        @toggle="emit('toggle', $event)"
      />
    </div>
  </div>
</template>
