<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";

import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  calTriggerCredentialOptions,
  calTriggerWebhookUrl,
  copyCalWebhookUrl,
  selectedNode,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div class="space-y-2">
        <Label>Webhook Secret Credential</Label>
        <Select
          :model-value="selectedNode.data.credentialId || ''"
          :options="calTriggerCredentialOptions"
          placeholder="Select Cal.com Trigger credential"
          @update:model-value="updateNodeData('credentialId', $event)"
        />
        <p
          v-if="!selectedNode.data.credentialId"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          No credential set — Cal.com requests will be rejected.
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Must match the secret configured on the Cal.com webhook.
        </p>
      </div>

      <label class="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          :checked="selectedNode.data.active !== false"
          @change="updateNodeData('active', ($event.target as HTMLInputElement).checked)"
        >
        Trigger enabled
      </label>

      <div class="space-y-2">
        <Label>Webhook URL</Label>
        <div class="flex gap-2">
          <Input
            :model-value="calTriggerWebhookUrl"
            readonly
            class="font-mono text-xs"
          />
          <Button
            variant="outline"
            size="sm"
            @click="copyCalWebhookUrl"
          >
            Copy
          </Button>
        </div>
        <p class="text-xs text-muted-foreground">
          Create and manage the remote webhook with a separate Cal.com node. Cal.com Cloud
          requires a publicly reachable HTTPS URL.
        </p>
      </div>

      <div class="space-y-2 border-t pt-2">
        <Label class="text-xs text-muted-foreground">Available output fields</Label>
        <div class="space-y-1 font-mono text-xs text-muted-foreground">
          <div>${{ selectedNode.data.label }}.event — full Cal.com webhook body</div>
          <div>${{ selectedNode.data.label }}.triggerEvent — top-level event name</div>
          <div>${{ selectedNode.data.label }}.payload — nested payload or complete body</div>
          <div>${{ selectedNode.data.label }}.headers — sanitized HTTP headers</div>
          <div>${{ selectedNode.data.label }}.triggered_at — ISO timestamp</div>
        </div>
      </div>
    </div>
  </template>
</template>
