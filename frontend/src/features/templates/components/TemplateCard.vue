<script setup lang="ts">
import { computed, ref } from "vue";
import { Calendar, Pencil, Trash2, Zap } from "lucide-vue-next";

import type { NodeTemplate, WorkflowTemplate } from "../types/template.types";
import ReadonlyCanvasSurface from "@/components/Canvas/ReadonlyCanvasSurface.vue";
import { buildTemplatePreviewGraph } from "@/features/templates/lib/templatePreviewGraph";
import WorkflowNodeBadge from "./WorkflowNodeBadge.vue";

interface Props {
  template: WorkflowTemplate | NodeTemplate;
  kind: "workflow" | "node";
  useLoading?: boolean;
  isOwner?: boolean;
}

const props = withDefaults(defineProps<Props>(), { useLoading: false, isOwner: false });

const emit = defineEmits<{
  preview: [];
  use: [];
  edit: [];
  delete: [];
}>();

const confirmingDelete = ref(false);

function startDelete(): void {
  confirmingDelete.value = true;
}

function cancelDelete(): void {
  confirmingDelete.value = false;
}

function confirmDelete(): void {
  confirmingDelete.value = false;
  emit("delete");
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function isWorkflow(_t: WorkflowTemplate | NodeTemplate): _t is WorkflowTemplate {
  return props.kind === "workflow";
}

const cardRef = ref<HTMLElement | null>(null);
const previewGraph = computed(() => buildTemplatePreviewGraph(props.template, props.kind));
const thumbnailFitPadding = computed((): number => {
  if (props.kind === "node") {
    return 0.85;
  }
  return previewGraph.value.nodes.length <= 1 ? 0.94 : 0.18;
});
const thumbnailMaxZoom = computed((): number => {
  if (props.kind === "node") {
    return 0.82;
  }
  return previewGraph.value.nodes.length <= 1 ? 0.92 : 0.18;
});
</script>

<template>
  <div
    ref="cardRef"
    class="group relative flex flex-col rounded-2xl border border-border/40 bg-card/80 shadow-sm hover:shadow-md hover:border-primary/30 transition-all duration-200 overflow-hidden cursor-pointer"
    @click="emit('preview')"
  >
    <!-- Mini canvas preview -->
    <div class="h-36 border-b border-border/30 overflow-hidden bg-muted/20">
      <ReadonlyCanvasSurface
        :nodes="previewGraph.nodes"
        :edges="previewGraph.edges"
        :interactive="false"
        :show-controls="false"
        :show-mini-map="false"
        :fit-padding="thumbnailFitPadding"
        :max-zoom="thumbnailMaxZoom"
        :background-gap="16"
        :framed="false"
        :empty-message="kind === 'workflow' ? 'No workflow preview' : 'No node preview'"
      />
    </div>

    <!-- Card body -->
    <div class="flex flex-col gap-2 p-4 flex-1">
      <h3 class="text-sm font-semibold text-foreground truncate leading-snug">
        {{ template.name }}
      </h3>

      <p
        v-if="template.description"
        class="text-xs text-muted-foreground line-clamp-2"
      >
        {{ template.description }}
      </p>

      <!-- Node badges (workflow only) -->
      <div
        v-if="kind === 'workflow' && isWorkflow(template) && template.nodes.length"
        class="flex gap-1 overflow-x-auto scrollbar-thin pb-0.5"
        @click.stop
      >
        <WorkflowNodeBadge
          v-for="(node, i) in template.nodes.slice(0, 5)"
          :key="i"
          :node-type="String(node.type ?? '')"
        />
        <span
          v-if="(template as WorkflowTemplate).nodes.length > 5"
          class="inline-flex items-center px-2 py-0.5 text-xs text-muted-foreground shrink-0"
        >
          +{{ (template as WorkflowTemplate).nodes.length - 5 }}
        </span>
      </div>

      <!-- Tags -->
      <div
        v-if="template.tags.length"
        class="flex flex-wrap gap-1"
      >
        <span
          v-for="tag in template.tags.slice(0, 3)"
          :key="tag"
          class="px-1.5 py-0.5 rounded text-xs bg-primary/8 text-primary/80 border border-primary/15"
        >
          #{{ tag }}
        </span>
      </div>

      <div class="mt-auto pt-2">
        <!-- Normal state -->
        <div
          v-if="!confirmingDelete"
          class="flex items-center justify-between"
        >
          <div class="flex flex-col gap-0.5 text-xs text-muted-foreground">
            <span
              v-if="template.author_name"
              class="font-medium text-foreground/80"
            >
              {{ template.author_name }}
            </span>
            <div class="flex items-center gap-3">
              <span class="flex items-center gap-1">
                <Zap class="w-3 h-3" />
                {{ template.use_count }}
              </span>
              <span class="flex items-center gap-1">
                <Calendar class="w-3 h-3" />
                {{ formatDate(template.created_at) }}
              </span>
            </div>
          </div>

          <div class="flex items-center gap-1.5">
            <template v-if="isOwner">
              <button
                class="p-1.5 rounded-lg text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors opacity-0 group-hover:opacity-100"
                type="button"
                title="Edit template"
                @click.stop="emit('edit')"
              >
                <Pencil class="w-3.5 h-3.5" />
              </button>
              <button
                class="p-1.5 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors opacity-0 group-hover:opacity-100"
                type="button"
                title="Delete template"
                @click.stop="startDelete"
              >
                <Trash2 class="w-3.5 h-3.5" />
              </button>
            </template>
            <button
              class="px-3 py-1 text-xs rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 shrink-0"
              type="button"
              :disabled="useLoading"
              @click.stop="emit('use')"
            >
              {{ useLoading ? "…" : "Use" }}
            </button>
          </div>
        </div>

        <!-- Confirm delete state -->
        <div
          v-else
          class="flex items-center justify-between gap-2"
          @click.stop
        >
          <span class="text-xs text-destructive font-medium">Delete this template?</span>
          <div class="flex gap-1.5 shrink-0">
            <button
              class="px-2.5 py-1 text-xs rounded-lg border border-border/50 hover:bg-muted/60 transition-colors"
              type="button"
              @click.stop="cancelDelete"
            >
              Cancel
            </button>
            <button
              class="px-2.5 py-1 text-xs rounded-lg bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors"
              type="button"
              @click.stop="confirmDelete"
            >
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
