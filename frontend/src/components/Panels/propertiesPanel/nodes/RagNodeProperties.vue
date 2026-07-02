<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  ragQueryInputRef,
  ragDocumentInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  vectorStoreOptions,
  ragDbTypeOptions,
  ragOperationOptions,
  cohereCredentialOptions,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Database</Label>
      <Select
        :model-value="selectedNode.data.dbType || 'qdrant'"
        :options="ragDbTypeOptions"
        @update:model-value="
          updateNodeData('dbType', $event);
          updateNodeData('vectorStoreId', '');
        "
      />
      <p class="text-xs text-muted-foreground">
        Qdrant uses an external server; Postgres (pgvector) stores vectors in
        Heym's own database.
      </p>
    </div>

    <div class="space-y-2">
      <Label>Vector Store</Label>
      <Select
        :model-value="selectedNode.data.vectorStoreId || ''"
        :options="vectorStoreOptions"
        @update:model-value="updateNodeData('vectorStoreId', $event)"
      />
      <div v-if="!selectedNode.data.vectorStoreId">
        <p class="text-xs text-amber-500 flex items-center gap-1">
          <AlertTriangle class="h-3 w-3" />
          Vector Store is required.
        </p>
        <p class="text-xs text-muted-foreground mt-1">
          <a
            href="/?tab=vectorstores"
            class="text-primary hover:underline"
            @click.prevent="$router.push('/?tab=vectorstores')"
          >Create a vector store</a> in Dashboard
        </p>
      </div>
    </div>

    <div class="space-y-2">
      <Label>Operation</Label>
      <SearchableSelect
        :model-value="selectedNode.data.ragOperation || ''"
        :options="ragOperationOptions"
        search-placeholder="Search RAG operations..."
        @update:model-value="updateNodeData('ragOperation', $event)"
      />
      <p
        v-if="!selectedNode.data.ragOperation"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Operation is required
      </p>
    </div>

    <template v-if="selectedNode.data.ragOperation === 'insert'">
      <div class="space-y-2">
        <Label>Document Content <span class="text-destructive">*</span></Label>
        <ExpressionInput
          ref="ragDocumentInputRef"
          :model-value="selectedNode.data.documentContent || ''"
          placeholder="$input.text"
          :rows="3"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Document content"
          field-key="documentContent"
          @update:model-value="updateNodeData('documentContent', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Text content to embed and store (supports expressions)
        </p>
      </div>

      <div class="space-y-2">
        <Label>Document Metadata (JSON)</Label>
        <Textarea
          :model-value="selectedNode.data.documentMetadata || '{}'"
          placeholder="{&quot;source&quot;: &quot;manual&quot;, &quot;category&quot;: &quot;faq&quot;}"
          :rows="3"
          @update:model-value="updateNodeData('documentMetadata', $event)"
        />
        <p class="text-xs text-muted-foreground">
          JSON metadata to associate with the document
        </p>
      </div>
    </template>

    <template v-if="selectedNode.data.ragOperation === 'search'">
      <div class="space-y-2">
        <Label>Query Text <span class="text-destructive">*</span></Label>
        <ExpressionInput
          ref="ragQueryInputRef"
          :model-value="selectedNode.data.queryText || ''"
          placeholder="$input.text"
          :rows="2"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Query text"
          field-key="queryText"
          @update:model-value="updateNodeData('queryText', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Query text to embed and search (supports expressions)
        </p>
      </div>

      <div class="space-y-2">
        <Label>Search Limit</Label>
        <Input
          type="number"
          :model-value="selectedNode.data.searchLimit || 5"
          placeholder="5"
          min="1"
          max="100"
          @update:model-value="updateNodeData('searchLimit', $event ? parseInt($event as string) : 5)"
        />
        <p class="text-xs text-muted-foreground">
          Number of results to return (default: 5)
        </p>
      </div>

      <div class="space-y-2">
        <Label>Metadata Filters (JSON)</Label>
        <Textarea
          :model-value="selectedNode.data.metadataFilters || '{}'"
          placeholder="{&quot;category&quot;: &quot;faq&quot;}"
          :rows="3"
          @update:model-value="updateNodeData('metadataFilters', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Filter results by metadata (exact match)
        </p>
      </div>

      <div class="space-y-3 pt-3 border-t">
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
          Use Cohere to rerank results for better relevance
        </p>

        <template v-if="selectedNode.data.enableReranker">
          <div class="space-y-2">
            <Label>Cohere Credential</Label>
            <Select
              :model-value="selectedNode.data.rerankerCredentialId || ''"
              :options="cohereCredentialOptions"
              @update:model-value="updateNodeData('rerankerCredentialId', $event)"
            />
            <div v-if="!selectedNode.data.rerankerCredentialId">
              <p class="text-xs text-amber-500 flex items-center gap-1">
                <AlertTriangle class="h-3 w-3" />
                Cohere credential required for reranking
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                <a
                  href="/?tab=credentials"
                  class="text-primary hover:underline"
                  @click.prevent="$router.push('/?tab=credentials')"
                >Add Cohere credential</a> in Dashboard
              </p>
            </div>
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

    <div class="space-y-2 pt-2 border-t">
      <Label class="text-muted-foreground">Output</Label>
      <div class="text-xs font-mono space-y-1 text-muted-foreground">
        <template v-if="selectedNode.data.ragOperation === 'insert'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.operation - "insert"</div>
          <div>${{ selectedNode.data.label }}.point_id - Vector ID</div>
        </template>
        <template v-else-if="selectedNode.data.ragOperation === 'search'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.operation - "search"</div>
          <div>${{ selectedNode.data.label }}.reranked - Boolean</div>
          <div>${{ selectedNode.data.label }}.results - Array of results</div>
          <div>${{ selectedNode.data.label }}.results[0].text - Document text</div>
          <div>${{ selectedNode.data.label }}.results[0].score - Similarity score</div>
          <div v-if="selectedNode.data.enableReranker">
            ${{ selectedNode.data.label }}.results[0].relevance_score - Reranker score
          </div>
          <div>${{ selectedNode.data.label }}.results[0].metadata - Metadata</div>
          <div>${{ selectedNode.data.label }}.count - Number of results</div>
        </template>
        <template v-else>
          <div>Select an operation to see output fields</div>
        </template>
      </div>
    </div>
  </template>
</template>
