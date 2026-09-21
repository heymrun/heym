<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { ChevronDown, ChevronRight, Plus, Sparkles, Trash2 } from "lucide-vue-next";

import type { DecisionQuestion } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const emit = defineEmits<{ generate: [] }>();

const {
  workflowStore,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  updateNodeData,
  decisionExpressionFieldCount,
  decisionExpressionFieldIndex,
  setDecisionExpressionInputRef,
  handleDecisionExpressionFieldNavigate,
  onDecisionRegisterExpressionFieldIndex,
} = usePropertiesPanelContext();

const TYPE_OPTIONS = [
  { value: "noul", label: "Noul - does this hold?" },
  { value: "choice", label: "Choice - pick one" },
  { value: "score", label: "Score - rate on a scale" },
];

const expanded = ref<Record<number, boolean>>({ 0: true });
const rowElements = new Map<number, HTMLElement>();

function setRowElement(index: number, el: unknown): void {
  if (el instanceof HTMLElement) {
    rowElements.set(index, el);
  } else {
    rowElements.delete(index);
  }
}

const rows = computed((): DecisionQuestion[] => selectedNode.value?.data.questions ?? []);

/** Ids that appear more than once. An answer is keyed by its id, so a repeat loses one. */
const duplicateIds = computed((): Set<string> => {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const row of rows.value) {
    const id = (row.id ?? "").trim();
    if (!id) continue;
    if (seen.has(id)) duplicates.add(id);
    seen.add(id);
  }
  return duplicates;
});

function commit(mutate: (draft: DecisionQuestion[]) => void): void {
  const draft = rows.value.map((row) => ({
    ...row,
    options: row.options ? row.options.map((option) => ({ ...option })) : undefined,
    levels: row.levels ? [...row.levels] : undefined,
  }));
  mutate(draft);
  updateNodeData("questions", draft);
}

function toggle(index: number): void {
  expanded.value = { ...expanded.value, [index]: !expanded.value[index] };
}

function addQuestion(): void {
  commit((draft) => {
    draft.push({ id: `question_${draft.length + 1}`, type: "noul", instructions: "" });
  });
  const index = rows.value.length - 1;
  expanded.value = { ...expanded.value, [index]: true };
  // The panel scrolls, so bring the new row into view instead of leaving it below the fold.
  void nextTick(() => {
    rowElements.get(index)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
}

function removeQuestion(index: number): void {
  commit((draft) => {
    draft.splice(index, 1);
  });
}

function setId(index: number, value: string): void {
  commit((draft) => {
    draft[index].id = value;
  });
}

function setInstructions(index: number, value: string): void {
  commit((draft) => {
    draft[index].instructions = value;
  });
}

function setCriteria(index: number, key: "criteriaTrue" | "criteriaFalse", value: string): void {
  commit((draft) => {
    draft[index][key] = value;
  });
}

function setType(index: number, type: string): void {
  commit((draft) => {
    const row = draft[index];
    row.type = type as DecisionQuestion["type"];
    if (row.type === "choice" && !row.options?.length) {
      row.options = [
        { key: "option_1", description: "" },
        { key: "option_2", description: "" },
      ];
    }
    if (row.type === "score" && (row.levels?.length ?? 0) < 2) {
      row.levels = ["", ""];
    }
  });
}

function setOptionKey(index: number, optionIndex: number, value: string): void {
  commit((draft) => {
    const options = draft[index].options ?? [];
    options[optionIndex].key = value;
  });
}

function setOptionDescription(index: number, optionIndex: number, value: string): void {
  commit((draft) => {
    const options = draft[index].options ?? [];
    options[optionIndex].description = value;
  });
}

function addOption(index: number): void {
  commit((draft) => {
    const options = draft[index].options ?? [];
    options.push({ key: `option_${options.length + 1}`, description: "" });
    draft[index].options = options;
  });
}

function removeOption(index: number, optionIndex: number): void {
  commit((draft) => {
    draft[index].options?.splice(optionIndex, 1);
  });
}

function setLevel(index: number, levelIndex: number, value: string): void {
  commit((draft) => {
    const levels = draft[index].levels ?? [];
    levels[levelIndex] = value;
  });
}

function addLevel(index: number): void {
  commit((draft) => {
    draft[index].levels = [...(draft[index].levels ?? []), ""];
  });
}

function removeLevel(index: number, levelIndex: number): void {
  commit((draft) => {
    draft[index].levels?.splice(levelIndex, 1);
  });
}

function fieldKey(index: number, suffix: string): string {
  return `q:${index}:${suffix}`;
}
</script>

<template>
  <div
    v-if="selectedNode"
    class="min-w-0 space-y-2"
  >
    <div class="flex min-w-0 items-center justify-between gap-2">
      <Label class="min-w-0 truncate">Questions</Label>
      <div class="flex shrink-0 items-center gap-1">
        <Button
          variant="outline"
          size="sm"
          class="gap-1"
          @click="emit('generate')"
        >
          <Sparkles class="h-3 w-3 text-primary" /> Generate
        </Button>
        <Button
          variant="outline"
          size="sm"
          class="gap-1"
          @click="addQuestion"
        >
          <Plus class="h-3 w-3" /> Add
        </Button>
      </div>
    </div>

    <p
      v-if="rows.length === 0"
      class="text-xs text-muted-foreground"
    >
      Add at least one question. The model answers each one about the state above and
      returns a probability, not prose.
    </p>

    <div
      v-for="(row, index) in rows"
      :key="index"
      :ref="(el: unknown) => setRowElement(index, el)"
      class="min-w-0 space-y-2 rounded border border-input p-2"
    >
      <div class="flex min-w-0 items-center gap-1">
        <Input
          :model-value="row.id"
          placeholder="question_id"
          class="min-w-0 flex-1"
          @update:model-value="setId(index, String($event))"
        />
        <button
          type="button"
          class="shrink-0 rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground"
          :aria-label="expanded[index] ? 'Collapse question' : 'Expand question'"
          @click="toggle(index)"
        >
          <ChevronDown
            v-if="expanded[index]"
            class="h-3.5 w-3.5"
          />
          <ChevronRight
            v-else
            class="h-3.5 w-3.5"
          />
        </button>
        <button
          type="button"
          class="shrink-0 rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground"
          aria-label="Remove question"
          @click="removeQuestion(index)"
        >
          <Trash2 class="h-3.5 w-3.5" />
        </button>
      </div>

      <Select
        :model-value="row.type"
        :options="TYPE_OPTIONS"
        class="w-full"
        @update:model-value="setType(index, String($event))"
      />

      <p
        v-if="duplicateIds.has((row.id ?? '').trim())"
        class="text-xs text-destructive"
      >
        Duplicate question id. Answers come back keyed by id, so each must be unique.
      </p>
      <p
        v-else-if="!(row.id ?? '').trim()"
        class="text-xs text-destructive"
      >
        Every question needs an id.
      </p>

      <template v-if="expanded[index]">
        <div class="space-y-1">
          <Label class="text-xs">Instructions</Label>
          <ExpressionInput
            :ref="(el: unknown) => setDecisionExpressionInputRef(fieldKey(index, 'instructions'), el)"
            :model-value="row.instructions || ''"
            placeholder="Does this convey urgency?"
            :rows="3"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Instructions"
            :field-key="fieldKey(index, 'instructions')"
            expandable
            :navigation-enabled="decisionExpressionFieldCount > 1"
            :navigation-index="decisionExpressionFieldIndex(fieldKey(index, 'instructions'))"
            :navigation-total="decisionExpressionFieldCount"
            @navigate="handleDecisionExpressionFieldNavigate"
            @register-field-index="onDecisionRegisterExpressionFieldIndex"
            @update:model-value="setInstructions(index, String($event))"
          />
          <p class="text-xs text-muted-foreground">
            The id never reaches the model, so say the whole judgment here.
          </p>
        </div>

        <template v-if="row.type === 'noul'">
          <div class="space-y-1">
            <Label class="text-xs">Yes means</Label>
            <ExpressionInput
              :ref="(el: unknown) => setDecisionExpressionInputRef(fieldKey(index, 'criteriaTrue'), el)"
              :model-value="row.criteriaTrue || ''"
              placeholder="Explicitly time-sensitive"
              :rows="2"
              :nodes="workflowStore.nodes"
              :node-results="workflowStore.nodeResults"
              :edges="workflowStore.edges"
              :current-node-id="selectedNode.id"
              :dialog-node-label="selectedNodeEvaluateDialogLabel"
              dialog-key-label="Yes means"
              :field-key="fieldKey(index, 'criteriaTrue')"
              expandable
              :navigation-enabled="decisionExpressionFieldCount > 1"
              :navigation-index="decisionExpressionFieldIndex(fieldKey(index, 'criteriaTrue'))"
              :navigation-total="decisionExpressionFieldCount"
              @navigate="handleDecisionExpressionFieldNavigate"
              @register-field-index="onDecisionRegisterExpressionFieldIndex"
              @update:model-value="setCriteria(index, 'criteriaTrue', String($event))"
            />
          </div>
          <div class="space-y-1">
            <Label class="text-xs">No means</Label>
            <ExpressionInput
              :ref="(el: unknown) => setDecisionExpressionInputRef(fieldKey(index, 'criteriaFalse'), el)"
              :model-value="row.criteriaFalse || ''"
              placeholder="No urgency expressed"
              :rows="2"
              :nodes="workflowStore.nodes"
              :node-results="workflowStore.nodeResults"
              :edges="workflowStore.edges"
              :current-node-id="selectedNode.id"
              :dialog-node-label="selectedNodeEvaluateDialogLabel"
              dialog-key-label="No means"
              :field-key="fieldKey(index, 'criteriaFalse')"
              expandable
              :navigation-enabled="decisionExpressionFieldCount > 1"
              :navigation-index="decisionExpressionFieldIndex(fieldKey(index, 'criteriaFalse'))"
              :navigation-total="decisionExpressionFieldCount"
              @navigate="handleDecisionExpressionFieldNavigate"
              @register-field-index="onDecisionRegisterExpressionFieldIndex"
              @update:model-value="setCriteria(index, 'criteriaFalse', String($event))"
            />
            <p class="text-xs text-muted-foreground">
              Both sides are optional. Leave them blank and the question ships without
              criteria.
            </p>
          </div>
        </template>

        <template v-else-if="row.type === 'choice'">
          <div class="space-y-1">
            <div class="flex min-w-0 items-center justify-between gap-2">
              <Label class="min-w-0 truncate text-xs">Options</Label>
              <Button
                variant="outline"
                size="sm"
                class="gap-1"
                @click="addOption(index)"
              >
                <Plus class="h-3 w-3" /> Option
              </Button>
            </div>
            <div
              v-for="(option, optionIndex) in row.options ?? []"
              :key="optionIndex"
              class="min-w-0 space-y-1 rounded border border-input/60 p-1.5"
            >
              <div class="flex min-w-0 items-center gap-1">
                <Input
                  :model-value="option.key"
                  placeholder="option_key"
                  class="min-w-0 flex-1"
                  @update:model-value="setOptionKey(index, optionIndex, String($event))"
                />
                <button
                  type="button"
                  class="shrink-0 rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground"
                  aria-label="Remove option"
                  @click="removeOption(index, optionIndex)"
                >
                  <Trash2 class="h-3.5 w-3.5" />
                </button>
              </div>
              <div class="min-w-0">
                <ExpressionInput
                  :ref="(el: unknown) => setDecisionExpressionInputRef(fieldKey(index, `option:${optionIndex}`), el)"
                  :model-value="option.description || ''"
                  placeholder="What this option means"
                  :rows="3"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Option"
                  :field-key="fieldKey(index, `option:${optionIndex}`)"
                  expandable
                  :navigation-enabled="decisionExpressionFieldCount > 1"
                  :navigation-index="decisionExpressionFieldIndex(fieldKey(index, `option:${optionIndex}`))"
                  :navigation-total="decisionExpressionFieldCount"
                  @navigate="handleDecisionExpressionFieldNavigate"
                  @register-field-index="onDecisionRegisterExpressionFieldIndex"
                  @update:model-value="setOptionDescription(index, optionIndex, String($event))"
                />
              </div>
            </div>
            <p class="text-xs text-muted-foreground">
              Add an option that covers "none of these" when nothing may fit.
            </p>
          </div>
        </template>

        <template v-else>
          <div class="space-y-1">
            <div class="flex min-w-0 items-center justify-between gap-2">
              <Label class="min-w-0 truncate text-xs">Levels (lowest first)</Label>
              <Button
                variant="outline"
                size="sm"
                class="gap-1"
                @click="addLevel(index)"
              >
                <Plus class="h-3 w-3" /> Level
              </Button>
            </div>
            <div
              v-for="(level, levelIndex) in row.levels ?? []"
              :key="levelIndex"
              class="min-w-0 space-y-1 rounded border border-input/60 p-1.5"
            >
              <div class="flex min-w-0 items-center justify-between gap-1">
                <span class="text-[11px] text-muted-foreground">
                  Level {{ levelIndex }}<span v-if="levelIndex === 0"> &middot; lowest</span>
                  <span v-else-if="levelIndex === (row.levels?.length ?? 0) - 1"> &middot; highest</span>
                </span>
                <button
                  type="button"
                  class="shrink-0 rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground"
                  aria-label="Remove level"
                  @click="removeLevel(index, levelIndex)"
                >
                  <Trash2 class="h-3.5 w-3.5" />
                </button>
              </div>
              <div class="min-w-0">
                <ExpressionInput
                  :ref="(el: unknown) => setDecisionExpressionInputRef(fieldKey(index, `level:${levelIndex}`), el)"
                  :model-value="level || ''"
                  placeholder="What this level looks like"
                  :rows="3"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Level"
                  :field-key="fieldKey(index, `level:${levelIndex}`)"
                  expandable
                  :navigation-enabled="decisionExpressionFieldCount > 1"
                  :navigation-index="decisionExpressionFieldIndex(fieldKey(index, `level:${levelIndex}`))"
                  :navigation-total="decisionExpressionFieldCount"
                  @navigate="handleDecisionExpressionFieldNavigate"
                  @register-field-index="onDecisionRegisterExpressionFieldIndex"
                  @update:model-value="setLevel(index, levelIndex, String($event))"
                />
              </div>
            </div>
            <p class="text-xs text-muted-foreground">
              At least two levels. Each one should describe a concrete situation.
            </p>
          </div>
        </template>
      </template>
    </div>
  </div>
</template>
