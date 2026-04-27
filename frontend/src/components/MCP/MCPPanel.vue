<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  AlertTriangle,
  Check,
  Copy,
  ExternalLink,
  Eye,
  EyeOff,
  Info,
  RefreshCw,
  Server,
  ToggleLeft,
  ToggleRight,
  Workflow,
  X,
} from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import { joinOriginAndPath } from "@/lib/appUrl";
import { cn } from "@/lib/utils";
import { mcpApi, type MCPConfigResponse, type MCPWorkflowItem } from "@/services/api";

const router = useRouter();

const config = ref<MCPConfigResponse | null>(null);
const loading = ref(true);
const connectionTab = ref<"api-key" | "claude">("api-key");
const showApiKey = ref(false);
const regenerating = ref(false);
const togglingWorkflowId = ref<string | null>(null);

const toastMessage = ref("");
const toastVisible = ref(false);
const toastType = ref<"error" | "success">("success");

const enabledCount = computed(() => {
  return config.value?.workflows.filter((w) => w.mcp_enabled).length ?? 0;
});

// Use browser's URL for SSE endpoint instead of backend-provided URL
const sseEndpointUrl = computed(() => {
  return joinOriginAndPath(window.location.origin, "/api/mcp/sse");
});

const maskedApiKey = computed(() => {
  if (!config.value?.mcp_api_key) return null;
  const key = config.value.mcp_api_key;
  return key.slice(0, 8) + "..." + key.slice(-4);
});

function showToast(message: string, type: "error" | "success" = "success"): void {
  toastMessage.value = message;
  toastType.value = type;
  toastVisible.value = true;
  setTimeout(() => {
    toastVisible.value = false;
  }, 4000);
}

onMounted(async () => {
  await loadConfig();
});

async function loadConfig(): Promise<void> {
  loading.value = true;
  try {
    config.value = await mcpApi.getConfig();
  } finally {
    loading.value = false;
  }
}

async function toggleWorkflow(workflow: MCPWorkflowItem): Promise<void> {
  if (togglingWorkflowId.value) return;

  togglingWorkflowId.value = workflow.id;
  try {
    const updated = await mcpApi.toggleWorkflow(workflow.id, !workflow.mcp_enabled);
    const index = config.value?.workflows.findIndex((w) => w.id === workflow.id);
    if (index !== undefined && index !== -1 && config.value) {
      config.value.workflows[index] = updated;
    }
    showToast(
      updated.mcp_enabled
        ? `"${workflow.name}" enabled for MCP`
        : `"${workflow.name}" disabled for MCP`,
    );
  } catch (error) {
    showToast("Failed to toggle workflow", "error");
  } finally {
    togglingWorkflowId.value = null;
  }
}

async function regenerateKey(): Promise<void> {
  if (regenerating.value) return;

  if (!confirm("Are you sure you want to regenerate your MCP API key? This will invalidate the current key.")) {
    return;
  }

  regenerating.value = true;
  try {
    const result = await mcpApi.regenerateKey();
    if (config.value) {
      config.value.mcp_api_key = result.mcp_api_key;
    }
    showApiKey.value = true;
    showToast("API key regenerated successfully");
  } catch (error) {
    showToast("Failed to regenerate API key", "error");
  } finally {
    regenerating.value = false;
  }
}

async function copyToClipboard(text: string, label: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    showToast(`${label} copied to clipboard`);
  } catch {
    showToast("Failed to copy to clipboard", "error");
  }
}

function openWorkflow(event: Event, workflowId: string): void {
  event.stopPropagation();
  router.push({ name: "editor", params: { id: workflowId } });
}

const mcpConfigJson = computed(() => {
  return JSON.stringify(
    {
      mcpServers: {
        heym: {
          url: sseEndpointUrl.value,
          headers: {
            "X-MCP-Key": config.value?.mcp_api_key || "YOUR_API_KEY",
          },
        },
      },
    },
    null,
    2,
  );
});

const cursorDeepLink = computed(() => {
  const mcpConfig = {
    url: sseEndpointUrl.value,
    headers: {
      "X-MCP-Key": config.value?.mcp_api_key || "YOUR_API_KEY",
    },
  };
  const configBase64 = btoa(JSON.stringify(mcpConfig));
  return `cursor://anysphere.cursor-deeplink/mcp/install?name=${encodeURIComponent("heym")}&config=${configBase64}`;
});

function addToCursor(): void {
  window.open(cursorDeepLink.value, "_self");
}
</script>

<template>
  <div class="overflow-x-hidden">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold tracking-tight">
          MCP Server
        </h2>
        <p class="text-muted-foreground mt-1">
          Expose your workflows as MCP tools for AI assistants
        </p>
      </div>
    </div>

    <div
      v-if="loading"
      class="space-y-4"
    >
      <Card class="p-6 animate-pulse">
        <div class="h-6 bg-muted rounded w-1/3 mb-4" />
        <div class="h-4 bg-muted rounded w-2/3" />
      </Card>
    </div>

    <div
      v-else-if="config"
      class="space-y-6"
    >
      <Card class="p-6">
        <div class="flex items-start gap-4">
          <div class="flex items-center justify-center w-12 h-12 rounded-lg bg-primary/10 text-primary shrink-0">
            <Server class="w-6 h-6" />
          </div>
          <div class="flex-1 min-w-0">
            <h3 class="font-semibold text-lg mb-1">
              MCP Connection
            </h3>
            <p class="text-sm text-muted-foreground mb-4">
              Connect your AI assistant to your workflows via MCP protocol.
            </p>

            <div class="flex gap-1 p-1 bg-muted rounded-lg mb-4 w-fit">
              <button
                :class="cn(
                  'px-3 py-1.5 text-sm font-medium rounded-md transition-colors',
                  connectionTab === 'api-key' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'
                )"
                @click="connectionTab = 'api-key'"
              >
                API Key
              </button>
              <button
                :class="cn(
                  'px-3 py-1.5 text-sm font-medium rounded-md transition-colors',
                  connectionTab === 'claude' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'
                )"
                @click="connectionTab = 'claude'"
              >
                Claude Connector
              </button>
            </div>

            <div
              v-if="connectionTab === 'api-key'"
              class="space-y-4"
            >
              <div>
                <label class="text-sm font-medium text-muted-foreground block mb-1.5">
                  SSE Endpoint URL
                </label>
                <div class="flex items-center gap-2">
                  <code class="flex-1 px-3 py-2 bg-muted rounded-md text-sm font-mono truncate">
                    {{ sseEndpointUrl }}
                  </code>
                  <Button
                    variant="outline"
                    size="sm"
                    @click="copyToClipboard(sseEndpointUrl, 'Endpoint URL')"
                  >
                    <Copy class="w-4 h-4" />
                  </Button>
                </div>
              </div>

              <div>
                <label class="text-sm font-medium text-muted-foreground block mb-1.5">
                  API Key (X-MCP-Key header)
                </label>
                <div class="flex items-center gap-2 flex-wrap">
                  <div class="flex-1 min-w-0 flex items-center gap-2 px-3 py-2 bg-muted rounded-md">
                    <code
                      v-if="config.mcp_api_key"
                      class="text-sm font-mono truncate flex-1 min-w-0"
                    >
                      {{ showApiKey ? config.mcp_api_key : maskedApiKey }}
                    </code>
                    <span
                      v-else
                      class="text-sm text-muted-foreground italic truncate flex-1 min-w-0"
                    >
                      No API key generated yet
                    </span>
                    <Button
                      v-if="config.mcp_api_key"
                      variant="ghost"
                      size="sm"
                      class="h-6 w-6 p-0 shrink-0"
                      @click="showApiKey = !showApiKey"
                    >
                      <Eye
                        v-if="!showApiKey"
                        class="w-4 h-4"
                      />
                      <EyeOff
                        v-else
                        class="w-4 h-4"
                      />
                    </Button>
                  </div>
                  <Button
                    v-if="config.mcp_api_key"
                    variant="outline"
                    size="sm"
                    class="shrink-0"
                    @click="copyToClipboard(config.mcp_api_key!, 'API Key')"
                  >
                    <Copy class="w-4 h-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    class="shrink-0"
                    :disabled="regenerating"
                    @click="regenerateKey"
                  >
                    <RefreshCw
                      class="w-4 h-4"
                      :class="{ 'animate-spin': regenerating }"
                    />
                    {{ config.mcp_api_key ? 'Regenerate' : 'Generate' }}
                  </Button>
                </div>
              </div>
            </div>

            <div
              v-else-if="connectionTab === 'claude'"
              class="space-y-4"
            >
              <div>
                <label class="text-sm font-medium text-muted-foreground block mb-1.5">
                  MCP Server URL
                </label>
                <div class="flex items-center gap-2">
                  <code class="flex-1 px-3 py-2 bg-muted rounded-md text-sm font-mono truncate">
                    {{ sseEndpointUrl }}
                  </code>
                  <Button
                    variant="outline"
                    size="sm"
                    @click="copyToClipboard(sseEndpointUrl, 'MCP Server URL')"
                  >
                    <Copy class="w-4 h-4" />
                  </Button>
                </div>
              </div>

              <div class="rounded-lg bg-muted/50 border p-4 space-y-3">
                <h4 class="font-medium text-sm">
                  Setup Instructions
                </h4>
                <ol class="text-sm text-muted-foreground space-y-2 list-decimal list-inside">
                  <li>Open <strong class="text-foreground">claude.ai</strong> and go to Settings</li>
                  <li>Navigate to <strong class="text-foreground">Integrations</strong></li>
                  <li>Click <strong class="text-foreground">Add custom connector</strong></li>
                  <li>Enter the name <strong class="text-foreground">Heym</strong> and paste the MCP Server URL above</li>
                  <li>Leave OAuth Client ID and Secret blank — Claude will register automatically</li>
                  <li>Click <strong class="text-foreground">Add</strong> and authorize with your Heym credentials</li>
                </ol>
              </div>

              <div class="flex items-start gap-2 p-3 rounded-md bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800/50 text-sm">
                <Info class="w-4 h-4 shrink-0 mt-0.5" />
                <span>Claude uses OAuth 2.1 to securely authenticate. Your Heym credentials are used to authorize access and are never shared with Claude.</span>
              </div>
            </div>
          </div>
        </div>
      </Card>

      <div>
        <div class="flex items-center justify-between mb-4">
          <h3 class="font-semibold text-lg">
            Available Workflows
          </h3>
          <span class="text-sm text-muted-foreground">
            {{ enabledCount }} of {{ config.workflows.length }} enabled
          </span>
        </div>

        <div
          v-if="config.workflows.length === 0"
          class="text-center py-12"
        >
          <div class="flex items-center justify-center w-16 h-16 rounded-full bg-muted mx-auto mb-4">
            <Workflow class="w-8 h-8 text-muted-foreground" />
          </div>
          <h4 class="text-lg font-medium mb-2">
            No workflows yet
          </h4>
          <p class="text-muted-foreground">
            Create workflows to expose them as MCP tools
          </p>
        </div>

        <div
          v-else
          class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
        >
          <Card
            v-for="workflow in config.workflows"
            :key="workflow.id"
            :class="cn(
              'p-4 transition-all cursor-pointer hover:border-primary/50',
              workflow.mcp_enabled && 'border-primary/30 bg-primary/5'
            )"
            @click="toggleWorkflow(workflow)"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-1">
                  <h4 class="font-medium truncate">
                    {{ workflow.name }}
                  </h4>
                  <button
                    class="p-1 rounded hover:bg-muted text-muted-foreground hover:text-primary transition-colors"
                    title="Open workflow"
                    @click="openWorkflow($event, workflow.id)"
                  >
                    <ExternalLink class="w-4 h-4" />
                  </button>
                </div>
                <p
                  v-if="workflow.description"
                  class="text-sm text-muted-foreground line-clamp-2 mb-2"
                >
                  {{ workflow.description }}
                </p>
                <p
                  v-else
                  class="text-sm text-muted-foreground italic mb-2"
                >
                  No description
                </p>
                <div
                  v-if="workflow.input_fields.length > 0"
                  class="flex flex-wrap gap-1"
                >
                  <span
                    v-for="field in workflow.input_fields.slice(0, 3)"
                    :key="field.key"
                    class="inline-flex items-center px-2 py-0.5 rounded text-xs bg-muted"
                  >
                    {{ field.key }}
                  </span>
                  <span
                    v-if="workflow.input_fields.length > 3"
                    class="text-xs text-muted-foreground"
                  >
                    +{{ workflow.input_fields.length - 3 }} more
                  </span>
                </div>
              </div>
              <div class="shrink-0">
                <button
                  class="text-muted-foreground hover:text-foreground transition-colors"
                  :disabled="togglingWorkflowId === workflow.id"
                >
                  <ToggleRight
                    v-if="workflow.mcp_enabled"
                    class="w-8 h-8 text-primary"
                    :class="{ 'animate-pulse': togglingWorkflowId === workflow.id }"
                  />
                  <ToggleLeft
                    v-else
                    class="w-8 h-8"
                    :class="{ 'animate-pulse': togglingWorkflowId === workflow.id }"
                  />
                </button>
              </div>
            </div>
          </Card>
        </div>
      </div>

      <Card
        v-if="connectionTab === 'api-key'"
        class="p-6 bg-muted/50 border-dashed"
      >
        <div class="flex items-center justify-between mb-2">
          <h4 class="font-medium">
            How to connect
          </h4>
          <div class="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              class="gap-2"
              @click="copyToClipboard(mcpConfigJson, 'MCP Configuration')"
            >
              <Copy class="w-4 h-4" />
              Copy JSON
            </Button>
            <Button
              variant="default"
              size="sm"
              class="gap-2 bg-black hover:bg-neutral-800 text-white border-0"
              @click="addToCursor"
            >
              <svg
                class="w-4 h-4"
                viewBox="0 0 100 100"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  d="M10 90L90 50L10 10V40L50 50L10 60V90Z"
                  fill="currentColor"
                />
              </svg>
              Add to Cursor
            </Button>
          </div>
        </div>
        <p class="text-sm text-muted-foreground mb-4">
          Add the following to your MCP client configuration (e.g., <code
            class="px-1 py-0.5 bg-muted rounded"
          >~/.cursor/mcp.json</code>):
        </p>
        <div class="relative group">
          <pre class="p-4 bg-background rounded-lg text-sm overflow-x-auto"><code>{{ mcpConfigJson }}</code></pre>
        </div>
      </Card>
    </div>

    <Transition
      enter-active-class="transition ease-out duration-300"
      enter-from-class="translate-y-2 opacity-0"
      enter-to-class="translate-y-0 opacity-100"
      leave-active-class="transition ease-in duration-200"
      leave-from-class="translate-y-0 opacity-100"
      leave-to-class="translate-y-2 opacity-0"
    >
      <div
        v-if="toastVisible"
        :class="cn(
          'fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg max-w-sm',
          toastType === 'error' ? 'bg-destructive text-destructive-foreground' : 'bg-emerald-600 text-white'
        )"
      >
        <AlertTriangle
          v-if="toastType === 'error'"
          class="w-5 h-5 shrink-0"
        />
        <Check
          v-else
          class="w-5 h-5 shrink-0"
        />
        <span class="text-sm font-medium">{{ toastMessage }}</span>
        <button
          class="ml-auto p-1 hover:bg-white/10 rounded"
          @click="toastVisible = false"
        >
          <X class="w-4 h-4" />
        </button>
      </div>
    </Transition>
  </div>
</template>