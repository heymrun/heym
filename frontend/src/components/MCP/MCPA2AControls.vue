<script setup lang="ts">
import { computed } from "vue";
import { Copy, Network } from "lucide-vue-next";

import type { MCPChatToolConfig, MCPChatToolUpdate } from "@/services/api";
import { a2aAgentCardUrl, a2aCurlExample, a2aEndpointUrl } from "@/components/MCP/a2aLinks";

interface Props {
  chatTool: MCPChatToolConfig;
  /** The named server; null for the global server. */
  serverId: string | null;
}

interface AddressRow {
  label: string;
  value: string;
  testId: string;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  update: [update: MCPChatToolUpdate];
  copy: [text: string, label: string];
}>();

const cardUrl = computed<string>(() => a2aAgentCardUrl(window.location.origin, props.serverId));

const rows = computed<AddressRow[]>(() => [
  { label: "Agent Card", value: cardUrl.value, testId: "mcp-a2a-card-url" },
  {
    label: "JSON-RPC endpoint",
    value: a2aEndpointUrl(window.location.origin, props.serverId),
    testId: "mcp-a2a-endpoint-url",
  },
]);

function onToggle(event: Event): void {
  emit("update", { a2a_enabled: (event.target as HTMLInputElement).checked });
}
</script>

<template>
  <div
    class="mt-3 border-t pt-3"
    data-testid="mcp-a2a-controls"
  >
    <label class="flex cursor-pointer items-start gap-2">
      <input
        type="checkbox"
        class="mt-0.5 h-4 w-4 accent-primary"
        :checked="chatTool.a2a_enabled"
        data-testid="mcp-a2a-toggle"
        @change="onToggle"
      >
      <span class="min-w-0">
        <span class="flex items-center gap-1.5 text-sm font-medium">
          <Network class="h-3.5 w-3.5" />
          Enable A2A
        </span>
        <span class="mt-0.5 block text-xs text-muted-foreground">
          Other agents can send the Heym Agent tasks over the Agent2Agent protocol (A2A 1.0).
          They authenticate with this server's key in the X-MCP-Key header, or with Heym OAuth.
        </span>
      </span>
    </label>

    <div
      v-if="chatTool.a2a_enabled"
      class="mt-3 space-y-2"
    >
      <div
        v-for="row in rows"
        :key="row.label"
        class="min-w-0"
      >
        <span class="mb-1 block text-xs font-medium text-muted-foreground">{{ row.label }}</span>
        <div class="flex items-center gap-2">
          <code
            class="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1 text-xs"
            :data-testid="row.testId"
          >{{ row.value }}</code>
          <button
            type="button"
            class="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
            :aria-label="`Copy the ${row.label}`"
            @click="emit('copy', row.value, row.label)"
          >
            <Copy class="h-4 w-4" />
          </button>
        </div>
      </div>
      <p class="text-xs text-muted-foreground">
        Check that the card is live:
        <code class="rounded bg-muted px-1 py-0.5">{{ a2aCurlExample(cardUrl) }}</code>
      </p>
    </div>
  </div>
</template>
