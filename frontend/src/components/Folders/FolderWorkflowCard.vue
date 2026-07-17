<script setup lang="ts">
import { Clock, Copy, Settings, Trash2, Workflow } from "lucide-vue-next";

import type { WorkflowListItem } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import { nodeIcons } from "@/lib/nodeIcons";
import { cn, formatDate } from "@/lib/utils";

interface Props {
  workflow: WorkflowListItem;
  index: number;
  copyingId: string | null;
  isDragging: boolean;
  isMobile: boolean;
  onWorkflowTouchStart?: (event: TouchEvent, workflow: WorkflowListItem) => void;
  onWorkflowTouchEnd?: () => void;
  onWorkflowTouchMove?: () => void;
}

const props = withDefaults(defineProps<Props>(), {
  onWorkflowTouchStart: undefined,
  onWorkflowTouchEnd: undefined,
  onWorkflowTouchMove: undefined,
});

const emit = defineEmits<{
  open: [id: string, event: MouseEvent];
  edit: [workflow: WorkflowListItem, event: Event];
  copy: [id: string, event: Event];
  delete: [id: string, event: Event];
  dragStart: [event: DragEvent, id: string];
  dragEnd: [];
}>();

function handleTouchStart(event: TouchEvent): void {
  if (props.isMobile) props.onWorkflowTouchStart?.(event, props.workflow);
}

function handleTouchEnd(): void {
  if (props.isMobile) props.onWorkflowTouchEnd?.();
}

function handleTouchMove(): void {
  if (props.isMobile) props.onWorkflowTouchMove?.();
}
</script>

<template>
  <Card
    :data-testid="`workflow-card-${workflow.id}`"
    variant="interactive"
    :class="cn(
      'workflow-card p-3 cursor-pointer group relative',
      isDragging && 'workflow-card--dragging'
    )"
    :style="{ animationDelay: `${index * 60}ms` }"
    :hover="false"
    draggable="true"
    @click="emit('open', workflow.id, $event)"
    @touchstart.passive="handleTouchStart"
    @touchend="handleTouchEnd"
    @touchmove="handleTouchMove"
    @dragstart="emit('dragStart', $event, workflow.id)"
    @dragend="emit('dragEnd')"
  >
    <div class="flex items-start justify-between mb-2 gap-1.5">
      <div class="flex items-start gap-3 min-w-0 flex-1">
        <div class="workflow-icon relative flex items-center justify-center w-9 h-9 rounded-lg text-primary shrink-0">
          <div class="absolute inset-0 rounded-lg bg-gradient-to-br from-primary/15 via-primary/10 to-primary/5" />
          <div class="absolute inset-0 rounded-lg ring-1 ring-inset ring-primary/20" />
          <component
            :is="workflow.first_node_type && nodeIcons[workflow.first_node_type] ? nodeIcons[workflow.first_node_type] : Workflow"
            class="relative z-10 h-4 w-4"
          />
        </div>
        <div class="min-w-0">
          <h3 class="workflow-card-title font-semibold text-sm line-clamp-2 leading-snug transition-colors duration-200">
            {{ workflow.name }}
          </h3>
          <div class="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground">
            <Clock class="w-3 h-3" />
            <span>{{ formatDate(workflow.updated_at) }}</span>
          </div>
        </div>
      </div>
      <div class="flex items-center gap-0.5 shrink-0">
        <Button
          variant="ghost"
          size="icon"
          class="h-8 w-8 md:h-7 md:w-7 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all duration-200 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-lg"
          title="Copy workflow"
          :disabled="copyingId === workflow.id"
          @click.stop="emit('copy', workflow.id, $event)"
        >
          <Copy
            class="w-3.5 h-3.5"
            :class="{ 'animate-spin-slow': copyingId === workflow.id }"
          />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="h-8 w-8 md:h-7 md:w-7 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all duration-200 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-lg"
          title="Edit workflow"
          @click.stop="emit('edit', workflow, $event)"
        >
          <Settings class="w-3.5 h-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="h-8 w-8 md:h-7 md:w-7 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all duration-200 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg"
          title="Delete workflow"
          @click.stop="emit('delete', workflow.id, $event)"
        >
          <Trash2 class="w-3.5 h-3.5" />
        </Button>
      </div>
    </div>
    <div
      v-if="workflow.description"
      class="mt-0.5 pt-2 border-t border-border/40 ml-[48px]"
    >
      <p class="text-muted-foreground text-xs line-clamp-2 leading-relaxed">
        {{ workflow.description }}
      </p>
    </div>
  </Card>
</template>

<style scoped>
.workflow-card {
  animation: fade-in-up 0.3s ease-out forwards;
  opacity: 0;
}

.workflow-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
}

.workflow-icon {
  transition: all 0.3s ease;
}

.workflow-card:hover .workflow-icon {
  transform: scale(1.03);
  box-shadow: 0 0 8px hsl(var(--primary) / 0.2);
}

@keyframes fade-in-up {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
