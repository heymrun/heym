<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  discordTriggerWebhookUrl,
  copyDiscordWebhookUrl,
  discordTriggerCredentials,
  selectedNode,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div class="space-y-2">
        <Label>Public Key Credential</Label>
        <Select
          :model-value="selectedNode.data.credentialId || ''"
          :options="discordTriggerCredentials.map((c) => ({ value: c.id, label: c.name }))"
          placeholder="Select Discord Trigger credential"
          @update:model-value="updateNodeData('credentialId', $event)"
        />
        <p
          v-if="!selectedNode.data.credentialId"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          No credential set — Discord requests will be rejected
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Used to verify incoming Discord interaction signatures (Ed25519)
        </p>
      </div>

      <div class="space-y-2">
        <Label>Interactions URL</Label>
        <div class="flex gap-2">
          <Input
            :model-value="discordTriggerWebhookUrl"
            readonly
            class="font-mono text-xs"
          />
          <Button
            variant="outline"
            size="sm"
            @click="copyDiscordWebhookUrl"
          >
            Copy
          </Button>
        </div>
        <p class="text-xs text-muted-foreground">
          Paste this URL into Discord Developer Portal → your application → Interactions Endpoint URL.
          PING verification is handled automatically.
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label class="text-xs text-muted-foreground">Available output fields</Label>
        <div class="text-xs text-muted-foreground space-y-1 font-mono">
          <div>${{ selectedNode.data.label }}.interaction — full Discord interaction payload</div>
          <div>${{ selectedNode.data.label }}.type — interaction type (2 = slash command)</div>
          <div>${{ selectedNode.data.label }}.data — command/button/modal data</div>
          <div>${{ selectedNode.data.label }}.data.options — slash command options</div>
          <div>${{ selectedNode.data.label }}.headers — sanitized HTTP headers</div>
          <div>${{ selectedNode.data.label }}.triggered_at — ISO timestamp</div>
        </div>
      </div>
    </div>
  </template>
</template>
