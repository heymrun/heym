<script setup lang="ts">
import { computed } from "vue";
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

const SCOPES = [
  { value: "all", label: "Every event the app receives" },
  { value: "messages", label: "Messages in channels and DMs" },
  { value: "directMessages", label: "Direct messages to the bot" },
  { value: "mentions", label: "Mentions of the bot" },
  { value: "channel", label: "Messages in one channel" },
];

const scope = computed((): string => String(selectedNode.value?.data.slackEventScope || "all"));
// One URL per credential: every Slack Trigger on it hears the app's events.
const eventsUrl = computed((): string => {
  const credentialId = String(selectedNode.value?.data.credentialId || "");
  return credentialId ? `${window.location.origin}/api/slack/events/${credentialId}` : "";
});

function copyEventsUrl(): void {
  void navigator.clipboard.writeText(eventsUrl.value);
}
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
        <Label>Start on</Label>
        <Select
          :model-value="scope"
          :options="SCOPES"
          @update:model-value="updateNodeData('slackEventScope', $event)"
        />
        <Input
          v-if="scope === 'channel'"
          :model-value="selectedNode.data.slackEventChannel || ''"
          placeholder="Channel ID, e.g. C0123ABCD"
          @update:model-value="updateNodeData('slackEventChannel', $event)"
        />
        <p class="text-xs text-muted-foreground">
          DMs need the app's Messages tab and the message.im event; the Slack Bot manifest sets both.
        </p>
      </div>

      <div
        v-if="eventsUrl"
        class="space-y-2"
      >
        <Label>Events URL for this credential</Label>
        <div class="flex gap-2">
          <Input
            :model-value="eventsUrl"
            readonly
            class="font-mono text-xs"
          />
          <Button
            variant="outline"
            size="sm"
            @click="copyEventsUrl"
          >
            Copy
          </Button>
        </div>
        <p class="text-xs text-muted-foreground">
          Recommended. A Slack app has one Request URL; this one starts every Slack Trigger that uses this credential.
        </p>
      </div>

      <div class="space-y-2">
        <Label>Webhook URL for this workflow only</Label>
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
