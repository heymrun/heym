<script setup lang="ts">
import { Loader2, Play, Sparkles } from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import {
  apiErrorText,
  formatRunTime,
  inputText,
  parseInputValue,
} from "@/components/Evals/AgentSuite/agentSuiteFormat";
import AgentSuiteRunCount from "@/components/Evals/AgentSuite/AgentSuiteRunCount.vue";
import Button from "@/components/ui/Button.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { useAiDefaults } from "@/composables/useAiDefaults";
import { credentialsApi, evalsApi } from "@/services/api";
import type { CredentialListItem, LLMModel } from "@/types/credential";
import type { AgentSuiteRun, AgentSuiteRunInputs } from "@/types/evals";

interface Props {
  suiteId: string;
  workflowId: string;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "run-changed", run: AgentSuiteRun | null): void;
}>();

const MAX_RUNS = 20;

const inputsInfo = ref<AgentSuiteRunInputs | null>(null);
const values = ref<Record<string, string>>({});
const count = ref(3);
const generate = ref(false);
const credentials = ref<CredentialListItem[]>([]);
const credentialId = ref("");
const models = ref<LLMModel[]>([]);
const model = ref("");
const activeRun = ref<AgentSuiteRun | null>(null);
const starting = ref(false);
const error = ref<string | null>(null);
const aiDefaults = useAiDefaults();
let pollTimer: ReturnType<typeof setInterval> | null = null;

const fieldKeys = computed((): string[] => {
  const info = inputsInfo.value;
  return info?.fields.length ? info.fields : Object.keys(info?.previous_inputs ?? {});
});

const running = computed((): boolean => activeRun.value?.status === "running");
const progressText = computed((): string => {
  const run = activeRun.value;
  if (!run || run.status !== "running") return "";
  if (run.generate_inputs && run.results.length === 0 && run.inputs.length <= 1) {
    return "Writing inputs...";
  }
  return `Running ${Math.min(run.results.length + 1, run.requested_count)} of ${run.requested_count}...`;
});

const canRun = computed((): boolean =>
  !running.value && (!generate.value || (Boolean(credentialId.value) && Boolean(model.value))));

function stopPolling(): void {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

function setRun(run: AgentSuiteRun | null): void {
  activeRun.value = run;
  emit("run-changed", run);
  if (run?.status === "running") {
    if (!pollTimer) pollTimer = setInterval(() => void poll(), 2000);
  } else {
    stopPolling();
  }
}

async function poll(): Promise<void> {
  if (!activeRun.value) return;
  try {
    setRun(await evalsApi.getAgentSuiteRun(activeRun.value.id));
  } catch (e: unknown) {
    error.value = apiErrorText(e, "Lost track of the run.");
    stopPolling();
  }
}

async function startRun(): Promise<void> {
  starting.value = true;
  error.value = null;
  try {
    const inputs = Object.fromEntries(
      fieldKeys.value.map((key) => [
        key,
        parseInputValue(inputsInfo.value?.previous_inputs?.[key], values.value[key] ?? ""),
      ]),
    );
    setRun(
      await evalsApi.startAgentSuiteRun(props.suiteId, {
        count: count.value,
        inputs,
        generate_inputs: generate.value,
        credential_id: generate.value ? credentialId.value : null,
        model: generate.value ? model.value : null,
      }),
    );
  } catch (e: unknown) {
    error.value = apiErrorText(e, "Could not start the run.");
  } finally {
    starting.value = false;
  }
}

watch(credentialId, async (id) => {
  models.value = [];
  model.value = "";
  if (!id) return;
  try {
    models.value = await credentialsApi.getModels(id);
    model.value = aiDefaults.resolveModel(id, models.value, {}) ?? models.value[0]?.id ?? "";
  } catch {
    models.value = [];
  }
});

onMounted(async () => {
  try {
    const [info, latest] = await Promise.all([
      evalsApi.getAgentSuiteRunInputs(props.suiteId),
      evalsApi.getLatestAgentSuiteRun(props.suiteId),
    ]);
    inputsInfo.value = info;
    values.value = Object.fromEntries(
      fieldKeys.value.map((key) => [key, inputText(info.previous_inputs?.[key])]),
    );
    setRun(latest);
  } catch (e: unknown) {
    error.value = apiErrorText(e, "Could not load the run settings.");
  }
  try {
    // A Model Router picks its own model per request, which suits writing inputs too.
    credentials.value = await credentialsApi.listLLM();
    credentialId.value = aiDefaults.resolveCredentialId(credentials.value, {}) ?? "";
  } catch {
    credentials.value = [];
  }
});

onUnmounted(stopPolling);
</script>

<template>
  <div class="rounded-xl border border-border/60 bg-card p-4">
    <div class="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div class="min-w-0">
        <h3 class="text-sm font-medium text-foreground">
          Run the workflow
        </h3>
        <p class="mt-0.5 text-xs text-muted-foreground">
          Runs the whole workflow. Disable the nodes you want to skip first.
          <RouterLink
            :to="{ name: 'editor', params: { id: workflowId } }"
            target="_blank"
            class="font-medium text-primary hover:underline dark:text-brand-primary-soft"
            data-testid="agent-suite-run-go-to-workflow"
          >
            Go to workflow
          </RouterLink>
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <span
          v-if="running"
          class="flex items-center gap-1.5 text-xs text-muted-foreground"
          data-testid="agent-suite-run-progress"
        >
          <Loader2 class="h-3.5 w-3.5 animate-spin" />
          {{ progressText }}
        </span>
        <div class="flex items-center gap-2 text-sm text-muted-foreground">
          Runs
          <AgentSuiteRunCount
            v-model="count"
            :max="MAX_RUNS"
          />
        </div>
        <button
          type="button"
          role="switch"
          :aria-checked="generate"
          class="flex min-h-[44px] items-center gap-2 text-sm text-foreground"
          data-testid="agent-suite-generate-toggle"
          @click="generate = !generate"
        >
          <span
            class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors"
            :class="generate ? 'bg-primary' : 'bg-muted'"
          >
            <span
              class="inline-block h-4 w-4 rounded-full bg-background shadow transition-transform"
              :class="generate ? 'translate-x-[18px]' : 'translate-x-0.5'"
            />
          </span>
          Generate inputs
          <Sparkles class="h-4 w-4 text-primary dark:text-brand-primary-soft" />
        </button>
        <Button
          variant="gradient"
          class="gap-2"
          :loading="starting"
          :disabled="!canRun"
          data-testid="agent-suite-run"
          @click="startRun"
        >
          <Play class="h-4 w-4" />
          Run {{ count }} {{ count === 1 ? "time" : "times" }}
        </Button>
      </div>
    </div>

    <p
      v-if="error || activeRun?.status === 'failed'"
      class="mt-2 text-xs text-destructive"
    >
      {{ error || activeRun?.error }}
    </p>

    <div
      v-if="generate"
      class="mt-3 grid gap-3 sm:grid-cols-2"
    >
      <SearchableSelect
        v-model="credentialId"
        :options="credentials.map((c) => ({ value: c.id, label: c.name }))"
        placeholder="Credential"
        data-testid="agent-suite-run-credential"
      />
      <SearchableSelect
        v-model="model"
        :options="models.map((m) => ({ value: m.id, label: m.name }))"
        :disabled="!credentialId"
        placeholder="Model"
        data-testid="agent-suite-run-model"
      />
    </div>

    <div class="mt-4 border-t border-border/40 pt-3">
      <p class="mb-2 text-xs text-muted-foreground">
        <span class="font-medium text-foreground">Inputs</span> ·
        <template v-if="generate">
          the model writes a different one for each run, using these as the example.
        </template>
        <template v-else-if="inputsInfo?.previous_run_at">
          filled from the run on {{ formatRunTime(inputsInfo.previous_run_at) }}, used by every run.
        </template>
        <template v-else>
          used by every run.
        </template>
      </p>
      <div
        v-if="fieldKeys.length > 0"
        class="grid gap-3"
        :class="fieldKeys.length > 1 ? 'sm:grid-cols-2' : ''"
      >
        <div
          v-for="key in fieldKeys"
          :key="key"
        >
          <Label class="mb-1 block font-mono text-xs text-muted-foreground">{{ key }}</Label>
          <Textarea
            :model-value="values[key] ?? ''"
            :rows="2"
            class="min-h-[64px] text-sm"
            :data-testid="`agent-suite-run-input-${key}`"
            @update:model-value="(v) => (values = { ...values, [key]: v })"
          />
        </div>
      </div>
      <p
        v-else-if="inputsInfo"
        class="text-xs text-muted-foreground"
      >
        This workflow takes no inputs.
      </p>
    </div>
  </div>
</template>
