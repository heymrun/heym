<script setup lang="ts">
import Button from "@/components/ui/Button.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { usePropertiesPanelContext } from "./usePropertiesPanelController";

const {
  isEditingPinnedData,
  editedPinnedData,
  nodeOutput,
  pinnedData,
  pinNodeOutput,
  clearPinnedData,
  startEditingPinnedData,
  cancelEditingPinnedData,
  displayPinnedData,
} = usePropertiesPanelContext();
</script>

<template>
  <div class="space-y-2 pt-4 border-t">
    <div class="flex items-center justify-between">
      <Label>Pinned Data</Label>
      <div class="flex items-center gap-2">
        <template v-if="isEditingPinnedData">
          <Button
            variant="ghost"
            size="sm"
            class="h-11 min-h-[44px] md:h-7 px-2"
            @click="cancelEditingPinnedData"
          >
            Cancel
          </Button>
          <Button
            variant="outline"
            size="sm"
            class="h-11 min-h-[44px] md:h-7 px-2"
            @click="pinNodeOutput"
          >
            Save
          </Button>
        </template>
        <template v-else>
          <Button
            v-if="!pinnedData"
            variant="outline"
            size="sm"
            class="h-7 px-2"
            :disabled="!nodeOutput"
            @click="pinNodeOutput"
          >
            Pin
          </Button>
          <Button
            variant="ghost"
            size="sm"
            class="h-7 px-2"
            :disabled="!pinnedData"
            @click="clearPinnedData"
          >
            Clear
          </Button>
        </template>
      </div>
    </div>
    <div v-if="isEditingPinnedData">
      <Textarea
        v-model="editedPinnedData"
        class="font-mono text-xs"
        :rows="8"
        placeholder="{}"
      />
      <p class="text-xs text-muted-foreground mt-1">
        Edit JSON directly. Click Save to apply.
      </p>
    </div>
    <div
      v-else-if="pinnedData"
      class="p-2 rounded-md bg-amber-500/10 text-xs font-mono overflow-auto max-h-40 cursor-pointer hover:bg-amber-500/20 transition-colors"
      title="Double-click to edit"
      @dblclick="startEditingPinnedData"
    >
      <pre>{{ JSON.stringify(displayPinnedData, null, 2) }}</pre>
    </div>
    <p
      v-else
      class="text-xs text-muted-foreground"
    >
      No pinned data for this node.
    </p>
  </div>
</template>
