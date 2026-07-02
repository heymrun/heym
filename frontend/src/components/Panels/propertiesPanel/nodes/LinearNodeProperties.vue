<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  linearLimitExpressionInputRef,
  linearAfterExpressionInputRef,
  linearTeamIdExpressionInputRef,
  linearProjectIdExpressionInputRef,
  linearIssueIdExpressionInputRef,
  linearTitleExpressionInputRef,
  linearDescriptionExpressionInputRef,
  linearStateIdExpressionInputRef,
  linearIssueLinkUrlExpressionInputRef,
  linearAssigneeIdExpressionInputRef,
  linearPriorityExpressionInputRef,
  linearCommentIdExpressionInputRef,
  linearCommentBodyExpressionInputRef,
  linearParentCommentIdExpressionInputRef,
  selectedNode,
  isLinearPaginatedOperation,
  isLinearIssueIdOperation,
  isLinearCommentIdOperation,
  linearExpressionNavBindings,
  handleLinearExpressionFieldNavigate,
  onLinearRegisterExpressionFieldIndex,
  linearCredentialOptions,
  linearOperationOptions,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div
      class="space-y-2"
      data-testid="linear-credential-field"
    >
      <Label>Linear Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="linearCredentialOptions"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <p
        v-if="!selectedNode.data.credentialId"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Credential is required.
      </p>
    </div>

    <div
      class="space-y-2"
      data-testid="linear-operation-field"
    >
      <Label>Operation</Label>
      <Select
        :model-value="selectedNode.data.linearOperation || 'listIssues'"
        :options="linearOperationOptions"
        @update:model-value="updateNodeData('linearOperation', $event)"
      />
    </div>

    <label
      v-if="isLinearPaginatedOperation()"
      class="flex items-center gap-2 text-sm"
    >
      <input
        type="checkbox"
        :checked="!!selectedNode.data.linearReturnAll"
        @change="updateNodeData('linearReturnAll', ($event.target as HTMLInputElement).checked)"
      >
      <span>Return All</span>
    </label>

    <div
      v-if="isLinearPaginatedOperation() && !selectedNode.data.linearReturnAll"
      class="space-y-2"
      data-testid="linear-limit-field"
    >
      <Label>Limit</Label>
      <ExpressionInput
        ref="linearLimitExpressionInputRef"
        :model-value="selectedNode.data.linearLimit || '50'"
        placeholder="50"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="linearLimit"
        v-bind="linearExpressionNavBindings('linearLimit')"
        @update:model-value="updateNodeData('linearLimit', $event)"
        @navigate="handleLinearExpressionFieldNavigate"
        @register-field-index="onLinearRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="isLinearPaginatedOperation() && !selectedNode.data.linearReturnAll"
      class="space-y-2"
      data-testid="linear-after-field"
    >
      <Label>After Cursor (Optional)</Label>
      <ExpressionInput
        ref="linearAfterExpressionInputRef"
        :model-value="selectedNode.data.linearAfter || ''"
        placeholder="pageInfo.endCursor from a previous list"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="linearAfter"
        v-bind="linearExpressionNavBindings('linearAfter')"
        @update:model-value="updateNodeData('linearAfter', $event)"
        @navigate="handleLinearExpressionFieldNavigate"
        @register-field-index="onLinearRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.linearOperation === 'listIssues' || selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue' || selectedNode.data.linearOperation === 'listWorkflowStates' || selectedNode.data.linearOperation === 'listTeamMembers'"
      class="space-y-2"
      data-testid="linear-team-id-field"
    >
      <Label>
        Team ID
        <span v-if="selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'listWorkflowStates' || selectedNode.data.linearOperation === 'listTeamMembers'">*</span>
      </Label>
      <ExpressionInput
        ref="linearTeamIdExpressionInputRef"
        :model-value="selectedNode.data.linearTeamId || ''"
        placeholder="team UUID"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="linearTeamId"
        v-bind="linearExpressionNavBindings('linearTeamId')"
        @update:model-value="updateNodeData('linearTeamId', $event)"
        @navigate="handleLinearExpressionFieldNavigate"
        @register-field-index="onLinearRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.linearOperation === 'listIssues' || selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
      class="space-y-2"
    >
      <Label>Project ID (Optional)</Label>
      <ExpressionInput
        ref="linearProjectIdExpressionInputRef"
        :model-value="selectedNode.data.linearProjectId || ''"
        placeholder="project UUID"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="linearProjectId"
        v-bind="linearExpressionNavBindings('linearProjectId')"
        @update:model-value="updateNodeData('linearProjectId', $event)"
        @navigate="handleLinearExpressionFieldNavigate"
        @register-field-index="onLinearRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="isLinearIssueIdOperation()"
      class="space-y-2"
      data-testid="linear-issue-id-field"
    >
      <Label>
        Issue ID or Identifier
        <span>*</span>
      </Label>
      <ExpressionInput
        ref="linearIssueIdExpressionInputRef"
        :model-value="selectedNode.data.linearIssueId || ''"
        placeholder="ENG-123 or issue UUID"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="linearIssueId"
        v-bind="linearExpressionNavBindings('linearIssueId')"
        @update:model-value="updateNodeData('linearIssueId', $event)"
        @navigate="handleLinearExpressionFieldNavigate"
        @register-field-index="onLinearRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
      class="space-y-2"
    >
      <Label>
        Title
        <span v-if="selectedNode.data.linearOperation === 'createIssue'">*</span>
      </Label>
      <ExpressionInput
        ref="linearTitleExpressionInputRef"
        :model-value="selectedNode.data.linearTitle || ''"
        placeholder="Issue title"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="linearTitle"
        v-bind="linearExpressionNavBindings('linearTitle')"
        @update:model-value="updateNodeData('linearTitle', $event)"
        @navigate="handleLinearExpressionFieldNavigate"
        @register-field-index="onLinearRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
      class="space-y-2"
    >
      <Label>Description (Optional)</Label>
      <ExpressionInput
        ref="linearDescriptionExpressionInputRef"
        :model-value="selectedNode.data.linearDescription || ''"
        placeholder="$input.text"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="linearDescription"
        v-bind="linearExpressionNavBindings('linearDescription')"
        @update:model-value="updateNodeData('linearDescription', $event)"
        @navigate="handleLinearExpressionFieldNavigate"
        @register-field-index="onLinearRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
      class="space-y-2"
    >
      <Label>State ID (Optional)</Label>
      <ExpressionInput
        ref="linearStateIdExpressionInputRef"
        :model-value="selectedNode.data.linearStateId || ''"
        placeholder="workflow state UUID"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="linearStateId"
        v-bind="linearExpressionNavBindings('linearStateId')"
        @update:model-value="updateNodeData('linearStateId', $event)"
        @navigate="handleLinearExpressionFieldNavigate"
        @register-field-index="onLinearRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.linearOperation === 'addIssueLink'"
      class="space-y-2"
    >
      <Label>
        Link URL
        <span>*</span>
      </Label>
      <ExpressionInput
        ref="linearIssueLinkUrlExpressionInputRef"
        :model-value="selectedNode.data.linearIssueLinkUrl || ''"
        placeholder="https://example.com"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="linearIssueLinkUrl"
        v-bind="linearExpressionNavBindings('linearIssueLinkUrl')"
        @update:model-value="updateNodeData('linearIssueLinkUrl', $event)"
        @navigate="handleLinearExpressionFieldNavigate"
        @register-field-index="onLinearRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
      class="grid grid-cols-2 gap-3"
    >
      <div class="space-y-2">
        <Label>Assignee ID</Label>
        <ExpressionInput
          ref="linearAssigneeIdExpressionInputRef"
          :model-value="selectedNode.data.linearAssigneeId || ''"
          placeholder="user UUID"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="linearAssigneeId"
          v-bind="linearExpressionNavBindings('linearAssigneeId')"
          @update:model-value="updateNodeData('linearAssigneeId', $event)"
          @navigate="handleLinearExpressionFieldNavigate"
          @register-field-index="onLinearRegisterExpressionFieldIndex"
        />
      </div>
      <div class="space-y-2">
        <Label>Priority (0–4)</Label>
        <ExpressionInput
          ref="linearPriorityExpressionInputRef"
          :model-value="selectedNode.data.linearPriority || ''"
          placeholder="0"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="linearPriority"
          v-bind="linearExpressionNavBindings('linearPriority')"
          @update:model-value="updateNodeData('linearPriority', $event)"
          @navigate="handleLinearExpressionFieldNavigate"
          @register-field-index="onLinearRegisterExpressionFieldIndex"
        />
      </div>
    </div>

    <div
      v-if="selectedNode.data.linearOperation === 'updateIssue'"
      class="text-xs text-muted-foreground"
    >
      Leave optional update fields empty to keep their current values. Set a field to
      <code class="font-mono">null</code> to clear description, project, assignee, or state.
    </div>

    <div
      v-if="isLinearCommentIdOperation()"
      class="space-y-2"
      data-testid="linear-comment-id-field"
    >
      <Label>
        Comment ID
        <span>*</span>
      </Label>
      <ExpressionInput
        ref="linearCommentIdExpressionInputRef"
        :model-value="selectedNode.data.linearCommentId || ''"
        placeholder="comment UUID"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="linearCommentId"
        v-bind="linearExpressionNavBindings('linearCommentId')"
        @update:model-value="updateNodeData('linearCommentId', $event)"
        @navigate="handleLinearExpressionFieldNavigate"
        @register-field-index="onLinearRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.linearOperation === 'createComment' || selectedNode.data.linearOperation === 'updateComment'"
      class="space-y-2"
      data-testid="linear-comment-body-field"
    >
      <Label>Comment Body</Label>
      <ExpressionInput
        ref="linearCommentBodyExpressionInputRef"
        :model-value="selectedNode.data.linearCommentBody || '$input.text'"
        placeholder="$input.text"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="linearCommentBody"
        v-bind="linearExpressionNavBindings('linearCommentBody')"
        @update:model-value="updateNodeData('linearCommentBody', $event)"
        @navigate="handleLinearExpressionFieldNavigate"
        @register-field-index="onLinearRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.linearOperation === 'createComment'"
      class="space-y-2"
      data-testid="linear-parent-comment-id-field"
    >
      <Label>Parent Comment ID (Optional)</Label>
      <ExpressionInput
        ref="linearParentCommentIdExpressionInputRef"
        :model-value="selectedNode.data.linearParentCommentId || ''"
        placeholder="comment UUID"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="linearParentCommentId"
        v-bind="linearExpressionNavBindings('linearParentCommentId')"
        @update:model-value="updateNodeData('linearParentCommentId', $event)"
        @navigate="handleLinearExpressionFieldNavigate"
        @register-field-index="onLinearRegisterExpressionFieldIndex"
      />
    </div>

    <div class="p-3 rounded-lg bg-muted/50 space-y-1">
      <div class="text-xs font-medium">
        Output
      </div>
      <div class="text-xs text-muted-foreground font-mono space-y-0.5">
        <div>${{ selectedNode.data.label }}.success - Boolean</div>
        <div>${{ selectedNode.data.label }}.operation - String</div>
        <div v-if="selectedNode.data.linearOperation === 'getViewer'">
          ${{ selectedNode.data.label }}.viewer - User
        </div>
        <div v-else-if="selectedNode.data.linearOperation === 'listTeams'">
          ${{ selectedNode.data.label }}.teams - Team array
        </div>
        <div v-else-if="selectedNode.data.linearOperation === 'listProjects'">
          ${{ selectedNode.data.label }}.projects - Project array
        </div>
        <div v-else-if="selectedNode.data.linearOperation === 'listIssues'">
          ${{ selectedNode.data.label }}.issues - Issue array
        </div>
        <div v-else-if="selectedNode.data.linearOperation === 'listWorkflowStates'">
          ${{ selectedNode.data.label }}.states - Workflow state array
        </div>
        <div v-else-if="selectedNode.data.linearOperation === 'listTeamMembers'">
          ${{ selectedNode.data.label }}.members - Team member array
        </div>
        <div v-else-if="selectedNode.data.linearOperation === 'listComments'">
          ${{ selectedNode.data.label }}.comments - Comment array
        </div>
        <div v-else-if="selectedNode.data.linearOperation === 'createComment' || selectedNode.data.linearOperation === 'updateComment' || selectedNode.data.linearOperation === 'resolveComment' || selectedNode.data.linearOperation === 'unresolveComment'">
          ${{ selectedNode.data.label }}.comment - Comment
        </div>
        <div v-else-if="selectedNode.data.linearOperation === 'addIssueLink'">
          ${{ selectedNode.data.label }}.link - Link result
        </div>
        <div v-else-if="selectedNode.data.linearOperation === 'deleteIssue' || selectedNode.data.linearOperation === 'deleteComment'">
          ${{ selectedNode.data.label }}.deleted - Boolean
        </div>
        <div v-if="selectedNode.data.linearOperation === 'deleteComment'">
          ${{ selectedNode.data.label }}.entityId - Deleted comment ID
        </div>
        <div v-if="selectedNode.data.linearOperation === 'getIssue' || selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'">
          ${{ selectedNode.data.label }}.issue - Issue
        </div>
        <div
          v-if="isLinearPaginatedOperation() || selectedNode.data.linearOperation === 'listWorkflowStates'"
        >
          ${{ selectedNode.data.label }}.count - Number
        </div>
        <div
          v-if="isLinearPaginatedOperation()"
        >
          ${{ selectedNode.data.label }}.pageInfo.hasNextPage - Boolean
        </div>
        <div
          v-if="isLinearPaginatedOperation()"
        >
          ${{ selectedNode.data.label }}.pageInfo.endCursor - String
        </div>
        <div
          v-if="selectedNode.data.linearOperation === 'getIssue' || selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
        >
          ${{ selectedNode.data.label }}.identifier - String
        </div>
        <div
          v-if="selectedNode.data.linearOperation === 'getIssue' || selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
        >
          ${{ selectedNode.data.label }}.url - String
        </div>
      </div>
    </div>
  </template>
</template>
