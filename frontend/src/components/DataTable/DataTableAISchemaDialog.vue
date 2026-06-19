<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, watchEffect } from "vue";
import { ChevronDown, Plus, Sparkles, Trash2 } from "lucide-vue-next";

import type { CredentialListItem, LLMModel } from "@/types/credential";
import type { DataTable, DataTableColumn, DataTableSchemaSuggestion } from "@/types/dataTable";
import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { credentialsApi, dataTablesApi } from "@/services/api";
import { playSuccessSound } from "@/utils/audio";

const props = defineProps<{
  mode: "create" | "extend";
  existingTable?: DataTable | null;
}>();
const emit = defineEmits<{ created: [table: DataTable]; updated: [table: DataTable]; close: [] }>();

const COLUMN_TYPES: DataTableColumn["type"][] = ["string", "number", "boolean", "date", "json"];

const phase = ref<"input" | "review">("input");
const prompt = ref("");
const promptInputRef = ref<InstanceType<typeof Textarea> | null>(null);
const credentialId = ref("");
const modelName = ref("");
const credentials = ref<CredentialListItem[]>([]);
const models = ref<LLMModel[]>([]);
const generating = ref(false);
const saving = ref(false);
const error = ref("");

const name = ref("");
const description = ref("");
const columns = ref<DataTableColumn[]>([]);

const existingColumns = computed<DataTableColumn[]>(() => props.existingTable?.columns ?? []);

// Guarantee Esc closes the dialog regardless of focus / shared-Dialog quirks.
function handleEscape(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.stopPropagation();
    emit("close");
  }
}
onMounted(() => {
  window.addEventListener("keydown", handleEscape, true);
  focusPromptInput();
});
onBeforeUnmount(() => window.removeEventListener("keydown", handleEscape, true));

function focusPromptInput(): void {
  nextTick(() => {
    nextTick(() => promptInputRef.value?.focus());
  });
}

watch(phase, (nextPhase) => {
  if (nextPhase === "input") {
    focusPromptInput();
  }
});

const canGenerate = computed(
  () => prompt.value.trim().length > 0 && credentialId.value !== "" && modelName.value !== "",
);
const canSave = computed(
  () =>
    columns.value.length > 0 &&
    columns.value.every((c) => c.name.trim().length > 0) &&
    (props.mode === "extend" || name.value.trim().length > 0),
);

watchEffect(async () => {
  if (credentials.value.length === 0) {
    credentials.value = await credentialsApi.listLLM();
    if (credentials.value.length > 0) {
      credentialId.value = credentials.value[0].id;
    }
  }
});

async function loadModels(): Promise<void> {
  modelName.value = "";
  models.value = [];
  if (!credentialId.value) return;
  models.value = await credentialsApi.getModels(credentialId.value);
  if (models.value.length > 0) {
    modelName.value = models.value[models.value.length - 1].id;
  }
}

watchEffect(() => {
  if (credentialId.value) void loadModels();
});

async function handleGenerate(): Promise<void> {
  if (!canGenerate.value) return;
  generating.value = true;
  error.value = "";
  try {
    const suggestion: DataTableSchemaSuggestion = await dataTablesApi.generateSchema({
      credential_id: credentialId.value,
      model: modelName.value,
      prompt: prompt.value.trim(),
      existing_columns: props.mode === "extend" ? existingColumns.value : undefined,
    });
    columns.value = suggestion.columns;
    if (props.mode === "create") {
      name.value = suggestion.name;
      description.value = suggestion.description ?? "";
    }
    phase.value = "review";
    playSuccessSound();
  } catch {
    error.value = "Couldn't generate a schema. Try rephrasing your description.";
  } finally {
    generating.value = false;
  }
}

function addColumn(): void {
  columns.value.push({
    id: crypto.randomUUID(),
    name: "",
    type: "string",
    required: false,
    defaultValue: null,
    unique: false,
    order: columns.value.length,
  });
}

function removeColumn(id: string): void {
  columns.value = columns.value.filter((c) => c.id !== id);
}

async function handleSave(): Promise<void> {
  if (!canSave.value) return;
  saving.value = true;
  error.value = "";
  const normalized = columns.value.map((c, i) => ({
    ...c,
    name: c.name.trim(),
    defaultValue: c.defaultValue === "" ? null : c.defaultValue,
    order: i,
  }));
  try {
    if (props.mode === "create") {
      const table = await dataTablesApi.create({
        name: name.value.trim(),
        description: description.value.trim() || undefined,
        columns: normalized,
      });
      emit("created", table);
    } else if (props.existingTable) {
      const merged = [
        ...existingColumns.value,
        ...normalized.map((c, i) => ({ ...c, order: existingColumns.value.length + i })),
      ];
      const table = await dataTablesApi.update(props.existingTable.id, { columns: merged });
      emit("updated", table);
    }
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : "Failed to save";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Dialog
    :open="true"
    size="2xl"
    :title="mode === 'create' ? 'Generate Table with AI' : 'Generate Columns with AI'"
    @close="emit('close')"
  >
    <div class="flex flex-col gap-4 p-4">
      <!-- ── INPUT PHASE ── -->
      <template v-if="phase === 'input'">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <Label>LLM Credential</Label>
            <div class="relative mt-1">
              <select
                v-model="credentialId"
                class="w-full appearance-none rounded border bg-background px-3 py-2 pr-8 text-sm"
              >
                <option
                  v-for="cred in credentials"
                  :key="cred.id"
                  :value="cred.id"
                >
                  {{ cred.name }}
                </option>
              </select>
              <ChevronDown class="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            </div>
          </div>
          <div>
            <Label>Model</Label>
            <div class="relative mt-1">
              <select
                v-model="modelName"
                class="w-full appearance-none rounded border bg-background px-3 py-2 pr-8 text-sm"
              >
                <option
                  v-for="m in models"
                  :key="m.id"
                  :value="m.id"
                >
                  {{ m.id }}
                </option>
              </select>
              <ChevronDown class="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            </div>
          </div>
        </div>

        <div>
          <Label>Describe your table, or paste JSON</Label>
          <Textarea
            ref="promptInputRef"
            v-model="prompt"
            placeholder="e.g. A table of books with title, author, page count and whether I've read it"
            class="mt-1"
            :rows="5"
          />
        </div>

        <p
          v-if="credentials.length === 0"
          class="text-sm text-muted-foreground"
        >
          No LLM credentials found. Add one in Settings to use AI generation.
        </p>

        <div
          v-if="error"
          class="text-sm text-red-500"
        >
          {{ error }}
        </div>

        <div class="flex justify-end">
          <Button
            :disabled="!canGenerate || generating"
            @click="handleGenerate"
          >
            <Sparkles class="mr-1 h-4 w-4" />
            {{ generating ? "Generating..." : "Generate" }}
          </Button>
        </div>
      </template>

      <!-- ── REVIEW PHASE ── -->
      <template v-else>
        <div
          v-if="mode === 'create'"
          class="flex flex-col gap-3"
        >
          <div>
            <Label>Name</Label>
            <Input
              v-model="name"
              placeholder="Table name"
              class="mt-1"
            />
          </div>
          <div>
            <Label>Description (optional)</Label>
            <Textarea
              v-model="description"
              class="mt-1"
              :rows="2"
            />
          </div>
        </div>

        <!-- existing columns (extend mode, read-only) -->
        <div v-if="mode === 'extend' && existingColumns.length > 0">
          <Label>Existing columns</Label>
          <div class="mt-1 flex flex-wrap gap-1">
            <span
              v-for="col in existingColumns"
              :key="col.id"
              class="rounded border bg-muted px-2 py-0.5 text-xs text-muted-foreground"
            >
              {{ col.name }} ({{ col.type }})
            </span>
          </div>
        </div>

        <div>
          <Label>{{ mode === "extend" ? "New columns" : "Columns" }}</Label>
          <div class="mt-1 flex flex-col gap-2">
            <div
              v-for="col in columns"
              :key="col.id"
              class="flex items-center gap-2 rounded border p-2"
            >
              <Input
                v-model="col.name"
                placeholder="column name"
                class="min-w-0 flex-1"
              />
              <div class="relative shrink-0">
                <select
                  v-model="col.type"
                  class="w-full appearance-none rounded border bg-background py-2 pl-2 pr-8 text-sm"
                >
                  <option
                    v-for="t in COLUMN_TYPES"
                    :key="t"
                    :value="t"
                  >
                    {{ t }}
                  </option>
                </select>
                <ChevronDown class="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              </div>
              <Input
                v-model="col.defaultValue as string"
                placeholder="default"
                class="w-20 shrink-0"
              />
              <label class="flex shrink-0 items-center gap-1 text-xs">
                <input
                  v-model="col.unique"
                  type="checkbox"
                >
                unique
              </label>
              <label class="flex shrink-0 items-center gap-1 text-xs">
                <input
                  v-model="col.required"
                  type="checkbox"
                >
                notEmpty
              </label>
              <button
                type="button"
                class="shrink-0 text-muted-foreground hover:text-red-500"
                @click="removeColumn(col.id)"
              >
                <Trash2 class="h-4 w-4" />
              </button>
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            class="mt-2"
            @click="addColumn"
          >
            <Plus class="mr-1 h-4 w-4" />
            Add column
          </Button>
        </div>

        <div
          v-if="error"
          class="text-sm text-red-500"
        >
          {{ error }}
        </div>

        <div class="flex justify-between">
          <Button
            variant="outline"
            @click="phase = 'input'"
          >
            Back
          </Button>
          <Button
            :disabled="!canSave || saving"
            @click="handleSave"
          >
            {{ saving ? "Saving..." : mode === "create" ? "Create Table" : "Add Columns" }}
          </Button>
        </div>
      </template>
    </div>
  </Dialog>
</template>
