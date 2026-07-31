<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";

import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  calTriggerWebhookUrl,
  calTriggerCredentials,
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
          :options="calTriggerCredentials.map((credential) => ({
            value: credential.id,
            label: credential.name,
          }))"
          placeholder="Select Cal.com Trigger credential"
          @update:model-value="updateNodeData('credentialId', $event)"
        />
        <p
          v-if="!selectedNode.data.credentialId"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          No credential set — Cal.com requests will be rejected
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Must match the secret configured on the Cal.com webhook.
        </p>
      </div>

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
          Use this as the subscriber URL when creating a webhook in Cal.com. Configure the same
          secret there and select the booking or meeting events that should trigger this workflow.
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label class="text-xs text-muted-foreground">Available output fields</Label>
        <div class="text-xs text-muted-foreground space-y-1 font-mono">
          <div>${{ selectedNode.data.label }}.event — full Cal.com webhook body</div>
          <div>${{ selectedNode.data.label }}.triggerEvent — event name</div>
          <div>${{ selectedNode.data.label }}.payload — event-specific payload</div>
          <div>${{ selectedNode.data.label }}.headers — sanitized HTTP headers</div>
          <div>${{ selectedNode.data.label }}.triggered_at — ISO timestamp</div>
        </div>
      </div>
    </div>
  </template>
</template>
