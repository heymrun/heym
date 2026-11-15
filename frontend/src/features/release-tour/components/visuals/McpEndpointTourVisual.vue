<script setup lang="ts">
import { computed } from "vue";
import { Check, Copy, Server, Sparkles } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only.
// 0: default /api/mcp endpoint
// 1: new named server with /api/mcp/servers/{id}/mcp
// 2: legacy named server with /api/mcp/servers/{id}/sse preserved
// 3: client config with right address
const step = useCycleStep(4, 2200);

interface MockEndpointState {
  badge: string;
  serverName: string;
  path: string;
  transport: string;
}

const currentState = computed<MockEndpointState>(() => {
  switch (step.value) {
    case 0:
      return {
        badge: "Default",
        serverName: "Heym Server",
        path: "/api/mcp",
        transport: "Streamable HTTP",
      };
    case 1:
      return {
        badge: "New server",
        serverName: "Production Agent",
        path: "/api/mcp/servers/9b2e/mcp",
        transport: "Streamable HTTP",
      };
    case 2:
      return {
        badge: "Existing server",
        serverName: "Legacy Server",
        path: "/api/mcp/servers/1a4c/sse",
        transport: "SSE preserved",
      };
    default:
      return {
        badge: "Cursor & Claude",
        serverName: "Client Config",
        path: "/api/mcp/servers/9b2e/mcp",
        transport: "Auto-generated",
      };
  }
});

const caption = computed<string>(() =>
  [
    "New MCP connections use /api/mcp",
    "New named servers get an address ending in /mcp",
    "Existing servers keep their /sse address",
    "Copy JSON and Add to Cursor use the right address",
  ][step.value],
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2 rounded-lg bg-card p-3">
    <div class="flex items-center justify-between text-[11px] leading-4 text-muted-foreground">
      <div class="flex items-center gap-1.5 font-medium text-foreground">
        <Server class="h-3 w-3 text-muted-foreground" />
        <span>{{ currentState.serverName }}</span>
      </div>
      <span class="rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
        {{ currentState.badge }}
      </span>
    </div>

    <div class="flex min-h-0 flex-1 flex-col justify-center rounded-md border border-border bg-muted/40 p-2.5 space-y-2">
      <div class="space-y-1">
        <div class="flex items-center justify-between text-[10px] text-muted-foreground">
          <span>MCP Endpoint URL</span>
          <span class="font-mono text-[9px]">{{ currentState.transport }}</span>
        </div>
        <div class="flex items-center gap-1.5 rounded border border-border bg-background px-2 py-1 font-mono text-[10.5px] text-foreground">
          <span class="truncate flex-1">{{ currentState.path }}</span>
          <span
            v-if="step === 3"
            class="flex items-center gap-1 rounded border border-border bg-muted px-1.5 py-0.5 text-[9px] font-sans font-medium text-foreground"
          >
            <Check class="h-2.5 w-2.5 text-muted-foreground" /> Copied
          </span>
          <Copy
            v-else
            class="h-3 w-3 shrink-0 text-muted-foreground"
          />
        </div>
      </div>

      <div class="rounded border border-border bg-background p-2 font-mono text-[10px] space-y-1 text-muted-foreground">
        <div class="text-foreground font-medium font-sans flex items-center gap-1 text-[10px]">
          <Sparkles class="h-3 w-3 text-muted-foreground" />
          <span>Config JSON</span>
        </div>
        <div class="break-all text-[9.5px] leading-snug text-foreground">
          "url": "http://localhost:4017{{ currentState.path }}"
        </div>
      </div>
    </div>

    <p class="shrink-0 text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
