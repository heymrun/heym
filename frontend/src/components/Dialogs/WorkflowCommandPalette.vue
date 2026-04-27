<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import {
  Activity,
  BarChart3,
  BookOpen,
  CalendarDays,
  Database,
  FlaskConical,
  HardDrive,
  History,
  Key,
  LayoutTemplate,
  LifeBuoy,
  MessageCircle,
  Search,
  Server,
  Table2,
  Terminal,
  Trash2,
  Variable,
  Workflow,
} from "lucide-vue-next";

import { getAllDocItems } from "@/docs/manifest";
import { cn, formatDate } from "@/lib/utils";
import { nodeIcons } from "@/lib/nodeIcons";
import { useRecentWorkflows } from "@/composables/useRecentWorkflows";
import { useFolderStore } from "@/stores/folder";
import { templatesApi } from "@/services/api";
import type { WorkflowListItem } from "@/types/workflow";
import type { NodeTemplate, WorkflowTemplate } from "@/features/templates/types/template.types";

const TABS = [
  { id: "workflows", label: "Workflows", icon: Workflow },
  { id: "globalvariables", label: "Variables", icon: Variable },
  { id: "chat", label: "Chat", icon: MessageCircle },
  { id: "drive", label: "Drive", icon: HardDrive },
  { id: "credentials", label: "Credentials", icon: Key },
  { id: "vectorstores", label: "Vectors", icon: Database },
  { id: "mcp", label: "MCP", icon: Server },
  { id: "traces", label: "Traces", icon: Activity },
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "datatable", label: "DataTable", icon: Table2 },
  { id: "evals", label: "Evals", icon: FlaskConical },
  { id: "schedules", label: "Scheduled", icon: CalendarDays },
  { id: "logs", label: "Logs", icon: Terminal },
] as const;

type PaletteItemType = "history" | "tab" | "workflow" | "doc" | "template" | "node-template" | "support";

interface PaletteItem {
  type: PaletteItemType;
  id: string;
  label: string;
  icon: (typeof TABS)[number]["icon"] | typeof Workflow | typeof BookOpen | typeof Trash2 | typeof LayoutTemplate;
  workflow?: WorkflowListItem;
  folderPath?: string;
  categoryId?: string;
  slug?: string;
  categoryLabel?: string;
  template?: WorkflowTemplate;
  nodeTemplate?: NodeTemplate;
}

interface Props {
  open: boolean;
  workflows: WorkflowListItem[];
  context: "dashboard" | "editor";
  activeTab?: string;
}

const props = withDefaults(
  defineProps<Props>(),
  { activeTab: "workflows" }
);

const emit = defineEmits<{
  (e: "select", workflowId: string, event?: MouseEvent): void;
  (e: "tabSelect", tabId: string, event?: MouseEvent): void;
  (e: "docSelect", categoryId: string, slug: string, event?: MouseEvent): void;
  (e: "templateSelect", templateId: string, event?: MouseEvent): void;
  (e: "nodeTemplateSelect", template: NodeTemplate, event?: MouseEvent): void;
  (e: "close"): void;
}>();

const { getRecent } = useRecentWorkflows();
const folderStore = useFolderStore();
const workflowTemplates = ref<WorkflowTemplate[]>([]);
const nodeTemplates = ref<NodeTemplate[]>([]);

async function fetchTemplates(): Promise<void> {
  try {
    const res = await templatesApi.list();
    workflowTemplates.value = res.workflow_templates;
    nodeTemplates.value = res.node_templates;
  } catch {
    workflowTemplates.value = [];
    nodeTemplates.value = [];
  }
}

function getFolderPath(workflow: WorkflowListItem | undefined): string {
  if (!workflow?.folder_id) return "";
  const breadcrumb = folderStore.getBreadcrumb(workflow.folder_id);
  return breadcrumb.map((f) => f.name).join(" / ");
}

const searchQuery = ref("");
const selectedIndex = ref(0);
const inputRef = ref<HTMLInputElement | null>(null);
const listRef = ref<HTMLDivElement | null>(null);
const itemRefs = ref<(HTMLDivElement | null)[]>([]);

const recentWorkflows = computed(() => getRecent());

const filteredTabs = computed(() => {
  const query = searchQuery.value.toLowerCase().trim();
  if (!query) return TABS;
  return TABS.filter((t) => t.label.toLowerCase().includes(query));
});

const filteredWorkflows = computed(() => {
  if (!searchQuery.value.trim()) {
    return props.workflows.filter((w) => !w.scheduled_for_deletion);
  }
  const query = searchQuery.value.toLowerCase();
  return props.workflows.filter((w) => {
    if (w.scheduled_for_deletion) return false;
    const nameMatch = w.name.toLowerCase().includes(query);
    const descriptionMatch = w.description
      ? w.description.toLowerCase().includes(query)
      : false;
    return nameMatch || descriptionMatch;
  });
});

const filteredScheduledWorkflows = computed(() => {
  const scheduled = props.workflows.filter((w) => w.scheduled_for_deletion);
  if (!searchQuery.value.trim()) return scheduled;
  const query = searchQuery.value.toLowerCase();
  return scheduled.filter((w) => {
    const nameMatch = w.name.toLowerCase().includes(query);
    const descriptionMatch = w.description
      ? w.description.toLowerCase().includes(query)
      : false;
    return nameMatch || descriptionMatch;
  });
});

const filteredTemplates = computed(() => {
  const q = searchQuery.value.toLowerCase().trim();
  if (!q) return workflowTemplates.value;
  return workflowTemplates.value.filter(
    (t) =>
      t.name.toLowerCase().includes(q) ||
      (t.description ?? "").toLowerCase().includes(q) ||
      (t.tags ?? []).some((tag) => tag.toLowerCase().includes(q))
  );
});

const filteredNodeTemplates = computed(() => {
  const q = searchQuery.value.toLowerCase().trim();
  if (!q) return nodeTemplates.value;
  return nodeTemplates.value.filter(
    (t) =>
      t.name.toLowerCase().includes(q) ||
      (t.description ?? "").toLowerCase().includes(q) ||
      t.node_type.toLowerCase().includes(q) ||
      (t.tags ?? []).some((tag) => tag.toLowerCase().includes(q))
  );
});

const filteredDocs = computed(() => {
  const query = searchQuery.value.toLowerCase().trim();
  const items = getAllDocItems();
  if (!query) return items;
  return items.filter(
    (item) =>
      item.title.toLowerCase().includes(query) ||
      item.slug.toLowerCase().includes(query) ||
      item.categoryLabel.toLowerCase().includes(query)
  );
});

interface CategoryGroup {
  id: string;
  label: string;
  items: PaletteItem[];
}

const categoryGroups = computed((): CategoryGroup[] => {
  const query = searchQuery.value.toLowerCase().trim();
  const groups: CategoryGroup[] = [];

  // 1. Recent (always at top)
  const recentItems: PaletteItem[] = [];
  recentWorkflows.value.forEach((r) => {
    if (!query || r.name.toLowerCase().includes(query)) {
      const workflow = props.workflows.find((w) => w.id === r.id);
      recentItems.push({
        type: "history",
        id: r.id,
        label: r.name,
        icon: History,
        workflow,
        folderPath: getFolderPath(workflow),
      });
    }
  });
  if (recentItems.length > 0) {
    groups.push({ id: "recent", label: "Recent", items: recentItems });
  }

  // 2. Workflows
  const historyIds = new Set(recentWorkflows.value.map((r) => r.id));
  const workflowItems: PaletteItem[] = [];
  filteredWorkflows.value.forEach((w) => {
    if (!historyIds.has(w.id)) {
      workflowItems.push({
        type: "workflow",
        id: w.id,
        label: w.name,
        icon: (w.first_node_type && nodeIcons[w.first_node_type]
          ? nodeIcons[w.first_node_type]
          : Workflow) as (typeof TABS)[number]["icon"],
        workflow: w,
        folderPath: getFolderPath(w),
      });
    }
  });
  if (workflowItems.length > 0) {
    groups.push({ id: "workflows", label: "Workflows", items: workflowItems });
  }

  // 3. Scheduled for Deletion
  const scheduledItems: PaletteItem[] = filteredScheduledWorkflows.value.map((w) => ({
    type: "workflow",
    id: w.id,
    label: w.name,
    icon: Trash2,
    workflow: w,
    folderPath: getFolderPath(w),
  }));
  if (scheduledItems.length > 0) {
    groups.push({
      id: "scheduled",
      label: "Scheduled for Deletion",
      items: scheduledItems,
    });
  }

  // 4. Go to tab
  const tabItems: PaletteItem[] = filteredTabs.value.map((t) => ({
    type: "tab" as const,
    id: t.id,
    label: t.label,
    icon: t.icon,
  }));
  if (tabItems.length > 0) {
    groups.push({ id: "tabs", label: "Go to tab", items: tabItems });
  }

  // 5. Templates (workflow + node)
  const templateItems: PaletteItem[] = [
    ...filteredTemplates.value.map((t) => ({
      type: "template" as const,
      id: t.id,
      label: t.name,
      icon: LayoutTemplate,
      template: t,
      categoryLabel: "Workflow Template",
    })),
    ...filteredNodeTemplates.value.map((t) => ({
      type: "node-template" as const,
      id: t.id,
      label: t.name,
      icon: LayoutTemplate,
      nodeTemplate: t,
      categoryLabel: "Node Template",
    })),
  ];
  if (templateItems.length > 0) {
    groups.push({ id: "templates", label: "Templates", items: templateItems });
  }

  // 5. Documentation (always last)
  const docItems: PaletteItem[] = filteredDocs.value.map((item) => ({
    type: "doc" as const,
    id: `${item.categoryId}-${item.slug}`,
    label: item.title,
    icon: BookOpen,
    categoryId: item.categoryId,
    slug: item.slug,
    categoryLabel: item.categoryLabel,
  }));
  if (docItems.length > 0) {
    groups.push({ id: "docs", label: "Documentation", items: docItems });
  }

  const q = searchQuery.value.toLowerCase().trim();
  if (!q || "support".includes(q) || "contact".includes(q) || "help".includes(q)) {
    groups.push({
      id: "support",
      label: "Support",
      items: [{
        type: "support" as const,
        id: "support",
        label: "Contact Support",
        icon: LifeBuoy,
      }],
    });
  }

  return groups;
});

const allItems = computed((): PaletteItem[] =>
  categoryGroups.value.flatMap((g) => g.items)
);

watch(
  () => props.open,
  (open) => {
    if (open) {
      searchQuery.value = "";
      selectedIndex.value = 0;
      fetchTemplates();
      nextTick(() => {
        inputRef.value?.focus();
      });
    } else {
      searchQuery.value = "";
      selectedIndex.value = 0;
    }
  },
);

watch(allItems, (items) => {
  itemRefs.value = new Array(items.length).fill(null);
  if (selectedIndex.value >= items.length) {
    selectedIndex.value = Math.max(0, items.length - 1);
  }
});

function scrollToSelected(): void {
  nextTick(() => {
    const selectedElement = itemRefs.value[selectedIndex.value];
    if (selectedElement && listRef.value) {
      selectedElement.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      });
    }
  });
}

function handleKeyDown(event: KeyboardEvent): void {
  if (!props.open) return;

  if (event.key === "Escape") {
    event.preventDefault();
    emit("close");
    return;
  }

  if (event.key === "ArrowDown" || (event.key === "Tab" && !event.shiftKey)) {
    event.preventDefault();
    if (allItems.value.length > 0) {
      selectedIndex.value =
        selectedIndex.value >= allItems.value.length - 1
          ? 0
          : selectedIndex.value + 1;
      scrollToSelected();
    }
    return;
  }

  if (event.key === "ArrowUp" || (event.key === "Tab" && event.shiftKey)) {
    event.preventDefault();
    if (allItems.value.length > 0) {
      selectedIndex.value =
        selectedIndex.value <= 0
          ? allItems.value.length - 1
          : selectedIndex.value - 1;
      scrollToSelected();
    }
    return;
  }

  if (event.key === "Enter") {
    event.preventDefault();
    const item = allItems.value[selectedIndex.value];
    if (item) {
      handleSelectItem(item, selectedIndex.value, undefined);
    }
    return;
  }
}

function getFlatIndex(groupIdx: number, itemIdx: number): number {
  return categoryGroups.value
    .slice(0, groupIdx)
    .reduce((acc, g) => acc + g.items.length, 0) + itemIdx;
}

function setItemRef(el: unknown, groupIdx: number, itemIdx: number): void {
  if (!el) return;
  const flatIdx = getFlatIndex(groupIdx, itemIdx);
  itemRefs.value[flatIdx] = el as HTMLDivElement;
}

function handleSelectItem(
  item: PaletteItem,
  index: number,
  event?: MouseEvent
): void {
  selectedIndex.value = index;
  if (item.type === "tab") {
    emit("tabSelect", item.id, event);
  } else if (item.type === "doc" && item.categoryId && item.slug) {
    emit("docSelect", item.categoryId, item.slug, event);
  } else if (item.type === "template") {
    emit("templateSelect", item.id, event);
  } else if (item.type === "node-template" && item.nodeTemplate) {
    emit("nodeTemplateSelect", item.nodeTemplate, event);
  } else if (item.type === "support") {
    window.location.href = "mailto:support@heym.run";
    emit("close");
  } else {
    emit("select", item.id, event);
  }
}

onMounted(() => {
  document.addEventListener("keydown", handleKeyDown);
});

onUnmounted(() => {
  document.removeEventListener("keydown", handleKeyDown);
});
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-opacity duration-200"
      leave-active-class="transition-opacity duration-150"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open"
        class="fixed inset-0 z-50 min-h-[100dvh] flex flex-col sm:flex-row sm:items-start sm:justify-center sm:pt-[20vh] sm:pb-0 px-4"
        @click.self="emit('close')"
      >
        <div
          class="command-palette-backdrop fixed inset-0"
          @click="emit('close')"
        />
        <div
          class="flex-1 min-h-0 basis-0 sm:hidden"
          aria-hidden="true"
        />
        <div
          class="command-palette-content relative z-50 w-full max-w-2xl h-fit max-h-[calc(100dvh-1rem)] sm:h-auto sm:max-h-none flex flex-col shrink-0 basis-auto sm:flex-initial"
          @click.stop
        >
          <div
            class="command-palette-container rounded-2xl border border-border/60 bg-card/95 backdrop-blur-xl overflow-hidden overflow-x-hidden flex flex-col w-full sm:flex-initial"
          >
            <div class="flex items-center gap-3 px-4 py-3 border-b border-border/50">
              <Search class="w-5 h-5 text-muted-foreground shrink-0" />
              <input
                ref="inputRef"
                v-model="searchQuery"
                type="text"
                class="flex-1 bg-transparent border-0 outline-none text-sm placeholder:text-muted-foreground/60 focus:outline-none"
                placeholder="Search workflows, tabs, docs..."
                aria-label="Command palette search"
                autocomplete="off"
              >
            </div>

            <div
              ref="listRef"
              class="command-palette-list flex-none min-h-0 max-h-[calc(100dvh-8rem)] sm:max-h-[60vh] overflow-y-auto scrollbar-thin"
              role="listbox"
              aria-label="Command palette"
            >
              <div
                v-if="allItems.length === 0"
                class="px-4 py-12 text-center text-sm text-muted-foreground"
              >
                <p>No results found</p>
                <p
                  v-if="searchQuery.trim()"
                  class="mt-1 text-xs"
                >
                  Try a different search term
                </p>
              </div>

              <template
                v-for="(group, groupIdx) in categoryGroups"
                :key="group.id"
              >
                <div
                  class="px-4 pt-3 pb-1 text-xs font-semibold text-muted-foreground uppercase tracking-wider first:pt-2"
                  :class="{ 'pt-4 border-t border-border/40 mt-1': groupIdx > 0 }"
                >
                  {{ group.label }}
                </div>
                <div
                  v-for="(item, itemIdx) in group.items"
                  :key="`${item.type}-${item.id}`"
                  :ref="(el) => setItemRef(el, groupIdx, itemIdx)"
                  :class="cn(
                    'command-palette-item flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors duration-150',
                    selectedIndex === getFlatIndex(groupIdx, itemIdx)
                      ? 'bg-accent/50 text-accent-foreground'
                      : 'hover:bg-muted/50 text-foreground'
                  )"
                  role="option"
                  :aria-selected="selectedIndex === getFlatIndex(groupIdx, itemIdx)"
                  @click="handleSelectItem(item, getFlatIndex(groupIdx, itemIdx), $event)"
                >
                  <div
                    :class="cn(
                      'relative flex items-center justify-center w-10 h-10 rounded-lg shrink-0',
                      item.type === 'history'
                        ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400'
                        : item.type === 'tab'
                          ? 'bg-muted/80 text-muted-foreground'
                          : item.type === 'doc'
                            ? 'bg-sky-500/10 text-sky-600 dark:text-sky-400'
                            : item.type === 'template'
                              ? 'bg-violet-500/10 text-violet-500 dark:text-violet-400'
                              : item.type === 'node-template'
                                ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                                : item.type === 'support'
                                  ? 'bg-rose-500/10 text-rose-600 dark:text-rose-400'
                                  : item.workflow?.scheduled_for_deletion
                                    ? 'bg-destructive/10 text-destructive'
                                    : 'bg-primary/10 text-primary'
                    )"
                  >
                    <div
                      v-if="item.type === 'workflow' && !item.workflow?.scheduled_for_deletion"
                      class="absolute inset-0 rounded-lg ring-1 ring-inset ring-primary/15"
                    />
                    <component
                      :is="item.icon"
                      class="w-5 h-5 relative z-10"
                    />
                  </div>
                  <div class="flex-1 min-w-0">
                    <div class="font-medium text-sm truncate">
                      {{ item.label }}
                    </div>
                    <div
                      v-if="item.type === 'workflow' && item.workflow?.scheduled_for_deletion"
                      class="text-xs text-muted-foreground truncate mt-0.5"
                    >
                      Scheduled {{ formatDate(item.workflow.scheduled_for_deletion) }}
                    </div>
                    <div
                      v-else-if="item.type === 'workflow' && item.workflow?.description"
                      class="text-xs text-muted-foreground truncate mt-0.5"
                    >
                      {{ item.workflow.description }}
                    </div>
                    <div
                      v-else-if="item.type === 'workflow' && item.folderPath"
                      class="text-xs text-muted-foreground truncate mt-0.5"
                    >
                      In: {{ item.folderPath }}
                    </div>
                    <div
                      v-else-if="item.type === 'history'"
                      class="text-xs text-muted-foreground mt-0.5"
                    >
                      {{ item.folderPath ? `Recent · In: ${item.folderPath}` : "Recent" }}
                    </div>
                    <div
                      v-else-if="item.type === 'tab'"
                      class="text-xs text-muted-foreground mt-0.5"
                    >
                      Go to tab
                    </div>
                    <div
                      v-else-if="item.type === 'template'"
                      class="text-xs text-muted-foreground mt-0.5"
                    >
                      {{ item.template?.description ?? "Workflow Template" }}
                    </div>
                    <div
                      v-else-if="item.type === 'node-template'"
                      class="text-xs text-muted-foreground mt-0.5"
                    >
                      {{ item.nodeTemplate?.description ?? `Node · ${item.nodeTemplate?.node_type ?? ""}` }}
                    </div>
                    <div
                      v-else-if="item.type === 'doc' && item.categoryLabel"
                      class="text-xs text-muted-foreground mt-0.5"
                    >
                      {{ item.categoryLabel }}
                    </div>
                    <div
                      v-else-if="item.type === 'support'"
                      class="text-xs text-muted-foreground mt-0.5"
                    >
                      Get help from the Heym team
                    </div>
                  </div>
                </div>
              </template>
            </div>

            <div
              v-if="allItems.length > 0"
              class="px-4 py-3 sm:py-2 border-t border-border/50 text-xs text-muted-foreground flex items-center justify-between shrink-0"
            >
              <div class="flex items-center gap-4">
                <span class="flex items-center gap-1.5">
                  <kbd class="px-1.5 py-0.5 rounded bg-muted font-mono text-[10px]">↑↓</kbd>
                  <span>Navigate</span>
                </span>
                <span class="flex items-center gap-1.5">
                  <kbd class="px-1.5 py-0.5 rounded bg-muted font-mono text-[10px]">Enter</kbd>
                  <span>Select</span>
                </span>
                <span class="hidden sm:flex items-center gap-1.5">
                  <kbd class="px-1.5 py-0.5 rounded bg-muted font-mono text-[10px]">Ctrl</kbd>
                  <span>+ click to open in new tab</span>
                </span>
              </div>
              <span>{{ allItems.length }} item{{ allItems.length !== 1 ? 's' : '' }}</span>
            </div>
          </div>
        </div>
        <div
          class="flex-1 min-h-0 basis-0 sm:hidden"
          aria-hidden="true"
        />
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.command-palette-backdrop {
  background: hsl(0 0% 0% / 0.65);
  backdrop-filter: blur(12px);
}

.command-palette-content {
  animation: command-palette-scale-in 0.2s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes command-palette-scale-in {
  from {
    opacity: 0;
    transform: scale(0.95) translateY(-8px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .command-palette-content {
    animation: none;
  }

  .command-palette-item {
    transition: none;
  }
}

.command-palette-container {
  box-shadow:
    0 0 0 1px hsl(var(--border) / 0.5),
    0 16px 70px -12px hsl(0 0% 0% / 0.35),
    0 8px 30px -8px hsl(0 0% 0% / 0.2);
}

.command-palette-list {
  scrollbar-width: thin;
  scrollbar-color: hsl(var(--muted)) transparent;
}

.command-palette-list::-webkit-scrollbar {
  width: 6px;
}

.command-palette-list::-webkit-scrollbar-track {
  background: transparent;
}

.command-palette-list::-webkit-scrollbar-thumb {
  background: hsl(var(--muted));
  border-radius: 3px;
}

.command-palette-list::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground) / 0.3);
}

.command-palette-item {
  outline: none;
}

.command-palette-item:focus-visible {
  outline: 2px solid hsl(var(--primary));
  outline-offset: -2px;
}
</style>
