<script setup lang="ts">
import { computed } from "vue";
import {
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  Folder,
  FolderOpen,
  MoreHorizontal,
  Settings,
  Trash2,
  Workflow,
} from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import { cn, formatDate } from "@/lib/utils";
import { nodeIcons } from "@/lib/nodeIcons";
import { useFolderStore } from "@/stores/folder";
import type { FolderTree, WorkflowListItem } from "@/types/workflow";

interface Props {
  folder: FolderTree;
  isExpanded: boolean;
  dragOverFolderId: string | null;
  draggedWorkflowId: string | null;
  copyingId: string | null;
  depth?: number;
  isMobile?: boolean;
  onWorkflowTouchStart?: (e: TouchEvent, workflow: WorkflowListItem) => void;
  onWorkflowTouchEnd?: () => void;
  onWorkflowTouchMove?: () => void;
}

const props = withDefaults(defineProps<Props>(), {
  depth: 0,
  isMobile: false,
  onWorkflowTouchStart: undefined,
  onWorkflowTouchEnd: undefined,
  onWorkflowTouchMove: undefined,
});

const emit = defineEmits<{
  toggle: [id: string];
  dragOver: [event: DragEvent, id: string];
  dragLeave: [];
  drop: [event: DragEvent, id: string];
  contextMenu: [event: MouseEvent, folder: FolderTree];
  createSubfolder: [parentId: string];
  openWorkflow: [id: string, event: MouseEvent];
  editWorkflow: [workflow: WorkflowListItem, event: Event];
  copyWorkflow: [id: string, event: Event];
  deleteWorkflow: [id: string, event: Event];
  dragStartWorkflow: [event: DragEvent, id: string];
  dragEndWorkflow: [];
}>();

const folderStore = useFolderStore();

const hasContent = computed(() => props.folder.children.length > 0 || props.folder.workflows.length > 0);

function handleToggle(event: MouseEvent): void {
  event.stopPropagation();
  emit("toggle", props.folder.id);
}

function handleFolderClick(): void {
  emit("toggle", props.folder.id);
}

function handleContextMenu(event: MouseEvent): void {
  emit("contextMenu", event, props.folder);
}

function handleMenuClick(event: MouseEvent): void {
  event.stopPropagation();
  emit("contextMenu", event, props.folder);
}

function handleDragEnter(event: DragEvent): void {
  event.preventDefault();
}

function handleDragOver(event: DragEvent): void {
  event.preventDefault();
  emit("dragOver", event, props.folder.id);
}

function handleDragLeave(): void {
  emit("dragLeave");
}

function handleDrop(event: DragEvent): void {
  emit("drop", event, props.folder.id);
}

function handleContentDragOver(event: DragEvent): void {
  event.preventDefault();
  emit("dragOver", event, props.folder.id);
}

function handleContentDragLeave(event: DragEvent): void {
  const relatedTarget = event.relatedTarget as Node | null;
  const contentEl = event.currentTarget as HTMLElement;
  if (!relatedTarget || !contentEl.contains(relatedTarget)) {
    emit("dragLeave");
  }
}

function handleContentDrop(event: DragEvent): void {
  emit("drop", event, props.folder.id);
}
</script>

<template>
  <div class="folder-tree-item">
    <div
      :class="cn(
        'folder-header flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg transition-all cursor-pointer group',
        dragOverFolderId === folder.id
          ? 'bg-primary/10 border-2 border-primary border-dashed'
          : 'hover:bg-muted/30'
      )"
      :style="{ paddingLeft: `${depth * 14 + 8}px` }"
      @click="handleFolderClick"
      @contextmenu.prevent="handleContextMenu"
      @dragenter="handleDragEnter"
      @dragover="handleDragOver"
      @dragleave="handleDragLeave"
      @drop="handleDrop"
    >
      <button
        class="p-0.5 rounded hover:bg-muted/50 transition-colors"
        @click="handleToggle"
      >
        <ChevronDown
          v-if="isExpanded"
          class="w-4 h-4 text-muted-foreground"
        />
        <ChevronRight
          v-else
          class="w-4 h-4 text-muted-foreground"
        />
      </button>

      <div class="folder-icon w-6 h-6 rounded-md bg-gradient-to-br from-amber-500/15 to-amber-500/5 ring-1 ring-inset ring-amber-500/20 flex items-center justify-center">
        <FolderOpen
          v-if="isExpanded"
          class="w-3.5 h-3.5 text-amber-500"
        />
        <Folder
          v-else
          class="w-3.5 h-3.5 text-amber-500"
        />
      </div>

      <span class="font-medium text-sm flex-1">{{ folder.name }}</span>

      <span class="text-xs text-muted-foreground mr-2 hidden sm:inline">
        {{ folder.workflows.length }} workflow{{ folder.workflows.length !== 1 ? 's' : '' }}
      </span>

      <Button
        variant="ghost"
        size="icon"
        class="opacity-0 group-hover:opacity-100 transition-opacity w-6 h-6"
        @click="handleMenuClick"
      >
        <MoreHorizontal class="w-4 h-4" />
      </Button>
    </div>

    <div
      v-if="isExpanded && hasContent"
      :class="cn(
        'folder-content',
        dragOverFolderId === folder.id && 'rounded-lg border-2 border-primary border-dashed bg-primary/5 mt-0.5'
      )"
      @dragover="handleContentDragOver"
      @dragleave="handleContentDragLeave"
      @drop="handleContentDrop"
    >
      <FolderTreeItem
        v-for="child in folder.children"
        :key="child.id"
        :folder="child"
        :is-expanded="folderStore.isFolderExpanded(child.id)"
        :drag-over-folder-id="dragOverFolderId"
        :dragged-workflow-id="draggedWorkflowId"
        :copying-id="copyingId"
        :depth="depth + 1"
        :is-mobile="isMobile"
        :on-workflow-touch-start="onWorkflowTouchStart"
        :on-workflow-touch-end="onWorkflowTouchEnd"
        :on-workflow-touch-move="onWorkflowTouchMove"
        @toggle="(id) => emit('toggle', id)"
        @drag-over="(e, id) => emit('dragOver', e, id)"
        @drag-leave="emit('dragLeave')"
        @drop="(e, id) => emit('drop', e, id)"
        @context-menu="(e, f) => emit('contextMenu', e, f)"
        @create-subfolder="(id) => emit('createSubfolder', id)"
        @open-workflow="(id, e) => emit('openWorkflow', id, e)"
        @edit-workflow="(w, e) => emit('editWorkflow', w, e)"
        @copy-workflow="(id, e) => emit('copyWorkflow', id, e)"
        @delete-workflow="(id, e) => emit('deleteWorkflow', id, e)"
        @drag-start-workflow="(e, id) => emit('dragStartWorkflow', e, id)"
        @drag-end-workflow="emit('dragEndWorkflow')"
      />

      <div
        v-if="folder.workflows.length > 0"
        class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 mt-1.5"
        :style="{ paddingLeft: `${(depth + 1) * 14 + 8}px` }"
      >
        <Card
          v-for="(workflow, index) in folder.workflows"
          :key="workflow.id"
          variant="interactive"
          :class="cn(
            'workflow-card p-3 cursor-pointer group relative',
            draggedWorkflowId === workflow.id && 'opacity-50 scale-[0.98]'
          )"
          :style="{ animationDelay: `${index * 60}ms` }"
          :hover="false"
          draggable="true"
          @click="emit('openWorkflow', workflow.id, $event)"
          @touchstart.passive="isMobile && onWorkflowTouchStart?.(($event as TouchEvent), workflow)"
          @touchend="isMobile && onWorkflowTouchEnd?.()"
          @touchmove="isMobile && onWorkflowTouchMove?.()"
          @dragstart="emit('dragStartWorkflow', $event, workflow.id)"
          @dragend="emit('dragEndWorkflow')"
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
                @click.stop="emit('copyWorkflow', workflow.id, $event)"
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
                @click.stop="emit('editWorkflow', workflow, $event)"
              >
                <Settings class="w-3.5 h-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8 md:h-7 md:w-7 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all duration-200 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg"
                title="Delete workflow"
                @click.stop="emit('deleteWorkflow', workflow.id, $event)"
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
      </div>
    </div>
  </div>
</template>

<style scoped>
.folder-header {
  border: 1px solid transparent;
}

.folder-header:hover {
  border-color: hsl(var(--border) / 0.3);
}

.folder-icon {
  transition: all 0.2s ease;
}

.group:hover .folder-icon {
  transform: scale(1.03);
}

.folder-workflow-card .workflow-icon {
  transition: all 0.3s ease;
}

.folder-workflow-card:hover .workflow-icon {
  transform: scale(1.03);
  box-shadow: 0 0 8px hsl(var(--primary) / 0.2);
}

.workflow-card {
  animation: fadeInUp 0.3s ease-out forwards;
  opacity: 0;
}

.workflow-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
}

@keyframes fadeInUp {
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