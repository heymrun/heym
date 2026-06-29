<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  slackTriggerWebhookUrl,
  copySlackWebhookUrl,
  slackTriggerCredentials,
  selectedNode,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div class="space-y-2">
        <Label>Signing Secret Credential</Label>
        <Select
          :model-value="selectedNode.data.credentialId || ''"
          :options="slackTriggerCredentials.map((c) => ({ value: c.id, label: c.name }))"
          placeholder="Select Slack Trigger credential"
          @update:model-value="updateNodeData('credentialId', $event)"
        />
        <p
          v-if="!selectedNode.data.credentialId"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          No credential set — requests will not be verified
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Used to verify incoming Slack request signatures
        </p>
      </div>

      <div class="space-y-2">
        <Label>Webhook URL</Label>
        <div class="flex gap-2">
          <Input
            :model-value="slackTriggerWebhookUrl"
            readonly
            class="font-mono text-xs"
          />
          <Button
            variant="outline"
            size="sm"
            @click="copySlackWebhookUrl"
          >
            Copy
          </Button>
        </div>
        <p class="text-xs text-muted-foreground">
          Paste this URL into your Slack App → Event Subscriptions → Request URL.
          The challenge is verified automatically.
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label class="text-xs text-muted-foreground">Available output fields</Label>
        <div class="text-xs text-muted-foreground space-y-1 font-mono">
          <div>${{ selectedNode.data.label }}.event — full Slack event object</div>
          <div>${{ selectedNode.data.label }}.event.type — event type</div>
          <div>${{ selectedNode.data.label }}.event.text — message text</div>
          <div>${{ selectedNode.data.label }}.event.user — Slack user ID</div>
          <div>${{ selectedNode.data.label }}.headers — HTTP headers</div>
        </div>
      </div>
    </div>
  </template>
</template>
