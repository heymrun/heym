<script setup lang="ts">
import { computed, nextTick, reactive } from "vue";

import type { ClarifyAnswer, ClarifyOption, ClarifyQuestion } from "@/types/clarify";
import type { Credential } from "@/types/credential";
import type { DataTable } from "@/types/dataTable";

import CredentialFormButton from "@/components/Credentials/CredentialFormButton.vue";
import DataTableOptionDetails from "@/components/DataTable/DataTableOptionDetails.vue";
import { selectedTableOption } from "@/composables/clarifyDataTables";
import { clarifyPortKey, usePort } from "@/ports";

const props = defineProps<{
  questions: ClarifyQuestion[];
  disabled?: boolean;
}>();

const emit = defineEmits<{
  (e: "submit", answers: ClarifyAnswer[]): void;
  (e: "credential-saved", credential: Credential): void;
  (e: "data-table-created", table: DataTable): void;
}>();

const state = reactive<Record<string, ClarifyAnswer>>({});
const otherOpen = reactive<Record<string, boolean>>({});
const tables = usePort(clarifyPortKey).useClarifyDataTables();
// Top-level aliases, so the template unwraps the ref.
const creatingTables = tables.creating;
const tableErrors = tables.errors;

for (const q of props.questions) {
  state[q.id] = { id: q.id, text: q.text, selected: [], other: "", prefill: "" };
}

function selectSingle(q: ClarifyQuestion, option: ClarifyOption): void {
  if (props.disabled) return;
  // A credential saved through another option does not answer this one.
  if (!state[q.id].selected.includes(option.label)) state[q.id].credential = undefined;
  // Single choice and free-text are mutually exclusive: picking a chip clears Other.
  state[q.id].selected = [option.label];
  state[q.id].other = "";
  otherOpen[q.id] = false;
  state[q.id].prefill = option.prefill ?? "";
  tables.select(q, option);
}

function toggleMulti(q: ClarifyQuestion, option: ClarifyOption): void {
  if (props.disabled) return;
  const sel = state[q.id].selected;
  const idx = sel.indexOf(option.label);
  if (idx >= 0) sel.splice(idx, 1);
  else sel.push(option.label);
}

function onOtherFocus(q: ClarifyQuestion): void {
  if (props.disabled) return;
  // Focusing Other on a single-choice question deselects the chip
  // (multi keeps its selections so Other can add to them).
  if (q.type !== "multi") {
    state[q.id].selected = [];
    state[q.id].prefill = "";
  }
}

async function toggleOther(q: ClarifyQuestion, event: MouseEvent): Promise<void> {
  if (props.disabled) return;
  const question = (event.currentTarget as HTMLElement).closest(".clarify-question");
  otherOpen[q.id] = !otherOpen[q.id];
  state[q.id].other = "";
  if (!otherOpen[q.id]) return;
  onOtherFocus(q);
  await nextTick();
  question?.querySelector<HTMLInputElement>(".clarify-other-answer")?.focus();
}

function isSelected(q: ClarifyQuestion, option: ClarifyOption): boolean {
  return state[q.id].selected.includes(option.label);
}

function selectedPrefillOption(q: ClarifyQuestion): ClarifyOption | undefined {
  if (q.type !== "single") return undefined;
  return q.options?.find((o) => o.prefill !== undefined && isSelected(q, o));
}

function selectedCredentialOption(q: ClarifyQuestion): ClarifyOption | undefined {
  if (q.type !== "single") return undefined;
  return q.options?.find((o) => (o.create || o.edit) && isSelected(q, o));
}

function selectedTable(q: ClarifyQuestion): ClarifyOption | undefined {
  return selectedTableOption(q, state[q.id]);
}

function isAnswered(q: ClarifyQuestion): boolean {
  const a = state[q.id];
  if (selectedCredentialOption(q)) return a.credential !== undefined;
  return a.selected.length > 0 || a.other.trim().length > 0;
}

function otherPlaceholder(q: ClarifyQuestion): string {
  if (q.type === "text") return q.optional ? "Optional" : "Your answer";
  return q.optional ? "Other… (optional)" : "Other…";
}

const canSubmit = computed(() => {
  if (props.disabled || creatingTables.value) return false;
  return props.questions.every((q) => q.optional || isAnswered(q));
});

async function submit(): Promise<void> {
  if (!canSubmit.value) return;
  // Proposed data tables are created here, so the answers can carry their ids.
  const ready = await tables.prepare(props.questions, state, (table) => emit("data-table-created", table));
  if (!ready) return;
  emit(
    "submit",
    props.questions.map((q) => ({ ...state[q.id] })),
  );
}

function onCredentialSaved(q: ClarifyQuestion, credential: Credential): void {
  state[q.id].credential = { type: credential.type, name: credential.name };
  emit("credential-saved", credential);
}
</script>

<template>
  <div
    class="clarify-card"
    :class="{ disabled: props.disabled }"
  >
    <div
      v-for="q in props.questions"
      :key="q.id"
      class="clarify-question"
      role="group"
      :aria-label="q.text"
    >
      <div class="clarify-text">
        {{ q.text }}
      </div>

      <div
        v-if="q.type === 'single' || q.type === 'multi'"
        class="clarify-options"
      >
        <button
          v-for="opt in q.options ?? []"
          :key="opt.label"
          type="button"
          class="clarify-option"
          :class="{ active: isSelected(q, opt) }"
          :disabled="props.disabled"
          @click="q.type === 'single' ? selectSingle(q, opt) : toggleMulti(q, opt)"
        >
          {{ opt.label }}
        </button>
        <button
          type="button"
          class="clarify-option"
          :class="{ active: otherOpen[q.id] }"
          :aria-expanded="otherOpen[q.id] === true"
          :disabled="props.disabled"
          @click="toggleOther(q, $event)"
        >
          Other
        </button>
      </div>

      <label
        v-if="selectedPrefillOption(q)"
        class="clarify-prefill"
      >
        <span class="clarify-prefill-label">{{ q.prefillLabel || "Value" }}</span>
        <input
          v-model="state[q.id].prefill"
          type="text"
          class="clarify-other clarify-prefill-input"
          spellcheck="false"
          :disabled="props.disabled"
        >
      </label>

      <CredentialFormButton
        v-if="selectedCredentialOption(q)"
        :key="selectedCredentialOption(q)!.label"
        :create="selectedCredentialOption(q)!.create"
        :edit-id="selectedCredentialOption(q)!.edit?.id"
        :saved="state[q.id].credential"
        :disabled="props.disabled"
        @saved="(credential: Credential) => onCredentialSaved(q, credential)"
      />

      <DataTableOptionDetails
        v-if="selectedTable(q)"
        :key="selectedTable(q)!.label"
        :option="selectedTable(q)!"
        :table="tables.tableState(selectedTable(q)!)"
        :error="tableErrors[q.id]"
      />

      <input
        v-if="q.type === 'text' || otherOpen[q.id]"
        v-model="state[q.id].other"
        type="text"
        class="clarify-other clarify-other-answer"
        :aria-label="q.text"
        :placeholder="otherPlaceholder(q)"
        :disabled="props.disabled"
        @focus="onOtherFocus(q)"
      >
    </div>

    <button
      type="button"
      class="clarify-submit"
      :disabled="!canSubmit"
      @click="() => void submit()"
    >
      {{ creatingTables ? "Creating table…" : "Submit answers" }}
    </button>
  </div>
</template>

<style scoped src="./ClarifyCard.css"></style>
