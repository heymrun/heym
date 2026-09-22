import { computed, ref, watch } from "vue";
import type { ComputedRef, Ref } from "vue";

import type {
  ExecutionToken,
  ExecutionTokenListItem,
  ExecutionTokenMetadata,
} from "@/types/workflow";

interface ExecutionTokenState {
  executionTokens: Ref<ExecutionTokenMetadata[]>;
  selectedTokenId: Ref<string | null>;
  tokenVisibility: Ref<Record<string, boolean>>;
  bearerToken: ComputedRef<string>;
  tokenValue: (token: ExecutionTokenMetadata) => string | undefined;
  canUseToken: (token: ExecutionTokenMetadata) => boolean;
  selectToken: (token: ExecutionTokenMetadata) => void;
  replaceTokens: (tokens: ExecutionTokenListItem[]) => void;
  rememberCreatedToken: (token: ExecutionToken) => void;
  markRevoked: (tokenId: string) => void;
}

function metadata(token: ExecutionTokenMetadata): ExecutionTokenMetadata {
  return {
    id: token.id,
    expires_at: token.expires_at,
    created_at: token.created_at,
    revoked: token.revoked,
  };
}

export function useExecutionTokens(workflowId: Readonly<Ref<string>>): ExecutionTokenState {
  const executionTokens = ref<ExecutionTokenMetadata[]>([]);
  const selectedTokenId = ref<string | null>(null);
  const tokenVisibility = ref<Record<string, boolean>>({});
  // Raw values exist only in this editor instance, never in metadata or browser storage.
  const createdTokenValues = ref<Record<string, string>>({});

  function tokenValue(token: ExecutionTokenMetadata): string | undefined {
    if (token.revoked || !(new Date(token.expires_at).getTime() > Date.now())) return undefined;
    return createdTokenValues.value[token.id];
  }

  function canUseToken(token: ExecutionTokenMetadata): boolean {
    return !!tokenValue(token);
  }

  function selectToken(token: ExecutionTokenMetadata): void {
    if (canUseToken(token)) selectedTokenId.value = token.id;
  }

  function updateSelection(): void {
    const selected = executionTokens.value.find((token) => token.id === selectedTokenId.value);
    if (!selected || !canUseToken(selected)) {
      selectedTokenId.value = executionTokens.value.find(canUseToken)?.id ?? null;
    }
  }

  function replaceTokens(tokens: ExecutionTokenListItem[]): void {
    executionTokens.value = tokens.map(metadata);
    const availableIds = new Set(tokens.filter(canUseToken).map((token) => token.id));
    for (const id of Object.keys(createdTokenValues.value)) {
      if (!availableIds.has(id)) {
        delete createdTokenValues.value[id];
        delete tokenVisibility.value[id];
      }
    }
    updateSelection();
  }

  function rememberCreatedToken(token: ExecutionToken): void {
    createdTokenValues.value[token.id] = token.token;
    executionTokens.value.unshift(metadata(token));
    selectToken(token);
  }

  function markRevoked(tokenId: string): void {
    const token = executionTokens.value.find((item) => item.id === tokenId);
    if (token) token.revoked = true;
    delete createdTokenValues.value[tokenId];
    delete tokenVisibility.value[tokenId];
    updateSelection();
  }

  watch(workflowId, () => {
    executionTokens.value = [];
    selectedTokenId.value = null;
    tokenVisibility.value = {};
    createdTokenValues.value = {};
  }, { flush: "sync" });

  const bearerToken = computed(() => {
    const token = executionTokens.value.find((item) => item.id === selectedTokenId.value);
    return (token && tokenValue(token)) || "<your-execution-token>";
  });

  return {
    executionTokens, selectedTokenId, tokenVisibility, bearerToken, tokenValue, canUseToken,
    selectToken, replaceTokens, rememberCreatedToken, markRevoked,
  };
}
