<script setup lang="ts">
import { computed } from "vue";
import { Loader2, CheckCircle2, XCircle, PauseCircle } from "lucide-vue-next";

import type { BoardCard } from "@/types/board";

const props = defineProps<{ card: BoardCard }>();
const emit = defineEmits<{
  (e: "open", cardId: string): void;
}>();

const statusClasses = computed<string>(() => {
  switch (props.card.run_status) {
    case "success":
      return "border-emerald-500/70 bg-emerald-500/10";
    case "failed":
      return "border-red-500/70 bg-red-500/10";
    case "running":
      return "border-amber-500/70 bg-amber-500/10 animate-pulse";
    case "pending":
      return "border-amber-500/70 bg-amber-500/5";
    default:
      return "border-border bg-card";
  }
});

function onDragStart(event: DragEvent): void {
  event.dataTransfer?.setData("text/board-card", props.card.id);
  if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
}
</script>

<template>
  <div
    class="group cursor-pointer rounded-lg border p-3 text-sm shadow-sm transition-colors hover:border-primary/60"
    :class="statusClasses"
    draggable="true"
    :data-testid="`board-card-${card.id}`"
    @dragstart="onDragStart"
    @click="emit('open', card.id)"
  >
    <div class="flex items-start justify-between gap-2">
      <span class="line-clamp-2 font-medium">{{ card.title }}</span>
      <Loader2
        v-if="card.run_status === 'running'"
        class="h-4 w-4 shrink-0 animate-spin text-amber-500"
      />
      <PauseCircle
        v-else-if="card.run_status === 'pending'"
        class="h-4 w-4 shrink-0 text-amber-500"
      />
      <CheckCircle2
        v-else-if="card.run_status === 'success'"
        class="h-4 w-4 shrink-0 text-emerald-500"
      />
      <XCircle
        v-else-if="card.run_status === 'failed'"
        class="h-4 w-4 shrink-0 text-red-500"
      />
    </div>
    <p
      v-if="card.content"
      class="mt-1 line-clamp-2 text-xs text-muted-foreground"
    >
      {{ card.content }}
    </p>
  </div>
</template>
