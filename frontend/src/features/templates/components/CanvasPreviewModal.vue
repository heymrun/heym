<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { Pencil, X, Zap } from "lucide-vue-next";

import type { NodeTemplate, WorkflowTemplate } from "../types/template.types";
import ReadonlyCanvasPreview from "@/components/Canvas/ReadonlyCanvasPreview.vue";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { useAuthStore } from "@/stores/auth";
import { buildTemplatePreviewGraph } from "@/features/templates/lib/templatePreviewGraph";
import WorkflowNodeBadge from "./WorkflowNodeBadge.vue";

interface Props {
  template: WorkflowTemplate | NodeTemplate;
  kind: "workflow" | "node";
  loading?: boolean;
}

const props = withDefaults(defineProps<Props>(), { loading: false });
const emit = defineEmits<{
  close: [];
  use: [];
  edit: [];
}>();

const authStore = useAuthStore();
const selectedNode = ref<Record<string, unknown> | null>(null);
const canEdit = computed((): boolean => !!authStore.user && props.template.author_id === authStore.user.id);
const previewGraph = computed(() => buildTemplatePreviewGraph(props.template, props.kind));
let removeOverlayDismiss: (() => void) | null = null;

watch(
  () => [props.template.id, props.kind],
  () => {
    selectedNode.value = null;
  },
  { immediate: true },
);

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function handleKeyDown(event: KeyboardEvent): void {
  if (event.key !== "Escape") return;

  event.preventDefault();
  event.stopImmediatePropagation();

  if (selectedNode.value) {
    selectedNode.value = null;
    return;
  }

  emit("close");
}

onMounted(() => {
  document.body.dataset.heymOverlayEscapeTrap = "true";
  window.addEventListener("keydown", handleKeyDown, true);
  removeOverlayDismiss = onDismissOverlays(() => emit("close"));
});

onUnmounted(() => {
  delete document.body.dataset.heymOverlayEscapeTrap;
  window.removeEventListener("keydown", handleKeyDown, true);
  removeOverlayDismiss?.();
  removeOverlayDismiss = null;
});
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
      @click.self="emit('close')"
    >
      <div
        class="relative flex h-[82vh] max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-border/50 bg-card shadow-2xl"
        @click.stop
      >
        <div class="flex items-start justify-between gap-4 border-b border-border/40 p-6">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h2 class="truncate text-lg font-semibold text-foreground">
                {{ template.name }}
              </h2>
              <WorkflowNodeBadge
                v-if="kind === 'node'"
                :node-type="(template as NodeTemplate).node_type"
              />
            </div>
            <p
              v-if="template.description"
              class="mt-1 text-sm text-muted-foreground"
            >
              {{ template.description }}
            </p>
            <div class="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              <span>{{ template.use_count }} uses</span>
              <span>{{ formatDate(template.created_at) }}</span>
              <span v-if="kind === 'workflow'">{{ previewGraph.nodes.length }} nodes</span>
              <span v-else>Single node template</span>
            </div>
          </div>
          <button
            class="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
            type="button"
            @click="emit('close')"
          >
            <X class="h-5 w-5" />
          </button>
        </div>

        <div class="flex min-h-0 flex-1 flex-col gap-4 px-6 py-4">
          <div
            v-if="template.tags.length"
            class="flex flex-wrap gap-1.5"
          >
            <span
              v-for="tag in template.tags"
              :key="tag"
              class="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-xs text-primary"
            >
              #{{ tag }}
            </span>
          </div>

          <p class="text-xs text-muted-foreground">
            Click a node to inspect its saved configuration. The canvas stays read-only here.
          </p>

          <div class="min-h-0 flex-1">
            <ReadonlyCanvasPreview
              :nodes="previewGraph.nodes"
              :edges="previewGraph.edges"
              :selected-node="selectedNode"
              :empty-message="kind === 'workflow' ? 'No nodes in this template' : 'No node to preview'"
              @update:selected-node="selectedNode = $event"
            />
          </div>
        </div>

        <div class="flex items-center justify-between gap-3 px-6 pb-6">
          <button
            v-if="canEdit"
            class="flex items-center gap-2 rounded-lg border border-border/50 px-4 py-2 text-sm transition-colors hover:bg-muted/60"
            type="button"
            @click="emit('edit')"
          >
            <Pencil class="h-4 w-4" />
            Edit
          </button>
          <div
            v-else
            class="flex-1"
          />
          <div class="flex gap-3">
            <button
              class="rounded-lg border border-border/50 px-4 py-2 text-sm transition-colors hover:bg-muted/60"
              type="button"
              @click="emit('close')"
            >
              Cancel
            </button>
            <button
              class="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              type="button"
              :disabled="loading"
              @click="emit('use')"
            >
              <Zap class="h-4 w-4" />
              {{ loading ? "Loading…" : "Use This Template" }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
