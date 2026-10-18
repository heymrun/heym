<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import {
  ChevronDown,
  ChevronRight,
  Download,
  Edit2,
  Folder,
  FolderOpen,
  FolderPlus,
  MoreHorizontal,
  Palette,
  Trash2,
} from "lucide-vue-next";

import type { FolderTree, WorkflowListItem, WorkflowRowStatus } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import WorkflowListRow from "@/components/Workflows/WorkflowListRow.vue";
import { cn } from "@/lib/utils";
import { getFolderIcon } from "@/lib/folderIcons";
import { useFolderStore } from "@/stores/folder";
import WorkflowFolderDropPlaceholder from "./WorkflowFolderDropPlaceholder.vue";

interface Props {
  folder: FolderTree;
  isExpanded: boolean;
  dragOverFolderId: string | null;
  draggedWorkflowId: string | null;
  draggedWorkflowFolderId: string | null;
  draggedWorkflowName: string;
  copyingId: string | null;
  selectedWorkflowId?: string | null;
  pinnedWorkflowIds?: readonly string[];
  statusFor: (workflow: WorkflowListItem) => WorkflowRowStatus;
  forceExpandedFolderIds?: ReadonlySet<string>;
  depth?: number;
  parentPath?: string;
  isMobile?: boolean;
  onWorkflowTouchStart?: (e: TouchEvent, workflow: WorkflowListItem) => void;
  onWorkflowTouchEnd?: () => void;
  onWorkflowTouchMove?: () => void;
}

const props = withDefaults(defineProps<Props>(), {
  selectedWorkflowId: null,
  pinnedWorkflowIds: () => [],
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
  renameFolder: [folder: FolderTree];
  changeFolderIcon: [folder: FolderTree];
  downloadFolder: [folder: FolderTree];
  deleteFolder: [folder: FolderTree];
  selectWorkflow: [workflow: WorkflowListItem];
  openWorkflow: [id: string, event: MouseEvent];
  editWorkflow: [workflow: WorkflowListItem, event: Event];
  copyWorkflow: [id: string, event: Event];
  deleteWorkflow: [id: string, event: Event];
  togglePinWorkflow: [id: string];
  dragStartWorkflow: [event: DragEvent, id: string];
  dragEndWorkflow: [];
}>();

const folderStore = useFolderStore();
const folderDropZone = ref<HTMLElement | null>(null);
let expandTimer: ReturnType<typeof setTimeout> | null = null;

const hasContent = computed(
  () => props.folder.children.length > 0 || props.folder.workflows.length > 0,
);
const folderIconComponent = computed(() => getFolderIcon(props.folder.icon));
const folderPath = computed((): string => {
  return props.parentPath ? `${props.parentPath} / ${props.folder.name}` : props.folder.name;
});
const isActiveDropTarget = computed((): boolean => {
  if (props.folder.virtual) return false;
  return props.draggedWorkflowId !== null && props.dragOverFolderId === props.folder.id;
});
const isValidDropTarget = computed((): boolean => {
  if (props.folder.virtual) return false;
  return props.draggedWorkflowFolderId !== props.folder.id;
});

/** Counts nested folders too, so the badge matches what deleting the folder would remove. */
const itemCount = computed((): number => {
  function count(folder: FolderTree): number {
    return folder.workflows.length + folder.children.reduce((sum, child) => sum + count(child), 0);
  }
  return count(props.folder);
});

function isFolderExpandedForView(folderId: string): boolean {
  return props.forceExpandedFolderIds?.has(folderId) === true || folderStore.isFolderExpanded(folderId);
}

function handleFolderClick(): void {
  emit("toggle", props.folder.id);
}

function handleContextMenu(event: MouseEvent): void {
  if (props.folder.virtual) return;
  emit("contextMenu", event, props.folder);
}

function clearExpandTimer(): void {
  if (expandTimer) {
    clearTimeout(expandTimer);
    expandTimer = null;
  }
}

function handleDragOver(event: DragEvent): void {
  if (props.folder.virtual || !props.draggedWorkflowId) return;
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
  if (props.folder.virtual || !props.draggedWorkflowId) return;
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
        'group flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 transition-all sm:px-4',
        depth > 0 ? 'py-2' : 'py-2.5 sm:py-3',
        isActiveDropTarget && isValidDropTarget
          ? 'border-2 border-dashed border-primary bg-primary/10 shadow-sm'
          : isActiveDropTarget
            ? 'border-2 border-dashed border-border bg-muted/40'
            : 'border-border/50 bg-card hover:border-border hover:bg-muted/40',
      )"
      @click="handleFolderClick"
      @contextmenu.prevent="handleContextMenu"
    >
      <div
        :class="cn(
          'flex shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-amber-500/15 to-amber-500/5 ring-1 ring-inset ring-amber-500/20 transition-transform duration-200 group-hover:scale-[1.03] dark:from-amber-400/[0.12] dark:to-transparent dark:ring-amber-400/25',
          depth > 0 ? 'h-8 w-8' : 'h-9 w-9 sm:h-10 sm:w-10',
        )"
      >
        <component
          :is="folderIconComponent ?? (isExpanded ? FolderOpen : Folder)"
          :class="cn('text-amber-500 dark:text-amber-300', depth > 0 ? 'h-3.5 w-3.5' : 'h-4 w-4')"
        />
      </div>

      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-1.5">
          <ChevronDown
            v-if="isExpanded"
            class="h-3.5 w-3.5 shrink-0 text-muted-foreground"
          />
          <ChevronRight
            v-else
            class="h-3.5 w-3.5 shrink-0 text-muted-foreground"
          />
          <span
            :class="cn('truncate font-semibold', depth > 0 ? 'text-[13px]' : 'text-sm')"
          >{{ folder.name }}</span>
        </div>
        <p
          v-if="folder.description"
          :class="cn('truncate pl-5 text-muted-foreground', depth > 0 ? 'text-[11px]' : 'text-xs')"
        >
          {{ folder.description }}
        </p>
      </div>

      <span
        class="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground"
        :data-testid="`workflow-folder-count-${folder.id}`"
      >
        {{ itemCount }} item{{ itemCount === 1 ? '' : 's' }}
      </span>

      <Button
        v-if="!folder.virtual"
        variant="ghost"
        size="icon"
        class="h-8 w-8 shrink-0 rounded-lg text-muted-foreground sm:hidden"
        title="Folder actions"
        @click.stop="handleContextMenu"
      >
        <MoreHorizontal class="h-4 w-4" />
      </Button>

      <div
        v-if="!folder.virtual"
        class="hidden shrink-0 items-center gap-0.5 sm:flex"
        @click.stop
      >
        <Button
          variant="ghost"
          size="icon"
          class="h-8 w-8 rounded-lg text-muted-foreground hover:bg-primary/10 hover:text-primary md:h-7 md:w-7"
          title="New subfolder"
          @click="emit('createSubfolder', folder.id)"
        >
          <FolderPlus class="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="h-8 w-8 rounded-lg text-muted-foreground hover:bg-primary/10 hover:text-primary md:h-7 md:w-7"
          title="Rename folder"
          @click="emit('renameFolder', folder)"
        >
          <Edit2 class="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="hidden h-8 w-8 rounded-lg text-muted-foreground hover:bg-primary/10 hover:text-primary sm:inline-flex md:h-7 md:w-7"
          title="Change icon"
          @click="emit('changeFolderIcon', folder)"
        >
          <Palette class="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="hidden h-8 w-8 rounded-lg text-muted-foreground hover:bg-primary/10 hover:text-primary sm:inline-flex md:h-7 md:w-7"
          title="Download as ZIP"
          @click="emit('downloadFolder', folder)"
        >
          <Download class="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="h-8 w-8 rounded-lg text-destructive hover:bg-destructive/10 hover:text-destructive md:h-7 md:w-7"
          title="Delete folder"
          @click="emit('deleteFolder', folder)"
        >
          <Trash2 class="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>

    <div
      v-if="isActiveDropTarget"
      class="py-2 pl-5"
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
        'folder-content mt-1 space-y-1.5 border-l border-border/60 pl-3 sm:pl-4',
        isActiveDropTarget && isValidDropTarget && 'rounded-lg border-primary/40 bg-primary/[0.025]',
      )"
      :style="{ marginLeft: '1.25rem' }"
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
        :selected-workflow-id="selectedWorkflowId"
        :pinned-workflow-ids="pinnedWorkflowIds"
        :status-for="statusFor"
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
        @rename-folder="(f) => emit('renameFolder', f)"
        @change-folder-icon="(f) => emit('changeFolderIcon', f)"
        @download-folder="(f) => emit('downloadFolder', f)"
        @delete-folder="(f) => emit('deleteFolder', f)"
        @select-workflow="(w) => emit('selectWorkflow', w)"
        @open-workflow="(id, e) => emit('openWorkflow', id, e)"
        @edit-workflow="(w, e) => emit('editWorkflow', w, e)"
        @copy-workflow="(id, e) => emit('copyWorkflow', id, e)"
        @delete-workflow="(id, e) => emit('deleteWorkflow', id, e)"
        @toggle-pin-workflow="(id) => emit('togglePinWorkflow', id)"
        @drag-start-workflow="(e, id) => emit('dragStartWorkflow', e, id)"
        @drag-end-workflow="emit('dragEndWorkflow')"
      />

      <WorkflowListRow
        v-for="(workflow, index) in folder.workflows"
        :key="workflow.id"
        :workflow="workflow"
        :status="statusFor(workflow)"
        :selected="selectedWorkflowId === workflow.id"
        :pinned="pinnedWorkflowIds.includes(workflow.id)"
        compact
        :index="index"
        :copying-id="copyingId"
        :is-dragging="draggedWorkflowId === workflow.id"
        :is-mobile="isMobile"
        :on-touch-start-row="onWorkflowTouchStart"
        :on-touch-end-row="onWorkflowTouchEnd"
        :on-touch-move-row="onWorkflowTouchMove"
        @select="(w) => emit('selectWorkflow', w)"
        @open="(id, event) => emit('openWorkflow', id, event)"
        @edit="(item, event) => emit('editWorkflow', item, event)"
        @copy="(id, event) => emit('copyWorkflow', id, event)"
        @delete="(id, event) => emit('deleteWorkflow', id, event)"
        @toggle-pin="(id) => emit('togglePinWorkflow', id)"
        @drag-start="(event, id) => emit('dragStartWorkflow', event, id)"
        @drag-end="emit('dragEndWorkflow')"
      />
    </div>
  </div>
</template>
