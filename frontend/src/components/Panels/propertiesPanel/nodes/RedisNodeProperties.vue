<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  redisKeyInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  redisCredentialOptions,
  redisOperationOptions,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="redisCredentialOptions"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <div v-if="!selectedNode.data.credentialId">
        <p class="text-xs text-amber-500 flex items-center gap-1">
          <AlertTriangle class="h-3 w-3" />
          Credential is required.
        </p>
        <p class="text-xs text-muted-foreground mt-1">
          <a
            href="/?tab=credentials"
            class="text-primary hover:underline"
            @click.prevent="$router.push('/?tab=credentials')"
          >Add credentials</a> in Dashboard
        </p>
      </div>
    </div>

    <div class="space-y-2">
      <Label>Operation</Label>
      <SearchableSelect
        :model-value="selectedNode.data.redisOperation || ''"
        :options="redisOperationOptions"
        search-placeholder="Search Redis operations..."
        @update:model-value="updateNodeData('redisOperation', $event)"
      />
      <p
        v-if="!selectedNode.data.redisOperation"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Operation is required
      </p>
    </div>

    <div class="space-y-2">
      <Label>Key <span class="text-destructive">*</span></Label>
      <ExpressionInput
        ref="redisKeyInputRef"
        :model-value="selectedNode.data.redisKey || ''"
        placeholder="cache:$userInput.body.userId"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Key"
        field-key="redisKey"
        @update:model-value="updateNodeData('redisKey', $event)"
      />
      <p
        v-if="!selectedNode.data.redisKey || selectedNode.data.redisKey.trim() === ''"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Key is required
      </p>
      <p
        v-else
        class="text-xs text-muted-foreground"
      >
        Redis key (supports expressions)
      </p>
    </div>

    <template v-if="selectedNode.data.redisOperation === 'set'">
      <div class="space-y-2">
        <Label>Value</Label>
        <ExpressionInput
          :model-value="selectedNode.data.redisValue || ''"
          placeholder="$previousNode.data"
          :rows="2"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Value"
          field-key="redisValue"
          @update:model-value="updateNodeData('redisValue', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Value to store (supports expressions)
        </p>
      </div>

      <div class="space-y-2">
        <Label>TTL (seconds)</Label>
        <Input
          type="number"
          :model-value="selectedNode.data.redisTtl || ''"
          placeholder="3600 (optional)"
          min="0"
          @update:model-value="updateNodeData('redisTtl', $event ? parseInt($event as string) : undefined)"
        />
        <p class="text-xs text-muted-foreground">
          Time-to-live in seconds (leave empty for no expiration)
        </p>
      </div>
    </template>

    <div class="space-y-2 pt-2 border-t">
      <Label class="text-muted-foreground">Output</Label>
      <div class="text-xs font-mono space-y-1 text-muted-foreground">
        <template v-if="selectedNode.data.redisOperation === 'set'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.key - The key that was set</div>
          <div>${{ selectedNode.data.label }}.ttl - TTL value (or null)</div>
        </template>
        <template v-else-if="selectedNode.data.redisOperation === 'get'">
          <div>${{ selectedNode.data.label }}.value - Retrieved value</div>
          <div>${{ selectedNode.data.label }}.exists - Boolean</div>
          <div>${{ selectedNode.data.label }}.key - The key queried</div>
        </template>
        <template v-else-if="selectedNode.data.redisOperation === 'hasKey'">
          <div>${{ selectedNode.data.label }}.exists - Boolean</div>
          <div>${{ selectedNode.data.label }}.key - The key checked</div>
        </template>
        <template v-else-if="selectedNode.data.redisOperation === 'deleteKey'">
          <div>${{ selectedNode.data.label }}.deleted - Boolean</div>
          <div>${{ selectedNode.data.label }}.key - The key deleted</div>
        </template>
        <template v-else>
          <div>Select an operation to see output fields</div>
        </template>
      </div>
    </div>
  </template>
</template>
