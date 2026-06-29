<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import AgentFieldToggle from "@/components/ui/AgentFieldToggle.vue";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  isWorkflowOwner,
  supabaseDiscoveredColumns,
  loadingSupabaseTables,
  loadingSupabaseColumns,
  supabaseSchemaExpressionInputRef,
  supabaseTableExpressionInputRef,
  supabaseSelectColumnsExpressionInputRef,
  supabaseFilterExpressionInputRef,
  supabaseOrderByExpressionInputRef,
  supabaseRowsExpressionInputRef,
  supabaseOnConflictExpressionInputRef,
  supabaseDataExpressionInputRef,
  loadSupabaseTablesForSelectedNode,
  loadSupabaseColumnsForSelectedNode,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  supabaseExpressionFieldCount,
  handleSupabaseExpressionFieldNavigate,
  onSupabaseRegisterExpressionFieldIndex,
  supabaseCredentialOptions,
  supabaseOperationOptions,
  supabaseDiscoveredTableOptions,
  parseSupabaseSelectedColumns,
  toggleSupabaseSelectedColumn,
  useAllDiscoveredSupabaseColumns,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Supabase Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="supabaseCredentialOptions"
        :disabled="!isWorkflowOwner"
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
      <Select
        :model-value="selectedNode.data.supabaseOperation || ''"
        :options="supabaseOperationOptions"
        @update:model-value="updateNodeData('supabaseOperation', $event)"
      />
    </div>

    <div class="space-y-2">
      <Label>Schema</Label>
      <ExpressionInput
        ref="supabaseSchemaExpressionInputRef"
        :model-value="selectedNode.data.supabaseSchema ?? 'public'"
        placeholder="public"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="supabaseSchema"
        :navigation-enabled="supabaseExpressionFieldCount > 1"
        :navigation-index="0"
        :navigation-total="supabaseExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Schema"
        @update:model-value="updateNodeData('supabaseSchema', $event)"
        @navigate="handleSupabaseExpressionFieldNavigate"
        @register-field-index="onSupabaseRegisterExpressionFieldIndex"
      />
    </div>

    <div class="space-y-2">
      <Label>Table</Label>
      <ExpressionInput
        ref="supabaseTableExpressionInputRef"
        :model-value="selectedNode.data.supabaseTable || ''"
        placeholder="users"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="supabaseTable"
        :navigation-enabled="supabaseExpressionFieldCount > 1"
        :navigation-index="1"
        :navigation-total="supabaseExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Table"
        @update:model-value="updateNodeData('supabaseTable', $event)"
        @navigate="handleSupabaseExpressionFieldNavigate"
        @register-field-index="onSupabaseRegisterExpressionFieldIndex"
      />
      <div class="flex items-center gap-2">
        <Select
          :model-value="String(selectedNode.data.supabaseTable || '')"
          :options="supabaseDiscoveredTableOptions"
          placeholder="Discovered tables..."
          :disabled="loadingSupabaseTables || supabaseDiscoveredTableOptions.length === 0"
          @update:model-value="updateNodeData('supabaseTable', $event || '')"
        />
        <Button
          variant="outline"
          size="sm"
          class="shrink-0"
          :loading="loadingSupabaseTables"
          :disabled="!selectedNode.data.credentialId"
          @click="loadSupabaseTablesForSelectedNode"
        >
          Refresh
        </Button>
      </div>
    </div>

    <template v-if="selectedNode.data.supabaseOperation === 'select'">
      <div class="space-y-2">
        <Label>Select Columns</Label>
        <ExpressionInput
          ref="supabaseSelectColumnsExpressionInputRef"
          :model-value="selectedNode.data.supabaseSelectColumns || '*'"
          placeholder="id,name,email"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="supabaseSelectColumns"
          :navigation-enabled="supabaseExpressionFieldCount > 1"
          :navigation-index="2"
          :navigation-total="supabaseExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Select Columns"
          @update:model-value="updateNodeData('supabaseSelectColumns', $event)"
          @navigate="handleSupabaseExpressionFieldNavigate"
          @register-field-index="onSupabaseRegisterExpressionFieldIndex"
        />
        <div class="flex items-center justify-between gap-2">
          <p class="text-xs text-muted-foreground">
            Discover columns from the selected table, then click to add or remove them.
          </p>
          <div class="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              class="shrink-0"
              :loading="loadingSupabaseColumns"
              :disabled="!selectedNode.data.credentialId || !selectedNode.data.supabaseTable"
              @click="loadSupabaseColumnsForSelectedNode"
            >
              Refresh
            </Button>
            <Button
              variant="ghost"
              size="sm"
              class="shrink-0"
              :disabled="supabaseDiscoveredColumns.length === 0"
              @click="useAllDiscoveredSupabaseColumns"
            >
              Use all
            </Button>
          </div>
        </div>
        <div
          v-if="supabaseDiscoveredColumns.length > 0"
          class="flex flex-wrap gap-2"
        >
          <button
            v-for="columnName in supabaseDiscoveredColumns"
            :key="columnName"
            type="button"
            :class="[
              'rounded-full border px-2 py-1 text-xs transition-colors',
              parseSupabaseSelectedColumns(String(selectedNode.data.supabaseSelectColumns || '*')).includes(columnName)
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border text-muted-foreground hover:text-foreground hover:border-border/80'
            ]"
            @click="toggleSupabaseSelectedColumn(columnName)"
          >
            {{ columnName }}
          </button>
        </div>
      </div>

      <div class="space-y-2">
        <Label>Filter (JSON object)</Label>
        <ExpressionInput
          ref="supabaseFilterExpressionInputRef"
          :model-value="selectedNode.data.supabaseFilter || '{}'"
          placeholder="{&quot;status&quot;:&quot;active&quot;}"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="supabaseFilter"
          :navigation-enabled="supabaseExpressionFieldCount > 1"
          :navigation-index="3"
          :navigation-total="supabaseExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Filter"
          @update:model-value="updateNodeData('supabaseFilter', $event)"
          @navigate="handleSupabaseExpressionFieldNavigate"
          @register-field-index="onSupabaseRegisterExpressionFieldIndex"
        />
      </div>

      <div class="space-y-2">
        <div class="flex items-center justify-between gap-2">
          <Label>Limit <span class="text-muted-foreground font-normal">(0 = unlimited)</span></Label>
          <AgentFieldToggle
            :node-id="selectedNode.id"
            field-key="supabaseLimit"
          />
        </div>
        <input
          type="number"
          min="0"
          :value="selectedNode.data.supabaseLimit ?? '100'"
          placeholder="100"
          class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          @input="updateNodeData('supabaseLimit', String(($event.target as HTMLInputElement).value))"
        >
      </div>

      <div class="space-y-2">
        <Label>Order By</Label>
        <ExpressionInput
          ref="supabaseOrderByExpressionInputRef"
          :model-value="selectedNode.data.supabaseOrderBy || ''"
          placeholder="created_at"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="supabaseOrderBy"
          :navigation-enabled="supabaseExpressionFieldCount > 1"
          :navigation-index="4"
          :navigation-total="supabaseExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Order By"
          @update:model-value="updateNodeData('supabaseOrderBy', $event)"
          @navigate="handleSupabaseExpressionFieldNavigate"
          @register-field-index="onSupabaseRegisterExpressionFieldIndex"
        />
        <label class="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            class="rounded border-input"
            :checked="selectedNode.data.supabaseAscending !== false"
            @change="updateNodeData('supabaseAscending', ($event.target as HTMLInputElement).checked)"
          >
          Ascending sort
        </label>
      </div>
    </template>

    <template v-else-if="selectedNode.data.supabaseOperation === 'insert' || selectedNode.data.supabaseOperation === 'upsert'">
      <div class="flex items-center gap-2 rounded-md border border-input p-1">
        <button
          :class="[
            'flex-1 rounded text-xs py-1 transition-colors',
            (selectedNode.data.supabaseRowsInputMode || 'raw') === 'raw'
              ? 'bg-primary text-primary-foreground font-medium'
              : 'text-muted-foreground hover:text-foreground'
          ]"
          @click="updateNodeData('supabaseRowsInputMode', 'raw')"
        >
          JSON array
        </button>
        <button
          :class="[
            'flex-1 rounded text-xs py-1 transition-colors',
            selectedNode.data.supabaseRowsInputMode === 'auto'
              ? 'bg-primary text-primary-foreground font-medium'
              : 'text-muted-foreground hover:text-foreground'
          ]"
          @click="updateNodeData('supabaseRowsInputMode', 'auto')"
        >
          Auto-map input
        </button>
      </div>

      <div class="space-y-2">
        <template v-if="(selectedNode.data.supabaseRowsInputMode || 'raw') === 'raw'">
          <Label>Rows (JSON array)</Label>
          <ExpressionInput
            ref="supabaseRowsExpressionInputRef"
            :model-value="selectedNode.data.supabaseRows || '[]'"
            placeholder="[{&quot;name&quot;:&quot;$input.name&quot;}]"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="supabaseRows"
            :navigation-enabled="supabaseExpressionFieldCount > 1"
            :navigation-index="2"
            :navigation-total="supabaseExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Rows"
            @update:model-value="updateNodeData('supabaseRows', $event)"
            @navigate="handleSupabaseExpressionFieldNavigate"
            @register-field-index="onSupabaseRegisterExpressionFieldIndex"
          />
        </template>
        <template v-else>
          <Label>Auto-map rows</Label>
          <p class="text-xs text-muted-foreground">
            Uses the single upstream input automatically. Objects become one row; arrays
            of objects or upstream <code class="font-mono">rows</code> arrays become many rows.
          </p>
          <div class="space-y-2">
            <div class="flex items-center justify-between gap-2">
              <Label class="text-xs text-muted-foreground">Ignore fields</Label>
              <AgentFieldToggle
                :node-id="selectedNode.id"
                field-key="supabaseIgnoredInputFields"
              />
            </div>
            <Input
              :model-value="String(selectedNode.data.supabaseIgnoredInputFields || '')"
              placeholder="id, created_at"
              @input="updateNodeData('supabaseIgnoredInputFields', String(($event.target as HTMLInputElement).value))"
            />
          </div>
        </template>
      </div>

      <div
        v-if="selectedNode.data.supabaseOperation === 'upsert'"
        class="space-y-2"
      >
        <Label>On Conflict</Label>
        <ExpressionInput
          ref="supabaseOnConflictExpressionInputRef"
          :model-value="selectedNode.data.supabaseOnConflict || ''"
          placeholder="id or tenant_id,email"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="supabaseOnConflict"
          :navigation-enabled="supabaseExpressionFieldCount > 1"
          :navigation-index="(selectedNode.data.supabaseRowsInputMode || 'raw') === 'raw' ? 3 : 2"
          :navigation-total="supabaseExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="On Conflict"
          @update:model-value="updateNodeData('supabaseOnConflict', $event)"
          @navigate="handleSupabaseExpressionFieldNavigate"
          @register-field-index="onSupabaseRegisterExpressionFieldIndex"
        />
        <p class="text-xs text-muted-foreground">
          Optional comma-separated conflict target columns passed to PostgREST
          `on_conflict`.
        </p>
      </div>
    </template>

    <template v-else-if="selectedNode.data.supabaseOperation === 'update'">
      <div class="flex items-center gap-2 rounded-md border border-input p-1">
        <button
          :class="[
            'flex-1 rounded text-xs py-1 transition-colors',
            (selectedNode.data.supabaseDataInputMode || 'raw') === 'raw'
              ? 'bg-primary text-primary-foreground font-medium'
              : 'text-muted-foreground hover:text-foreground'
          ]"
          @click="updateNodeData('supabaseDataInputMode', 'raw')"
        >
          JSON object
        </button>
        <button
          :class="[
            'flex-1 rounded text-xs py-1 transition-colors',
            selectedNode.data.supabaseDataInputMode === 'auto'
              ? 'bg-primary text-primary-foreground font-medium'
              : 'text-muted-foreground hover:text-foreground'
          ]"
          @click="updateNodeData('supabaseDataInputMode', 'auto')"
        >
          Auto-map input
        </button>
      </div>

      <div class="space-y-2">
        <template v-if="(selectedNode.data.supabaseDataInputMode || 'raw') === 'raw'">
          <Label>Data (JSON object)</Label>
          <ExpressionInput
            ref="supabaseDataExpressionInputRef"
            :model-value="selectedNode.data.supabaseData || '{}'"
            placeholder="{&quot;status&quot;:&quot;processed&quot;}"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="supabaseData"
            :navigation-enabled="supabaseExpressionFieldCount > 1"
            :navigation-index="2"
            :navigation-total="supabaseExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Data"
            @update:model-value="updateNodeData('supabaseData', $event)"
            @navigate="handleSupabaseExpressionFieldNavigate"
            @register-field-index="onSupabaseRegisterExpressionFieldIndex"
          />
        </template>
        <template v-else>
          <Label>Auto-map update data</Label>
          <p class="text-xs text-muted-foreground">
            Uses the single upstream object as the update payload. Ignore any fields you
            do not want to write.
          </p>
          <div class="space-y-2">
            <div class="flex items-center justify-between gap-2">
              <Label class="text-xs text-muted-foreground">Ignore fields</Label>
              <AgentFieldToggle
                :node-id="selectedNode.id"
                field-key="supabaseIgnoredInputFields"
              />
            </div>
            <Input
              :model-value="String(selectedNode.data.supabaseIgnoredInputFields || '')"
              placeholder="id, created_at"
              @input="updateNodeData('supabaseIgnoredInputFields', String(($event.target as HTMLInputElement).value))"
            />
          </div>
        </template>
      </div>

      <div class="space-y-2">
        <Label>Filter (JSON object)</Label>
        <ExpressionInput
          ref="supabaseFilterExpressionInputRef"
          :model-value="selectedNode.data.supabaseFilter || '{}'"
          placeholder="{&quot;id&quot;:123}"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="supabaseFilter"
          :navigation-enabled="supabaseExpressionFieldCount > 1"
          :navigation-index="(selectedNode.data.supabaseDataInputMode || 'raw') === 'raw' ? 3 : 2"
          :navigation-total="supabaseExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Filter"
          @update:model-value="updateNodeData('supabaseFilter', $event)"
          @navigate="handleSupabaseExpressionFieldNavigate"
          @register-field-index="onSupabaseRegisterExpressionFieldIndex"
        />
        <p class="text-xs text-muted-foreground">
          Supports exact matches plus operator objects like
          <code class="font-mono">{&quot;created_at&quot;:{&quot;gte&quot;:&quot;2026-01-01&quot;}}</code>
          and logical groups like
          <code class="font-mono">{&quot;or&quot;:[{&quot;status&quot;:&quot;active&quot;},{&quot;score&quot;:{&quot;gte&quot;:10}}]}</code>.
        </p>
      </div>
    </template>

    <template v-else-if="selectedNode.data.supabaseOperation === 'delete'">
      <div class="space-y-2">
        <Label>Filter (JSON object)</Label>
        <ExpressionInput
          ref="supabaseFilterExpressionInputRef"
          :model-value="selectedNode.data.supabaseFilter || '{}'"
          placeholder="{&quot;id&quot;:123}"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="supabaseFilter"
          :navigation-enabled="supabaseExpressionFieldCount > 1"
          :navigation-index="2"
          :navigation-total="supabaseExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Filter"
          @update:model-value="updateNodeData('supabaseFilter', $event)"
          @navigate="handleSupabaseExpressionFieldNavigate"
          @register-field-index="onSupabaseRegisterExpressionFieldIndex"
        />
      </div>
    </template>

    <div class="rounded-md bg-muted/40 border p-3 space-y-1">
      <p class="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        Output
      </p>
      <div class="text-xs font-mono space-y-0.5">
        <div>${{ selectedNode.data.label }}.rows - Returned row objects</div>
        <div>${{ selectedNode.data.label }}.count - Number of affected rows</div>
        <div>${{ selectedNode.data.label }}.success - Boolean success flag</div>
      </div>
    </div>
  </template>
</template>
