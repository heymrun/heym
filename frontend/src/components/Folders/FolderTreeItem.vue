<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import {
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  MoreHorizontal,
} from "lucide-vue-next";

import type { FolderTree, WorkflowListItem } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import { cn } from "@/lib/utils";
import { useFolderStore } from "@/stores/folder";
import FolderWorkflowCard from "./FolderWorkflowCard.vue";
import WorkflowFolderDropPlaceholder from "./WorkflowFolderDropPlaceholder.vue";

interface Props {
  folder: FolderTree;
  isExpanded: boolean;
  dragOverFolderId: string | null;
  draggedWorkflowId: string | null;
  draggedWorkflowFolderId: string | null;
  draggedWorkflowName: string;
  copyingId: string | null;
  forceExpandedFolderIds?: ReadonlySet<string>;
  depth?: number;
  parentPath?: string;
  isMobile?: boolean;
  onWorkflowTouchStart?: (e: TouchEvent, workflow: WorkflowListItem) => void;
  onWorkflowTouchEnd?: () => void;
  onWorkflowTouchMove?: () => void;
}

const props = withDefaults(defineProps<Props>(), {
  forceExpandedFolderIds: undefined,
  depth: 0,
  parentPath: "",
  isMobile: false,
  onWorkflowTouchStart: undefined,
  onWorkflowTouchEnd: undefined,
  onWorkflowTouchMove: undefined,
});

const emit = defineEmits<{
  toggle: [id: string];
  expand: [id: string];
  dragOver: [event: DragEvent, id: string];
  dragLeave: [id: string];
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
const folderDropZone = ref<HTMLElement | null>(null);
let expandTimer: ReturnType<typeof setTimeout> | null = null;

const hasContent = computed(() => props.folder.children.length > 0 || props.folder.workflows.length > 0);
const folderPath = computed((): string => {
  return props.parentPath ? `${props.parentPath} / ${props.folder.name}` : props.folder.name;
});
const isActiveDropTarget = computed((): boolean => {
  return props.draggedWorkflowId !== null && props.dragOverFolderId === props.folder.id;
});
const isValidDropTarget = computed((): boolean => {
  return props.draggedWorkflowFolderId !== props.folder.id;
});

function handleToggle(event: MouseEvent): void {
  event.stopPropagation();
  emit("toggle", props.folder.id);
}

function isFolderExpandedForView(folderId: string): boolean {
  return props.forceExpandedFolderIds?.has(folderId) === true || folderStore.isFolderExpanded(folderId);
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

function clearExpandTimer(): void {
  if (expandTimer) {
    clearTimeout(expandTimer);
    expandTimer = null;
  }
}

function handleDragOver(event: DragEvent): void {
  if (!props.draggedWorkflowId) return;
  event.preventDefault();
  event.stopPropagation();
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = isValidDropTarget.value ? "move" : "none";
  }
  emit("dragOver", event, props.folder.id);
  if (!props.isExpanded && !expandTimer) {
    expandTimer = setTimeout(() => {
      expandTimer = null;
      emit("expand", props.folder.id);
    }, 550);
  }
}

function handleDragLeave(event: DragEvent): void {
  if (!props.draggedWorkflowId) return;
  event.stopPropagation();
  const relatedTarget = event.relatedTarget;
  const zone = folderDropZone.value;
  if (relatedTarget instanceof Node && zone?.contains(relatedTarget)) return;

  // Browsers may report no related target while the page scrolls under a stationary pointer.
  // Keep the active destination until another lane takes over or the drag finishes.
  if (!relatedTarget) return;

  clearExpandTimer();
  emit("dragLeave", props.folder.id);
}

function handleDrop(event: DragEvent): void {
  if (!props.draggedWorkflowId) return;
  event.preventDefault();
  event.stopPropagation();
  clearExpandTimer();
  emit("drop", event, props.folder.id);
}

onUnmounted(clearExpandTimer);
</script>

<template>
  <div
    ref="folderDropZone"
    class="folder-tree-item rounded-xl transition-colors"
    :class="isActiveDropTarget && (isValidDropTarget ? 'bg-primary/[0.035]' : 'bg-muted/15')"
    :data-testid="`workflow-folder-drop-zone-${folder.id}`"
    :data-drop-active="String(isActiveDropTarget)"
    :data-drop-valid="String(isValidDropTarget)"
    @dragover="handleDragOver"
    @dragleave="handleDragLeave"
    @drop="handleDrop"
  >
    <div
      :data-testid="`workflow-folder-header-${folder.id}`"
      :class="cn(
        'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-transparent transition-all cursor-pointer group hover:border-border/30',
        isActiveDropTarget && isValidDropTarget
          ? 'bg-primary/10 border-2 border-primary border-dashed shadow-sm'
          : isActiveDropTarget
            ? 'bg-muted/40 border-2 border-border border-dashed'
            : 'hover:bg-muted/30'
      )"
      :style="{ paddingLeft: `${depth * 14 + 8}px` }"
      @click="handleFolderClick"
      @contextmenu.prevent="handleContextMenu"
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

      <div class="w-6 h-6 rounded-md bg-gradient-to-br from-amber-500/15 to-amber-500/5 ring-1 ring-inset ring-amber-500/20 flex items-center justify-center transition-transform duration-200 group-hover:scale-[1.03]">
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
      v-if="isActiveDropTarget"
      class="grid grid-cols-1 gap-2 py-2 sm:grid-cols-2 lg:grid-cols-3"
      :style="{ paddingLeft: `${(depth + 1) * 14 + 8}px`, paddingRight: '8px' }"
    >
      <WorkflowFolderDropPlaceholder
        :target-id="folder.id"
        :target-kind="depth > 0 ? 'Subfolder' : 'Folder'"
        :target-label="folderPath"
        :workflow-name="draggedWorkflowName"
        :valid="isValidDropTarget"
      />
    </div>

    <div
      v-if="isExpanded && hasContent"
      :class="cn(
        'folder-content',
        isActiveDropTarget && isValidDropTarget && 'rounded-lg border border-primary/40 bg-primary/[0.025] mt-0.5'
      )"
    >
      <FolderTreeItem
        v-for="child in folder.children"
        :key="child.id"
        :folder="child"
        :is-expanded="isFolderExpandedForView(child.id)"
        :force-expanded-folder-ids="forceExpandedFolderIds"
        :drag-over-folder-id="dragOverFolderId"
        :dragged-workflow-id="draggedWorkflowId"
        :dragged-workflow-folder-id="draggedWorkflowFolderId"
        :dragged-workflow-name="draggedWorkflowName"
        :copying-id="copyingId"
        :depth="depth + 1"
        :parent-path="folderPath"
        :is-mobile="isMobile"
        :on-workflow-touch-start="onWorkflowTouchStart"
        :on-workflow-touch-end="onWorkflowTouchEnd"
        :on-workflow-touch-move="onWorkflowTouchMove"
        @toggle="(id) => emit('toggle', id)"
        @expand="(id) => emit('expand', id)"
        @drag-over="(e, id) => emit('dragOver', e, id)"
        @drag-leave="(id) => emit('dragLeave', id)"
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
        <FolderWorkflowCard
          v-for="(workflow, index) in folder.workflows"
          :key="workflow.id"
          :workflow="workflow"
          :index="index"
          :copying-id="copyingId"
          :is-dragging="draggedWorkflowId === workflow.id"
          :is-mobile="isMobile"
          :on-workflow-touch-start="onWorkflowTouchStart"
          :on-workflow-touch-end="onWorkflowTouchEnd"
          :on-workflow-touch-move="onWorkflowTouchMove"
          @open="(id, event) => emit('openWorkflow', id, event)"
          @edit="(item, event) => emit('editWorkflow', item, event)"
          @copy="(id, event) => emit('copyWorkflow', id, event)"
          @delete="(id, event) => emit('deleteWorkflow', id, event)"
          @drag-start="(event, id) => emit('dragStartWorkflow', event, id)"
          @drag-end="emit('dragEndWorkflow')"
        />
      </div>
    </div>
  </div>
</template>
