<script setup lang="ts">
import { ChevronDown } from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { onClickOutside } from "@vueuse/core";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import { credentialsApi, evalsApi } from "@/services/api";
import type { CredentialListItem } from "@/types/credential";
import type { LLMModel } from "@/types/credential";
import type { EvalRun, EvalSuite, ReasoningEffort } from "@/types/evals";

interface Props {
  suite: EvalSuite;
  currentRun?: EvalRun | null;
  isRunInProgress?: boolean;
  showEditButton?: boolean;
  initialTemperature?: number;
  initialReasoningEffort?: ReasoningEffort;
}

const props = withDefaults(defineProps<Props>(), {
  currentRun: null,
  isRunInProgress: false,
  showEditButton: false,
  initialTemperature: undefined,
  initialReasoningEffort: undefined,
});

const isViewingHistory = computed(
  () =>
    !!props.currentRun &&
    (props.currentRun.status === "completed" || props.currentRun.status === "failed"),
);

const displaySystemPrompt = computed(() =>
  isViewingHistory.value && props.currentRun
    ? (props.currentRun.system_prompt_snapshot ?? "")
    : systemPrompt.value,
);

const displayTemperature = computed(() =>
  isViewingHistory.value && props.currentRun
    ? (props.currentRun.temperature ?? 0.7)
    : temperature.value,
);

const displayReasoningEffort = computed((): ReasoningEffort => {
  if (
    isViewingHistory.value &&
    props.currentRun?.reasoning_effort &&
    ["low", "medium", "high"].includes(props.currentRun.reasoning_effort)
  ) {
    return props.currentRun.reasoning_effort as ReasoningEffort;
  }
  return reasoningEffort.value;
});

const emit = defineEmits<{
  (e: "suite-updated", suite: EvalSuite): void;
  (e: "run-completed", run: import("@/types/evals").EvalRun): void;
  (e: "credential-changed", id: string): void;
}>();

const credentials = ref<CredentialListItem[]>([]);
const models = ref<LLMModel[]>([]);
const selectedCredentialId = ref<string>("");
const selectedModelIds = ref<Set<string>>(new Set());
const scoringMethod = ref<string>("exact_match");
const judgeCredentialId = ref<string>("");
const judgeModelId = ref<string>("");
const judgeModels = ref<LLMModel[]>([]);
const temperature = ref(0.7);
const reasoningEffort = ref<ReasoningEffort>("medium");
const runsPerTest = ref(1);

const REASONING_EFFORT_OPTIONS: { value: ReasoningEffort; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];
let pollIntervalId: ReturnType<typeof setInterval> | null = null;

onMounted(() => {
  const unsub = onDismissOverlays(() => {
    optimizeDialogOpen.value = false;
  });
  onUnmounted(() => unsub());
  if (props.initialTemperature != null) {
    temperature.value = props.initialTemperature;
  }
  if (props.initialReasoningEffort != null) {
    reasoningEffort.value = props.initialReasoningEffort;
  }
});

onUnmounted(() => {
  if (pollIntervalId) clearInterval(pollIntervalId);
});
const systemPrompt = ref("");
const suiteName = ref("");
const optimizeDialogOpen = ref(false);
const optimizedPrompt = ref("");
const selectedOptimizeModelId = ref<string>("");
const isOptimizing = ref(false);
const isRunning = ref(false);
const showModelsDropdown = ref(false);
const modelsDropdownRef = ref<HTMLElement | null>(null);
onClickOutside(modelsDropdownRef, () => {
  showModelsDropdown.value = false;
});

const SCORING_OPTIONS = [
  { value: "exact_match", label: "Exact Match" },
  { value: "contains", label: "Contains" },
  { value: "llm_judge", label: "LLM-as-Judge" },
];

let savePromptTimeout: ReturnType<typeof setTimeout> | null = null;
let saveNameTimeout: ReturnType<typeof setTimeout> | null = null;

function debouncedSavePrompt(): void {
  if (savePromptTimeout) clearTimeout(savePromptTimeout);
  savePromptTimeout = setTimeout(async () => {
    savePromptTimeout = null;
    try {
      const updated = await evalsApi.updateSuite(props.suite.id, {
        system_prompt: systemPrompt.value,
      });
      emit("suite-updated", updated);
    } catch (e) {
      console.error("Failed to save prompt:", e);
    }
  }, 1000);
}

function debouncedSaveName(): void {
  if (saveNameTimeout) clearTimeout(saveNameTimeout);
  saveNameTimeout = setTimeout(async () => {
    saveNameTimeout = null;
    const trimmed = suiteName.value.trim();
    if (!trimmed || trimmed === props.suite.name) return;
    try {
      const updated = await evalsApi.updateSuite(props.suite.id, {
        name: trimmed,
      });
      emit("suite-updated", updated);
    } catch (e) {
      console.error("Failed to save suite name:", e);
    }
  }, 500);
}

watch(
  () => props.suite.system_prompt,
  (v) => {
    systemPrompt.value = v ?? "";
  },
  { immediate: true },
);

watch(
  () => props.suite.name,
  (v) => {
    suiteName.value = v ?? "";
  },
  { immediate: true },
);

watch(systemPrompt, () => {
  debouncedSavePrompt();
});

watch(suiteName, () => {
  debouncedSaveName();
});

async function loadCredentials(): Promise<void> {
  try {
    credentials.value = await credentialsApi.listLLM();
    if (credentials.value.length > 0 && !selectedCredentialId.value) {
      selectedCredentialId.value = credentials.value[0].id;
    }
  } catch {
    credentials.value = [];
  }
}

async function loadModels(): Promise<void> {
  if (!selectedCredentialId.value) {
    models.value = [];
    return;
  }
  try {
    models.value = await credentialsApi.getModels(selectedCredentialId.value);
  } catch {
    models.value = [];
  }
}

watch(
  selectedCredentialId,
  (id) => {
    if (id) emit("credential-changed", id);
    loadModels();
    selectedModelIds.value = new Set();
  },
  { immediate: true },
);

watch(
  judgeCredentialId,
  async (id) => {
    if (!id) {
      judgeModels.value = [];
      judgeModelId.value = "";
      return;
    }
    try {
      judgeModels.value = await credentialsApi.getModels(id);
      judgeModelId.value =
        judgeModels.value.length > 0 ? judgeModels.value[0].id : "";
    } catch {
      judgeModels.value = [];
      judgeModelId.value = "";
    }
  },
  { immediate: true },
);

watch(scoringMethod, () => {
  if (scoringMethod.value !== "llm_judge") {
    judgeCredentialId.value = "";
    judgeModelId.value = "";
  }
});

watch(
  () => props.suite.id,
  () => {
    loadCredentials();
  },
  { immediate: true },
);

function toggleModel(id: string): void {
  const next = new Set(selectedModelIds.value);
  if (next.has(id)) {
    next.delete(id);
  } else {
    next.add(id);
  }
  selectedModelIds.value = next;
}

function openOptimizeDialog(): void {
  optimizeDialogOpen.value = true;
  pushOverlayState();
  optimizedPrompt.value = "";
  selectedOptimizeModelId.value =
    models.value.length > 0 ? models.value[0].id : "";
}

async function runOptimize(): Promise<void> {
  if (!selectedCredentialId.value || !selectedOptimizeModelId.value) return;
  const model = models.value.find((m) => m.id === selectedOptimizeModelId.value);
  if (!model) return;
  isOptimizing.value = true;
  try {
    const res = await evalsApi.optimizePrompt(props.suite.id, {
      credential_id: selectedCredentialId.value,
      model: model.id,
      system_prompt: systemPrompt.value,
    });
    optimizedPrompt.value = res.optimized_prompt;
  } catch (e) {
    console.error("Optimize failed:", e);
    optimizedPrompt.value = systemPrompt.value;
  } finally {
    isOptimizing.value = false;
  }
}

function applyOptimizedPrompt(): void {
  systemPrompt.value = optimizedPrompt.value;
  optimizeDialogOpen.value = false;
}

async function handleRunEvals(): Promise<void> {
  if (
    !selectedCredentialId.value ||
    selectedModelIds.value.size === 0
  ) {
    return;
  }
  // Judge is optional for llm_judge; when provided, uses separate judge for unbiased scoring
  isRunning.value = true;
  try {
    const run = await evalsApi.runEvals(props.suite.id, {
      credential_id: selectedCredentialId.value,
      models: Array.from(selectedModelIds.value),
      scoring_method: scoringMethod.value,
      temperature: temperature.value,
      reasoning_effort: reasoningEffort.value,
      runs_per_test: runsPerTest.value,
      judge_credential_id:
        scoringMethod.value === "llm_judge" && judgeCredentialId.value && judgeModelId.value
          ? judgeCredentialId.value
          : null,
      judge_model:
        scoringMethod.value === "llm_judge" && judgeCredentialId.value && judgeModelId.value
          ? judgeModelId.value
          : null,
    });
    emit("run-completed", run);
    if (run.status !== "completed") {
      pollIntervalId = setInterval(async () => {
        try {
          const updated = await evalsApi.getRun(run.id);
          emit("run-completed", updated);
          if (updated.status === "completed") {
            if (pollIntervalId) clearInterval(pollIntervalId);
            pollIntervalId = null;
          }
        } catch {
          if (pollIntervalId) clearInterval(pollIntervalId);
          pollIntervalId = null;
        }
      }, 1500);
    }
  } catch (e) {
    console.error("Run failed:", e);
  } finally {
    isRunning.value = false;
  }
}
</script>

<template>
  <div class="h-full flex flex-col overflow-hidden border-r border-border/40">
    <div class="p-4 border-b border-border/40 shrink-0">
      <Label class="text-xs font-medium text-muted-foreground mb-2 block">
        Suite name
      </Label>
      <Input
        v-model="suiteName"
        placeholder="Enter suite name..."
        class="font-medium"
      />
    </div>
    <div class="flex-1 min-h-0 overflow-y-auto pb-4">
      <div class="p-4 border-b border-border/40">
        <Label class="text-xs font-medium text-muted-foreground mb-2 block">
          System Prompt
        </Label>
        <Textarea
          :model-value="displaySystemPrompt"
          class="min-h-[120px] font-mono text-sm"
          placeholder="Enter your system prompt..."
          :rows="6"
          :disabled="isViewingHistory"
          @update:model-value="(v) => { if (!isViewingHistory) systemPrompt = v }"
        />
        <Button
          variant="outline"
          size="sm"
          class="mt-2 w-full"
          :disabled="isViewingHistory || !selectedCredentialId"
          @click="openOptimizeDialog"
        >
          Optimize Prompt
        </Button>
      </div>
      <div class="p-4 pb-2 space-y-4">
        <div>
          <Label class="text-xs font-medium text-muted-foreground mb-2 block">
            Credential
          </Label>
          <Select
            v-model="selectedCredentialId"
            :options="credentials.map((c) => ({ value: c.id, label: c.name }))"
            placeholder="Select credential"
          />
        </div>
        <div
          ref="modelsDropdownRef"
          class="relative"
        >
          <Label class="text-xs font-medium text-muted-foreground mb-2 block">
            Models
          </Label>
          <button
            type="button"
            class="relative w-full h-10 min-h-[44px] rounded-xl border border-border bg-background px-3 pr-10 text-sm text-left flex items-center focus:outline-none focus:ring-2 focus:ring-primary/20"
            @click="showModelsDropdown = !showModelsDropdown"
          >
            <span class="truncate text-muted-foreground">
              {{ selectedModelIds.size > 0
                ? `${selectedModelIds.size} selected`
                : "Select models" }}
            </span>
            <ChevronDown class="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none shrink-0" />
          </button>
          <div
            v-if="showModelsDropdown"
            class="absolute top-full left-0 right-0 mt-1 rounded-xl border border-border bg-card shadow-lg z-10 max-h-48 overflow-y-auto py-2"
          >
            <label
              v-for="m in models"
              :key="m.id"
              class="flex items-center gap-2 px-3 py-2 hover:bg-muted/50 cursor-pointer"
            >
              <input
                type="checkbox"
                :checked="selectedModelIds.has(m.id)"
                @change="toggleModel(m.id)"
              >
              <span class="text-sm">{{ m.name }}</span>
            </label>
          </div>
        </div>
        <div>
          <Label class="text-xs font-medium text-muted-foreground mb-2 block">
            Scoring Method
          </Label>
          <Select
            v-model="scoringMethod"
            :options="SCORING_OPTIONS.map((o) => ({ value: o.value, label: o.label }))"
          />
        </div>
        <template v-if="scoringMethod === 'llm_judge'">
          <div>
            <Label class="text-xs font-medium text-muted-foreground mb-2 block">
              Judge Credential (optional)
            </Label>
            <Select
              v-model="judgeCredentialId"
              :options="credentials.map((c) => ({ value: c.id, label: c.name }))"
              placeholder="Separate judge for unbiased scoring"
            />
          </div>
          <div>
            <Label class="text-xs font-medium text-muted-foreground mb-2 block">
              Judge Model (optional)
            </Label>
            <Select
              v-model="judgeModelId"
              :options="judgeModels.map((m) => ({ value: m.id, label: m.name }))"
              placeholder="Separate judge for unbiased scoring"
            />
          </div>
        </template>
        <div>
          <Label class="text-xs font-medium text-muted-foreground mb-2 block">
            Temperature: {{ displayTemperature.toFixed(1) }}
          </Label>
          <input
            :value="displayTemperature"
            type="range"
            min="0"
            max="2"
            step="0.1"
            class="w-full h-6"
            :disabled="isViewingHistory"
            @input="(e) => { if (!isViewingHistory) temperature = parseFloat((e.target as HTMLInputElement).value) }"
          >
          <p class="text-xs text-muted-foreground mt-1">
            For non-reasoning models
          </p>
        </div>
        <div>
          <Label class="text-xs font-medium text-muted-foreground mb-2 block">
            Reasoning Effort
          </Label>
          <Select
            :model-value="displayReasoningEffort"
            :options="REASONING_EFFORT_OPTIONS.map((o) => ({ value: o.value, label: o.label }))"
            :disabled="isViewingHistory"
            @update:model-value="(v) => { if (!isViewingHistory) reasoningEffort = v as ReasoningEffort }"
          />
          <p class="text-xs text-muted-foreground mt-1">
            For reasoning models (GPT-5, o1, o3)
          </p>
        </div>
        <div>
          <Label class="text-xs font-medium text-muted-foreground mb-2 block">
            Runs per test
          </Label>
          <Input
            :model-value="String(runsPerTest)"
            type="number"
            min="1"
            max="20"
            class="w-full"
            @update:model-value="(v) => { const n = parseInt(v, 10); runsPerTest = isNaN(n) ? 1 : Math.max(1, Math.min(20, n)); }"
          />
        </div>
      </div>
    </div>
    <div class="shrink-0 border-t border-border/40">
      <Button
        class="w-full"
        variant="gradient"
        :loading="isRunning"
        :disabled="props.isRunInProgress || !selectedCredentialId || selectedModelIds.size === 0 || (props.suite.test_cases?.length ?? 0) === 0"
        @click="handleRunEvals"
      >
        {{ showEditButton ? "Re-Run Evals" : "Run Evals" }}
      </Button>
    </div>
  </div>

  <Dialog
    :open="optimizeDialogOpen"
    title="Optimize Prompt"
    size="2xl"
    @close="optimizeDialogOpen = false"
  >
    <div class="space-y-4">
      <div>
        <Label class="text-xs font-medium text-muted-foreground mb-2 block">
          Model
        </Label>
        <Select
          v-model="selectedOptimizeModelId"
          :options="models.map((m) => ({ value: m.id, label: m.name }))"
          placeholder="Select model"
        />
      </div>
      <Button
        variant="outline"
        class="w-full"
        :loading="isOptimizing"
        :disabled="!selectedOptimizeModelId"
        @click="runOptimize"
      >
        Optimize
      </Button>
      <div v-if="optimizedPrompt">
        <Label class="text-xs font-medium text-muted-foreground mb-2 block">
          Optimized Prompt
        </Label>
        <Textarea
          v-model="optimizedPrompt"
          class="min-h-[200px] font-mono text-sm"
          :rows="12"
        />
      </div>
      <div class="flex gap-2 justify-end">
        <Button
          variant="outline"
          @click="optimizeDialogOpen = false"
        >
          Cancel
        </Button>
        <Button
          :disabled="!optimizedPrompt"
          @click="applyOptimizedPrompt"
        >
          Apply
        </Button>
      </div>
    </div>
  </Dialog>
</template>
