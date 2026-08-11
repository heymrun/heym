<script setup lang="ts">
import { computed, ref, watch } from "vue";

import AlertAiPrompt from "./AlertAiPrompt.vue";
import StepCondition from "./StepCondition.vue";
import StepResponse from "./StepResponse.vue";
import StepReview from "./StepReview.vue";
import StepScope from "./StepScope.vue";
import StepType from "./StepType.vue";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import { useAlertsStore } from "@/stores/alerts";
import {
  defaultConfigForType,
  type Alert,
  type AlertConfig,
  type AlertDraft,
  type AlertPayload,
  type AlertScope,
  type AlertType,
  type NotifyWorkflowMode,
  type RenotifyMode,
} from "@/types/alerts";

interface WorkflowOption {
  value: string;
  label: string;
}

interface Props {
  open: boolean;
  workflows: WorkflowOption[];
  editing?: Alert | null;
}

const props = withDefaults(defineProps<Props>(), { editing: null });
const emit = defineEmits<{ close: []; saved: [alert: Alert] }>();

const alertsStore = useAlertsStore();

const STEP_TITLES = ["Type", "Scope", "Condition", "Response", "Review"];

const step = ref(0);
const name = ref("");
const description = ref<string | null>(null);
const alertType = ref<AlertType | null>(null);
const scope = ref<AlertScope>("workflow");
const workflowId = ref<string | null>(null);
const config = ref<AlertConfig>(defaultConfigForType("error_threshold"));
const notifyWorkflowId = ref<string | null>(null);
const notifyMode = ref<NotifyWorkflowMode>("create");
const renotifyMode = ref<RenotifyMode>("on_recovery");
const cooldownMinutes = ref<number | null>(null);
const aiFilledFields = ref<string[]>([]);
const wasAiDrafted = ref(false);
const saving = ref(false);
const saveError = ref<string | null>(null);

const isEditing = computed((): boolean => props.editing !== null);

const dialogTitle = computed(
  (): string =>
    `${isEditing.value ? "Edit alert" : "New alert"} — ${STEP_TITLES[step.value]}`,
);

const workflowName = computed(
  (): string | null =>
    props.workflows.find((option) => option.value === workflowId.value)?.label ?? null,
);

const notifyWorkflowName = computed(
  (): string | null =>
    props.workflows.find((option) => option.value === notifyWorkflowId.value)?.label ?? null,
);

const canAdvance = computed((): boolean => {
  if (step.value === 0) return alertType.value !== null;
  if (step.value === 1) return scope.value === "system" || workflowId.value !== null;
  return true;
});

const canSave = computed(
  (): boolean => alertType.value !== null && name.value.trim().length > 0 && !saving.value,
);

function reset(): void {
  const editing = props.editing;
  step.value = editing ? 4 : 0;
  name.value = editing?.name ?? "";
  description.value = editing?.description ?? null;
  alertType.value = editing?.alert_type ?? null;
  scope.value = editing?.scope ?? "workflow";
  workflowId.value = editing?.workflow_id ?? null;
  config.value = editing?.config ?? defaultConfigForType("error_threshold");
  notifyWorkflowId.value = editing?.notify_workflow_id ?? null;
  // "create" is the default for a new alert so it leaves the wizard with somewhere
  // to add notification nodes. Editing keeps whatever the alert already points at.
  notifyMode.value = editing ? (editing.notify_workflow_id ? "existing" : "none") : "create";
  renotifyMode.value = editing?.renotify_mode ?? "on_recovery";
  cooldownMinutes.value = editing?.cooldown_minutes ?? null;
  aiFilledFields.value = [];
  wasAiDrafted.value = false;
  saveError.value = null;
}

watch(() => props.open, (isOpen) => { if (isOpen) reset(); });

function onTypeSelected(type: AlertType): void {
  alertType.value = type;
  config.value = defaultConfigForType(type);
}

/**
 * Applies whatever the AI worked out and leaves the rest alone.
 *
 * The draft is partial by design, so this never overwrites a field with an
 * absent one. The wizard then opens on the earliest step that still needs a
 * decision, which is Review when the draft is complete.
 */
function applyDraft(draft: AlertDraft): void {
  if (draft.alert_type) {
    alertType.value = draft.alert_type;
    config.value = defaultConfigForType(draft.alert_type);
  }
  if (draft.config) config.value = draft.config;
  if (draft.scope) scope.value = draft.scope;
  if (draft.workflow_id) workflowId.value = draft.workflow_id;
  if (draft.notify_workflow_id) {
    notifyWorkflowId.value = draft.notify_workflow_id;
    notifyMode.value = "existing";
  } else if (draft.create_notify_workflow === true) {
    notifyMode.value = "create";
  } else if (draft.create_notify_workflow === false) {
    notifyMode.value = "none";
  }
  if (draft.renotify_mode) renotifyMode.value = draft.renotify_mode;
  if (draft.cooldown_minutes !== null && draft.cooldown_minutes !== undefined) {
    cooldownMinutes.value = draft.cooldown_minutes;
  }
  if (draft.name) name.value = draft.name;
  if (draft.description) description.value = draft.description;
  aiFilledFields.value = draft.filled_fields;
  wasAiDrafted.value = true;
  step.value = firstIncompleteStep();
}

/** Steps that still need a decision, in wizard order. */
const missingSteps = computed((): { step: number; label: string }[] => {
  const missing: { step: number; label: string }[] = [];
  if (alertType.value === null) missing.push({ step: 0, label: "which kind of threshold to watch" });
  if (scope.value === "workflow" && workflowId.value === null) {
    missing.push({ step: 1, label: "which workflow to watch" });
  }
  if (renotifyMode.value === "cooldown" && cooldownMinutes.value === null) {
    missing.push({ step: 3, label: "how often to keep notifying" });
  }
  if (notifyMode.value === "existing" && notifyWorkflowId.value === null) {
    missing.push({ step: 3, label: "which workflow to run on fire" });
  }
  if (name.value.trim().length === 0) missing.push({ step: 4, label: "a name" });
  return missing;
});

/**
 * Derived rather than stored, so answering one of the gaps clears it from the note
 * immediately. A stored string from the API would keep asking for a workflow after
 * the user had already picked one.
 */
const aiNote = computed((): string | null => {
  if (!wasAiDrafted.value || missingSteps.value.length === 0) return null;
  return `Still needed: ${missingSteps.value.map((entry) => entry.label).join(", ")}.`;
});

function firstIncompleteStep(): number {
  return missingSteps.value[0]?.step ?? 4;
}

async function save(): Promise<void> {
  if (!alertType.value) return;
  saving.value = true;
  saveError.value = null;
  try {
    const payload: AlertPayload = {
      name: name.value.trim(),
      description: description.value,
      alert_type: alertType.value,
      scope: scope.value,
      workflow_id: scope.value === "workflow" ? workflowId.value : null,
      config: config.value,
      notify_workflow_id: notifyMode.value === "existing" ? notifyWorkflowId.value : null,
      create_notify_workflow: notifyMode.value === "create",
      renotify_mode: renotifyMode.value,
      cooldown_minutes: renotifyMode.value === "cooldown" ? (cooldownMinutes.value ?? 60) : null,
    };
    const saved = props.editing
      ? await alertsStore.updateAlert(props.editing.id, payload)
      : await alertsStore.createAlert(payload);
    emit("saved", saved);
    emit("close");
  } catch (err: unknown) {
    saveError.value = err instanceof Error ? err.message : "Could not save the alert";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Dialog
    :open="open"
    :title="dialogTitle"
    size="2xl"
    @close="emit('close')"
  >
    <div class="space-y-5">
      <!-- Shown while editing too: Back still walks the same five steps, so hiding
           the progress made an edit look like a dead end on Review. -->
      <div class="flex gap-1">
        <div
          v-for="(title, index) in STEP_TITLES"
          :key="title"
          class="h-1 flex-1 rounded-full"
          :class="index <= step ? 'bg-primary' : 'bg-border'"
        />
      </div>

      <!-- Survives the jump off step 0, so the user can see what the AI left open
           while filling it in. Advisory only: it never blocks Next or Create. -->
      <p
        v-if="aiNote"
        class="rounded-md bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400"
      >
        {{ aiNote }}
      </p>

      <template v-if="step === 0">
        <AlertAiPrompt @drafted="applyDraft" />
        <StepType
          :alert-type="alertType"
          @update:alert-type="onTypeSelected"
        />
      </template>

      <StepScope
        v-else-if="step === 1"
        :scope="scope"
        :workflow-id="workflowId"
        :workflows="workflows"
        @update:scope="scope = $event"
        @update:workflow-id="workflowId = $event"
      />

      <StepCondition
        v-else-if="step === 2 && alertType"
        :alert-type="alertType"
        :config="config"
        @update:config="config = $event"
      />

      <StepResponse
        v-else-if="step === 3"
        :notify-workflow-id="notifyWorkflowId"
        :notify-mode="notifyMode"
        :renotify-mode="renotifyMode"
        :cooldown-minutes="cooldownMinutes"
        :workflows="workflows"
        :own-workflow-id="workflowId"
        @update:notify-workflow-id="notifyWorkflowId = $event"
        @update:notify-mode="notifyMode = $event"
        @update:renotify-mode="renotifyMode = $event"
        @update:cooldown-minutes="cooldownMinutes = $event"
      />

      <StepReview
        v-else-if="step === 4 && alertType"
        :name="name"
        :description="description"
        :alert-type="alertType"
        :scope="scope"
        :workflow-id="workflowId"
        :workflow-name="workflowName"
        :config="config"
        :renotify-mode="renotifyMode"
        :cooldown-minutes="cooldownMinutes"
        :notify-workflow-name="notifyWorkflowName"
        :notify-mode="notifyMode"
        :ai-filled-fields="aiFilledFields"
        @update:name="name = $event"
        @update:description="description = $event"
      />

      <p
        v-if="saveError"
        class="text-sm text-destructive"
      >
        {{ saveError }}
      </p>

      <!-- Dialog renders a single default slot and has no footer slot, so the
           step controls live here rather than in a #footer template. -->
      <div class="flex items-center justify-between gap-2 border-t border-border/60 pt-4">
        <Button
          v-if="step > 0"
          variant="ghost"
          @click="step -= 1"
        >
          Back
        </Button>
        <span v-else />

        <div class="flex gap-2">
          <Button
            variant="ghost"
            @click="emit('close')"
          >
            Cancel
          </Button>
          <Button
            v-if="step < 4"
            :disabled="!canAdvance"
            @click="step += 1"
          >
            Next
          </Button>
          <Button
            v-else
            :disabled="!canSave"
            @click="save"
          >
            {{ isEditing ? "Save changes" : "Create alert" }}
          </Button>
        </div>
      </div>
    </div>
  </Dialog>
</template>
