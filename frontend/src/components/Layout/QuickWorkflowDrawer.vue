<script setup lang="ts">
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  Clock3,
  Copy,
  Image as ImageIcon,
  Loader2,
  MoveRight,
  Pin,
  Play,
  Search,
  Square,
  Sparkles,
  Workflow,
  X,
} from "lucide-vue-next";

import ImageLightbox from "@/components/ui/ImageLightbox.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import { useToast } from "@/composables/useToast";
import { cn } from "@/lib/utils";
import { useQuickDrawerStore } from "@/stores/quickDrawer";
import type { QuickDrawerWorkflowViewModel } from "@/types/quickDrawer";
import type { NodeResult } from "@/types/workflow";

interface Props {
  open: boolean;
}

defineProps<Props>();

const quickDrawerStore = useQuickDrawerStore();
const { showToast } = useToast();
const router = useRouter();
const selectedImageSrc = ref<string | null>(null);

const {
  currentInputValues,
  filterText,
  filteredOtherWorkflows,
  filteredPinnedWorkflows,
  isDetailPanelOpen,
  isLoadingWorkflows,
  runState,
  selectedWorkflow,
  workflowLoadError,
} = storeToRefs(quickDrawerStore);

const hasAnyWorkflowMatch = computed(() => {
  return filteredPinnedWorkflows.value.length > 0 || filteredOtherWorkflows.value.length > 0;
});

const isRunning = computed(() => runState.value.status === "running");

const resultTone = computed(() => {
  if (runState.value.status === "success") {
    return "border-success/30 bg-success/10 text-success";
  }
  if (runState.value.status === "pending") {
    return "border-warning/30 bg-warning/10 text-foreground";
  }
  if (runState.value.status === "error") {
    return "border-destructive/30 bg-destructive/10 text-destructive";
  }
  return "border-border/60 bg-muted/30 text-muted-foreground";
});

const outputImages = computed(() => {
  return extractImages(runState.value.outputs, runState.value.nodeResults);
});

const visibleNodeResults = computed<NodeResult[]>(() => {
  const dedupedResults: NodeResult[] = [];
  const seenNodeIds = new Set<string>();

  for (let index = runState.value.nodeResults.length - 1; index >= 0; index -= 1) {
    const nodeResult = runState.value.nodeResults[index];
    if (nodeResult.status === "skipped") {
      continue;
    }
    if (seenNodeIds.has(nodeResult.node_id)) {
      continue;
    }
    seenNodeIds.add(nodeResult.node_id);
    dedupedResults.unshift(nodeResult);
  }

  return dedupedResults;
});

function formatExecutionTime(executionTimeMs: number | null): string {
  if (executionTimeMs === null) return "Pending";
  if (executionTimeMs < 1000) return `${executionTimeMs.toFixed(0)} ms`;
  return `${(executionTimeMs / 1000).toFixed(2)} s`;
}

function formatJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function isSelectedWorkflow(workflowId: string): boolean {
  return selectedWorkflow.value?.id === workflowId;
}

function workflowSubtitle(workflow: QuickDrawerWorkflowViewModel): string {
  if (workflow.outputNode?.label) {
    return `Output: ${workflow.outputNode.label}`;
  }
  if (workflow.description) {
    return workflow.description;
  }
  return "Quick run";
}

function normalizeImage(value: string): string | null {
  if (value.startsWith("data:image/") || value.startsWith("http")) {
    return value;
  }
  if (value.length > 100 && /^[A-Za-z0-9+/=]+$/.test(value)) {
    return `data:image/png;base64,${value}`;
  }
  return null;
}

function extractImagesFromObject(obj: Record<string, unknown>): string[] {
  const images: string[] = [];

  const directImage = typeof obj.image === "string" ? normalizeImage(obj.image) : null;
  if (directImage) {
    images.push(directImage);
  }

  const screenshot =
    typeof obj.screenshot === "string" ? normalizeImage(obj.screenshot) : null;
  if (screenshot) {
    images.push(screenshot);
  }

  if (obj.results && typeof obj.results === "object") {
    for (const value of Object.values(obj.results as Record<string, unknown>)) {
      if (typeof value !== "string") continue;
      const image = normalizeImage(value);
      if (image) {
        images.push(image);
      }
    }
  }

  return images;
}

function extractImages(
  outputs: Record<string, unknown> | null,
  nodeResults: NodeResult[],
): string[] {
  const seen = new Set<string>();
  const images: string[] = [];

  if (outputs) {
    for (const value of Object.values(outputs)) {
      if (typeof value !== "object" || value === null) continue;
      for (const image of extractImagesFromObject(value as Record<string, unknown>)) {
        if (seen.has(image)) continue;
        seen.add(image);
        images.push(image);
      }
    }
  }

  for (const nodeResult of nodeResults) {
    if (typeof nodeResult.output !== "object" || nodeResult.output === null) continue;
    for (const image of extractImagesFromObject(nodeResult.output as Record<string, unknown>)) {
      if (seen.has(image)) continue;
      seen.add(image);
      images.push(image);
    }
  }

  return images;
}

async function copyFinalOutput(): Promise<void> {
  if (!runState.value.outputs) return;

  try {
    await navigator.clipboard.writeText(formatJson(runState.value.outputs));
    showToast("Final output copied", "success");
  } catch {
    showToast("Failed to copy final output", "error");
  }
}

function goToSelectedWorkflow(): void {
  if (!selectedWorkflow.value) return;
  quickDrawerStore.closeDrawer();
  router.push({
    name: "editor",
    params: { id: selectedWorkflow.value.id },
  });
}
</script>

<template>
  <aside
    :class="cn(
      'quick-workflow-drawer fixed right-0 top-0 z-40 h-screen border-l border-border/60 bg-card/96 shadow-2xl backdrop-blur-xl transition-transform duration-300 ease-out',
      open ? 'translate-x-0' : 'translate-x-full pointer-events-none'
    )"
    :style="{ width: 'var(--quick-drawer-width)' }"
    aria-label="Quick workflows drawer"
  >
    <div class="relative flex h-full flex-col overflow-hidden">
      <div class="border-b border-border/60 px-5 py-4">
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">
              <Sparkles class="h-3.5 w-3.5" />
              Quick Drawer
            </div>
            <h2 class="mt-3 text-xl font-semibold text-foreground">
              Workflows
            </h2>
            <p class="mt-1 text-sm text-muted-foreground">
              Search, pin, and run workflows without leaving the page.
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            class="h-10 w-10 shrink-0"
            aria-label="Close quick workflows drawer"
            @click="quickDrawerStore.closeDrawer()"
          >
            <X class="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div class="border-b border-border/60 px-5 py-4">
        <div class="relative">
          <Search class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            :model-value="filterText"
            placeholder="Filter workflows"
            class="pl-10"
            @update:model-value="quickDrawerStore.updateFilter"
          />
        </div>
      </div>

      <div class="flex-1 overflow-y-auto px-5 py-4">
        <div
          v-if="isLoadingWorkflows"
          class="flex items-center gap-2 text-sm text-muted-foreground"
        >
          <Loader2 class="h-4 w-4 animate-spin" />
          Loading quick workflows...
        </div>

        <div
          v-else-if="workflowLoadError"
          class="rounded-2xl border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          {{ workflowLoadError }}
        </div>

        <template v-else>
          <div
            v-if="filteredPinnedWorkflows.length > 0"
            class="space-y-2"
          >
            <div class="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              <Pin class="h-3.5 w-3.5" />
              Pinned
            </div>
            <div
              v-for="workflow in filteredPinnedWorkflows"
              :key="workflow.id"
              role="button"
              tabindex="0"
              :class="cn(
                'group flex w-full items-start gap-3 rounded-2xl border px-3 py-3 text-left transition-all',
                isSelectedWorkflow(workflow.id)
                  ? 'border-primary/40 bg-primary/10 shadow-sm'
                  : 'border-border/60 bg-background/70 hover:border-primary/30 hover:bg-accent/50'
              )"
              @click="quickDrawerStore.selectWorkflow(workflow.id)"
              @keydown.enter.prevent="quickDrawerStore.selectWorkflow(workflow.id)"
              @keydown.space.prevent="quickDrawerStore.selectWorkflow(workflow.id)"
            >
              <div class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Workflow class="h-4 w-4" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="truncate text-sm font-semibold text-foreground">
                  {{ workflow.name }}
                </div>
                <div class="mt-1 line-clamp-2 text-xs text-muted-foreground">
                  {{ workflowSubtitle(workflow) }}
                </div>
              </div>
              <button
                type="button"
                class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-primary transition-colors hover:bg-primary/10"
                :aria-label="`Unpin ${workflow.name}`"
                @click.stop="quickDrawerStore.togglePin(workflow.id)"
              >
                <Pin class="h-4 w-4 fill-current" />
              </button>
            </div>
          </div>

          <div
            class="space-y-2"
            :class="filteredPinnedWorkflows.length > 0 ? 'mt-5' : ''"
          >
            <div class="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              <Workflow class="h-3.5 w-3.5" />
              All Workflows
            </div>

            <div
              v-for="workflow in filteredOtherWorkflows"
              :key="workflow.id"
              role="button"
              tabindex="0"
              :class="cn(
                'group flex w-full items-start gap-3 rounded-2xl border px-3 py-3 text-left transition-all',
                isSelectedWorkflow(workflow.id)
                  ? 'border-primary/40 bg-primary/10 shadow-sm'
                  : 'border-border/60 bg-background/70 hover:border-primary/30 hover:bg-accent/50'
              )"
              @click="quickDrawerStore.selectWorkflow(workflow.id)"
              @keydown.enter.prevent="quickDrawerStore.selectWorkflow(workflow.id)"
              @keydown.space.prevent="quickDrawerStore.selectWorkflow(workflow.id)"
            >
              <div class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-muted text-foreground">
                <Workflow class="h-4 w-4" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="truncate text-sm font-semibold text-foreground">
                  {{ workflow.name }}
                </div>
                <div class="mt-1 line-clamp-2 text-xs text-muted-foreground">
                  {{ workflowSubtitle(workflow) }}
                </div>
              </div>
              <button
                type="button"
                class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                :aria-label="`Pin ${workflow.name}`"
                @click.stop="quickDrawerStore.togglePin(workflow.id)"
              >
                <Pin class="h-4 w-4" />
              </button>
            </div>

            <div
              v-if="!hasAnyWorkflowMatch"
              class="rounded-2xl border border-dashed border-border/60 px-4 py-6 text-center text-sm text-muted-foreground"
            >
              No workflows match this filter.
            </div>
          </div>
        </template>
      </div>

      <Transition
        enter-active-class="transition-all duration-300 ease-out"
        enter-from-class="translate-y-full opacity-0"
        enter-to-class="translate-y-0 opacity-100"
        leave-active-class="transition-all duration-200 ease-in"
        leave-from-class="translate-y-0 opacity-100"
        leave-to-class="translate-y-full opacity-0"
      >
        <div
          v-if="selectedWorkflow && isDetailPanelOpen"
          class="absolute inset-0 z-20 flex flex-col bg-card"
        >
          <div class="border-b border-border/60 px-5 py-4">
            <div class="flex items-center justify-between gap-3">
              <div class="flex min-w-0 items-center gap-3">
                <Button
                  variant="ghost"
                  size="icon"
                  class="h-10 w-10 shrink-0"
                  aria-label="Back to workflow list"
                  @click="quickDrawerStore.closeDetailPanel()"
                >
                  <ChevronLeft class="h-4 w-4" />
                </Button>
                <div class="min-w-0">
                  <div class="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                    Selected Workflow
                  </div>
                  <div class="truncate text-lg font-semibold text-foreground">
                    {{ selectedWorkflow.name }}
                  </div>
                  <button
                    type="button"
                    class="mt-1 inline-flex items-center gap-1 text-xs font-medium text-primary transition-colors hover:text-primary/80"
                    @click="goToSelectedWorkflow"
                  >
                    <span>Go to workflow</span>
                    <MoveRight class="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <div class="flex items-center gap-2">
                <button
                  type="button"
                  class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-border/60 text-muted-foreground transition-colors hover:border-primary/30 hover:text-primary"
                  :aria-label="selectedWorkflow.pinned ? `Unpin ${selectedWorkflow.name}` : `Pin ${selectedWorkflow.name}`"
                  @click="quickDrawerStore.togglePin(selectedWorkflow.id)"
                >
                  <Pin
                    class="h-4 w-4"
                    :class="selectedWorkflow.pinned ? 'fill-current text-primary' : ''"
                  />
                </button>
                <Button
                  variant="ghost"
                  size="icon"
                  class="h-10 w-10 shrink-0"
                  aria-label="Close quick workflows drawer"
                  @click="quickDrawerStore.closeDrawer()"
                >
                  <X class="h-4 w-4" />
                </Button>
              </div>
            </div>
            <p
              v-if="selectedWorkflow.description"
              class="mt-3 text-sm text-muted-foreground"
            >
              {{ selectedWorkflow.description }}
            </p>
          </div>

          <div class="flex-1 overflow-y-auto px-5 py-4">
            <div class="space-y-5">
              <section class="rounded-3xl border border-border/60 bg-background/80 p-4">
                <div class="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  Inputs
                </div>

                <div class="mt-4 space-y-3">
                  <template v-if="selectedWorkflow.inputFields.length > 0">
                    <div
                      v-for="field in selectedWorkflow.inputFields"
                      :key="field.key"
                      class="space-y-1.5"
                    >
                      <label
                        :for="`quick-drawer-input-${field.key}`"
                        class="block text-sm font-medium text-foreground"
                      >
                        {{ field.key }}
                      </label>
                      <Input
                        :id="`quick-drawer-input-${field.key}`"
                        :model-value="currentInputValues[field.key] ?? ''"
                        :placeholder="field.defaultValue || `Enter ${field.key}`"
                        @update:model-value="(value) => quickDrawerStore.updateInputValue(field.key, value)"
                      />
                    </div>
                  </template>
                  <div
                    v-else
                    class="rounded-2xl border border-dashed border-border/60 px-4 py-3 text-sm text-muted-foreground"
                  >
                    This workflow does not require any input fields.
                  </div>
                </div>

                <div class="mt-4 flex items-center gap-3">
                  <Button
                    v-if="!isRunning"
                    variant="gradient"
                    class="flex-1"
                    @click="quickDrawerStore.runSelectedWorkflow()"
                  >
                    <Play class="h-4 w-4" />
                    <span>Run Workflow</span>
                  </Button>
                  <Button
                    v-else
                    variant="destructive"
                    class="flex-1"
                    @click="quickDrawerStore.stopSelectedWorkflowExecution()"
                  >
                    <Square class="h-4 w-4" />
                    <span>Stop Workflow</span>
                  </Button>
                </div>
              </section>

              <section class="rounded-3xl border border-border/60 bg-background/80 p-4">
                <div class="flex items-center justify-between gap-3">
                  <div>
                    <div class="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      Progress & Result
                    </div>
                    <div
                      class="mt-2 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium"
                      :class="resultTone"
                    >
                      <Loader2
                        v-if="runState.status === 'running'"
                        class="h-3.5 w-3.5 animate-spin"
                      />
                      <CheckCircle2
                        v-else-if="runState.status === 'success'"
                        class="h-3.5 w-3.5"
                      />
                      <Clock3
                        v-else-if="runState.status === 'pending'"
                        class="h-3.5 w-3.5"
                      />
                      <AlertTriangle
                        v-else-if="runState.status === 'error'"
                        class="h-3.5 w-3.5"
                      />
                      <Workflow
                        v-else
                        class="h-3.5 w-3.5"
                      />
                      <span class="capitalize">{{ runState.status }}</span>
                    </div>
                  </div>

                  <div
                    v-if="runState.executionTimeMs !== null || runState.status === 'pending'"
                    class="text-right text-xs text-muted-foreground"
                  >
                    <div class="font-medium text-foreground">
                      {{ formatExecutionTime(runState.executionTimeMs) }}
                    </div>
                    <div v-if="runState.executionHistoryId">
                      History: {{ runState.executionHistoryId }}
                    </div>
                  </div>
                </div>

                <div
                  v-if="runState.status === 'idle'"
                  class="mt-4 rounded-2xl border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground"
                >
                  Choose a workflow and run it to see progress here.
                </div>

                <div
                  v-else
                  class="mt-4 space-y-4"
                >
                  <div
                    v-if="runState.errorMessage"
                    class="rounded-2xl border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm text-destructive"
                  >
                    {{ runState.errorMessage }}
                  </div>

                  <div
                    v-if="visibleNodeResults.length > 0"
                    class="space-y-2"
                  >
                    <div class="text-sm font-medium text-foreground">
                      Step Progress
                    </div>
                    <div class="space-y-2">
                      <div
                        v-for="nodeResult in visibleNodeResults"
                        :key="`${nodeResult.node_id}-${nodeResult.status}`"
                        class="rounded-2xl border border-border/60 bg-card/70 px-3 py-3"
                      >
                        <div class="flex items-center justify-between gap-3">
                          <div class="min-w-0">
                            <div class="truncate text-sm font-medium text-foreground">
                              {{ nodeResult.node_label }}
                            </div>
                            <div class="mt-0.5 text-xs text-muted-foreground">
                              {{ nodeResult.node_type }}
                            </div>
                          </div>
                          <div class="text-right">
                            <div
                              class="text-xs font-medium capitalize"
                              :class="{
                                'text-success': nodeResult.status === 'success',
                                'text-destructive': nodeResult.status === 'error',
                                'text-warning': nodeResult.status === 'pending',
                                'text-primary': nodeResult.status === 'running',
                                'text-muted-foreground': nodeResult.status === 'skipped',
                              }"
                            >
                              {{ nodeResult.status }}
                            </div>
                            <div class="text-[11px] text-muted-foreground">
                              {{ formatExecutionTime(nodeResult.execution_time_ms) }}
                            </div>
                          </div>
                        </div>
                        <div
                          v-if="nodeResult.error"
                          class="mt-2 rounded-xl bg-destructive/10 px-3 py-2 text-xs text-destructive"
                        >
                          {{ nodeResult.error }}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div
                    v-if="outputImages.length > 0"
                    class="space-y-2"
                  >
                    <div class="flex items-center gap-2 text-sm font-medium text-foreground">
                      <ImageIcon class="h-4 w-4 text-primary" />
                      Images
                    </div>
                    <div class="grid grid-cols-2 gap-3">
                      <button
                        v-for="imageSrc in outputImages"
                        :key="imageSrc"
                        type="button"
                        class="overflow-hidden rounded-2xl border border-border/60 bg-muted/20 transition-colors hover:border-primary/40"
                        @click="selectedImageSrc = imageSrc"
                      >
                        <img
                          :src="imageSrc"
                          alt="Workflow output image"
                          class="h-32 w-full object-cover"
                        >
                      </button>
                    </div>
                  </div>

                  <div
                    v-if="runState.outputs"
                    class="space-y-2"
                  >
                    <div class="flex items-center justify-between gap-3">
                      <div class="text-sm font-medium text-foreground">
                        Final Output
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        @click="copyFinalOutput"
                      >
                        <Copy class="h-4 w-4" />
                        Copy
                      </Button>
                    </div>
                    <pre class="max-h-64 overflow-auto rounded-2xl border border-border/60 bg-slate-950 px-4 py-3 text-xs text-slate-100">{{ formatJson(runState.outputs) }}</pre>
                  </div>
                </div>
              </section>
            </div>
          </div>
        </div>
      </Transition>

      <ImageLightbox
        :src="selectedImageSrc"
        alt="Quick drawer output image"
        @close="selectedImageSrc = null"
      />
    </div>
  </aside>
</template>
