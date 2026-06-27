<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Copy,
  ExternalLink,
  Eye,
  EyeOff,
  Info,
  Plus,
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
import {
  mcpApi,
  mcpServersApi,
  type MCPConfigResponse,
  type MCPServerItem,
  type MCPWorkflowItem,
} from "@/services/api";

const router = useRouter();

const config = ref<MCPConfigResponse | null>(null);
const loading = ref(true);
const connectionTab = ref<"api-key" | "claude" | "openai">("api-key");
const showApiKey = ref(false);
const regenerating = ref(false);
const togglingWorkflowId = ref<string | null>(null);

const namedServers = ref<MCPServerItem[]>([]);
const expandedServer = ref<string | null>(null);
const newServerName = ref("");
const creatingServer = ref(false);
const allWorkflows = ref<MCPWorkflowItem[]>([]);
const showServerApiKey = ref<Record<string, boolean>>({});
const regeneratingServerKey = ref<string | null>(null);
const togglingServerWorkflow = ref<string | null>(null);

const toastMessage = ref("");
const toastVisible = ref(false);
const toastType = ref<"error" | "success">("success");

const enabledCount = computed(() => {
  return config.value?.workflows.filter((w) => w.mcp_enabled).length ?? 0;
});

const serverWorkflowsSorted = computed(() => {
  return [...allWorkflows.value].sort((a, b) => {
    const aTime = a.updated_at ?? "";
    const bTime = b.updated_at ?? "";
    if (aTime !== bTime) return bTime.localeCompare(aTime);
    return a.name.localeCompare(b.name);
  });
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
    allWorkflows.value = config.value.workflows;
    await loadNamedServers();
  } finally {
    loading.value = false;
  }
}

function serverSseUrl(serverId: string): string {
  return joinOriginAndPath(window.location.origin, `/api/mcp/servers/${serverId}/sse`);
}

async function loadNamedServers(): Promise<void> {
  const result = await mcpServersApi.list();
  namedServers.value = result.servers;
}

async function createServer(): Promise<void> {
  if (creatingServer.value || !newServerName.value.trim()) return;
  creatingServer.value = true;
  try {
    const server = await mcpServersApi.create(newServerName.value.trim());
    namedServers.value.push(server);
    newServerName.value = "";
    expandedServer.value = server.id;
    showToast(`Server "${server.name}" created`);
  } catch {
    showToast("Failed to create server", "error");
  } finally {
    creatingServer.value = false;
  }
}

async function deleteServer(server: MCPServerItem): Promise<void> {
  if (!confirm(`Delete server "${server.name}"? This cannot be undone.`)) return;
  try {
    await mcpServersApi.delete(server.id);
    namedServers.value = namedServers.value.filter((s) => s.id !== server.id);
    if (expandedServer.value === server.id) expandedServer.value = null;
    showToast(`Server "${server.name}" deleted`);
  } catch {
    showToast("Failed to delete server", "error");
  }
}

async function regenerateServerKey(server: MCPServerItem): Promise<void> {
  if (regeneratingServerKey.value) return;
  if (!confirm(`Regenerate API key for "${server.name}"? The current key will stop working.`)) return;
  regeneratingServerKey.value = server.id;
  try {
    const updated = await mcpServersApi.regenerateKey(server.id);
    const idx = namedServers.value.findIndex((s) => s.id === server.id);
    if (idx !== -1) namedServers.value[idx] = updated;
    showServerApiKey.value[server.id] = true;
    showToast("API key regenerated");
  } catch {
    showToast("Failed to regenerate key", "error");
  } finally {
    regeneratingServerKey.value = null;
  }
}

function toggleServerKeyVisibility(serverId: string): void {
  showServerApiKey.value[serverId] = !showServerApiKey.value[serverId];
}

function serverMcpConfigJson(server: MCPServerItem): string {
  return JSON.stringify(
    {
      mcpServers: {
        [server.name.toLowerCase().replace(/\s+/g, "_")]: {
          url: serverSseUrl(server.id),
          headers: {
            "X-MCP-Key": server.api_key,
          },
        },
      },
    },
    null,
    2,
  );
}

function addServerToCursor(server: MCPServerItem): void {
  const mcpConfig = {
    url: serverSseUrl(server.id),
    headers: { "X-MCP-Key": server.api_key },
  };
  const configBase64 = btoa(JSON.stringify(mcpConfig));
  window.open(
    `cursor://anysphere.cursor-deeplink/mcp/install?name=${encodeURIComponent(server.name)}&config=${configBase64}`,
    "_self",
  );
}

async function toggleServerWorkflow(server: MCPServerItem, workflowId: string): Promise<void> {
  if (togglingServerWorkflow.value) return;
  togglingServerWorkflow.value = workflowId;
  const enabled = !server.workflow_ids.includes(workflowId);
  try {
    await mcpServersApi.toggleWorkflow(server.id, workflowId, enabled);
    const idx = namedServers.value.findIndex((s) => s.id === server.id);
    if (idx !== -1) {
      const ids = [...namedServers.value[idx].workflow_ids];
      if (enabled) {
        ids.push(workflowId);
      } else {
        const wIdx = ids.indexOf(workflowId);
        if (wIdx !== -1) ids.splice(wIdx, 1);
      }
      namedServers.value[idx] = { ...namedServers.value[idx], workflow_ids: ids };
    }
  } catch {
    showToast("Failed to update workflow assignment", "error");
  } finally {
    togglingServerWorkflow.value = null;
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
  } catch {
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
  } catch {
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
              <button
                :class="cn(
                  'px-3 py-1.5 text-sm font-medium rounded-md transition-colors',
                  connectionTab === 'openai' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'
                )"
                @click="connectionTab = 'openai'"
              >
                ChatGPT Connector
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

            <div
              v-else-if="connectionTab === 'openai'"
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
                  <li>Open <strong class="text-foreground">chatgpt.com</strong> in your browser and go to Settings</li>
                  <li>Navigate to <strong class="text-foreground">Apps → Advanced settings</strong> and enable <strong class="text-foreground">Developer mode</strong></li>
                  <li>Go to <strong class="text-foreground">Settings → Apps → Create app</strong></li>
                  <li>Enter the name <strong class="text-foreground">Heym</strong> and paste the MCP Server URL above</li>
                  <li>Choose <strong class="text-foreground">OAuth</strong> for authentication — ChatGPT will register automatically</li>
                  <li>Click <strong class="text-foreground">Create</strong> and authorize with your Heym credentials</li>
                </ol>
              </div>

              <div class="flex items-start gap-2 p-3 rounded-md bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800/50 text-sm">
                <Info class="w-4 h-4 shrink-0 mt-0.5" />
                <span>ChatGPT uses OAuth 2.1 to securely authenticate. Your Heym credentials are used to authorize access and are never shared with ChatGPT. Developer mode is required to add custom MCP connectors.</span>
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

      <div>
        <div class="flex items-center justify-between mb-4">
          <div>
            <h3 class="font-semibold text-lg">
              Named MCP Servers
            </h3>
            <p class="text-sm text-muted-foreground mt-0.5">
              Create separate MCP endpoints and assign specific workflows to each
            </p>
          </div>
        </div>

        <div class="flex gap-2 mb-4">
          <input
            v-model="newServerName"
            type="text"
            placeholder="Server name (e.g. CRM Tools)"
            maxlength="100"
            class="flex-1 px-3 py-2 text-sm bg-background border rounded-md focus:outline-none focus:ring-2 focus:ring-primary/30"
            @keydown.enter="createServer"
          >
          <Button
            variant="default"
            size="sm"
            class="gap-2 shrink-0"
            :disabled="creatingServer || !newServerName.trim()"
            @click="createServer"
          >
            <Plus class="w-4 h-4" />
            Create
          </Button>
        </div>

        <div
          v-if="namedServers.length === 0"
          class="text-center py-8 border border-dashed rounded-lg"
        >
          <Server class="w-8 h-8 text-muted-foreground mx-auto mb-2" />
          <p class="text-sm text-muted-foreground">
            No named servers yet. Create one to get a dedicated MCP endpoint.
          </p>
        </div>

        <div
          v-else
          class="space-y-3"
        >
          <Card
            v-for="server in namedServers"
            :key="server.id"
            class="overflow-hidden"
          >
            <div
              class="flex items-center justify-between p-4 cursor-pointer hover:bg-muted/50 transition-colors"
              @click="expandedServer = expandedServer === server.id ? null : server.id"
            >
              <div class="flex items-center gap-3 min-w-0">
                <div class="flex items-center justify-center w-8 h-8 rounded-md bg-primary/10 text-primary shrink-0">
                  <Server class="w-4 h-4" />
                </div>
                <div class="min-w-0">
                  <p class="font-medium text-sm truncate">
                    {{ server.name }}
                  </p>
                  <p class="text-xs text-muted-foreground truncate">
                    {{ server.workflow_ids.length }} workflow{{ server.workflow_ids.length !== 1 ? 's' : '' }} assigned
                  </p>
                </div>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <button
                  class="p-1.5 rounded hover:bg-destructive/10 hover:text-destructive text-muted-foreground transition-colors"
                  title="Delete server"
                  @click.stop="deleteServer(server)"
                >
                  <X class="w-4 h-4" />
                </button>
                <ChevronDown
                  class="w-4 h-4 text-muted-foreground transition-transform"
                  :class="{ 'rotate-180': expandedServer === server.id }"
                />
              </div>
            </div>

            <div
              v-if="expandedServer === server.id"
              class="border-t px-4 pb-4 pt-3 space-y-4"
            >
              <div>
                <label class="text-xs font-medium text-muted-foreground block mb-1.5">SSE Endpoint</label>
                <div class="flex items-center gap-2">
                  <code class="flex-1 px-3 py-2 bg-muted rounded-md text-xs font-mono truncate">
                    {{ serverSseUrl(server.id) }}
                  </code>
                  <Button
                    variant="outline"
                    size="sm"
                    @click="copyToClipboard(serverSseUrl(server.id), 'Endpoint URL')"
                  >
                    <Copy class="w-4 h-4" />
                  </Button>
                </div>
              </div>

              <div>
                <label class="text-xs font-medium text-muted-foreground block mb-1.5">
                  API Key (X-MCP-Key header)
                </label>
                <div class="flex items-center gap-2 flex-wrap">
                  <div class="flex-1 min-w-0 flex items-center gap-2 px-3 py-2 bg-muted rounded-md">
                    <code class="text-xs font-mono truncate flex-1 min-w-0">
                      {{ showServerApiKey[server.id] ? server.api_key : server.api_key.slice(0, 8) + '...' + server.api_key.slice(-4) }}
                    </code>
                    <button
                      class="p-1 rounded hover:bg-background text-muted-foreground hover:text-foreground transition-colors shrink-0"
                      @click.stop="toggleServerKeyVisibility(server.id)"
                    >
                      <Eye
                        v-if="!showServerApiKey[server.id]"
                        class="w-4 h-4"
                      />
                      <EyeOff
                        v-else
                        class="w-4 h-4"
                      />
                    </button>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    class="shrink-0"
                    @click="copyToClipboard(server.api_key, 'API Key')"
                  >
                    <Copy class="w-4 h-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    class="shrink-0"
                    :disabled="regeneratingServerKey === server.id"
                    @click="regenerateServerKey(server)"
                  >
                    <RefreshCw
                      class="w-4 h-4"
                      :class="{ 'animate-spin': regeneratingServerKey === server.id }"
                    />
                  </Button>
                </div>
              </div>

              <div class="pt-1 border-t">
                <label class="text-xs font-medium text-muted-foreground block mb-2">How to connect</label>
                <div class="flex items-center gap-2 flex-wrap">
                  <Button
                    variant="outline"
                    size="sm"
                    class="gap-2"
                    @click="copyToClipboard(serverMcpConfigJson(server), 'MCP Configuration')"
                  >
                    <Copy class="w-4 h-4" />
                    Copy JSON
                  </Button>
                  <Button
                    variant="default"
                    size="sm"
                    class="gap-2 bg-black hover:bg-neutral-800 text-white border-0"
                    @click="addServerToCursor(server)"
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

              <div>
                <label class="text-xs font-medium text-muted-foreground block mb-2">Assigned Workflows</label>
                <div
                  v-if="serverWorkflowsSorted.length === 0"
                  class="text-xs text-muted-foreground italic"
                >
                  No workflows available. Create workflows to assign them here.
                </div>
                <div
                  v-else
                  class="space-y-1 max-h-48 overflow-y-auto pr-1"
                >
                  <div
                    v-for="workflow in serverWorkflowsSorted"
                    :key="workflow.id"
                    class="flex items-center justify-between gap-2 p-2 rounded-md hover:bg-muted/50 transition-colors cursor-pointer"
                    @click="toggleServerWorkflow(server, workflow.id)"
                  >
                    <span class="text-sm truncate flex-1">{{ workflow.name }}</span>
                    <button
                      class="shrink-0 text-muted-foreground"
                      :disabled="togglingServerWorkflow === workflow.id"
                    >
                      <ToggleRight
                        v-if="server.workflow_ids.includes(workflow.id)"
                        class="w-7 h-7 text-primary"
                        :class="{ 'animate-pulse': togglingServerWorkflow === workflow.id }"
                      />
                      <ToggleLeft
                        v-else
                        class="w-7 h-7"
                        :class="{ 'animate-pulse': togglingServerWorkflow === workflow.id }"
                      />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>
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