<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { MessagesSquare, ToggleLeft, ToggleRight } from "lucide-vue-next";

import type { CredentialListItem, LLMModel } from "@/types/credential";
import type { MCPChatToolConfig, MCPChatToolUpdate } from "@/services/api";

import MCPA2AControls from "@/components/MCP/MCPA2AControls.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import { agentReachText } from "@/components/MCP/a2aLinks";
import { useAiDefaults } from "@/composables/useAiDefaults";
import { cn } from "@/lib/utils";
import { credentialsApi } from "@/services/api";

interface Props {
  chatTool: MCPChatToolConfig;
  credentials: CredentialListItem[];
  /** Rendered inside a named server panel, which uses tighter spacing. */
  compact?: boolean;
  /** The named server this card belongs to; null for the global server. */
  serverId?: string | null;
}

const props = withDefaults(defineProps<Props>(), { compact: false, serverId: null });

const emit = defineEmits<{
  update: [update: MCPChatToolUpdate];
  copy: [text: string, label: string];
}>();

const aiDefaults = useAiDefaults();

const models = ref<LLMModel[]>([]);
const loadingModels = ref(false);
const modelsError = ref(false);
const saving = ref(false);

const credentialOptions = computed(() =>
  props.credentials.map((credential) => ({
    value: credential.id,
    label: credential.name,
  })),
);

const modelOptions = computed(() =>
  models.value.map((model) => ({ value: model.id, label: model.id })),
);

/** The credential the tool actually runs with, falling back to the account preference. */
const effectiveCredentialId = computed<string | null>(() => {
  if (props.chatTool.credential_id) return props.chatTool.credential_id;
  return aiDefaults.resolveCredentialId(props.credentials, {}) ?? null;
});

/**
 * The model the tool actually runs with. Mirrors the backend fallback: a stored
 * model wins, otherwise the account's preferred model applies when it belongs to
 * the credential in use.
 */
const effectiveModel = computed<string | null>(() =>
  aiDefaults.resolveModel(effectiveCredentialId.value ?? "", models.value, {
    savedModel: props.chatTool.model,
  }),
);

const isConfigured = computed(
  () => Boolean(effectiveCredentialId.value) && Boolean(effectiveModel.value),
);

const statusText = computed(() => agentReachText(props.chatTool, isConfigured.value));

async function loadModels(credentialId: string | null): Promise<void> {
  models.value = [];
  modelsError.value = false;
  if (!credentialId) return;
  loadingModels.value = true;
  try {
    models.value = await credentialsApi.getModels(credentialId);
  } catch {
    modelsError.value = true;
  } finally {
    loadingModels.value = false;
  }
}

watch(effectiveCredentialId, (credentialId) => void loadModels(credentialId), {
  immediate: true,
});

function emitUpdate(update: MCPChatToolUpdate): void {
  saving.value = true;
  emit("update", update);
  saving.value = false;
}

function toggleEnabled(): void {
  const update: MCPChatToolUpdate = { enabled: !props.chatTool.enabled };
  // Turning it on with nothing stored persists whatever the account defaults resolve
  // to, so the saved config matches what the dropdowns already show.
  if (update.enabled) {
    if (!props.chatTool.credential_id && effectiveCredentialId.value) {
      update.credential_id = effectiveCredentialId.value;
    }
    if (!props.chatTool.model && effectiveModel.value) {
      update.model = effectiveModel.value;
    }
  }
  emitUpdate(update);
}

function onCredentialSelect(value: string | undefined): void {
  emitUpdate({ credential_id: value || null, model: null });
}

function onModelSelect(value: string | undefined): void {
  emitUpdate({ model: value || null });
}
</script>

<template>
  <div
    :class="cn(
      'rounded-lg border transition-colors',
      compact ? 'p-3' : 'p-4',
      chatTool.enabled ? 'border-primary/30 bg-primary/5' : 'border-dashed',
    )"
    data-testid="mcp-chat-tool-controls"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <div
          v-if="!compact"
          class="flex items-center justify-center w-9 h-9 rounded-md bg-primary/10 text-primary shrink-0"
        >
          <MessagesSquare class="w-4 h-4" />
        </div>
        <div class="min-w-0">
          <p :class="cn('font-medium', compact ? 'text-sm' : 'text-base')">
            Heym Agent
          </p>
          <p class="text-xs text-muted-foreground mt-0.5">
            {{ statusText }}
          </p>
        </div>
      </div>
      <button
        class="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
        :disabled="saving"
        :aria-pressed="chatTool.enabled"
        aria-label="Toggle the Heym Agent"
        data-testid="mcp-chat-tool-toggle"
        @click="toggleEnabled"
      >
        <ToggleRight
          v-if="chatTool.enabled"
          class="w-8 h-8 text-primary"
        />
        <ToggleLeft
          v-else
          class="w-8 h-8"
        />
      </button>
    </div>

    <p
      v-if="!compact"
      class="text-sm text-muted-foreground mt-3"
    >
      The Chat tab engine as one agent. MCP clients call it as the
      <code class="px-1 py-0.5 bg-muted rounded">heym_chat</code> tool; with A2A on, other agents
      send it tasks. It handles workflows, analytics, boards, schedules, docs, and anything the
      Chat tab picks up later. Every call lands in your Chat history.
    </p>

    <div
      v-if="chatTool.enabled"
      class="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3"
    >
      <div class="min-w-0">
        <label class="text-xs font-medium text-muted-foreground block mb-1.5">
          Credential
        </label>
        <SearchableSelect
          :model-value="effectiveCredentialId ?? ''"
          :options="credentialOptions"
          placeholder="Select credential..."
          search-placeholder="Search credentials..."
          empty-text="No LLM credentials found."
          select-class="h-9 rounded-md border-input bg-background shadow-none"
          content-class="z-[60]"
          data-testid="mcp-chat-tool-credential"
          @update:model-value="onCredentialSelect"
        />
      </div>
      <div class="min-w-0">
        <label class="text-xs font-medium text-muted-foreground block mb-1.5">
          Model
        </label>
        <SearchableSelect
          :model-value="effectiveModel ?? ''"
          :options="modelOptions"
          :placeholder="loadingModels ? 'Loading models...' : 'Select model...'"
          search-placeholder="Search models..."
          empty-text="No models found."
          :disabled="!effectiveCredentialId || loadingModels || modelsError"
          select-class="h-9 rounded-md border-input bg-background shadow-none"
          content-class="z-[60]"
          data-testid="mcp-chat-tool-model"
          @update:model-value="onModelSelect"
        />
      </div>
    </div>

    <p
      v-if="chatTool.enabled && modelsError"
      class="text-xs text-amber-600 dark:text-amber-400 mt-2"
    >
      This credential's model list could not be loaded. Pick another credential.
    </p>
    <p
      v-else-if="chatTool.enabled && !isConfigured"
      class="text-xs text-amber-600 dark:text-amber-400 mt-2"
    >
      The Heym Agent is on but calls will fail until a credential and model are selected.
    </p>
    <MCPA2AControls
      v-if="chatTool.enabled"
      :chat-tool="chatTool"
      :server-id="serverId"
      @update="emitUpdate"
      @copy="(text, label) => emit('copy', text, label)"
    />
  </div>
</template>
