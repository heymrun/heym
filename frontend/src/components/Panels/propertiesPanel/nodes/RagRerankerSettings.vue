<script setup lang="ts">
import { computed } from "vue";
import { AlertTriangle } from "lucide-vue-next";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";
import { buildRerankerCredentialOptions, rerankerUsesDecisionModel } from "./ragReranker";

const { selectedNode, cohereCredentials, decisionCredentials, updateNodeData } =
  usePropertiesPanelContext();

const rerankerCredentialId = computed(
  (): string | undefined => selectedNode.value?.data.rerankerCredentialId || undefined,
);

const credentialOptions = computed(() =>
  buildRerankerCredentialOptions(
    cohereCredentials.value,
    decisionCredentials.value,
    rerankerCredentialId.value,
  ),
);

const usesDecisionModel = computed((): boolean =>
  rerankerUsesDecisionModel(
    cohereCredentials.value,
    decisionCredentials.value,
    rerankerCredentialId.value,
    selectedNode.value?.data.rerankerModel,
  ),
);
</script>

<template>
  <div
    v-if="selectedNode"
    class="space-y-3 pt-3 border-t"
  >
    <div class="flex items-center justify-between">
      <Label>Enable Reranker</Label>
      <label class="relative inline-flex items-center cursor-pointer">
        <input
          type="checkbox"
          :checked="selectedNode.data.enableReranker || false"
          class="sr-only peer"
          @change="updateNodeData('enableReranker', ($event.target as HTMLInputElement).checked)"
        >
        <div
          class="w-9 h-5 bg-muted rounded-full peer peer-checked:bg-primary transition-colors after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-4"
        />
      </label>
    </div>
    <p class="text-xs text-muted-foreground">
      Rerank results by relevance to the query with Cohere or a Decision Model
    </p>

    <template v-if="selectedNode.data.enableReranker">
      <div class="space-y-2">
        <Label>Reranker Credential</Label>
        <Select
          :model-value="selectedNode.data.rerankerCredentialId || ''"
          :options="credentialOptions"
          @update:model-value="updateNodeData('rerankerCredentialId', $event)"
        />
        <div v-if="!selectedNode.data.rerankerCredentialId">
          <p class="text-xs text-amber-500 flex items-center gap-1">
            <AlertTriangle class="h-3 w-3" />
            A Cohere or Decision Model credential is required for reranking
          </p>
          <p class="text-xs text-muted-foreground mt-1">
            <a
              href="/?tab=credentials"
              class="text-primary hover:underline"
              @click.prevent="$router.push('/?tab=credentials')"
            >Add a credential</a> in Dashboard
          </p>
        </div>
      </div>

      <div
        v-if="usesDecisionModel"
        class="space-y-2"
      >
        <Label>Decision Model</Label>
        <Input
          :model-value="selectedNode.data.rerankerModel || ''"
          placeholder="jev-latest"
          @update:model-value="updateNodeData('rerankerModel', $event)"
        />
        <p
          v-if="!(selectedNode.data.rerankerModel || '').trim()"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          Model is required
        </p>
        <p class="text-xs text-muted-foreground">
          Scores each result against the query in its own request
        </p>
      </div>

      <div class="space-y-2">
        <Label>Reranker Top N</Label>
        <Input
          type="number"
          :model-value="selectedNode.data.rerankerTopN || selectedNode.data.searchLimit || 5"
          placeholder="5"
          min="1"
          max="50"
          @update:model-value="updateNodeData('rerankerTopN', $event ? parseInt($event as string) : 5)"
        />
        <p class="text-xs text-muted-foreground">
          Number of top results to return after reranking
        </p>
      </div>
    </template>
  </div>
</template>
