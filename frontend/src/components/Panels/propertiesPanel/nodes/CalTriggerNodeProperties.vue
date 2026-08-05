<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";

import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  calApiCredentialOptions,
  calSubscription,
  calSubscriptionError,
  calSubscriptionLoading,
  calTriggerCredentialOptions,
  calTriggerWebhookUrl,
  calWebhookEvents,
  copyCalWebhookUrl,
  deactivateCalSubscription,
  selectedNode,
  syncCalSubscription,
  updateNodeData,
} = usePropertiesPanelContext();

const setupModeOptions = [
  { value: "manual", label: "Manual webhook" },
  { value: "managed", label: "Managed with Cal.com API" },
];

const payloadVersionOptions = [
  { value: "2021-10-20", label: "2021-10-20" },
  { value: "2026-07-27", label: "2026-07-27 (includes optional ICS content)" },
];

const noShowTimeUnitOptions = [
  { value: "MINUTE", label: "Minutes" },
  { value: "HOUR", label: "Hours" },
  { value: "DAY", label: "Days" },
];

const noShowEvents = new Set([
  "AFTER_HOSTS_CAL_VIDEO_NO_SHOW",
  "AFTER_GUESTS_CAL_VIDEO_NO_SHOW",
]);

function selectedEvents(): string[] {
  const events = selectedNode.value?.data.events;
  return Array.isArray(events) ? events.map(String) : [];
}

function toggleEvent(event: string, checked: boolean): void {
  const next = new Set(selectedEvents());
  if (checked) next.add(event);
  else next.delete(event);
  updateNodeData("events", Array.from(next));
}

function hasNoShowEvent(): boolean {
  return selectedEvents().some((event) => noShowEvents.has(event));
}

function updateNoShowTime(value: string | number): void {
  const parsed = Number(value);
  if (Number.isInteger(parsed) && parsed >= 1) updateNodeData("noShowTime", parsed);
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div class="space-y-2">
        <Label>Setup mode</Label>
        <Select
          :model-value="selectedNode.data.setupMode || 'manual'"
          :options="setupModeOptions"
          @update:model-value="updateNodeData('setupMode', $event)"
        />
      </div>

      <template v-if="(selectedNode.data.setupMode || 'manual') === 'manual'">
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
            No credential set — Cal.com requests will be rejected
          </p>
          <p
            v-else
            class="text-xs text-muted-foreground"
          >
            Must match the secret configured on the Cal.com webhook.
          </p>
        </div>
      </template>

      <template v-else>
        <div class="space-y-2">
          <Label>Cal.com API Credential</Label>
          <Select
            :model-value="selectedNode.data.calApiCredentialId || ''"
            :options="calApiCredentialOptions"
            placeholder="Select Cal.com API credential"
            @update:model-value="updateNodeData('calApiCredentialId', $event)"
          />
        </div>

        <div class="space-y-2">
          <Label>Events</Label>
          <div class="max-h-48 space-y-1 overflow-y-auto rounded-md border p-2">
            <label
              v-for="event in calWebhookEvents"
              :key="event"
              class="flex cursor-pointer items-center gap-2 text-xs"
            >
              <input
                type="checkbox"
                :checked="selectedEvents().includes(event)"
                @change="toggleEvent(event, ($event.target as HTMLInputElement).checked)"
              >
              <span class="font-mono">{{ event }}</span>
            </label>
          </div>
          <p
            v-if="selectedEvents().length === 0"
            class="text-xs text-amber-500"
          >
            Select at least one event.
          </p>
        </div>

        <div class="space-y-2">
          <Label>Payload version</Label>
          <Select
            :model-value="selectedNode.data.payloadVersion || '2021-10-20'"
            :options="payloadVersionOptions"
            @update:model-value="updateNodeData('payloadVersion', $event)"
          />
        </div>

        <div
          v-if="hasNoShowEvent()"
          class="space-y-2"
        >
          <Label>No-show evaluation delay</Label>
          <div class="grid grid-cols-2 gap-2">
            <Input
              type="number"
              min="1"
              :model-value="selectedNode.data.noShowTime || 5"
              @update:model-value="updateNoShowTime"
            />
            <Select
              :model-value="selectedNode.data.noShowTimeUnit || 'MINUTE'"
              :options="noShowTimeUnitOptions"
              @update:model-value="updateNodeData('noShowTimeUnit', $event)"
            />
          </div>
          <p class="text-xs text-muted-foreground">
            Required by Cal.com for host and guest Cal Video no-show events.
          </p>
        </div>

        <div class="space-y-2">
          <Label>Payload template (optional)</Label>
          <Textarea
            :model-value="selectedNode.data.payloadTemplate || ''"
            placeholder="Cal.com payload template"
            :rows="3"
            @update:model-value="updateNodeData('payloadTemplate', $event)"
          />
        </div>

        <label class="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            :checked="selectedNode.data.active !== false"
            @change="updateNodeData('active', ($event.target as HTMLInputElement).checked)"
          >
          Trigger enabled
        </label>

        <div class="space-y-2 rounded-md border p-3 text-xs">
          <div>
            Status:
            <span class="font-medium">{{ calSubscription?.status || 'not synced' }}</span>
          </div>
          <div
            v-if="calSubscription?.external_webhook_id"
            class="font-mono break-all"
          >
            ID: {{ calSubscription.external_webhook_id }}
          </div>
          <p
            v-if="calSubscriptionError"
            class="text-destructive"
          >
            {{ calSubscriptionError }}
          </p>
          <div class="flex gap-2">
            <Button
              size="sm"
              :disabled="calSubscriptionLoading || !selectedNode.data.calApiCredentialId || selectedEvents().length === 0 || selectedNode.data.active === false"
              @click="syncCalSubscription"
            >
              {{ calSubscriptionLoading ? 'Working…' : 'Save & Sync' }}
            </Button>
            <Button
              v-if="calSubscription?.external_webhook_id"
              variant="outline"
              size="sm"
              :disabled="calSubscriptionLoading"
              @click="deactivateCalSubscription"
            >
              Disable webhook
            </Button>
          </div>
        </div>
      </template>

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
          The managed mode registers this URL automatically. Cal.com Cloud requires a publicly
          reachable HTTPS URL; self-hosted Cal.com can use an internal HTTP URL.
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
