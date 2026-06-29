<script setup lang="ts">
import { Loader2, Plug, Server } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  mcpCallConnectionEnvInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  handleMCPCallExpressionFieldNavigate,
  setMCPCallArgumentInputRef,
  onMCPCallRegisterExpressionFieldIndex,
  mcpCallArgumentKeys,
  mcpCallExpressionFieldCount,
  formatMCPJsonValue,
  mcpCallFetchState,
  updateMCPCallConnectionField,
  fetchMCPCallTools,
  selectMCPCallTool,
  updateMCPCallArgument,
  mcpCallSelectedTool,
  mcpCallToolOptions,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <!-- Connection -->
      <div class="space-y-2">
        <Label class="text-muted-foreground flex items-center gap-1">
          <Plug class="w-3.5 h-3.5" />
          MCP Connection
        </Label>
        <div class="rounded border p-3 space-y-2">
          <div class="flex gap-2">
            <div class="flex-1">
              <Label class="text-xs">Transport</Label>
              <Select
                :model-value="selectedNode.data.connection?.transport ?? 'sse'"
                :options="[
                  { value: 'stdio', label: 'stdio' },
                  { value: 'sse', label: 'SSE' },
                  { value: 'streamable_http', label: 'Streamable HTTP' },
                ]"
                @update:model-value="updateMCPCallConnectionField('transport', $event)"
              />
            </div>
            <div class="w-24">
              <Label class="text-xs">Timeout (s)</Label>
              <Input
                type="number"
                :model-value="String(selectedNode.data.connection?.timeoutSeconds ?? 30)"
                min="1"
                max="3600"
                placeholder="30"
                @update:model-value="updateMCPCallConnectionField('timeoutSeconds', parseInt($event, 10) || 30)"
              />
            </div>
          </div>
          <div>
            <Label class="text-xs">Label (optional)</Label>
            <Input
              :model-value="selectedNode.data.connection?.label ?? ''"
              placeholder="my-mcp-server"
              @update:model-value="updateMCPCallConnectionField('label', $event)"
            />
          </div>
          <template v-if="selectedNode.data.connection?.transport === 'stdio'">
            <div>
              <Label class="text-xs">Command</Label>
              <Input
                :model-value="selectedNode.data.connection?.command ?? ''"
                placeholder="npx"
                @update:model-value="updateMCPCallConnectionField('command', $event)"
              />
            </div>
            <div>
              <Label class="text-xs">Args (JSON array)</Label>
              <Textarea
                :model-value="formatMCPJsonValue(selectedNode.data.connection?.args, [])"
                placeholder="[&quot;-y&quot;, &quot;@modelcontextprotocol/server-filesystem&quot;]"
                :rows="2"
                wrap="off"
                class="overflow-x-auto whitespace-pre font-mono text-xs"
                @update:model-value="updateMCPCallConnectionField('args', $event)"
              />
            </div>
            <div>
              <Label class="text-xs">Env (JSON object)</Label>
              <ExpressionInput
                ref="mcpCallConnectionEnvInputRef"
                :model-value="formatMCPJsonValue(selectedNode.data.connection?.env, {})"
                placeholder="{&quot;API_KEY&quot;: &quot;your_key&quot;}"
                :rows="2"
                wrap="off"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="MCP env"
                @update:model-value="updateMCPCallConnectionField('env', $event)"
              />
            </div>
          </template>
          <template v-else-if="selectedNode.data.connection?.transport === 'sse' || selectedNode.data.connection?.transport === 'streamable_http'">
            <div>
              <Label class="text-xs">URL</Label>
              <Input
                :model-value="selectedNode.data.connection?.url ?? ''"
                :placeholder="selectedNode.data.connection?.transport === 'streamable_http' ? 'https://example.com/mcp' : 'https://example.com/mcp/sse'"
                @update:model-value="updateMCPCallConnectionField('url', $event)"
              />
            </div>
            <div>
              <Label class="text-xs">Headers (JSON object)</Label>
              <Textarea
                :model-value="formatMCPJsonValue(selectedNode.data.connection?.headers, {})"
                placeholder="{&quot;Authorization&quot;: &quot;Bearer ...&quot;}"
                :rows="2"
                wrap="off"
                class="overflow-x-auto whitespace-pre font-mono text-xs"
                @update:model-value="updateMCPCallConnectionField('headers', $event)"
              />
            </div>
          </template>
          <!-- Fetch tools button -->
          <div class="pt-2 flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              class="gap-1"
              :disabled="
                (selectedNode.data.connection?.transport === 'stdio' && !selectedNode.data.connection?.command) ||
                  ((selectedNode.data.connection?.transport === 'sse' || selectedNode.data.connection?.transport === 'streamable_http') && !selectedNode.data.connection?.url) ||
                  mcpCallFetchState.loading
              "
              @click="fetchMCPCallTools"
            >
              <Loader2
                v-if="mcpCallFetchState.loading"
                class="w-3.5 h-3.5 animate-spin"
              />
              <Server
                v-else
                class="w-3.5 h-3.5"
              />
              {{ mcpCallFetchState.loading ? "Connecting…" : "Fetch tools" }}
            </Button>
            <span
              v-if="mcpCallFetchState.error"
              class="text-xs text-destructive truncate min-w-0 flex-1"
              :title="mcpCallFetchState.error"
            >{{ mcpCallFetchState.error }}</span>
            <span
              v-else-if="mcpCallFetchState.tools.length > 0"
              class="text-xs text-muted-foreground"
            >{{ mcpCallFetchState.tools.length }} tool(s) found</span>
          </div>
        </div>
      </div>

      <!-- Tool selection (required) -->
      <div class="space-y-2">
        <Label class="text-xs flex items-center gap-1">
          Tool
          <span class="text-destructive">*</span>
        </Label>
        <Select
          :model-value="selectedNode.data.selectedTool ?? ''"
          :options="mcpCallToolOptions"
          :class="!selectedNode.data.selectedTool ? 'border-destructive' : ''"
          @update:model-value="selectMCPCallTool($event ?? '')"
        />
        <p
          v-if="!selectedNode.data.selectedTool"
          class="text-xs text-destructive"
        >
          A tool must be selected — this node will not run without one.
        </p>
        <p
          v-else-if="mcpCallSelectedTool?.description"
          class="text-xs text-muted-foreground leading-snug break-words"
        >
          {{ mcpCallSelectedTool.description }}
        </p>
      </div>

      <!-- Tool arguments -->
      <div
        v-if="mcpCallSelectedTool"
        class="space-y-2"
      >
        <Label class="text-xs text-muted-foreground">Arguments</Label>
        <div
          v-if="Object.keys(mcpCallSelectedTool.inputSchema?.properties ?? {}).length === 0"
          class="text-xs text-muted-foreground italic"
        >
          This tool takes no arguments.
        </div>
        <div
          v-for="(propDef, propKey) in (mcpCallSelectedTool.inputSchema?.properties ?? {})"
          :key="propKey"
          class="space-y-1"
        >
          <Label class="text-xs flex items-center gap-1">
            {{ propKey }}
            <span
              v-if="mcpCallSelectedTool.inputSchema?.required?.includes(String(propKey))"
              class="text-destructive"
            >*</span>
          </Label>
          <p
            v-if="propDef.description"
            class="text-xs text-muted-foreground leading-snug break-words"
          >
            {{ propDef.description }}
          </p>
          <ExpressionInput
            :ref="(el) => setMCPCallArgumentInputRef(String(propKey), el)"
            :model-value="String(selectedNode.data.toolArguments?.[propKey] ?? '')"
            placeholder="value or $expr"
            single-line
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            expandable
            navigation-enabled
            :navigation-index="mcpCallArgumentKeys.indexOf(String(propKey))"
            :navigation-total="mcpCallExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            :dialog-key-label="`MCP argument · ${String(propKey)}`"
            @update:model-value="updateMCPCallArgument(String(propKey), $event)"
            @navigate="handleMCPCallExpressionFieldNavigate"
            @register-field-index="onMCPCallRegisterExpressionFieldIndex"
          />
        </div>
        <p class="text-xs text-muted-foreground">
          Values support DSL expressions: <code class="bg-muted px-1 rounded">$nodeLabel.field</code>
        </p>
      </div>

      <!-- Output reference -->
      <div class="space-y-1 pt-2 border-t">
        <Label class="text-xs text-muted-foreground">Output</Label>
        <div class="text-xs font-mono">
          <div>${{ selectedNode.data.label }}.result — tool result (object or string)</div>
        </div>
      </div>
    </div>
  </template>
</template>
