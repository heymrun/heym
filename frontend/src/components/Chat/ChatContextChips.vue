<script setup lang="ts">
import { History, Workflow, X } from "lucide-vue-next";

import {
  formatChatContextLabel,
  formatChatContextTitle,
  type ChatContextItem,
} from "@/lib/chatContext";

interface Props {
  items: readonly ChatContextItem[];
  /** Composer chips can be removed; chips in a sent message cannot. */
  removable?: boolean;
  /** `message` sits on the primary-colored user bubble. */
  variant?: "composer" | "message";
}

withDefaults(defineProps<Props>(), { removable: false, variant: "composer" });

const emit = defineEmits<{
  remove: [index: number];
}>();
</script>

<template>
  <div
    class="flex min-w-0 flex-wrap items-center gap-1.5"
    data-testid="chat-context-chips"
  >
    <span
      v-for="(item, index) in items"
      :key="`${item.kind}-${item.executionId ?? item.workflowId}`"
      :class="[
        'inline-flex min-w-0 max-w-[16rem] items-center gap-1.5 rounded-lg border px-2 py-0.5 text-xs',
        variant === 'message'
          ? 'border-primary-foreground/25 bg-primary-foreground/15 text-primary-foreground'
          : 'border-border/40 bg-muted/60 text-foreground',
      ]"
      :title="formatChatContextTitle(item)"
      :data-testid="`chat-context-chip-${item.kind}`"
    >
      <component
        :is="item.kind === 'execution' ? History : Workflow"
        :class="[
          'h-3 w-3 shrink-0',
          variant === 'message' ? 'opacity-80' : 'text-muted-foreground',
        ]"
      />
      <span class="truncate">{{ formatChatContextLabel(item) }}</span>
      <button
        v-if="removable"
        type="button"
        class="ml-0.5 shrink-0 rounded p-0.5 hover:bg-muted/80"
        :aria-label="item.kind === 'execution' ? 'Remove execution context' : 'Remove workflow context'"
        @click="emit('remove', index)"
      >
        <X class="h-3 w-3" />
      </button>
    </span>
  </div>
</template>
