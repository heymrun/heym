<script setup lang="ts">
import { Minus, Plus } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  selectedNode,
  updateInputCount,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Number of Inputs</Label>
      <div class="flex items-center gap-2">
        <Button
          variant="outline"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-8 md:w-8"
          :disabled="(selectedNode.data.inputCount || 2) <= 2"
          @click="updateInputCount(-1)"
        >
          <Minus class="w-4 h-4" />
        </Button>
        <span class="text-sm font-medium w-8 text-center">
          {{ selectedNode.data.inputCount || 2 }}
        </span>
        <Button
          variant="outline"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-8 md:w-8"
          :disabled="(selectedNode.data.inputCount || 2) >= 10"
          @click="updateInputCount(1)"
        >
          <Plus class="w-4 h-4" />
        </Button>
      </div>
      <p class="text-xs text-muted-foreground">
        Waits for all inputs before merging data.
      </p>
    </div>
  </template>
</template>
