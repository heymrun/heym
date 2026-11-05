<script setup lang="ts">
import { computed, ref, watch } from "vue";
import axios from "axios";
import { Loader2 } from "lucide-vue-next";

import type { BoardCard, BoardMember, CardPriority } from "@/types/board";
import type { CardFieldForm } from "@/lib/boardCardFields";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import { useToast } from "@/composables/useToast";
import { fieldChanges, formFromCard, PRIORITY_LABELS } from "@/lib/boardCardFields";
import { boardApi } from "@/services/api";

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

const changes = computed(() => fieldChanges(props.card, form.value));
// The searchable select clears to undefined; the form keeps "" for "not set".
const assignee = computed({
  get: (): string => form.value.assigneeUserId,
  set: (value: string | undefined): void => {
    form.value.assigneeUserId = value ?? "";
  },
});
const priority = computed({
  get: (): string => form.value.priority,
  set: (value: string | undefined): void => {
    form.value.priority = (value ?? "") as CardPriority | "";
  },
});
const dirty = computed<boolean>(() => Object.keys(changes.value).length > 0);

// A reload (the dialog polls while a run is active) must not wipe unsaved edits.
watch(
  () => [props.card.id, props.card.edit_version] as const,
  ([id], [previousId]) => {
    if (id !== previousId || !dirty.value) form.value = formFromCard(props.card);
  },
);

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
      <SearchableSelect
        id="card-field-assignee"
        v-model="assignee"
        :options="assigneeOptions"
        placeholder="Unassigned"
        search-placeholder="Search people…"
        :disabled="readOnly"
      />
    </label>
    <label class="flex flex-col gap-1 text-xs text-muted-foreground">
      Priority
      <SearchableSelect
        id="card-field-priority"
        v-model="priority"
        :options="priorityOptions"
        placeholder="None"
        search-placeholder="Search…"
        :disabled="readOnly"
      />
    </label>
    <label class="flex flex-col gap-1 text-xs text-muted-foreground">
      Due date
      <!-- The picker icon sits at the right edge, and is light on the dark theme. -->
      <Input
        v-model="form.dueDate"
        type="date"
        :disabled="readOnly"
        class="[&::-webkit-calendar-picker-indicator]:ml-auto [&::-webkit-calendar-picker-indicator]:cursor-pointer dark:[color-scheme:dark]"
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
