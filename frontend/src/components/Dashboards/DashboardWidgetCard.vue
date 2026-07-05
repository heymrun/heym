<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { Component } from "vue";
import { onClickOutside } from "@vueuse/core";
import { ExternalLink, Loader2, MoreVertical, Pencil, RefreshCw, Settings, Sparkles, Trash2 } from "lucide-vue-next";

import type { ChartPayload, DashboardWidget } from "@/types/dashboard";
import ChartRenderer from "@/components/Dashboards/ChartRenderer.vue";
import { toggleTaskItemLocal, updateOrRemoveTaskItemLocal } from "@/lib/markdownTaskList";
import { dashboardApi } from "@/services/api";

const props = defineProps<{
  widget: DashboardWidget;
  editMode: boolean;
}>();

const emit = defineEmits<{
  (e: "edit", workflowId: string): void;
  (e: "delete", widgetId: string): void;
  (e: "refine", widget: DashboardWidget): void;
  (e: "settings", widget: DashboardWidget): void;
  (e: "title-change", payload: { id: string; title: string }): void;
}>();

const payload = ref<ChartPayload | null>(null);
const markdownTaskSaving = ref(false);
// Only surface http(s) links. The url can come from a dynamic expression over upstream
// data, so reject javascript:/data:/relative values to avoid an injected-link XSS.
const externalUrl = computed<string | null>(() => {
  const raw = payload.value?.url;
  if (!raw) return null;
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
});
const loading = ref(true);
const error = ref<string | null>(null);
const editingTitle = ref(false);
const titleDraft = ref(props.widget.title);

// Header actions are shared between the inline icon row (sm+) and the collapsed
// 3-dot menu (small screens), so the two stay in sync from a single source.
interface WidgetAction {
  key: string;
  icon: Component;
  label: string;
  danger?: boolean;
  run: () => void;
}

const actions: WidgetAction[] = [
  { key: "refine", icon: Sparkles, label: "Fine-tune with AI", run: () => emit("refine", props.widget) },
  { key: "refresh", icon: RefreshCw, label: "Refresh", run: () => void loadData(true) },
  { key: "edit", icon: Pencil, label: "Edit workflow", run: () => emit("edit", props.widget.workflow_id) },
  { key: "settings", icon: Settings, label: "Settings", run: () => emit("settings", props.widget) },
  { key: "delete", icon: Trash2, label: "Delete widget", danger: true, run: () => emit("delete", props.widget.id) },
];

const menuOpen = ref(false);
const triggerRef = ref<HTMLElement | null>(null);
const menuPanelRef = ref<HTMLElement | null>(null);
const menuPos = ref<{ top: number; left: number }>({ top: 0, left: 0 });
const MENU_WIDTH = 176;

// The menu is teleported to <body> because each grid item is transformed and so
// forms its own stacking/clipping context — a z-indexed dropdown would otherwise
// be hidden behind neighbouring widgets.
onClickOutside(
  triggerRef,
  () => {
    menuOpen.value = false;
  },
  { ignore: [menuPanelRef] },
);

function toggleMenu(): void {
  if (menuOpen.value) {
    menuOpen.value = false;
    return;
  }
  const rect = triggerRef.value?.getBoundingClientRect();
  if (rect) {
    menuPos.value = {
      top: rect.bottom + 4,
      left: Math.max(8, rect.right - MENU_WIDTH),
    };
  }
  menuOpen.value = true;
}

function closeMenu(): void {
  menuOpen.value = false;
}

function runAction(action: WidgetAction): void {
  menuOpen.value = false;
  action.run();
}

watch(menuOpen, (open) => {
  if (open) {
    window.addEventListener("scroll", closeMenu, true);
    window.addEventListener("resize", closeMenu);
  } else {
    window.removeEventListener("scroll", closeMenu, true);
    window.removeEventListener("resize", closeMenu);
  }
});

async function loadData(force = false): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const response = await dashboardApi.getWidgetData(props.widget.id, force);
    payload.value = response.payload;
    error.value = response.error ?? null;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load widget";
  } finally {
    loading.value = false;
  }
}

async function onMarkdownTaskToggle(lineIndex: number): Promise<void> {
  if (!payload.value || payload.value.type !== "text" || !payload.value.text_interactive) {
    return;
  }
  const previousPayload = payload.value;
  const previousText = previousPayload.text ?? "";
  markdownTaskSaving.value = true;
  try {
    payload.value = {
      ...previousPayload,
      text: toggleTaskItemLocal(previousText, lineIndex),
    };
    const response = await dashboardApi.toggleMarkdownTask(props.widget.id, lineIndex);
    payload.value = response.payload;
    error.value = response.error ?? null;
  } catch (e) {
    payload.value = previousPayload;
    error.value = e instanceof Error ? e.message : "Failed to update checkbox";
  } finally {
    markdownTaskSaving.value = false;
  }
}

async function onMarkdownTaskUpdate(update: { lineIndex: number; text: string }): Promise<void> {
  if (!payload.value || payload.value.type !== "text" || !payload.value.text_interactive) {
    return;
  }
  const previousPayload = payload.value;
  const previousText = previousPayload.text ?? "";
  markdownTaskSaving.value = true;
  try {
    payload.value = {
      ...previousPayload,
      text: updateOrRemoveTaskItemLocal(previousText, update.lineIndex, update.text),
    };
    const response = await dashboardApi.updateMarkdownTask(
      props.widget.id,
      update.lineIndex,
      update.text,
    );
    payload.value = response.payload;
    error.value = response.error ?? null;
  } catch (e) {
    payload.value = previousPayload;
    error.value = e instanceof Error ? e.message : "Failed to update checkbox item";
  } finally {
    markdownTaskSaving.value = false;
  }
}

function commitTitle(): void {
  editingTitle.value = false;
  const next = titleDraft.value.trim();
  if (next && next !== props.widget.title) {
    emit("title-change", { id: props.widget.id, title: next });
  } else {
    titleDraft.value = props.widget.title;
  }
}

function onBodyDoubleClick(): void {
  emit("edit", props.widget.workflow_id);
}

// Reload when the widget's workflow changes (AI refine, settings) — updated_at bumps.
watch(
  () => props.widget.updated_at,
  () => {
    titleDraft.value = props.widget.title;
    void loadData(true);
  },
);

onMounted(() => {
  void loadData();
});

onBeforeUnmount(() => {
  window.removeEventListener("scroll", closeMenu, true);
  window.removeEventListener("resize", closeMenu);
});
</script>

<template>
  <div class="relative flex h-full flex-col rounded-lg border bg-card shadow-sm">
    <div class="flex items-center justify-between gap-2 border-b px-3 py-2">
      <input
        v-if="editingTitle"
        v-model="titleDraft"
        class="w-full min-w-0 bg-transparent text-sm font-medium outline-none"
        autofocus
        @blur="commitTitle"
        @keyup.enter="commitTitle"
      >
      <button
        v-else
        class="min-w-0 flex-1 truncate text-left text-sm font-medium hover:text-primary"
        :title="widget.title"
        @click="editingTitle = true"
      >
        {{ widget.title }}
      </button>

      <a
        v-if="externalUrl"
        :href="externalUrl"
        target="_blank"
        rel="noopener noreferrer"
        class="shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        title="Open link"
      >
        <ExternalLink class="h-3.5 w-3.5" />
      </a>

      <!-- sm+: inline icon row -->
      <div class="hidden shrink-0 items-center gap-1 sm:flex">
        <button
          v-for="action in actions"
          :key="action.key"
          class="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          :class="action.danger ? 'hover:bg-destructive/10 hover:text-destructive' : ''"
          :title="action.label"
          @click="action.run()"
        >
          <component
            :is="action.icon"
            class="h-3.5 w-3.5"
          />
        </button>
      </div>

      <!-- below sm: collapsed 3-dot menu so the title keeps its space -->
      <div
        ref="triggerRef"
        class="shrink-0 sm:hidden"
      >
        <button
          class="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          title="Actions"
          @click.stop="toggleMenu"
        >
          <MoreVertical class="h-4 w-4" />
        </button>
      </div>

      <Teleport to="body">
        <div
          v-if="menuOpen"
          ref="menuPanelRef"
          class="fixed z-[100] w-44 overflow-hidden rounded-lg border border-border bg-card py-1 shadow-lg"
          :style="{ top: `${menuPos.top}px`, left: `${menuPos.left}px` }"
        >
          <button
            v-for="action in actions"
            :key="action.key"
            class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent"
            :class="action.danger ? 'text-destructive hover:bg-destructive/10' : 'text-foreground'"
            @click.stop="runAction(action)"
          >
            <component
              :is="action.icon"
              class="h-4 w-4 shrink-0"
            />
            {{ action.label }}
          </button>
        </div>
      </Teleport>
    </div>

    <div
      class="flex-1 overflow-hidden p-3"
      @dblclick="onBodyDoubleClick"
    >
      <div
        v-if="loading"
        class="flex h-full min-h-[120px] items-center justify-center text-muted-foreground"
      >
        <Loader2 class="h-5 w-5 animate-spin" />
      </div>
      <div
        v-else-if="error"
        class="flex h-full min-h-[120px] items-center justify-center px-2 text-center text-xs text-destructive"
      >
        {{ error }}
      </div>
      <ChartRenderer
        v-else
        :payload="payload"
        :markdown-task-saving="markdownTaskSaving"
        @markdown-task-toggle="onMarkdownTaskToggle"
        @markdown-task-update="onMarkdownTaskUpdate"
      />
    </div>
  </div>
</template>
