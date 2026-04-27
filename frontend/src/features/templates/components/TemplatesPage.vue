<script setup lang="ts">
import { onMounted, ref } from "vue";
import { Globe, LayoutTemplate } from "lucide-vue-next";

import TemplateCard from "./TemplateCard.vue";
import TemplateSearchBar from "./TemplateSearchBar.vue";
import CanvasPreviewModal from "./CanvasPreviewModal.vue";
import EditTemplateModal from "./EditTemplateModal.vue";
import TemplatesBrowseDialog from "./TemplatesBrowseDialog.vue";
import NodeTemplateDestinationModal from "./NodeTemplateDestinationModal.vue";
import { useTemplates } from "../hooks/useTemplates";
import { useCreateFromTemplate } from "../hooks/useCreateFromTemplate";
import type { NodeTemplate, TemplateKind, WorkflowTemplate } from "../types/template.types";
import { templatesApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";

interface Props {
  autoOpenId?: string;
  autoOpenKind?: TemplateKind;
}

const props = withDefaults(defineProps<Props>(), {
  autoOpenId: undefined,
  autoOpenKind: undefined,
});

const { kind, loading, error, filteredWorkflowTemplates, filteredNodeTemplates, fetchTemplates, onSearchChange } =
  useTemplates("workflow");

const { loading: useLoading, useWorkflowTemplate, useNodeTemplate } =
  useCreateFromTemplate();

const authStore = useAuthStore();

const activeKind = ref<TemplateKind>("workflow");
const showBrowseDialog = ref(false);

const previewTemplate = ref<WorkflowTemplate | NodeTemplate | null>(null);
const destinationTemplate = ref<NodeTemplate | null>(null);
const editingTemplate = ref<WorkflowTemplate | NodeTemplate | null>(null);

function isOwner(t: WorkflowTemplate | NodeTemplate): boolean {
  return !!authStore.user && t.author_id === authStore.user.id;
}

function switchKind(k: TemplateKind): void {
  activeKind.value = k;
  kind.value = k;
}

function openPreview(t: WorkflowTemplate | NodeTemplate): void {
  previewTemplate.value = t;
}

async function handleUseFromPreview(): Promise<void> {
  if (!previewTemplate.value) return;
  if (activeKind.value === "workflow") {
    await useWorkflowTemplate(previewTemplate.value as WorkflowTemplate);
  } else {
    destinationTemplate.value = previewTemplate.value as NodeTemplate;
  }
  previewTemplate.value = null;
}

async function handleUseCard(t: WorkflowTemplate | NodeTemplate): Promise<void> {
  if (activeKind.value === "workflow") {
    await useWorkflowTemplate(t as WorkflowTemplate);
  } else {
    destinationTemplate.value = t as NodeTemplate;
  }
}

async function handleDestination(dest: "new" | "existing", workflowId?: string): Promise<void> {
  if (!destinationTemplate.value) return;
  const t = destinationTemplate.value;
  destinationTemplate.value = null;
  await useNodeTemplate(t, dest, workflowId);
}

function handleEditCard(t: WorkflowTemplate | NodeTemplate): void {
  editingTemplate.value = t;
}

function handleEditUpdated(updated: WorkflowTemplate | NodeTemplate): void {
  // Patch the template in-place in the lists so the card updates immediately
  if (activeKind.value === "workflow") {
    const idx = filteredWorkflowTemplates.value.findIndex((x) => x.id === updated.id);
    if (idx !== -1) filteredWorkflowTemplates.value[idx] = updated as WorkflowTemplate;
  } else {
    const idx = filteredNodeTemplates.value.findIndex((x) => x.id === updated.id);
    if (idx !== -1) filteredNodeTemplates.value[idx] = updated as NodeTemplate;
  }
  editingTemplate.value = null;
}

async function handleDeleteCard(t: WorkflowTemplate | NodeTemplate): Promise<void> {
  try {
    if (activeKind.value === "workflow") {
      await templatesApi.deleteWorkflow(t.id);
    } else {
      await templatesApi.deleteNode(t.id);
    }
    await fetchTemplates();
  } catch {
    // silently ignore
  }
}

onMounted(async () => {
  if (props.autoOpenId && props.autoOpenKind) {
    // Switch tab first so fetchTemplates fetches the right kind
    switchKind(props.autoOpenKind);
  }

  await fetchTemplates();

  if (props.autoOpenId && props.autoOpenKind) {
    const list = props.autoOpenKind === "workflow"
      ? filteredWorkflowTemplates.value
      : filteredNodeTemplates.value;
    const found = list.find((t) => t.id === props.autoOpenId);
    if (found) openPreview(found);
  }
});
</script>

<template>
  <div class="flex flex-col gap-6 h-full">
    <!-- Top bar -->
    <div class="flex flex-col sm:flex-row sm:items-center gap-4">
      <!-- Kind toggle -->
      <div class="flex items-center bg-muted/40 rounded-xl p-1 border border-border/40 shrink-0">
        <button
          :class="[
            'px-4 py-1.5 text-sm rounded-lg font-medium transition-all',
            activeKind === 'workflow'
              ? 'bg-primary text-primary-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground',
          ]"
          type="button"
          @click="switchKind('workflow')"
        >
          Workflows
        </button>
        <button
          :class="[
            'px-4 py-1.5 text-sm rounded-lg font-medium transition-all',
            activeKind === 'node'
              ? 'bg-primary text-primary-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground',
          ]"
          type="button"
          @click="switchKind('node')"
        >
          Nodes
        </button>
      </div>

      <TemplateSearchBar
        :model-value="''"
        :placeholder="activeKind === 'node' ? 'Search nodes…' : 'Search templates…'"
        @update:model-value="onSearchChange"
      />

      <button
        class="flex items-center gap-2 rounded-xl border border-border/40 bg-card/60 px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground hover:bg-card shrink-0"
        type="button"
        @click="showBrowseDialog = true"
      >
        <Globe class="h-4 w-4" />
        Browse Public Templates
      </button>
    </div>

    <!-- Loading skeleton -->
    <div
      v-if="loading"
      class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
    >
      <div
        v-for="i in 8"
        :key="i"
        class="h-64 rounded-2xl bg-muted/40 animate-pulse"
      />
    </div>

    <!-- Error state -->
    <div
      v-else-if="error"
      class="flex flex-col items-center gap-3 py-20 text-center"
    >
      <p class="text-sm text-destructive">
        {{ error }}
      </p>
      <button
        class="px-4 py-2 text-sm rounded-lg bg-muted hover:bg-muted/80 transition-colors"
        type="button"
        @click="fetchTemplates"
      >
        Retry
      </button>
    </div>

    <!-- Empty state -->
    <div
      v-else-if="(activeKind === 'workflow' ? filteredWorkflowTemplates : filteredNodeTemplates).length === 0"
      class="flex flex-col items-center gap-4 py-20 text-center"
    >
      <LayoutTemplate class="w-12 h-12 text-muted-foreground/40" />
      <div>
        <p class="text-sm font-medium text-foreground">
          No templates found
        </p>
        <p class="text-xs text-muted-foreground mt-1">
          Share a workflow or node to create your first template.
        </p>
      </div>
    </div>

    <!-- Grid -->
    <div
      v-else
      class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
    >
      <TemplateCard
        v-for="template in (activeKind === 'workflow' ? filteredWorkflowTemplates : filteredNodeTemplates)"
        :key="template.id"
        :template="template"
        :kind="activeKind"
        :use-loading="useLoading"
        :is-owner="isOwner(template)"
        @preview="openPreview(template)"
        @use="handleUseCard(template)"
        @edit="handleEditCard(template)"
        @delete="handleDeleteCard(template)"
      />
    </div>

    <!-- Canvas preview modal -->
    <CanvasPreviewModal
      v-if="previewTemplate"
      :template="previewTemplate"
      :kind="activeKind"
      :loading="useLoading"
      @close="previewTemplate = null"
      @use="handleUseFromPreview"
      @edit="editingTemplate = previewTemplate; previewTemplate = null"
    />

    <!-- Node destination modal -->
    <NodeTemplateDestinationModal
      v-if="destinationTemplate"
      :template="destinationTemplate"
      @choose="handleDestination"
      @close="destinationTemplate = null"
    />

    <!-- Edit template modal (owner only) -->
    <EditTemplateModal
      v-if="editingTemplate"
      :kind="activeKind"
      :template="editingTemplate"
      @close="editingTemplate = null"
      @updated="handleEditUpdated"
    />

    <!-- Browse public templates dialog -->
    <TemplatesBrowseDialog
      :open="showBrowseDialog"
      @close="showBrowseDialog = false"
    />
  </div>
</template>
