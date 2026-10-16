<script setup lang="ts">
import { computed } from "vue";
import { Plus, Trash2 } from "lucide-vue-next";

import type { DecisionImage } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

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

/** The backend places each image in the state under its name, so it must be a plain key. */
const IMAGE_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

const enabled = computed((): boolean => !!selectedNode.value?.data.imagesEnabled);
const rows = computed((): DecisionImage[] => selectedNode.value?.data.images ?? []);

const duplicateNames = computed((): Set<string> => {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const row of rows.value) {
    const name = (row.name ?? "").trim();
    if (!name) continue;
    if (seen.has(name)) duplicates.add(name);
    seen.add(name);
  }
  return duplicates;
});

function nameProblem(row: DecisionImage): string | null {
  const name = (row.name ?? "").trim();
  if (!name) return "Every image needs a name.";
  if (!IMAGE_NAME_PATTERN.test(name)) {
    return "Use letters, digits and underscores, starting with a letter.";
  }
  if (duplicateNames.value.has(name)) return "Duplicate image name.";
  return null;
}

function commit(mutate: (draft: DecisionImage[]) => void): void {
  const draft = rows.value.map((row) => ({ ...row }));
  mutate(draft);
  updateNodeData("images", draft);
}

function toggle(value: boolean): void {
  updateNodeData("imagesEnabled", value);
  if (value && rows.value.length === 0) {
    updateNodeData("images", [{ name: "photo", source: "" }]);
  }
}

function addImage(): void {
  commit((draft) => {
    draft.push({ name: `image_${draft.length + 1}`, source: "" });
  });
}

function removeImage(index: number): void {
  commit((draft) => {
    draft.splice(index, 1);
  });
}

function setName(index: number, value: string): void {
  commit((draft) => {
    draft[index].name = value;
  });
}

function setSource(index: number, value: string): void {
  commit((draft) => {
    draft[index].source = value;
  });
}

function fieldKey(index: number): string {
  return `img:${index}:source`;
}
</script>

<template>
  <div
    v-if="selectedNode"
    class="min-w-0 space-y-2"
    data-testid="decision-images-editor"
  >
    <div class="flex items-center gap-2">
      <input
        id="decision-images-enabled"
        type="checkbox"
        class="h-4 w-4 rounded border-input bg-background"
        :checked="enabled"
        @change="toggle(($event.target as HTMLInputElement).checked)"
      >
      <Label
        for="decision-images-enabled"
        class="text-sm font-normal"
      >
        Send images
      </Label>
    </div>
    <p class="text-xs text-muted-foreground">
      Each image joins the state under its name, so a question refers to it in
      backticks: "Is there a dog in `photo`?". Images are experimental at TypeSafe:
      good for prototypes, not yet for production gates.
    </p>

    <template v-if="enabled">
      <div
        v-for="(row, index) in rows"
        :key="index"
        class="min-w-0 space-y-1 rounded border border-input p-2"
        data-testid="decision-image-row"
      >
        <div class="flex min-w-0 items-center gap-1">
          <Input
            :model-value="row.name"
            placeholder="photo"
            class="min-w-0 flex-1"
            aria-label="Image name"
            @update:model-value="setName(index, String($event))"
          />
          <button
            type="button"
            class="shrink-0 rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground"
            aria-label="Remove image"
            @click="removeImage(index)"
          >
            <Trash2 class="h-3.5 w-3.5" />
          </button>
        </div>
        <p
          v-if="nameProblem(row)"
          class="text-xs text-destructive"
        >
          {{ nameProblem(row) }}
        </p>
        <ExpressionInput
          :ref="(el: unknown) => setDecisionExpressionInputRef(fieldKey(index), el)"
          :model-value="row.source || ''"
          placeholder="$input.body.imageUrl"
          :rows="2"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Image"
          :field-key="fieldKey(index)"
          expandable
          :navigation-enabled="decisionExpressionFieldCount > 1"
          :navigation-index="decisionExpressionFieldIndex(fieldKey(index))"
          :navigation-total="decisionExpressionFieldCount"
          @navigate="handleDecisionExpressionFieldNavigate"
          @register-field-index="onDecisionRegisterExpressionFieldIndex"
          @update:model-value="setSource(index, String($event))"
        />
      </div>

      <Button
        variant="outline"
        size="sm"
        class="gap-1"
        @click="addImage"
      >
        <Plus class="h-3 w-3" /> Add image
      </Button>
      <p class="text-xs text-muted-foreground">
        A source is an image URL, a data:image/... URL or base64. Heym rotates, resizes
        and re-encodes each image to the provider's limits before sending it.
      </p>
    </template>
  </div>
</template>
