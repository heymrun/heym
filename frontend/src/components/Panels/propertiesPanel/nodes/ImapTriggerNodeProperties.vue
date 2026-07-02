<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  selectedNode,
  imapTriggerCredentialOptions,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div class="space-y-2">
        <Label>IMAP Credential</Label>
        <Select
          :model-value="selectedNode.data.credentialId || ''"
          :options="imapTriggerCredentialOptions"
          placeholder="Select IMAP credential"
          @update:model-value="updateNodeData('credentialId', $event)"
        />
        <p
          v-if="!selectedNode.data.credentialId"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          No IMAP credential set — inbox polling is disabled
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Heym logs in to this mailbox and checks for new email on the interval below.
        </p>
      </div>

      <div class="space-y-2">
        <Label for="imap-poll-interval">Poll Interval (Minutes)</Label>
        <Input
          id="imap-poll-interval"
          :model-value="String(selectedNode.data.pollIntervalMinutes ?? 5)"
          type="number"
          min="1"
          step="1"
          @update:model-value="updateNodeData('pollIntervalMinutes', Number.parseInt($event, 10) || 1)"
        />
        <p class="text-xs text-muted-foreground">
          Minimum 1 minute. First poll baselines the current inbox, then only newer emails trigger runs.
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label class="text-xs text-muted-foreground">Available output fields</Label>
        <div class="text-xs text-muted-foreground space-y-1 font-mono">
          <div>${{ selectedNode.data.label }}.email.subject — decoded email subject</div>
          <div>${{ selectedNode.data.label }}.email.from — raw from header</div>
          <div>${{ selectedNode.data.label }}.email.text — plain-text body</div>
          <div>${{ selectedNode.data.label }}.email.html — HTML body</div>
          <div>${{ selectedNode.data.label }}.email.attachments — attachment metadata array</div>
          <div>${{ selectedNode.data.label }}.email.headers — decoded header map</div>
          <div>${{ selectedNode.data.label }}.email.uid — IMAP UID for deduping</div>
        </div>
      </div>
    </div>
  </template>
</template>
