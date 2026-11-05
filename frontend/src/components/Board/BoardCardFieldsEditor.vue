<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import axios from "axios";
import { Link2, Loader2, Plus, X } from "lucide-vue-next";

import type { BoardCard, BoardMember, CardPriority } from "@/types/board";
import type { WorkflowListItem } from "@/types/workflow";
import type { CardFieldForm } from "@/lib/boardCardFields";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import { useToast } from "@/composables/useToast";
import { fieldChanges, formFromCard, PRIORITY_LABELS } from "@/lib/boardCardFields";
import { boardApi, workflowApi } from "@/services/api";

const CHANGED_ELSEWHERE = "This card was changed by someone else. Showing the latest version.";

const props = defineProps<{
  boardId: string;
  card: BoardCard;
  members: BoardMember[];
  readOnly: boolean;
}>();
const emit = defineEmits<{ (e: "saved", card: BoardCard): void }>();

const { showToast } = useToast();
const form = ref<CardFieldForm>(formFromCard(props.card));
const saving = ref(false);
const workflows = ref<WorkflowListItem[]>([]);
const linkWorkflowId = ref("");
const linkExecutionId = ref("");

const changes = computed(() => fieldChanges(props.card, form.value));
const dirty = computed<boolean>(() => Object.keys(changes.value).length > 0);
const hiddenLinks = computed<number>(() => props.card.fields.links.filter((l) => l.hidden).length);

// A reload (the dialog polls while a run is active) must not wipe unsaved edits.
watch(
  () => [props.card.id, props.card.edit_version] as const,
  ([id], [previousId]) => {
    if (id !== previousId || !dirty.value) form.value = formFromCard(props.card);
  },
);

onMounted(async () => {
  if (props.readOnly) return;
  try {
    workflows.value = await workflowApi.list();
  } catch {
    workflows.value = [];
  }
});

const assigneeOptions = computed(() => {
  const options = [
    { value: "", label: "Unassigned" },
    ...props.members.map((m) => ({ value: m.user_id, label: m.name || m.email })),
  ];
  const current = props.card.fields.assignee_user_id;
  if (current && !props.members.some((m) => m.user_id === current)) {
    options.push({ value: current, label: "Former member" });
  }
  return options;
});

const priorityOptions = [
  { value: "", label: "None" },
  ...(Object.keys(PRIORITY_LABELS) as CardPriority[]).map((value) => ({
    value,
    label: PRIORITY_LABELS[value],
  })),
];

const workflowOptions = computed(() =>
  workflows.value.map((workflow) => ({ value: workflow.id, label: workflow.name })),
);

function workflowName(workflowId: string): string {
  return (
    workflows.value.find((w) => w.id === workflowId)?.name ??
    props.card.fields.links.find((l) => l.workflow_id === workflowId)?.workflow_name ??
    "Workflow"
  );
}

function executionStatus(workflowId: string, executionId: string): string | null {
  const link = props.card.fields.links.find(
    (l) => l.workflow_id === workflowId && (l.execution_id ?? "") === executionId,
  );
  return link?.execution_status ?? null;
}

function addLink(): void {
  if (!linkWorkflowId.value) return;
  form.value.links = [
    ...form.value.links,
    { workflow_id: linkWorkflowId.value, execution_id: linkExecutionId.value.trim() },
  ];
  linkWorkflowId.value = "";
  linkExecutionId.value = "";
}

function removeLink(index: number): void {
  form.value.links = form.value.links.filter((_, i) => i !== index);
}

function errorDetail(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  }
  return "The details could not be saved.";
}

async function save(): Promise<void> {
  if (!dirty.value || saving.value) return;
  saving.value = true;
  try {
    const card = await boardApi.updateCard(props.boardId, props.card.id, {
      ...changes.value,
      expected_edit_version: props.card.edit_version,
    });
    showToast("Details saved", "success");
    emit("saved", card);
  } catch (err: unknown) {
    if (axios.isAxiosError(err) && err.response?.status === 409) {
      const latest = err.response.data?.detail?.card as BoardCard | undefined;
      showToast(CHANGED_ELSEWHERE, "error");
      if (latest) {
        form.value = formFromCard(latest);
        emit("saved", latest);
      }
    } else {
      showToast(errorDetail(err), "error");
    }
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div
    class="grid grid-cols-1 gap-2 sm:grid-cols-2"
    data-testid="card-fields"
  >
    <label class="flex flex-col gap-1 text-xs text-muted-foreground">
      Assignee
      <Select
        v-model="form.assigneeUserId"
        :options="assigneeOptions"
        placeholder=""
        :disabled="readOnly"
        data-testid="card-field-assignee"
      />
    </label>
    <label class="flex flex-col gap-1 text-xs text-muted-foreground">
      Priority
      <Select
        v-model="form.priority"
        :options="priorityOptions"
        placeholder=""
        :disabled="readOnly"
        data-testid="card-field-priority"
      />
    </label>
    <label class="flex flex-col gap-1 text-xs text-muted-foreground">
      Due date
      <Input
        v-model="form.dueDate"
        type="date"
        :disabled="readOnly"
        data-testid="card-field-due"
      />
    </label>
    <label class="flex flex-col gap-1 text-xs text-muted-foreground">
      Labels
      <Input
        v-model="form.labels"
        placeholder="Client, project"
        :disabled="readOnly"
        data-testid="card-field-labels"
      />
    </label>
    <div class="flex flex-col gap-1 text-xs text-muted-foreground sm:col-span-2">
      <span>Linked workflows and runs</span>
      <ul
        v-if="form.links.length || hiddenLinks"
        class="flex flex-col gap-1"
      >
        <li
          v-for="(link, index) in form.links"
          :key="`${link.workflow_id}:${link.execution_id}`"
          class="flex items-center gap-2 rounded-md border border-border/70 bg-muted/30 px-2 py-1 text-foreground"
          data-testid="card-field-link"
        >
          <Link2 class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span class="min-w-0 flex-1 truncate">{{ workflowName(link.workflow_id) }}</span>
          <span
            v-if="link.execution_id"
            class="truncate text-muted-foreground"
          >
            run {{ link.execution_id.slice(0, 8) }}
            <template v-if="executionStatus(link.workflow_id, link.execution_id)">
              · {{ executionStatus(link.workflow_id, link.execution_id) }}
            </template>
          </span>
          <button
            v-if="!readOnly"
            type="button"
            class="rounded p-0.5 text-muted-foreground hover:text-red-500"
            :aria-label="`Remove link to ${workflowName(link.workflow_id)}`"
            @click="removeLink(index)"
          >
            <X class="h-3.5 w-3.5" />
          </button>
        </li>
        <li
          v-if="hiddenLinks"
          class="px-2 text-muted-foreground"
        >
          {{ hiddenLinks }} linked workflow{{ hiddenLinks > 1 ? "s" : "" }} you cannot open
        </li>
      </ul>
      <div
        v-if="!readOnly"
        class="flex flex-wrap items-center gap-2"
      >
        <Select
          v-model="linkWorkflowId"
          :options="workflowOptions"
          placeholder="Link a workflow..."
          class="min-w-[12rem] flex-1"
          data-testid="card-field-link-workflow"
        />
        <Input
          v-model="linkExecutionId"
          placeholder="Run id (optional)"
          class="w-40"
          data-testid="card-field-link-execution"
        />
        <Button
          size="sm"
          variant="outline"
          :disabled="!linkWorkflowId"
          @click="addLink"
        >
          <Plus class="mr-1 h-3.5 w-3.5" /> Link
        </Button>
      </div>
    </div>
    <div
      v-if="!readOnly && (dirty || saving)"
      class="flex justify-end sm:col-span-2"
    >
      <Button
        size="sm"
        data-testid="card-fields-save"
        :disabled="saving"
        @click="save"
      >
        <Loader2
          v-if="saving"
          class="mr-1 h-3.5 w-3.5 animate-spin"
        />
        Save details
      </Button>
    </div>
  </div>
</template>
