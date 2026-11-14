<script setup lang="ts">
import { computed } from "vue";
import { Check, Copy, Server, Sparkles } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only.
// 0: default /api/mcp endpoint
// 1: new named server with /api/mcp/servers/{id}/mcp
// 2: legacy named server with /api/mcp/servers/{id}/sse preserved
// 3: copy config / one-click Cursor connection
const step = useCycleStep(4, 2200);

interface MockEndpointState {
  badge: string;
  badgeClass: string;
  serverName: string;
  path: string;
  transport: string;
}

const currentState = computed<MockEndpointState>(() => {
  switch (step.value) {
    case 0:
      return {
        badge: "Default Server",
        badgeClass: "bg-primary/10 text-primary",
        serverName: "Heym MCP Server",
        path: "/api/mcp",
        transport: "Streamable HTTP (2025-03-26)",
      };
    case 1:
      return {
        badge: "New Named Server",
        badgeClass: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
        serverName: "Production Agent",
        path: "/api/mcp/servers/9b2e.../mcp",
        transport: "Streamable HTTP (modern)",
      };
    case 2:
      return {
        badge: "Legacy Named Server",
        badgeClass: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
        serverName: "Legacy Integrations",
        path: "/api/mcp/servers/1a4c.../sse",
        transport: "SSE Handshake (preserved)",
      };
    default:
      return {
        badge: "Cursor & Claude",
        badgeClass: "bg-primary/10 text-primary",
        serverName: "Auto-generated Config",
        path: "/api/mcp/servers/9b2e.../mcp",
        transport: "Ready to paste or install",
      };
  }
});

const caption = computed<string>(() =>
  [
    "New connections default to the standardized /api/mcp endpoint",
    "New named servers use dedicated /api/mcp/servers/{id}/mcp routes",
    "Existing servers preserve /api/mcp/servers/{id}/sse with zero downtime",
    "Generated client configs and Cursor deep links point to the right URL",
  ][step.value],
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center justify-between text-[11px] leading-4 text-muted-foreground">
      <div class="flex items-center gap-1.5 font-medium text-foreground">
        <Server class="h-3.5 w-3.5 text-primary" />
        <span>{{ currentState.serverName }}</span>
      </div>
      <span
        class="rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors duration-300"
        :class="currentState.badgeClass"
      >
        {{ currentState.badge }}
      </span>
    </div>

    <div class="flex min-h-0 flex-1 flex-col justify-center rounded-md border border-border bg-muted/40 p-3 space-y-2.5">
      <div class="space-y-1">
        <div class="flex items-center justify-between text-[10px] text-muted-foreground">
          <span>MCP Endpoint URL</span>
          <span class="font-mono text-[9px]">{{ currentState.transport }}</span>
        </div>
        <div class="flex items-center gap-1.5 rounded border border-border bg-background px-2.5 py-1.5 font-mono text-[11px] text-foreground">
          <span class="truncate flex-1">{{ currentState.path }}</span>
          <span
            v-if="step === 3"
            class="flex items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 text-[9px] font-sans font-medium text-primary"
          >
            <Check class="h-2.5 w-2.5" /> Copied
          </span>
          <Copy
            v-else
            class="h-3 w-3 shrink-0 text-muted-foreground"
          />
        </div>
      </div>

      <div class="rounded border border-border/80 bg-background/80 p-2 text-[10px] space-y-1 font-mono text-muted-foreground">
        <div class="text-foreground font-semibold font-sans flex items-center gap-1">
          <Sparkles class="h-3 w-3 text-primary" />
          <span>Client Config</span>
        </div>
        <div class="truncate text-[9px]">
          "url": "https://heym.example.com{{ currentState.path }}"
        </div>
      </div>
    </div>

    <p class="shrink-0 truncate text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
