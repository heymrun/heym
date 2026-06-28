<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import DOMPurify from "dompurify";
import {
  AlertTriangle,
  ChevronDown,
  Eye,
  Loader2,
  Pencil,
  Save,
  Sparkles,
  X,
} from "lucide-vue-next";
import { marked } from "marked";
import { isAxiosError } from "axios";

import { preserveExplicitOrderedListNumbers } from "@/lib/markdown";
import { cn } from "@/lib/utils";
import {
  aiApi,
  credentialsApi,
  workflowApi,
  type AnalysisNoteEditor,
  type AnalysisNoteResponse,
} from "@/services/api";
import type { CredentialListItem, LLMModel } from "@/types/credential";
import { useWorkflowStore } from "@/stores/workflow";

interface AnalysisWorkflowPayload {
  id?: string;
  name?: string;
  description?: string | null;
  nodes: unknown[];
  edges: unknown[];
  error_workflow_id?: string | null;
  minutes_saved_per_run?: number | null;
}

const props = defineProps<{
  workflowId: string;
  currentWorkflow: AnalysisWorkflowPayload | null;
  runWorkflow?: () => Promise<Record<string, unknown> | undefined>;
}>();

const workflowStore = useWorkflowStore();

const loading = ref(false);
const savedContent = ref("");
const draft = ref("");
const revision = ref(0);
const updatedBy = ref<AnalysisNoteEditor | null>(null);
const updatedAt = ref<string | null>(null);
const mode = ref<"edit" | "preview">("edit");
const saving = ref(false);

const credentials = ref<CredentialListItem[]>([]);
const credentialId = ref("");
const models = ref<LLMModel[]>([]);
const model = ref("");

const analyzing = ref(false);
const running = ref(false);
const reanalyzePreview = ref<string | null>(null);
const conflict = ref<AnalysisNoteResponse | null>(null);
const errorMsg = ref<string | null>(null);
let abort: AbortController | null = null;

const dirty = computed(() => draft.value !== savedContent.value);
const hasContent = computed(() => savedContent.value.trim() !== "");
// While a reanalyze preview awaits Accept/Discard it owns the body, so the
// edit/preview/save controls are disabled until the user resolves it.
const pendingPreview = computed(() => reanalyzePreview.value !== null);
const isUnsavedWorkflow = computed(() => !props.workflowId);
const canAnalyze = computed(
  () =>
    !!credentialId.value &&
    !!model.value &&
    !isUnsavedWorkflow.value &&
    !analyzing.value,
);
const renderedHtml = computed(() => renderHtml(draft.value));
const reanalyzeHtml = computed(() => renderHtml(reanalyzePreview.value ?? ""));

function renderHtml(content: string): string {
  if (!content.trim()) return "";
  const prepared = preserveExplicitOrderedListNumbers(content);
  const html = marked(prepared, { breaks: true, gfm: true }) as string;
  return DOMPurify.sanitize(html);
}

function formatWhen(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString();
}

async function loadNote(): Promise<void> {
  conflict.value = null;
  errorMsg.value = null;
  if (!props.workflowId) {
    savedContent.value = "";
    draft.value = "";
    revision.value = 0;
    updatedBy.value = null;
    updatedAt.value = null;
    return;
  }
  loading.value = true;
  try {
    const note = await workflowApi.getAnalysisNote(props.workflowId);
    savedContent.value = note.content;
    draft.value = note.content;
    revision.value = note.revision;
    updatedBy.value = note.updated_by;
    updatedAt.value = note.updated_at;
    mode.value = note.content.trim() ? "preview" : "edit";
  } catch {
    errorMsg.value = "Failed to load the analysis note.";
  } finally {
    loading.value = false;
  }
}

async function loadCredentials(): Promise<void> {
  try {
    credentials.value = await credentialsApi.listLLM();
    if (credentials.value.length > 0) {
      credentialId.value = credentials.value[0].id;
      await loadModels();
    }
  } catch {
    credentials.value = [];
  }
}

async function loadModels(): Promise<void> {
  model.value = "";
  models.value = [];
  if (!credentialId.value) return;
  models.value = await credentialsApi.getModels(credentialId.value);
  if (models.value.length > 0) {
    model.value = models.value[models.value.length - 1].id;
  }
}

const EXECUTION_CANCELLED = "Execution cancelled";

async function startAnalyze(): Promise<void> {
  if (!canAnalyze.value) return;
  errorMsg.value = null;
  abort?.abort();
  abort = new AbortController();
  analyzing.value = true;

  const reanalyze = hasContent.value;
  if (reanalyze) {
    reanalyzePreview.value = "";
  } else {
    draft.value = "";
    mode.value = "edit";
  }

  // Run the workflow first so the analysis can reason over real results.
  let executionLog: Record<string, unknown> | undefined;
  if (props.runWorkflow) {
    running.value = true;
    try {
      executionLog = await props.runWorkflow();
    } catch (err) {
      if (err instanceof Error && err.message === EXECUTION_CANCELLED) {
        analyzing.value = false;
        if (reanalyze) {
          reanalyzePreview.value = null;
        } else {
          draft.value = savedContent.value;
        }
        return;
      }
      // Run failures are non-fatal; analyze the static workflow instead.
    } finally {
      running.value = false;
    }
  }

  if (!analyzing.value) return;

  aiApi.analyzeWorkflowStream(
    {
      credentialId: credentialId.value,
      model: model.value,
      currentWorkflow: props.currentWorkflow ?? undefined,
      executionLog: executionLog ?? null,
    },
    (text) => {
      if (reanalyze) {
        reanalyzePreview.value = (reanalyzePreview.value ?? "") + text;
      } else {
        draft.value += text;
      }
    },
    () => {
      analyzing.value = false;
      // A fresh (non-reanalyze) report finishes straight into preview mode.
      if (!reanalyze) mode.value = "preview";
    },
    (err) => {
      analyzing.value = false;
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      errorMsg.value = err.message || "Analysis failed.";
      if (reanalyze && !reanalyzePreview.value) reanalyzePreview.value = null;
    },
    abort.signal,
  );
}

function acceptReanalyze(): void {
  if (reanalyzePreview.value !== null) {
    draft.value = reanalyzePreview.value;
    mode.value = "preview";
  }
  reanalyzePreview.value = null;
}

function discardReanalyze(): void {
  reanalyzePreview.value = null;
}

async function save(baseRevision?: number): Promise<void> {
  if (!props.workflowId || saving.value) return;
  saving.value = true;
  errorMsg.value = null;
  try {
    const note = await workflowApi.saveAnalysisNote(
      props.workflowId,
      draft.value,
      baseRevision ?? revision.value,
    );
    savedContent.value = draft.value;
    revision.value = note.revision;
    updatedBy.value = note.updated_by;
    updatedAt.value = note.updated_at;
    conflict.value = null;
    void workflowStore.refreshAnalysisNoteEmpty();
  } catch (err) {
    if (isAxiosError(err) && err.response?.status === 409) {
      conflict.value = err.response.data as AnalysisNoteResponse;
    } else {
      errorMsg.value = "Failed to save.";
    }
  } finally {
    saving.value = false;
  }
}

function reloadFromServer(): void {
  if (!conflict.value) return;
  savedContent.value = conflict.value.content;
  draft.value = conflict.value.content;
  revision.value = conflict.value.revision;
  updatedBy.value = conflict.value.updated_by;
  updatedAt.value = conflict.value.updated_at;
  conflict.value = null;
}

function overwrite(): void {
  if (!conflict.value) return;
  void save(conflict.value.revision);
}

function close(): void {
  abort?.abort();
  workflowStore.analysisPanelOpen = false;
}

onMounted(() => {
  void loadCredentials();
  void loadNote();
});

watch(
  () => props.workflowId,
  () => {
    void loadNote();
  },
);

onBeforeUnmount(() => {
  abort?.abort();
});
</script>

<template>
  <aside
    :class="
      cn(
        'analysis-panel w-96 max-w-full md:w-[460px] lg:w-[540px] border-r border-border/40 flex flex-col h-full bg-background overflow-hidden',
      )
    "
  >
    <div class="flex items-center justify-between px-4 py-3 border-b border-border/40 shrink-0">
      <h2 class="font-semibold text-sm text-foreground flex items-center gap-2">
        <Sparkles class="w-4 h-4 text-primary" />
        Workflow Analysis
      </h2>
      <button
        class="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
        title="Close"
        @click="close"
      >
        <X class="w-4 h-4" />
      </button>
    </div>

    <div
      v-if="isUnsavedWorkflow"
      class="p-4 text-sm text-muted-foreground"
    >
      Save the workflow first to analyze it.
    </div>

    <template v-else>
      <div class="px-4 py-2 border-b border-border/40 space-y-2 shrink-0">
        <div class="flex items-center gap-2">
          <div class="relative flex-1 min-w-0">
            <select
              v-model="credentialId"
              class="h-9 w-full min-w-0 truncate rounded-md border border-border bg-background pl-2.5 pr-9 text-sm appearance-none cursor-pointer"
              :disabled="analyzing"
              @change="loadModels"
            >
              <option
                v-if="credentials.length === 0"
                value=""
              >
                No LLM credential
              </option>
              <option
                v-for="c in credentials"
                :key="c.id"
                :value="c.id"
              >
                {{ c.name }}
              </option>
            </select>
            <ChevronDown
              class="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 shrink-0 text-muted-foreground"
            />
          </div>
          <div class="relative flex-1 min-w-0">
            <select
              v-model="model"
              class="h-9 w-full min-w-0 truncate rounded-md border border-border bg-background pl-2.5 pr-9 text-sm appearance-none cursor-pointer disabled:opacity-50"
              :disabled="analyzing || models.length === 0"
            >
              <option
                v-for="m in models"
                :key="m.id"
                :value="m.id"
              >
                {{ m.name }}
              </option>
            </select>
            <ChevronDown
              class="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 shrink-0 text-muted-foreground"
            />
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button
            class="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
            :disabled="!canAnalyze"
            :title="
              credentials.length === 0 ? 'Add an LLM credential to analyze' : 'Run AI analysis'
            "
            @click="startAnalyze"
          >
            <Loader2
              v-if="analyzing"
              class="h-4 w-4 animate-spin"
            />
            <Sparkles
              v-else
              class="h-4 w-4"
            />
            {{ hasContent ? "Reanalyze" : "Analyze my workflow" }}
          </button>
          <div class="ml-auto flex items-center gap-1">
            <button
              class="inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-muted disabled:opacity-50"
              :class="mode === 'edit' ? 'bg-muted text-foreground' : 'text-muted-foreground'"
              :disabled="pendingPreview"
              title="Edit"
              @click="mode = 'edit'"
            >
              <Pencil class="h-4 w-4" />
            </button>
            <button
              class="inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-muted disabled:opacity-50"
              :class="mode === 'preview' ? 'bg-muted text-foreground' : 'text-muted-foreground'"
              :disabled="pendingPreview"
              title="Preview"
              @click="mode = 'preview'"
            >
              <Eye class="h-4 w-4" />
            </button>
            <button
              class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm font-medium hover:bg-muted disabled:opacity-50"
              :disabled="!dirty || saving || pendingPreview"
              title="Save"
              @click="save()"
            >
              <Loader2
                v-if="saving"
                class="h-4 w-4 animate-spin"
              />
              <Save
                v-else
                class="h-4 w-4"
              />
              Save
            </button>
          </div>
        </div>
        <p
          v-if="updatedBy"
          class="text-[11px] text-muted-foreground"
        >
          Last edited by {{ updatedBy.name }}
          <span v-if="updatedAt">· {{ formatWhen(updatedAt) }}</span>
        </p>
      </div>

      <div
        v-if="conflict"
        class="mx-4 mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs"
      >
        <p class="flex items-center gap-1.5 font-medium text-amber-700 dark:text-amber-400">
          <AlertTriangle class="w-3.5 h-3.5" />
          {{ conflict.updated_by ? conflict.updated_by.name : "Someone" }} edited this since you
          opened it.
        </p>
        <div class="mt-2 flex gap-2">
          <button
            class="rounded-md px-2 py-1 border border-border hover:bg-muted"
            @click="reloadFromServer"
          >
            Reload (discard mine)
          </button>
          <button
            class="rounded-md px-2 py-1 bg-amber-600 text-white hover:opacity-90"
            @click="overwrite"
          >
            Overwrite
          </button>
        </div>
      </div>

      <p
        v-if="errorMsg"
        class="mx-4 mt-3 text-xs text-destructive"
      >
        {{ errorMsg }}
      </p>

      <!-- eslint-disable vue/no-v-html -- Sanitized via DOMPurify in renderHtml -->
      <div class="flex-1 min-h-0 overflow-auto p-4">
        <div
          v-if="loading"
          class="text-sm text-muted-foreground"
        >
          Loading…
        </div>

        <div
          v-else-if="reanalyzePreview !== null"
          class="space-y-3"
        >
          <p class="text-xs font-medium text-muted-foreground">
            New analysis (preview)
          </p>
          <div
            class="prose prose-sm dark:prose-invert max-w-none rounded-md border border-border p-3 prose-headings:mt-8 prose-headings:mb-4 prose-p:my-4 prose-ul:my-4 prose-ol:my-4 prose-li:my-2.5 prose-li:leading-relaxed"
            v-html="
              reanalyzeHtml ||
                (running ? '<em>Running workflow…</em>' : '<em>Generating…</em>')
            "
          />
          <div class="flex gap-2">
            <button
              class="text-xs rounded-md px-2.5 py-1.5 bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
              :disabled="analyzing"
              @click="acceptReanalyze"
            >
              Accept
            </button>
            <button
              class="text-xs rounded-md px-2.5 py-1.5 border border-border hover:bg-muted"
              @click="discardReanalyze"
            >
              Discard
            </button>
          </div>
        </div>

        <textarea
          v-else-if="mode === 'edit'"
          v-model="draft"
          class="w-full h-full min-h-[300px] resize-none rounded-md border border-border bg-background p-3 text-sm font-mono leading-relaxed focus:outline-none focus:ring-1 focus:ring-primary"
          placeholder="Describe what this workflow does, its purpose, and improvement areas — or click Analyze to generate a draft."
        />

        <div
          v-else
          class="prose prose-sm dark:prose-invert max-w-none prose-headings:mt-8 prose-headings:mb-4 prose-p:my-4 prose-ul:my-4 prose-ol:my-4 prose-li:my-2.5 prose-li:leading-relaxed"
          v-html="renderedHtml || '<em>No content yet.</em>'"
        />
      </div>
      <!-- eslint-enable vue/no-v-html -->
    </template>
  </aside>
</template>
