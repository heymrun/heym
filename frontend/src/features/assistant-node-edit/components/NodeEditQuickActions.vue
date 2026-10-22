<script setup lang="ts">
import type { Component } from "vue";
import { MessageSquare, Wand2, Wrench } from "lucide-vue-next";

import {
  NODE_EDIT_QUICK_ACTIONS,
  type NodeEditQuickAction,
  type NodeEditActionId,
} from "@/features/assistant-node-edit/nodeEdit";

defineProps<{ disabled?: boolean; selected?: NodeEditActionId | null }>();
const emit = defineEmits<{ (event: "select", action: NodeEditQuickAction): void }>();

const ACTION_ICONS: Record<NodeEditActionId, Component> = {
  change: Wand2,
  fix: Wrench,
  other: MessageSquare,
};
</script>

<template>
  <div
    class="flex flex-col gap-1.5 pt-1"
    data-testid="ai-node-quick-actions"
  >
    <button
      v-for="action in NODE_EDIT_QUICK_ACTIONS"
      :key="action.id"
      type="button"
      class="flex h-9 items-center gap-2 rounded-md border px-3 text-left text-[13px] text-foreground transition-colors hover:border-primary/50 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/40 disabled:pointer-events-none disabled:opacity-50"
      :class="selected === action.id ? 'border-primary bg-primary/10' : 'border-border bg-background'"
      :aria-pressed="selected === action.id"
      :disabled="disabled"
      :data-testid="`ai-node-quick-action-${action.id}`"
      @click="emit('select', action)"
    >
      <component
        :is="ACTION_ICONS[action.id]"
        class="h-3.5 w-3.5 shrink-0 text-primary dark:text-brand-primary-soft"
      />
      {{ action.label }}
    </button>
  </div>
</template>
