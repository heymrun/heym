<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  telegramTriggerWebhookUrl,
  copyTelegramWebhookUrl,
  selectedNode,
  telegramTriggerCredentialOptions,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div class="space-y-2">
        <Label>Telegram Credential</Label>
        <Select
          :model-value="selectedNode.data.credentialId || ''"
          :options="telegramTriggerCredentialOptions"
          placeholder="Select Telegram credential"
          @update:model-value="updateNodeData('credentialId', $event)"
        />
        <p
          v-if="!selectedNode.data.credentialId"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          No Telegram credential set — bot-specific verification is disabled
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Uses the selected bot token for downstream sends and optionally verifies the Telegram secret token header on incoming webhooks.
        </p>
      </div>

      <div class="space-y-2">
        <Label>Webhook URL</Label>
        <div class="flex gap-2">
          <Input
            :model-value="telegramTriggerWebhookUrl"
            readonly
            class="font-mono text-xs"
          />
          <Button
            variant="outline"
            size="sm"
            @click="copyTelegramWebhookUrl"
          >
            Copy
          </Button>
        </div>
        <p class="text-xs text-muted-foreground">
          Register this URL with Telegram's <code>setWebhook</code> API for your bot. Reuse the same credential if you also send messages downstream.
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label class="text-xs text-muted-foreground">Available output fields</Label>
        <div class="text-xs text-muted-foreground space-y-1 font-mono">
          <div>${{ selectedNode.data.label }}.update — full Telegram update payload</div>
          <div>${{ selectedNode.data.label }}.message — primary message-like object</div>
          <div>${{ selectedNode.data.label }}.message.text — incoming message text</div>
          <div>${{ selectedNode.data.label }}.message.chat.id — destination chat ID</div>
          <div>${{ selectedNode.data.label }}.callback_query — callback query payload when present</div>
          <div>${{ selectedNode.data.label }}.headers — sanitized webhook headers</div>
          <div>${{ selectedNode.data.label }}.triggered_at — ISO timestamp</div>
        </div>
      </div>
    </div>
  </template>
</template>
