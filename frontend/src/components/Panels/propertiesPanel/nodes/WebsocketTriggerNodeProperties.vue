<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  websocketTriggerEventOptions,
  selectedNode,
  updateNodeData,
  toggleWebSocketTriggerEvent,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div class="space-y-2">
        <Label>WebSocket URL</Label>
        <Input
          :model-value="selectedNode.data.websocketUrl || ''"
          placeholder="wss://example.com/socket"
          @update:model-value="updateNodeData('websocketUrl', $event)"
        />
        <p
          v-if="!selectedNode.data.websocketUrl || selectedNode.data.websocketUrl.trim() === ''"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          URL is required
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Heym opens an outbound client connection to this remote socket. This node does not expose a Heym webhook or server socket.
        </p>
      </div>

      <div class="space-y-2">
        <Label>Headers (JSON object)</Label>
        <Textarea
          :model-value="selectedNode.data.websocketHeaders || ''"
          placeholder="{&quot;Authorization&quot;: &quot;Bearer token&quot;}"
          :rows="4"
          class="font-mono text-xs"
          @update:model-value="updateNodeData('websocketHeaders', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Optional handshake headers as a JSON object. Leave empty if the socket does not require custom headers.
        </p>
      </div>

      <div class="space-y-2">
        <Label>Subprotocols</Label>
        <Input
          :model-value="selectedNode.data.websocketSubprotocols || ''"
          placeholder="json, graphql-ws"
          @update:model-value="updateNodeData('websocketSubprotocols', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Optional comma-separated subprotocol list sent during the WebSocket handshake.
        </p>
      </div>

      <div class="space-y-3 pt-2 border-t">
        <Label>Emitted Events</Label>
        <div class="space-y-3">
          <div
            v-for="option in websocketTriggerEventOptions"
            :key="option.value"
            class="rounded-lg border border-border/60 p-3 space-y-1"
          >
            <div class="flex items-center gap-2">
              <input
                :id="`websocket-trigger-event-${option.value}`"
                type="checkbox"
                class="h-4 w-4 rounded border-input bg-background"
                :checked="(selectedNode.data.websocketTriggerEvents || []).includes(option.value)"
                @change="toggleWebSocketTriggerEvent(option.value, ($event.target as HTMLInputElement).checked)"
              >
              <Label
                :for="`websocket-trigger-event-${option.value}`"
                class="text-sm font-medium"
              >
                {{ option.label }}
              </Label>
            </div>
            <p class="text-xs text-muted-foreground pl-6">
              {{ option.description }}
            </p>
          </div>
        </div>
        <p
          v-if="(selectedNode.data.websocketTriggerEvents || []).length === 0"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          Select at least one emitted event
        </p>
      </div>

      <div class="space-y-3 pt-2 border-t">
        <Label>Reconnect After Drop</Label>
        <div class="flex items-center gap-2">
          <input
            id="websocket-trigger-retry-enabled"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="selectedNode.data.retryEnabled !== false"
            @change="updateNodeData('retryEnabled', ($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="websocket-trigger-retry-enabled"
            class="text-sm font-normal"
          >
            Retry when the remote socket closes
          </Label>
        </div>

        <div
          v-if="selectedNode.data.retryEnabled !== false"
          class="space-y-2 pl-6"
        >
          <Label>Retry Wait (Seconds)</Label>
          <Input
            type="number"
            :model-value="selectedNode.data.retryWaitSeconds || 5"
            min="1"
            max="3600"
            class="w-28"
            @update:model-value="updateNodeData('retryWaitSeconds', $event ? parseInt($event as string) : 5)"
          />
          <p class="text-xs text-muted-foreground">
            After a drop, Heym waits this many seconds before opening the connection again.
          </p>
        </div>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Disable this to stop the trigger after the first disconnect.
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label class="text-xs text-muted-foreground">Available output fields</Label>
        <div class="text-xs text-muted-foreground space-y-1 font-mono">
          <div>${{ selectedNode.data.label }}.eventName — onMessage / onConnected / onClosed</div>
          <div>${{ selectedNode.data.label }}.url — connected socket URL</div>
          <div>${{ selectedNode.data.label }}.triggered_at — ISO timestamp</div>
          <div>${{ selectedNode.data.label }}.message.data — parsed JSON or raw message body</div>
          <div>${{ selectedNode.data.label }}.message.text — decoded text payload when available</div>
          <div>${{ selectedNode.data.label }}.message.base64 — binary payload as base64</div>
          <div>${{ selectedNode.data.label }}.connection.reconnected — true after a reconnect</div>
          <div>${{ selectedNode.data.label }}.connection.subprotocol — negotiated subprotocol</div>
          <div>${{ selectedNode.data.label }}.close.initiatedBy — server / client / unknown</div>
          <div>${{ selectedNode.data.label }}.close.code — close code</div>
          <div>${{ selectedNode.data.label }}.close.reason — close reason text</div>
        </div>
      </div>
    </div>
  </template>
</template>
