<script setup lang="ts">
import { AlertTriangle, RefreshCw } from "lucide-vue-next";
import AgentFieldToggle from "@/components/ui/AgentFieldToggle.vue";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  loadingNotionDataSources,
  notionDataSourcesError,
  notionDataSourceSearch,
  notionDataSourcesHasMore,
  loadingNotionPages,
  notionPagesError,
  notionPageSearch,
  notionPagesHasMore,
  notionQueryExpressionInputRef,
  notionPageIdExpressionInputRef,
  notionDatabaseIdExpressionInputRef,
  notionDatabaseExpressionInputRef,
  notionDataSourceIdExpressionInputRef,
  notionDataSourceExpressionInputRef,
  notionBlockIdExpressionInputRef,
  notionPropertiesExpressionInputRef,
  notionParentPageIdExpressionInputRef,
  notionBlockExpressionInputRef,
  notionIconExpressionInputRef,
  notionCoverExpressionInputRef,
  notionChildrenExpressionInputRef,
  notionFilterExpressionInputRef,
  notionSortExpressionInputRef,
  notionSortsExpressionInputRef,
  notionStartCursorExpressionInputRef,
  notionAfterBlockIdExpressionInputRef,
  loadNotionDataSourcesForSelectedNode,
  loadNotionPagesForSelectedNode,
  selectedNode,
  notionExpressionNavBindings,
  handleNotionExpressionFieldNavigate,
  onNotionRegisterExpressionFieldIndex,
  notionCredentialOptions,
  notionOperationOptions,
  notionDataSourceOptions,
  notionAppendPositionOptions,
  notionPageOptions,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="notionCredentialOptions"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <p
        v-if="!selectedNode.data.credentialId"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Notion credential is required.
      </p>
    </div>

    <div class="space-y-2">
      <Label>Operation</Label>
      <Select
        :model-value="selectedNode.data.notionOperation || ''"
        :options="notionOperationOptions"
        @update:model-value="updateNodeData('notionOperation', $event)"
      />
    </div>

    <div
      v-if="selectedNode.data.notionOperation === 'search'"
      class="space-y-2"
    >
      <Label>Search Query</Label>
      <ExpressionInput
        ref="notionQueryExpressionInputRef"
        :model-value="selectedNode.data.notionQuery || ''"
        placeholder="Roadmap"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionQuery"
        v-bind="notionExpressionNavBindings('notionQuery')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionQuery', $event)"
      />
    </div>

    <div
      v-if="['getPage', 'updatePage', 'trashPage', 'restorePage'].includes(selectedNode.data.notionOperation || '')"
      class="space-y-2"
    >
      <Label>Page ID</Label>
      <ExpressionInput
        ref="notionPageIdExpressionInputRef"
        :model-value="selectedNode.data.notionPageId || ''"
        placeholder="Notion page ID"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionPageId"
        v-bind="notionExpressionNavBindings('notionPageId')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionPageId', $event)"
      />
    </div>

    <div
      v-if="['retrieveDatabase', 'updateDatabase'].includes(selectedNode.data.notionOperation || '')"
      class="space-y-2"
    >
      <Label>Database ID</Label>
      <ExpressionInput
        ref="notionDatabaseIdExpressionInputRef"
        :model-value="selectedNode.data.notionDatabaseId || ''"
        placeholder="Notion database ID, URL, or expression"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionDatabaseId"
        v-bind="notionExpressionNavBindings('notionDatabaseId')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionDatabaseId', $event)"
      />
    </div>

    <div
      v-if="['createDatabase', 'updateDatabase'].includes(selectedNode.data.notionOperation || '')"
      class="space-y-2"
    >
      <Label>Database Request (JSON object)</Label>
      <ExpressionInput
        ref="notionDatabaseExpressionInputRef"
        :model-value="selectedNode.data.notionDatabase || '{}'"
        :placeholder="selectedNode.data.notionOperation === 'createDatabase'
          ? '{&quot;parent&quot;:{&quot;type&quot;:&quot;page_id&quot;,&quot;page_id&quot;:&quot;...&quot;},&quot;title&quot;:[{&quot;type&quot;:&quot;text&quot;,&quot;text&quot;:{&quot;content&quot;:&quot;Tasks&quot;}}],&quot;initial_data_source&quot;:{&quot;properties&quot;:{&quot;Name&quot;:{&quot;title&quot;:{}}}}}'
          : '{&quot;title&quot;:[{&quot;type&quot;:&quot;text&quot;,&quot;text&quot;:{&quot;content&quot;:&quot;Updated&quot;}}]}'"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionDatabase"
        v-bind="notionExpressionNavBindings('notionDatabase')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionDatabase', $event)"
      />
      <p class="text-xs text-muted-foreground">
        {{
          selectedNode.data.notionOperation === "createDatabase"
            ? "Create requires a parent object. The request supports the current Notion Database API fields."
            : "Provide one or more fields supported by the current Notion Update Database API."
        }}
      </p>
    </div>

    <div
      v-if="['createPage', 'retrieveDataSource', 'updateDataSource', 'queryDataSource'].includes(selectedNode.data.notionOperation || '')"
      class="space-y-2"
    >
      <div class="flex items-center justify-between gap-2">
        <Label>Data Source</Label>
        <div class="flex items-center gap-1">
          <AgentFieldToggle
            :node-id="selectedNode.id"
            field-key="notionDataSourceId"
          />
          <Button
            v-if="(selectedNode.data.notionDataSourceInputMode || 'select') === 'select'"
            type="button"
            variant="outline"
            size="sm"
            :disabled="!selectedNode.data.credentialId || loadingNotionDataSources"
            @click="loadNotionDataSourcesForSelectedNode(false)"
          >
            <RefreshCw
              class="mr-1 h-3.5 w-3.5"
              :class="{ 'animate-spin': loadingNotionDataSources }"
            />
            Refresh
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            @click="updateNodeData(
              'notionDataSourceInputMode',
              (selectedNode.data.notionDataSourceInputMode || 'select') === 'select'
                ? 'expression'
                : 'select',
            )"
          >
            {{
              (selectedNode.data.notionDataSourceInputMode || "select") === "select"
                ? "Use expression"
                : "Use selector"
            }}
          </Button>
        </div>
      </div>
      <Select
        v-if="(selectedNode.data.notionDataSourceInputMode || 'select') === 'select'"
        :model-value="selectedNode.data.notionDataSourceId || ''"
        :options="notionDataSourceOptions"
        :disabled="!selectedNode.data.credentialId || loadingNotionDataSources"
        @update:model-value="updateNodeData('notionDataSourceId', $event)"
      />
      <Input
        v-if="(selectedNode.data.notionDataSourceInputMode || 'select') === 'select'"
        v-model="notionDataSourceSearch"
        placeholder="Search data sources..."
        :disabled="!selectedNode.data.credentialId"
      />
      <Button
        v-if="
          (selectedNode.data.notionDataSourceInputMode || 'select') === 'select' &&
            notionDataSourcesHasMore
        "
        type="button"
        variant="outline"
        size="sm"
        :loading="loadingNotionDataSources"
        :disabled="loadingNotionDataSources"
        @click="loadNotionDataSourcesForSelectedNode(true)"
      >
        Load more
      </Button>
      <ExpressionInput
        v-else
        ref="notionDataSourceIdExpressionInputRef"
        :model-value="selectedNode.data.notionDataSourceId || ''"
        placeholder="$input.dataSourceId or a Notion URL"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionDataSourceId"
        v-bind="notionExpressionNavBindings('notionDataSourceId')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionDataSourceId', $event)"
      />
      <p
        v-if="notionDataSourcesError && (selectedNode.data.notionDataSourceInputMode || 'select') === 'select'"
        class="text-xs text-destructive"
      >
        {{ notionDataSourcesError }}
      </p>
      <p
        v-else-if="(selectedNode.data.notionDataSourceInputMode || 'select') === 'select'"
        class="text-xs text-muted-foreground"
      >
        Shows data sources shared with the selected Notion integration.
      </p>
      <p
        v-else
        class="text-xs text-muted-foreground"
      >
        Accepts an expression, raw data source ID, or full Notion URL.
      </p>
    </div>

    <div
      v-if="['createDataSource', 'updateDataSource'].includes(selectedNode.data.notionOperation || '')"
      class="space-y-2"
    >
      <Label>Data Source Request (JSON object)</Label>
      <ExpressionInput
        ref="notionDataSourceExpressionInputRef"
        :model-value="selectedNode.data.notionDataSource || '{}'"
        :placeholder="selectedNode.data.notionOperation === 'createDataSource'
          ? '{&quot;parent&quot;:{&quot;type&quot;:&quot;database_id&quot;,&quot;database_id&quot;:&quot;...&quot;},&quot;properties&quot;:{&quot;Name&quot;:{&quot;title&quot;:{}}}}'
          : '{&quot;properties&quot;:{&quot;Status&quot;:{&quot;status&quot;:{}}}}'"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionDataSource"
        v-bind="notionExpressionNavBindings('notionDataSource')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionDataSource', $event)"
      />
      <p class="text-xs text-muted-foreground">
        {{
          selectedNode.data.notionOperation === "createDataSource"
            ? "Create requires a parent database object and a property schema."
            : "Provide one or more fields supported by the Notion Update Data Source API."
        }}
      </p>
    </div>

    <template v-if="selectedNode.data.notionOperation === 'createPage'">
      <div class="space-y-2">
        <div class="flex items-center justify-between gap-2">
          <Label>Parent Page</Label>
          <div class="flex items-center gap-1">
            <AgentFieldToggle
              :node-id="selectedNode.id"
              field-key="notionParentPageId"
            />
            <Button
              v-if="(selectedNode.data.notionParentPageInputMode || 'select') === 'select'"
              type="button"
              variant="outline"
              size="sm"
              :disabled="!selectedNode.data.credentialId || loadingNotionPages"
              @click="loadNotionPagesForSelectedNode(false)"
            >
              <RefreshCw
                class="mr-1 h-3.5 w-3.5"
                :class="{ 'animate-spin': loadingNotionPages }"
              />
              Refresh
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              @click="updateNodeData(
                'notionParentPageInputMode',
                (selectedNode.data.notionParentPageInputMode || 'select') === 'select'
                  ? 'expression'
                  : 'select',
              )"
            >
              {{
                (selectedNode.data.notionParentPageInputMode || "select") === "select"
                  ? "Use expression"
                  : "Use selector"
              }}
            </Button>
          </div>
        </div>
        <Select
          v-if="(selectedNode.data.notionParentPageInputMode || 'select') === 'select'"
          :model-value="selectedNode.data.notionParentPageId || ''"
          :options="notionPageOptions"
          :disabled="!selectedNode.data.credentialId || loadingNotionPages"
          @update:model-value="updateNodeData('notionParentPageId', $event)"
        />
        <Input
          v-if="(selectedNode.data.notionParentPageInputMode || 'select') === 'select'"
          v-model="notionPageSearch"
          placeholder="Search pages..."
          :disabled="!selectedNode.data.credentialId"
        />
        <Button
          v-if="
            (selectedNode.data.notionParentPageInputMode || 'select') === 'select' &&
              notionPagesHasMore
          "
          type="button"
          variant="outline"
          size="sm"
          :loading="loadingNotionPages"
          :disabled="loadingNotionPages"
          @click="loadNotionPagesForSelectedNode(true)"
        >
          Load more
        </Button>
        <ExpressionInput
          v-else
          ref="notionParentPageIdExpressionInputRef"
          :model-value="selectedNode.data.notionParentPageId || ''"
          placeholder="$input.parentPageId or a Notion URL"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="notionParentPageId"
          v-bind="notionExpressionNavBindings('notionParentPageId')"
          @navigate="handleNotionExpressionFieldNavigate"
          @register-field-index="onNotionRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('notionParentPageId', $event)"
        />
        <p
          v-if="notionPagesError && (selectedNode.data.notionParentPageInputMode || 'select') === 'select'"
          class="text-xs text-destructive"
        >
          {{ notionPagesError }}
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Set exactly one parent. Data Source ID takes precedence when both are present.
        </p>
      </div>
    </template>

    <div
      v-if="['getBlockChildren', 'updateBlock', 'deleteBlock', 'appendBlocks'].includes(selectedNode.data.notionOperation || '')"
      class="space-y-2"
    >
      <Label>Block or Page ID</Label>
      <ExpressionInput
        ref="notionBlockIdExpressionInputRef"
        :model-value="selectedNode.data.notionBlockId || ''"
        placeholder="Notion block or page ID"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionBlockId"
        v-bind="notionExpressionNavBindings('notionBlockId')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionBlockId', $event)"
      />
    </div>

    <div
      v-if="selectedNode.data.notionOperation === 'updateBlock'"
      class="space-y-2"
    >
      <Label>Block Update (JSON object)</Label>
      <ExpressionInput
        ref="notionBlockExpressionInputRef"
        :model-value="selectedNode.data.notionBlock || '{}'"
        placeholder="{&quot;paragraph&quot;:{&quot;rich_text&quot;:[{&quot;type&quot;:&quot;text&quot;,&quot;text&quot;:{&quot;content&quot;:&quot;Updated&quot;}}]}}"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionBlock"
        v-bind="notionExpressionNavBindings('notionBlock')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionBlock', $event)"
      />
    </div>

    <div
      v-if="['createPage', 'updatePage'].includes(selectedNode.data.notionOperation || '')"
      class="space-y-2"
    >
      <Label>Properties (JSON object)</Label>
      <ExpressionInput
        ref="notionPropertiesExpressionInputRef"
        :model-value="selectedNode.data.notionProperties || '{}'"
        placeholder="{&quot;Name&quot;:{&quot;title&quot;:[{&quot;text&quot;:{&quot;content&quot;:&quot;$input.title&quot;}}]}}"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionProperties"
        v-bind="notionExpressionNavBindings('notionProperties')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionProperties', $event)"
      />
    </div>

    <div
      v-if="['createPage', 'updatePage'].includes(selectedNode.data.notionOperation || '')"
      class="space-y-2"
    >
      <Label>Icon (JSON object)</Label>
      <ExpressionInput
        ref="notionIconExpressionInputRef"
        :model-value="selectedNode.data.notionIcon || '{}'"
        placeholder="{&quot;type&quot;:&quot;emoji&quot;,&quot;emoji&quot;:&quot;📌&quot;}"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionIcon"
        v-bind="notionExpressionNavBindings('notionIcon')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionIcon', $event)"
      />
    </div>

    <div
      v-if="['createPage', 'updatePage'].includes(selectedNode.data.notionOperation || '')"
      class="space-y-2"
    >
      <Label>Cover (JSON object)</Label>
      <ExpressionInput
        ref="notionCoverExpressionInputRef"
        :model-value="selectedNode.data.notionCover || '{}'"
        placeholder="{&quot;type&quot;:&quot;external&quot;,&quot;external&quot;:{&quot;url&quot;:&quot;https://example.com/cover.jpg&quot;}}"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionCover"
        v-bind="notionExpressionNavBindings('notionCover')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionCover', $event)"
      />
    </div>

    <div
      v-if="['createPage', 'appendBlocks'].includes(selectedNode.data.notionOperation || '')"
      class="space-y-2"
    >
      <Label>Children (JSON array)</Label>
      <ExpressionInput
        ref="notionChildrenExpressionInputRef"
        :model-value="selectedNode.data.notionChildren || '[]'"
        placeholder="[{&quot;object&quot;:&quot;block&quot;,&quot;type&quot;:&quot;paragraph&quot;,&quot;paragraph&quot;:{&quot;rich_text&quot;:[]}}]"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionChildren"
        v-bind="notionExpressionNavBindings('notionChildren')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionChildren', $event)"
      />
    </div>

    <div
      v-if="['search', 'queryDataSource'].includes(selectedNode.data.notionOperation || '')"
      class="space-y-2"
    >
      <Label>Filter (JSON object)</Label>
      <ExpressionInput
        ref="notionFilterExpressionInputRef"
        :model-value="selectedNode.data.notionFilter || '{}'"
        placeholder="{}"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionFilter"
        v-bind="notionExpressionNavBindings('notionFilter')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionFilter', $event)"
      />
    </div>

    <div
      v-if="selectedNode.data.notionOperation === 'search'"
      class="space-y-2"
    >
      <Label>Sort (JSON object)</Label>
      <ExpressionInput
        ref="notionSortExpressionInputRef"
        :model-value="selectedNode.data.notionSort || '{}'"
        placeholder="{&quot;direction&quot;:&quot;descending&quot;,&quot;timestamp&quot;:&quot;last_edited_time&quot;}"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionSort"
        v-bind="notionExpressionNavBindings('notionSort')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionSort', $event)"
      />
    </div>

    <div
      v-if="selectedNode.data.notionOperation === 'queryDataSource'"
      class="space-y-2"
    >
      <Label>Sorts (JSON array)</Label>
      <ExpressionInput
        ref="notionSortsExpressionInputRef"
        :model-value="selectedNode.data.notionSorts || '[]'"
        placeholder="[{&quot;property&quot;:&quot;Created&quot;,&quot;direction&quot;:&quot;descending&quot;}]"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionSorts"
        v-bind="notionExpressionNavBindings('notionSorts')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionSorts', $event)"
      />
    </div>

    <div
      v-if="['search', 'queryDataSource', 'getBlockChildren'].includes(selectedNode.data.notionOperation || '')"
      class="space-y-2"
    >
      <div class="flex items-center justify-between gap-2">
        <Label>Page Size <span class="font-normal text-muted-foreground">(0 = fetch all)</span></Label>
        <AgentFieldToggle
          :node-id="selectedNode.id"
          field-key="notionPageSize"
        />
      </div>
      <Input
        type="number"
        min="0"
        max="100"
        :model-value="selectedNode.data.notionPageSize || '100'"
        @input="updateNodeData('notionPageSize', String(($event.target as HTMLInputElement).value))"
      />
      <Label>Start Cursor</Label>
      <ExpressionInput
        ref="notionStartCursorExpressionInputRef"
        :model-value="selectedNode.data.notionStartCursor || ''"
        placeholder="Optional cursor"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionStartCursor"
        v-bind="notionExpressionNavBindings('notionStartCursor')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionStartCursor', $event)"
      />
    </div>

    <div
      v-if="selectedNode.data.notionOperation === 'appendBlocks'"
      class="space-y-2"
    >
      <div class="flex items-center justify-between gap-2">
        <Label>Position</Label>
        <AgentFieldToggle
          :node-id="selectedNode.id"
          field-key="notionAppendPosition"
        />
      </div>
      <Select
        :model-value="selectedNode.data.notionAppendPosition || (selectedNode.data.notionAfterBlockId ? 'after_block' : 'end')"
        :options="notionAppendPositionOptions"
        @update:model-value="updateNodeData('notionAppendPosition', $event)"
      />
      <Label
        v-if="(selectedNode.data.notionAppendPosition || (selectedNode.data.notionAfterBlockId ? 'after_block' : 'end')) === 'after_block'"
      >
        After Block ID
      </Label>
      <ExpressionInput
        v-if="(selectedNode.data.notionAppendPosition || (selectedNode.data.notionAfterBlockId ? 'after_block' : 'end')) === 'after_block'"
        ref="notionAfterBlockIdExpressionInputRef"
        :model-value="selectedNode.data.notionAfterBlockId || ''"
        placeholder="Block ID, URL, or expression"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="notionAfterBlockId"
        v-bind="notionExpressionNavBindings('notionAfterBlockId')"
        @navigate="handleNotionExpressionFieldNavigate"
        @register-field-index="onNotionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('notionAfterBlockId', $event)"
      />
    </div>

    <div class="rounded-md bg-muted/40 border p-3 space-y-1">
      <p class="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        Output
      </p>
      <div class="text-xs font-mono space-y-0.5">
        <div>${{ selectedNode.data.label }}.success - Boolean success flag</div>
        <div>${{ selectedNode.data.label }}.results - Search/query/block results</div>
        <div>${{ selectedNode.data.label }}.page - Created, retrieved, or updated page</div>
        <div>${{ selectedNode.data.label }}.database - Created, retrieved, or updated database</div>
        <div>${{ selectedNode.data.label }}.data_source - Retrieved data source schema</div>
        <div>${{ selectedNode.data.label }}.block - Updated or deleted block</div>
      </div>
    </div>
  </template>
</template>
