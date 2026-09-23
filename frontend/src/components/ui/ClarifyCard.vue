<script setup lang="ts">
import { computed, reactive } from "vue";

import type { ClarifyAnswer, ClarifyOption, ClarifyQuestion } from "@/types/clarify";
import type { Credential } from "@/types/credential";

import CredentialFormButton from "@/components/Credentials/CredentialFormButton.vue";

const props = defineProps<{
  questions: ClarifyQuestion[];
  disabled?: boolean;
}>();

const emit = defineEmits<{
  (e: "submit", answers: ClarifyAnswer[]): void;
  (e: "credential-saved", credential: Credential): void;
}>();

const state = reactive<Record<string, ClarifyAnswer>>({});

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
  state[q.id].prefill = option.prefill ?? "";
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
  if (props.disabled) return false;
  return props.questions.every((q) => q.optional || isAnswered(q));
});

function submit(): void {
  if (!canSubmit.value) return;
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

      <input
        v-if="q.type === 'text' || q.allowOther"
        v-model="state[q.id].other"
        type="text"
        class="clarify-other"
        :placeholder="otherPlaceholder(q)"
        :disabled="props.disabled"
        @focus="onOtherFocus(q)"
      >
    </div>

    <button
      type="button"
      class="clarify-submit"
      :disabled="!canSubmit"
      @click="submit"
    >
      Submit answers
    </button>
  </div>
</template>

<style scoped>
.clarify-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  margin-top: 8px;
  border: 1px solid hsl(var(--border));
  border-radius: 8px;
  background: hsl(var(--card));
}
.clarify-card.disabled {
  opacity: 0.6;
}
.clarify-question {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.clarify-text {
  font-size: 13px;
  font-weight: 600;
  color: hsl(var(--foreground));
}
.clarify-options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.clarify-option {
  padding: 4px 10px;
  font-size: 12px;
  color: hsl(var(--foreground));
  border: 1px solid hsl(var(--border));
  border-radius: 999px;
  background: hsl(var(--background));
  cursor: pointer;
  transition:
    background 0.12s ease,
    border-color 0.12s ease,
    color 0.12s ease;
}
.clarify-option:not(.active):hover:not(:disabled) {
  background: hsl(var(--muted));
}
.clarify-option.active {
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  border-color: hsl(var(--primary));
}
.clarify-option:disabled {
  cursor: not-allowed;
}
.clarify-other {
  padding: 6px 8px;
  font-size: 12px;
  color: hsl(var(--foreground));
  background: hsl(var(--background));
  border: 1px solid hsl(var(--border));
  border-radius: 6px;
}
.clarify-other::placeholder {
  color: hsl(var(--muted-foreground));
}
.clarify-other:focus {
  outline: none;
  border-color: hsl(var(--primary));
  box-shadow: 0 0 0 2px hsl(var(--primary) / 0.15);
}
.clarify-prefill {
  display: flex;
  align-items: center;
  gap: 8px;
}
.clarify-prefill-label {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}
.clarify-prefill-input {
  flex: 1;
  min-width: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.clarify-submit {
  align-self: flex-start;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  border: none;
  border-radius: 6px;
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  cursor: pointer;
}
.clarify-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
