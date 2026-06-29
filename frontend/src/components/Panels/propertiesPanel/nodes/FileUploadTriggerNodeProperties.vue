<script setup lang="ts">
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  selectedNode,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <p class="text-xs text-muted-foreground">
        Running this workflow returns a single-use <code>curl</code> upload link.
        Uploading a file to that link starts the run with the file available as
        <code>${{ selectedNode.data.label || "fileUpload" }}.file</code>.
      </p>

      <div class="space-y-2">
        <Label>Link TTL (minutes)</Label>
        <Input
          type="number"
          :min="1"
          :max="10080"
          :model-value="selectedNode.data.ttlMinutes ?? 60"
          placeholder="60"
          @update:model-value="updateNodeData('ttlMinutes', Number($event) || 60)"
        />
        <p class="text-xs text-muted-foreground">
          How long the upload link stays valid (1–10080 minutes). Default 60.
        </p>
      </div>

      <div class="space-y-2">
        <Label>Max file size (MB)</Label>
        <Input
          type="number"
          :min="1"
          :max="100"
          :model-value="selectedNode.data.maxSizeMb ?? 100"
          placeholder="100"
          @update:model-value="updateNodeData('maxSizeMb', Number($event) || 100)"
        />
        <p class="text-xs text-muted-foreground">
          Hard ceiling is 100 MB. Larger uploads are rejected.
        </p>
      </div>

      <div class="space-y-2">
        <Label>Allowed types (optional)</Label>
        <Input
          :model-value="selectedNode.data.allowedTypes || ''"
          placeholder="audio/*, .wav"
          @update:model-value="updateNodeData('allowedTypes', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Comma-separated MIME types or extensions. Leave empty to allow any type.
        </p>
      </div>
    </div>
  </template>
</template>
