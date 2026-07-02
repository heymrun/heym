<script setup lang="ts">
import { AlertTriangle, Minus, Plus } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  isGenericWebhookBodyMode,
  selectedNode,
  getInputFieldError,
  inputFields,
  addInputField,
  updateInputField,
  removeInputField,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-3">
      <template v-if="!isGenericWebhookBodyMode">
        <div class="flex items-center justify-between">
          <Label>Input Fields</Label>
          <Button
            variant="ghost"
            size="sm"
            class="h-11 min-h-[44px] md:h-7 px-2"
            @click="addInputField"
          >
            <Plus class="w-3 h-3 mr-1" />
            Add
          </Button>
        </div>
        <div
          v-for="(field, index) in inputFields"
          :key="index"
          class="space-y-1"
        >
          <div class="flex gap-1.5 items-center">
            <Input
              :model-value="field.key"
              placeholder="key"
              :class="[
                'w-24 shrink-0 font-mono text-xs',
                getInputFieldError(field.key) ? 'border-red-500 focus:ring-red-500' : ''
              ]"
              @update:model-value="updateInputField(index, 'key', $event)"
            />
            <Input
              :model-value="field.defaultValue || ''"
              placeholder="default (optional)"
              class="flex-1 text-xs"
              @update:model-value="updateInputField(index, 'defaultValue', $event)"
            />
            <Button
              variant="ghost"
              size="icon"
              class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-8 md:w-8 text-destructive shrink-0"
              @click="removeInputField(index)"
            >
              <Minus class="w-3 h-3" />
            </Button>
          </div>
          <p
            v-if="getInputFieldError(field.key)"
            class="text-xs text-red-500 flex items-center gap-1 ml-1"
          >
            <AlertTriangle class="h-3 w-3" />
            {{ getInputFieldError(field.key) }}
          </p>
        </div>
        <p class="text-xs text-muted-foreground">
          Access via ${{ selectedNode.data.label }}.body.key
        </p>
      </template>
      <p
        v-else
        class="text-xs text-muted-foreground"
      >
        Generic webhook mode keeps the incoming request body as raw JSON, so input field add/remove controls are hidden here. Access request data through ${{ selectedNode.data.label }}.body.*
      </p>
    </div>
  </template>
</template>
