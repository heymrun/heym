<script setup lang="ts">
import { AlertTriangle, BookOpen, Braces, Brain, ExternalLink, FileArchive, Loader2, Plus, Server, ShieldAlert, Sparkles, Trash2 } from "lucide-vue-next";
import AgentSkillCard from "@/components/Panels/AgentSkillCard.vue";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import type { GuardrailCategory, ReasoningEffort } from "@/types/workflow";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  workflowOptions,
  subWorkflowSearch,
  filteredWorkflowOptionsForSubWorkflows,
  userMessageInputRef,
  agentSystemInstructionInputRef,
  agentImageExpressionInputRef,
  loadingModels,
  loadingGuardrailModels,
  loadingFallbackModels,
  jsonFormatError,
  guardrailCredentialOptions,
  guardrailModelOptions,
  handleGuardrailCredentialChange,
  handleGuardrailModelChange,
  fallbackCredentialOptions,
  fallbackModelOptions,
  handleFallbackCredentialChange,
  handleFallbackModelChange,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  handleAgentExpressionFieldNavigate,
  setAgentMCPEnvInputRef,
  agentMCPEnvExpressionIndex,
  onAgentRegisterExpressionFieldIndex,
  credentialOptions,
  modelOptions,
  reasoningEffortOptions,
  GUARDRAIL_CATEGORIES,
  GUARDRAIL_SEVERITY_OPTIONS,
  toggleGuardrailCategory,
  agentExpressionFieldCount,
  selectedModelIsReasoning,
  agentModelContextLimit,
  handleModelChange,
  handleCredentialChange,
  availableSubAgentLabels,
  toggleSubAgentLabel,
  toggleSubWorkflowId,
  openSubWorkflowEditor,
  addAgentTool,
  removeAgentTool,
  updateAgentTool,
  addAgentMCPConnection,
  removeAgentMCPConnection,
  updateAgentMCPConnection,
  formatMCPJsonValue,
  addAgentSkill,
  removeAgentSkill,
  updateAgentSkill,
  updateAgentSkillFile,
  removeAgentSkillFile,
  skillZipLoading,
  skillZipError,
  skillDownloadLoadingId,
  handleSkillZipDrop,
  downloadAgentSkill,
  expandedSkillIds,
  toggleSkillExpanded,
  openSkillBuilderNew,
  openSkillBuilderEdit,
  openSkillHistory,
  getMCPFetchState,
  fetchMCPTools,
  formatJsonSchema,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="credentialOptions"
        @update:model-value="handleCredentialChange($event)"
      />
      <p
        v-if="!selectedNode.data.credentialId"
        class="text-xs text-muted-foreground"
      >
        <a
          href="/?tab=credentials"
          class="text-primary hover:underline"
          @click.prevent="$router.push('/?tab=credentials')"
        >Add credentials</a> in Dashboard
      </p>
    </div>
    <div class="space-y-2">
      <Label>Model</Label>
      <Select
        :model-value="selectedNode.data.model || ''"
        :options="modelOptions"
        :disabled="!selectedNode.data.credentialId || loadingModels"
        @update:model-value="handleModelChange($event)"
      />
      <p
        v-if="agentModelContextLimit"
        class="text-xs text-muted-foreground"
      >
        {{ agentModelContextLimit }} context window
      </p>
    </div>
    <div class="space-y-2 pt-2 border-t">
      <div class="flex items-center gap-2">
        <input
          id="agent-persistent-memory"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="!!selectedNode.data.persistentMemoryEnabled"
          @change="updateNodeData('persistentMemoryEnabled', ($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="agent-persistent-memory"
          class="text-sm font-normal"
        >
          Persistent memory (graph)
        </Label>
      </div>
      <p class="text-xs text-muted-foreground">
        Each run loads this graph into the system prompt when non-empty; after the run, new facts merge in the background. Sub-agents use their own graph. Use the pink brain on the node to view or edit.
      </p>
    </div>
    <div class="space-y-2 pt-2 border-t">
      <Label>Fallback (optional)</Label>
      <p class="text-xs text-muted-foreground">
        If primary credential/model fails, retry with fallback.
      </p>
      <Select
        :model-value="selectedNode.data.fallbackCredentialId || ''"
        :options="fallbackCredentialOptions"
        @update:model-value="handleFallbackCredentialChange($event)"
      />
      <Select
        :model-value="selectedNode.data.fallbackModel || ''"
        :options="fallbackModelOptions"
        :disabled="!selectedNode.data.fallbackCredentialId || loadingFallbackModels"
        @update:model-value="handleFallbackModelChange($event)"
      />
    </div>
    <div class="space-y-2 pt-2 border-t">
      <Label>System Instruction</Label>
      <ExpressionInput
        ref="agentSystemInstructionInputRef"
        :model-value="selectedNode.data.systemInstruction || ''"
        placeholder="You are a helpful assistant..."
        :rows="4"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        expandable
        navigation-enabled
        :navigation-index="0"
        :navigation-total="agentExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="System instruction"
        field-key="systemInstruction"
        @update:model-value="updateNodeData('systemInstruction', $event)"
        @navigate="handleAgentExpressionFieldNavigate"
        @register-field-index="onAgentRegisterExpressionFieldIndex"
      />
    </div>
    <div class="space-y-2">
      <Label>User Message</Label>
      <ExpressionInput
        ref="userMessageInputRef"
        :model-value="selectedNode.data.userMessage || ''"
        :placeholder="exampleRef"
        :rows="3"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        expandable
        navigation-enabled
        :navigation-index="1"
        :navigation-total="agentExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="User message"
        field-key="userMessage"
        @update:model-value="updateNodeData('userMessage', $event)"
        @navigate="handleAgentExpressionFieldNavigate"
        @register-field-index="onAgentRegisterExpressionFieldIndex"
      />
    </div>
    <div class="space-y-2 pt-2 border-t">
      <Label>Image Input</Label>
      <div class="flex items-center gap-2">
        <input
          id="agent-image-input"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="!!selectedNode.data.imageInputEnabled"
          @change="updateNodeData('imageInputEnabled', ($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="agent-image-input"
          class="text-sm font-normal"
        >
          Include image input
        </Label>
      </div>
      <ExpressionInput
        v-if="selectedNode.data.imageInputEnabled"
        ref="agentImageExpressionInputRef"
        :model-value="selectedNode.data.imageInput || ''"
        placeholder="$input.imageUrl"
        :rows="2"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        expandable
        navigation-enabled
        :navigation-index="2"
        :navigation-total="agentExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Image input"
        field-key="imageInput"
        @update:model-value="updateNodeData('imageInput', $event)"
        @navigate="handleAgentExpressionFieldNavigate"
        @register-field-index="onAgentRegisterExpressionFieldIndex"
      />
      <p class="text-xs text-muted-foreground">
        Supports image URLs or base64 data URLs.
      </p>
    </div>
    <div class="space-y-3 pt-2 border-t">
      <div
        v-if="selectedModelIsReasoning"
        class="space-y-2"
      >
        <div class="flex items-center gap-2">
          <Brain class="w-4 h-4 text-purple-500" />
          <Label class="text-purple-500">Reasoning Model</Label>
        </div>
        <Select
          :model-value="(selectedNode.data.reasoningEffort as ReasoningEffort) || 'medium'"
          :options="reasoningEffortOptions"
          @update:model-value="updateNodeData('reasoningEffort', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Reasoning effort level (replaces temperature)
        </p>
      </div>
      <div
        v-else
        class="space-y-2"
      >
        <Label>Temperature</Label>
        <Input
          type="number"
          :model-value="selectedNode.data.temperature || 0.7"
          min="0"
          max="2"
          step="0.1"
          @update:model-value="updateNodeData('temperature', parseFloat($event as string))"
        />
      </div>
    </div>
    <div class="space-y-2 pt-2 border-t">
      <Label>Request Timeout (seconds)</Label>
      <Input
        type="number"
        :model-value="String(selectedNode.data.requestTimeoutSeconds ?? 60)"
        min="1"
        max="3600"
        placeholder="60"
        @update:model-value="updateNodeData('requestTimeoutSeconds', parseInt($event, 10) || 60)"
      />
      <p class="text-xs text-muted-foreground">
        Max seconds to wait for the model response before timing out
      </p>
    </div>
    <div class="space-y-2 pt-2 border-t">
      <div class="flex items-center gap-2">
        <input
          id="agent-orchestrator"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="!!selectedNode.data.isOrchestrator"
          @change="updateNodeData('isOrchestrator', ($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="agent-orchestrator"
          class="text-sm font-normal"
        >
          Orchestrator mode (can call sub-agents)
        </Label>
      </div>
      <p class="text-xs text-muted-foreground">
        When enabled, this agent can delegate tasks to other agent nodes in the workflow.
      </p>
      <div
        v-if="selectedNode.data.isOrchestrator"
        class="space-y-2 pt-2"
      >
        <Label class="text-xs">Sub-Agents</Label>
        <div
          v-if="availableSubAgentLabels.length === 0"
          class="text-xs text-muted-foreground"
        >
          Add more agent nodes to the workflow to select them as sub-agents.
        </div>
        <div
          v-else
          class="flex flex-col gap-2"
        >
          <div
            v-for="label in availableSubAgentLabels"
            :key="label"
            class="flex items-center gap-2"
          >
            <input
              :id="`sub-agent-${label}`"
              type="checkbox"
              class="h-4 w-4 rounded border-input bg-background"
              :checked="(selectedNode.data.subAgentLabels || []).includes(label)"
              @change="toggleSubAgentLabel(label, ($event.target as HTMLInputElement).checked)"
            >
            <Label
              :for="`sub-agent-${label}`"
              class="text-sm font-normal"
            >
              {{ label }}
            </Label>
          </div>
        </div>
      </div>
    </div>
    <div class="space-y-2 pt-2 border-t">
      <Label class="text-sm font-medium">Sub-Workflows</Label>
      <p class="text-xs text-muted-foreground">
        Workflows this agent can call as tools. The agent will receive a
        call_sub_workflow tool.
      </p>
      <div
        v-if="workflowOptions.length === 0"
        class="text-xs text-muted-foreground"
      >
        No other workflows available.
      </div>
      <template v-else>
        <Input
          v-model="subWorkflowSearch"
          placeholder="Search workflows..."
          class="h-8 text-sm"
        />
        <div class="max-h-48 overflow-y-auto overflow-x-hidden rounded-md border border-input bg-background">
          <div
            v-for="opt in filteredWorkflowOptionsForSubWorkflows"
            :key="opt.value"
            class="group flex items-center gap-2 px-3 py-2 hover:bg-muted/50 cursor-pointer"
            @click="toggleSubWorkflowId(opt.value, opt.label, !(selectedNode.data.subWorkflowIds || []).includes(opt.value))"
          >
            <input
              :id="`sub-workflow-${opt.value}`"
              type="checkbox"
              class="h-4 w-4 shrink-0 rounded border-input bg-background pointer-events-none"
              :checked="(selectedNode.data.subWorkflowIds || []).includes(opt.value)"
            >
            <Label
              class="text-sm font-normal flex-1 min-w-0 break-words select-none"
              :title="opt.label"
            >
              {{ opt.label }}
            </Label>
            <button
              type="button"
              class="p-1.5 h-7 w-7 rounded hover:bg-muted text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity duration-200 shrink-0"
              title="Open in new tab"
              @click.stop="openSubWorkflowEditor(opt.value)"
            >
              <ExternalLink :size="14" />
            </button>
          </div>
        </div>
        <p class="text-xs text-muted-foreground">
          {{ (selectedNode.data.subWorkflowIds || []).length }} selected
        </p>
      </template>
    </div>
    <div
      v-if="(selectedNode.data.tools || []).length > 0"
      class="space-y-2 pt-2 border-t"
    >
      <Label>Tool Timeout (seconds)</Label>
      <Input
        type="number"
        :model-value="String(selectedNode.data.toolTimeoutSeconds ?? 30)"
        min="1"
        max="3600"
        placeholder="30"
        @update:model-value="updateNodeData('toolTimeoutSeconds', parseInt($event, 10) || 30)"
      />
      <p class="text-xs text-muted-foreground">
        Max seconds per tool execution
      </p>
    </div>
    <div class="space-y-2 pt-2 border-t">
      <div class="flex items-center justify-between">
        <Label>Tools</Label>
        <Button
          variant="outline"
          size="sm"
          class="gap-1"
          @click="addAgentTool"
        >
          <Plus class="w-3.5 h-3.5" />
          Add Tool
        </Button>
      </div>
      <div
        v-for="(tool, idx) in (selectedNode.data.tools || [])"
        :key="idx"
        class="rounded border p-3 space-y-2"
      >
        <div class="flex justify-between items-center">
          <span class="text-sm font-medium">Tool {{ idx + 1 }}</span>
          <Button
            variant="ghost"
            size="sm"
            class="gap-1 text-destructive hover:text-destructive hover:bg-destructive/10"
            @click="removeAgentTool(idx)"
          >
            <Trash2 class="w-3.5 h-3.5" />
            Remove
          </Button>
        </div>
        <div class="space-y-2">
          <Label class="text-xs">Name</Label>
          <Input
            :model-value="tool.name"
            placeholder="count_characters"
            @update:model-value="updateAgentTool(idx, 'name', $event)"
          />
          <Label class="text-xs">Description</Label>
          <Textarea
            :model-value="tool.description"
            placeholder="Counts characters in the given text"
            :rows="2"
            @update:model-value="updateAgentTool(idx, 'description', $event)"
          />
          <Label class="text-xs">Parameters (JSON Schema)</Label>
          <Textarea
            :model-value="tool.parameters"
            placeholder="{ &quot;type&quot;: &quot;object&quot;, &quot;properties&quot;: { &quot;text&quot;: { &quot;type&quot;: &quot;string&quot; } }, &quot;required&quot;: [&quot;text&quot;] }"
            :rows="4"
            class="font-mono text-xs"
            @update:model-value="updateAgentTool(idx, 'parameters', $event)"
          />
          <Label class="text-xs">Python Code</Label>
          <Textarea
            :model-value="tool.code"
            placeholder="def count_characters(text: str) -> int:&#10;    return len(text)"
            :rows="4"
            class="font-mono text-xs"
            @update:model-value="updateAgentTool(idx, 'code', $event)"
          />
        </div>
      </div>
      <p class="text-xs text-muted-foreground">
        Python tools the agent can call. Optional.
      </p>
    </div>
    <div class="space-y-2 pt-2 border-t">
      <div class="flex items-center justify-between">
        <Label class="flex items-center gap-1">
          <Server class="w-3.5 h-3.5" />
          MCP Connections
        </Label>
        <Button
          variant="outline"
          size="sm"
          class="gap-1"
          @click="addAgentMCPConnection"
        >
          <Plus class="w-3.5 h-3.5" />
          Add MCP
        </Button>
      </div>
      <div
        v-for="(conn, idx) in (selectedNode.data.mcpConnections || [])"
        :key="conn.id"
        class="rounded border p-3 space-y-2"
      >
        <div class="flex justify-between items-center">
          <span class="text-sm font-medium">MCP {{ idx + 1 }}</span>
          <Button
            variant="ghost"
            size="sm"
            class="gap-1 text-destructive hover:text-destructive hover:bg-destructive/10"
            @click="removeAgentMCPConnection(idx)"
          >
            <Trash2 class="w-3.5 h-3.5" />
            Remove
          </Button>
        </div>
        <div class="space-y-2">
          <div class="flex gap-2">
            <div class="flex-1">
              <Label class="text-xs">Transport</Label>
              <Select
                :model-value="conn.transport"
                :options="[
                  { value: 'stdio', label: 'stdio' },
                  { value: 'sse', label: 'SSE' },
                  { value: 'streamable_http', label: 'Streamable HTTP' },
                ]"
                @update:model-value="updateAgentMCPConnection(idx, 'transport', $event)"
              />
            </div>
            <div class="w-24">
              <Label class="text-xs">Timeout (s)</Label>
              <Input
                type="number"
                :model-value="String(conn.timeoutSeconds ?? 30)"
                min="1"
                max="3600"
                placeholder="30"
                @update:model-value="updateAgentMCPConnection(idx, 'timeoutSeconds', parseInt($event, 10) || 30)"
              />
            </div>
          </div>
          <div>
            <Label class="text-xs">Label (optional)</Label>
            <Input
              :model-value="conn.label ?? ''"
              placeholder="filesystem"
              @update:model-value="updateAgentMCPConnection(idx, 'label', $event)"
            />
          </div>
          <template v-if="conn.transport === 'stdio'">
            <div>
              <Label class="text-xs">Command</Label>
              <Input
                :model-value="conn.command ?? ''"
                placeholder="npx"
                @update:model-value="updateAgentMCPConnection(idx, 'command', $event)"
              />
            </div>
            <div>
              <Label class="text-xs">Args (JSON array)</Label>
              <Textarea
                :model-value="formatMCPJsonValue(conn.args, [])"
                placeholder="[&quot;-y&quot;, &quot;@modelcontextprotocol/server-filesystem&quot;, &quot;--path&quot;, &quot;/tmp&quot;]"
                :rows="2"
                wrap="off"
                class="overflow-x-auto whitespace-pre font-mono text-xs"
                @update:model-value="updateAgentMCPConnection(idx, 'args', $event)"
              />
            </div>
            <div>
              <Label class="text-xs">Env (JSON object)</Label>
              <ExpressionInput
                :ref="(el) => setAgentMCPEnvInputRef(conn.id, el)"
                :model-value="formatMCPJsonValue(conn.env, {})"
                placeholder="{&quot;API_KEY&quot;: &quot;your_key&quot;}"
                :rows="2"
                wrap="off"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                navigation-enabled
                :navigation-index="agentMCPEnvExpressionIndex(conn.id)"
                :navigation-total="agentExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                :dialog-key-label="`MCP ${idx + 1} env`"
                @update:model-value="updateAgentMCPConnection(idx, 'env', $event)"
                @navigate="handleAgentExpressionFieldNavigate"
                @register-field-index="onAgentRegisterExpressionFieldIndex"
              />
            </div>
          </template>
          <template v-else-if="conn.transport === 'sse' || conn.transport === 'streamable_http'">
            <div>
              <Label class="text-xs">URL</Label>
              <Input
                :model-value="conn.url ?? ''"
                :placeholder="conn.transport === 'streamable_http' ? 'https://example.com/mcp' : 'https://example.com/mcp/sse'"
                @update:model-value="updateAgentMCPConnection(idx, 'url', $event)"
              />
            </div>
            <div>
              <Label class="text-xs">Headers (JSON object)</Label>
              <Textarea
                :model-value="formatMCPJsonValue(conn.headers, {})"
                placeholder="{&quot;Authorization&quot;: &quot;Bearer ...&quot;, &quot;X-Custom&quot;: &quot;value&quot;}"
                :rows="2"
                wrap="off"
                class="overflow-x-auto whitespace-pre font-mono text-xs"
                @update:model-value="updateAgentMCPConnection(idx, 'headers', $event)"
              />
            </div>
          </template>
          <div class="pt-2 flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              class="gap-1"
              :disabled="(conn.transport === 'stdio' && !conn.command) ||
                ((conn.transport === 'sse' || conn.transport === 'streamable_http') && !conn.url) ||
                getMCPFetchState(conn.id).loading
              "
              @click="fetchMCPTools(conn, idx)"
            >
              <Loader2
                v-if="getMCPFetchState(conn.id).loading"
                class="w-3.5 h-3.5 animate-spin"
              />
              <Server
                v-else
                class="w-3.5 h-3.5"
              />
              {{ getMCPFetchState(conn.id).loading ? "Connecting…" : "Fetch tools" }}
            </Button>
            <span
              v-if="getMCPFetchState(conn.id).error"
              class="text-xs text-destructive truncate min-w-0 flex-1"
              :title="getMCPFetchState(conn.id).error ?? undefined"
            >
              {{ getMCPFetchState(conn.id).error }}
            </span>
            <span
              v-else-if="getMCPFetchState(conn.id).tools.length > 0"
              class="text-xs text-muted-foreground"
            >
              {{ getMCPFetchState(conn.id).tools.length }} tool(s)
            </span>
          </div>
          <div
            v-if="getMCPFetchState(conn.id).tools.length > 0"
            class="rounded border bg-muted/30 p-2 space-y-1.5 max-h-32 overflow-y-auto"
          >
            <div
              v-for="t in getMCPFetchState(conn.id).tools"
              :key="t.name"
              class="space-y-0.5 text-xs"
            >
              <div class="font-medium text-foreground break-words">
                {{ t.name }}
              </div>
              <p
                v-if="t.description"
                class="text-muted-foreground leading-snug break-words"
              >
                {{ t.description }}
              </p>
            </div>
          </div>
        </div>
      </div>
      <p class="text-xs text-muted-foreground">
        MCP servers the agent can call. Optional. stdio: command + args. SSE / Streamable HTTP: url + headers.
      </p>
    </div>
    <div class="space-y-2 pt-2 border-t">
      <div class="flex items-center justify-between">
        <Label class="flex items-center gap-1">
          <BookOpen class="w-3.5 h-3.5" />
          Skills
        </Label>
        <div class="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            class="gap-1"
            @click="addAgentSkill"
          >
            <Plus class="w-3.5 h-3.5" />
            Add Skill
          </Button>
          <Button
            variant="outline"
            size="sm"
            class="gap-1 border-primary/30 text-primary hover:bg-primary/10 hover:text-primary"
            :disabled="!selectedNode?.data?.credentialId || !selectedNode?.data?.model"
            @click="openSkillBuilderNew"
          >
            <Sparkles class="w-3.5 h-3.5" />
            AI Build
          </Button>
        </div>
      </div>
      <div
        class="rounded border border-dashed p-4 text-center text-sm text-muted-foreground transition-colors hover:border-primary/50 hover:bg-muted/30"
        :class="{ 'opacity-50 pointer-events-none': skillZipLoading }"
        @dragenter.stop.prevent
        @dragover.stop.prevent
        @drop.prevent="(e: DragEvent) => {
          e.stopPropagation();
          const f = e.dataTransfer?.files?.[0];
          if (f) handleSkillZipDrop(f);
        }"
      >
        <FileArchive class="w-8 h-8 mx-auto mb-2 opacity-60" />
        Drop .zip or .md file here
      </div>
      <p
        v-if="skillZipError"
        class="text-xs text-destructive"
      >
        {{ skillZipError }}
      </p>
      <AgentSkillCard
        v-for="(skill, idx) in (selectedNode.data.skills || [])"
        :key="skill.id"
        :skill="skill"
        :index="idx"
        :expanded="expandedSkillIds.has(skill.id)"
        :ai-edit-disabled="!selectedNode?.data?.credentialId || !selectedNode?.data?.model"
        :download-loading="skillDownloadLoadingId === skill.id"
        @toggle-expand="toggleSkillExpanded(skill.id)"
        @ai-edit="openSkillBuilderEdit(skill)"
        @download="downloadAgentSkill(skill)"
        @remove="removeAgentSkill(idx)"
        @history="openSkillHistory(skill, idx)"
        @update:name="updateAgentSkill(idx, 'name', $event)"
        @update:timeout-seconds="updateAgentSkill(idx, 'timeoutSeconds', $event)"
        @update:content="updateAgentSkill(idx, 'content', $event)"
        @update:file-content="(fileIndex, value) => updateAgentSkillFile(idx, fileIndex, 'content', value)"
        @remove-file="removeAgentSkillFile(idx, $event)"
      />
      <p class="text-xs text-muted-foreground">
        SKILL.md instructions and optional Python files. Optional. Drop zip or add manually.
      </p>
    </div>

    <div class="space-y-2 pt-2 border-t">
      <Label>Human Review</Label>
      <div class="flex items-center gap-2">
        <input
          id="agent-hitl-enabled"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="!!selectedNode.data.hitlEnabled"
          @change="updateNodeData('hitlEnabled', ($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="agent-hitl-enabled"
          class="text-sm font-normal"
        >
          Pause for human review
        </Label>
      </div>
      <Label
        v-if="selectedNode.data.hitlEnabled"
        class="text-xs uppercase tracking-[0.24em] text-muted-foreground"
      >
        Approval Guidelines
      </Label>
      <ExpressionInput
        v-if="selectedNode.data.hitlEnabled"
        :model-value="selectedNode.data.hitlSummary || ''"
        placeholder="Describe when this agent should ask for approval..."
        :rows="3"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        expandable
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Approval guidelines"
        field-key="hitlSummary"
        @update:model-value="updateNodeData('hitlSummary', $event)"
      />
      <p class="text-xs text-muted-foreground">
        HITL adds a human-review tool to this agent. Use the system prompt plus this field
        to describe when approval is needed. Heym asks the model to interpret MCP approval
        scope from these instructions as `always`, `once`, or `never`. The reviewer-facing
        summary is generated from the agent's review request, not from this field. Use the
        extra review output on the canvas to notify Slack, email, or other nodes while the
        run is waiting. Review links expire after 168 hours.
      </p>
      <p
        v-if="selectedNode.data.hitlEnabled && selectedNode.data.jsonOutputEnabled"
        class="text-xs text-amber-500"
      >
        HITL works only with text-mode agent outputs in v1.
      </p>
    </div>

    <div class="space-y-2 pt-2 border-t">
      <Label>JSON Output Parser</Label>
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <input
            id="agent-json-output"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="!!selectedNode.data.jsonOutputEnabled"
            @change="updateNodeData('jsonOutputEnabled', ($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="agent-json-output"
            class="text-sm font-normal"
          >
            Enable JSON output
          </Label>
        </div>
        <Button
          v-if="selectedNode.data.jsonOutputEnabled"
          variant="ghost"
          size="sm"
          :class="['h-11 min-h-[44px] md:h-7 px-2 gap-1.5', jsonFormatError ? 'text-red-500' : '']"
          :title="jsonFormatError ? 'Invalid JSON' : 'Format JSON'"
          @click="formatJsonSchema"
        >
          <Braces class="w-3.5 h-3.5" />
          <span class="text-xs">{{ jsonFormatError ? 'Invalid' : 'Format' }}</span>
        </Button>
      </div>
      <Textarea
        v-if="selectedNode.data.jsonOutputEnabled"
        :model-value="selectedNode.data.jsonOutputSchema || ''"
        placeholder="{ &quot;type&quot;: &quot;object&quot;, &quot;properties&quot;: { &quot;answer&quot;: { &quot;type&quot;: &quot;string&quot; } }, &quot;required&quot;: [&quot;answer&quot;] }"
        :rows="6"
        class="font-mono text-xs"
        @update:model-value="updateNodeData('jsonOutputSchema', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Provide a JSON schema to shape the agent's final response.
      </p>
    </div>

    <div class="space-y-4 pt-4 border-t">
      <div class="flex items-center gap-2">
        <input
          id="agent-guardrails-enabled"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="!!selectedNode.data.guardrailsEnabled"
          @change="updateNodeData('guardrailsEnabled', ($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="agent-guardrails-enabled"
          class="text-sm font-normal flex items-center gap-1.5"
        >
          <ShieldAlert class="w-3.5 h-3.5 text-amber-500" />
          Enable Guardrails
        </Label>
      </div>

      <template v-if="selectedNode.data.guardrailsEnabled">
        <div class="space-y-3 pl-6">
          <div
            v-if="!selectedNode.data.guardrailCredentialId || !selectedNode.data.guardrailModel"
            class="flex items-start gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 p-2 text-amber-600 dark:text-amber-400"
          >
            <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
            <p class="text-xs">
              Guardrail credential and model are required. The workflow cannot run until both are selected.
            </p>
          </div>
          <div class="space-y-2">
            <Label class="text-xs text-muted-foreground uppercase tracking-wide">Guardrail Credential</Label>
            <Select
              :model-value="selectedNode.data.guardrailCredentialId || ''"
              :options="guardrailCredentialOptions"
              @update:model-value="handleGuardrailCredentialChange($event)"
            />
            <p class="text-xs text-muted-foreground">
              Select a credential (e.g. OpenAI) for content safety. Required when guardrails are enabled.
            </p>
          </div>
          <div class="space-y-2">
            <Label class="text-xs text-muted-foreground uppercase tracking-wide">Guardrail Model</Label>
            <Select
              :model-value="selectedNode.data.guardrailModel || ''"
              :options="guardrailModelOptions"
              :disabled="loadingGuardrailModels"
              @update:model-value="handleGuardrailModelChange($event)"
            />
          </div>
          <div class="space-y-2">
            <Label class="text-xs text-muted-foreground uppercase tracking-wide">Blocked Categories</Label>
            <div class="grid grid-cols-1 gap-1.5">
              <div
                v-for="cat in GUARDRAIL_CATEGORIES"
                :key="cat.value"
                class="flex items-center gap-2"
              >
                <input
                  :id="`agent-guardrail-${cat.value}`"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background"
                  :checked="(selectedNode.data.guardrailsCategories || []).includes(cat.value as GuardrailCategory)"
                  @change="toggleGuardrailCategory(($event.target as HTMLInputElement).checked, cat.value as GuardrailCategory)"
                >
                <Label
                  :for="`agent-guardrail-${cat.value}`"
                  class="text-xs font-normal"
                >
                  {{ cat.label }}
                </Label>
              </div>
            </div>
          </div>

          <div class="space-y-2 pt-1">
            <Label class="text-xs text-muted-foreground uppercase tracking-wide">Sensitivity</Label>
            <Select
              :model-value="selectedNode.data.guardrailsSeverity || 'medium'"
              :options="GUARDRAIL_SEVERITY_OPTIONS"
              @update:model-value="updateNodeData('guardrailsSeverity', $event)"
            />
            <p class="text-xs text-muted-foreground">
              <span v-if="(selectedNode.data.guardrailsSeverity || 'medium') === 'low'">
                Low — flag even borderline cases
              </span>
              <span v-else-if="(selectedNode.data.guardrailsSeverity || 'medium') === 'medium'">
                Medium — flag clear violations
              </span>
              <span v-else>
                High — only flag extreme violations
              </span>
            </p>
          </div>
        </div>
        <p class="text-xs text-muted-foreground">
          If the user message matches a blocked category, the agent will throw an error instead of running.
        </p>
      </template>
    </div>
  </template>
</template>
