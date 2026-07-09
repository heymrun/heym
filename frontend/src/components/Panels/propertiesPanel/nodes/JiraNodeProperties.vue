<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import AgentFieldToggle from "@/components/ui/AgentFieldToggle.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  jiraLimitExpressionInputRef,
  jiraStartAtExpressionInputRef,
  jiraNextPageTokenExpressionInputRef,
  jiraFieldsExpressionInputRef,
  jiraProjectKeyExpressionInputRef,
  jiraIssueKeyExpressionInputRef,
  jiraIssueTypeExpressionInputRef,
  jiraIssueTypeIdExpressionInputRef,
  jiraSummaryExpressionInputRef,
  jiraDescriptionExpressionInputRef,
  jiraJqlExpressionInputRef,
  jiraAssigneeAccountIdExpressionInputRef,
  jiraLabelsExpressionInputRef,
  jiraCommentBodyExpressionInputRef,
  jiraCommentIdExpressionInputRef,
  jiraTransitionIdExpressionInputRef,
  jiraAttachmentIdExpressionInputRef,
  jiraAttachmentFilenameExpressionInputRef,
  jiraAttachmentBase64ExpressionInputRef,
  jiraAttachmentMimeTypeExpressionInputRef,
  jiraNotifySubjectExpressionInputRef,
  jiraNotifyTextBodyExpressionInputRef,
  jiraNotifyHtmlBodyExpressionInputRef,
  jiraNotifyToExpressionInputRef,
  jiraAccountIdExpressionInputRef,
  jiraUsernameExpressionInputRef,
  jiraUserEmailExpressionInputRef,
  jiraUserDisplayNameExpressionInputRef,
  jiraUserProductsExpressionInputRef,
  selectedNode,
  isJiraPaginatedOperation,
  isJiraSearchOperation,
  isJiraStartAtPaginatedOperation,
  isJiraIssueKeyOperation,
  isJiraCommentIdOperation,
  isJiraAttachmentIdOperation,
  isJiraAccountIdOperation,
  jiraExpressionNavBindings,
  handleJiraExpressionFieldNavigate,
  onJiraRegisterExpressionFieldIndex,
  jiraCredentialOptions,
  jiraOperationGroups,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div
      class="space-y-2"
      data-testid="jira-credential-field"
    >
      <Label>Jira Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="jiraCredentialOptions"
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
      data-testid="jira-operation-field"
    >
      <Label>Operation</Label>
      <SearchableSelect
        :model-value="selectedNode.data.jiraOperation || 'searchIssues'"
        :groups="jiraOperationGroups"
        search-placeholder="Search Jira operations..."
        @update:model-value="updateNodeData('jiraOperation', $event)"
      />
    </div>

    <div
      v-if="selectedNode.data.jiraOperation === 'createIssue'"
      class="space-y-2"
      data-testid="jira-project-key-field"
    >
      <Label>Project Key <span>*</span></Label>
      <ExpressionInput
        ref="jiraProjectKeyExpressionInputRef"
        :model-value="selectedNode.data.jiraProjectKey || ''"
        placeholder="ENG"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraProjectKey"
        v-bind="jiraExpressionNavBindings('jiraProjectKey')"
        @update:model-value="updateNodeData('jiraProjectKey', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="isJiraIssueKeyOperation()"
      class="space-y-2"
      data-testid="jira-issue-key-field"
    >
      <Label>Issue Key or ID <span>*</span></Label>
      <ExpressionInput
        ref="jiraIssueKeyExpressionInputRef"
        :model-value="selectedNode.data.jiraIssueKey || ''"
        placeholder="ENG-123"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraIssueKey"
        v-bind="jiraExpressionNavBindings('jiraIssueKey')"
        @update:model-value="updateNodeData('jiraIssueKey', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.jiraOperation === 'searchIssues'"
      class="space-y-2"
      data-testid="jira-jql-field"
    >
      <Label>JQL</Label>
      <ExpressionInput
        ref="jiraJqlExpressionInputRef"
        :model-value="selectedNode.data.jiraJql || 'updated >= -30d ORDER BY updated DESC'"
        placeholder="project = ENG AND updated >= -30d ORDER BY updated DESC"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraJql"
        v-bind="jiraExpressionNavBindings('jiraJql')"
        @update:model-value="updateNodeData('jiraJql', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.jiraOperation === 'searchIssues'"
      class="space-y-2"
      data-testid="jira-fields-field"
    >
      <Label>Issue Fields</Label>
      <ExpressionInput
        ref="jiraFieldsExpressionInputRef"
        :model-value="selectedNode.data.jiraFields || ''"
        placeholder="[&quot;key&quot;, &quot;summary&quot;, &quot;status&quot;] or comma-separated"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraFields"
        v-bind="jiraExpressionNavBindings('jiraFields')"
        @update:model-value="updateNodeData('jiraFields', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
      <p class="text-xs text-muted-foreground">
        Optional. Defaults to key, summary, status, assignee, and issuetype.
      </p>
    </div>

    <div
      v-if="selectedNode.data.jiraOperation === 'createIssue'"
      class="space-y-2"
      data-testid="jira-issue-type-field"
    >
      <Label>Issue Type</Label>
      <ExpressionInput
        ref="jiraIssueTypeExpressionInputRef"
        :model-value="selectedNode.data.jiraIssueType || 'Task'"
        placeholder="Task"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraIssueType"
        v-bind="jiraExpressionNavBindings('jiraIssueType')"
        @update:model-value="updateNodeData('jiraIssueType', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.jiraOperation === 'createIssue'"
      class="space-y-2"
      data-testid="jira-issue-type-id-field"
    >
      <Label>Issue Type ID</Label>
      <ExpressionInput
        ref="jiraIssueTypeIdExpressionInputRef"
        :model-value="selectedNode.data.jiraIssueTypeId || ''"
        placeholder="10001"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraIssueTypeId"
        v-bind="jiraExpressionNavBindings('jiraIssueTypeId')"
        @update:model-value="updateNodeData('jiraIssueTypeId', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
      <p class="text-xs text-muted-foreground">
        Optional. When set, overrides Issue Type name (useful for localized Jira sites).
      </p>
    </div>

    <div
      v-if="selectedNode.data.jiraOperation === 'createIssue' || selectedNode.data.jiraOperation === 'updateIssue'"
      class="space-y-2"
      data-testid="jira-summary-field"
    >
      <Label>Summary <span v-if="selectedNode.data.jiraOperation === 'createIssue'">*</span></Label>
      <ExpressionInput
        ref="jiraSummaryExpressionInputRef"
        :model-value="selectedNode.data.jiraSummary || ''"
        placeholder="Issue summary"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraSummary"
        v-bind="jiraExpressionNavBindings('jiraSummary')"
        @update:model-value="updateNodeData('jiraSummary', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.jiraOperation === 'createIssue' || selectedNode.data.jiraOperation === 'updateIssue'"
      class="space-y-2"
      data-testid="jira-description-field"
    >
      <Label>Description</Label>
      <ExpressionInput
        ref="jiraDescriptionExpressionInputRef"
        :model-value="selectedNode.data.jiraDescription || ''"
        placeholder="$input.text"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraDescription"
        v-bind="jiraExpressionNavBindings('jiraDescription')"
        @update:model-value="updateNodeData('jiraDescription', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.jiraOperation === 'createIssue' || selectedNode.data.jiraOperation === 'updateIssue'"
      class="space-y-2"
      data-testid="jira-assignee-field"
    >
      <Label>Assignee Account ID / Username</Label>
      <ExpressionInput
        ref="jiraAssigneeAccountIdExpressionInputRef"
        :model-value="selectedNode.data.jiraAssigneeAccountId || ''"
        placeholder="Jira accountId, username, or null"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraAssigneeAccountId"
        v-bind="jiraExpressionNavBindings('jiraAssigneeAccountId')"
        @update:model-value="updateNodeData('jiraAssigneeAccountId', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.jiraOperation === 'createIssue' || selectedNode.data.jiraOperation === 'updateIssue'"
      class="space-y-2"
      data-testid="jira-labels-field"
    >
      <Label>Labels</Label>
      <ExpressionInput
        ref="jiraLabelsExpressionInputRef"
        :model-value="selectedNode.data.jiraLabels || ''"
        placeholder="[&quot;automation&quot;, &quot;support&quot;] or comma-separated"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraLabels"
        v-bind="jiraExpressionNavBindings('jiraLabels')"
        @update:model-value="updateNodeData('jiraLabels', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="isJiraCommentIdOperation()"
      class="space-y-2"
      data-testid="jira-comment-id-field"
    >
      <Label>Comment ID <span>*</span></Label>
      <ExpressionInput
        ref="jiraCommentIdExpressionInputRef"
        :model-value="selectedNode.data.jiraCommentId || ''"
        placeholder="10001"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraCommentId"
        v-bind="jiraExpressionNavBindings('jiraCommentId')"
        @update:model-value="updateNodeData('jiraCommentId', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.jiraOperation === 'createComment' || selectedNode.data.jiraOperation === 'updateComment'"
      class="space-y-2"
      data-testid="jira-comment-body-field"
    >
      <Label>Comment Body <span>*</span></Label>
      <ExpressionInput
        ref="jiraCommentBodyExpressionInputRef"
        :model-value="selectedNode.data.jiraCommentBody || ''"
        placeholder="$input.text"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraCommentBody"
        v-bind="jiraExpressionNavBindings('jiraCommentBody')"
        @update:model-value="updateNodeData('jiraCommentBody', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
    </div>

    <template v-if="selectedNode.data.jiraOperation === 'notifyIssue'">
      <div
        class="space-y-2"
        data-testid="jira-notify-subject-field"
      >
        <Label>Subject <span>*</span></Label>
        <ExpressionInput
          ref="jiraNotifySubjectExpressionInputRef"
          :model-value="selectedNode.data.jiraNotifySubject || ''"
          placeholder="Issue update"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraNotifySubject"
          v-bind="jiraExpressionNavBindings('jiraNotifySubject')"
          @update:model-value="updateNodeData('jiraNotifySubject', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
      </div>

      <div
        class="space-y-2"
        data-testid="jira-notify-text-body-field"
      >
        <Label>Text Body <span>*</span></Label>
        <ExpressionInput
          ref="jiraNotifyTextBodyExpressionInputRef"
          :model-value="selectedNode.data.jiraNotifyTextBody || ''"
          placeholder="$input.text"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraNotifyTextBody"
          v-bind="jiraExpressionNavBindings('jiraNotifyTextBody')"
          @update:model-value="updateNodeData('jiraNotifyTextBody', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
      </div>

      <div
        class="space-y-2"
        data-testid="jira-notify-html-body-field"
      >
        <Label>HTML Body</Label>
        <ExpressionInput
          ref="jiraNotifyHtmlBodyExpressionInputRef"
          :model-value="selectedNode.data.jiraNotifyHtmlBody || ''"
          placeholder="<p>$input.text</p>"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraNotifyHtmlBody"
          v-bind="jiraExpressionNavBindings('jiraNotifyHtmlBody')"
          @update:model-value="updateNodeData('jiraNotifyHtmlBody', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
      </div>

      <div
        class="space-y-2"
        data-testid="jira-notify-to-field"
      >
        <Label>Recipients JSON</Label>
        <ExpressionInput
          ref="jiraNotifyToExpressionInputRef"
          :model-value="selectedNode.data.jiraNotifyTo || '{&quot;assignee&quot;:true}'"
          placeholder="{&quot;assignee&quot;:true,&quot;watchers&quot;:true}"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraNotifyTo"
          v-bind="jiraExpressionNavBindings('jiraNotifyTo')"
          @update:model-value="updateNodeData('jiraNotifyTo', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
      </div>
    </template>

    <div
      v-if="selectedNode.data.jiraOperation === 'transitionIssue'"
      class="space-y-2"
      data-testid="jira-transition-id-field"
    >
      <Label>Transition ID <span>*</span></Label>
      <ExpressionInput
        ref="jiraTransitionIdExpressionInputRef"
        :model-value="selectedNode.data.jiraTransitionId || ''"
        placeholder="31"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraTransitionId"
        v-bind="jiraExpressionNavBindings('jiraTransitionId')"
        @update:model-value="updateNodeData('jiraTransitionId', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
    </div>

    <div
      v-if="isJiraAttachmentIdOperation()"
      class="space-y-2"
      data-testid="jira-attachment-id-field"
    >
      <Label>Attachment ID <span>*</span></Label>
      <ExpressionInput
        ref="jiraAttachmentIdExpressionInputRef"
        :model-value="selectedNode.data.jiraAttachmentId || ''"
        placeholder="10001"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraAttachmentId"
        v-bind="jiraExpressionNavBindings('jiraAttachmentId')"
        @update:model-value="updateNodeData('jiraAttachmentId', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
    </div>

    <template v-if="selectedNode.data.jiraOperation === 'addAttachment'">
      <div
        class="space-y-2"
        data-testid="jira-attachment-filename-field"
      >
        <Label>Filename <span>*</span></Label>
        <ExpressionInput
          ref="jiraAttachmentFilenameExpressionInputRef"
          :model-value="selectedNode.data.jiraAttachmentFilename || ''"
          placeholder="report.txt"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraAttachmentFilename"
          v-bind="jiraExpressionNavBindings('jiraAttachmentFilename')"
          @update:model-value="updateNodeData('jiraAttachmentFilename', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
      </div>

      <div
        class="space-y-2"
        data-testid="jira-attachment-base64-field"
      >
        <Label>Base64 Content <span>*</span></Label>
        <ExpressionInput
          ref="jiraAttachmentBase64ExpressionInputRef"
          :model-value="selectedNode.data.jiraAttachmentBase64 || ''"
          placeholder="$input.file_base64"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraAttachmentBase64"
          v-bind="jiraExpressionNavBindings('jiraAttachmentBase64')"
          @update:model-value="updateNodeData('jiraAttachmentBase64', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
      </div>

      <div
        class="space-y-2"
        data-testid="jira-attachment-mime-type-field"
      >
        <Label>MIME Type</Label>
        <ExpressionInput
          ref="jiraAttachmentMimeTypeExpressionInputRef"
          :model-value="selectedNode.data.jiraAttachmentMimeType || ''"
          placeholder="text/plain"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraAttachmentMimeType"
          v-bind="jiraExpressionNavBindings('jiraAttachmentMimeType')"
          @update:model-value="updateNodeData('jiraAttachmentMimeType', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
      </div>
    </template>

    <label
      v-if="selectedNode.data.jiraOperation === 'getAttachment' || selectedNode.data.jiraOperation === 'listAttachments'"
      class="flex items-center gap-2 text-sm"
    >
      <input
        type="checkbox"
        :checked="!!selectedNode.data.jiraIncludeBinary"
        @change="updateNodeData('jiraIncludeBinary', ($event.target as HTMLInputElement).checked)"
      >
      <span>Include binary content as base64</span>
      <AgentFieldToggle
        :node-id="selectedNode.id"
        field-key="jiraIncludeBinary"
      />
    </label>

    <div
      v-if="isJiraAccountIdOperation()"
      class="space-y-2"
      data-testid="jira-account-id-field"
    >
      <p
        v-if="selectedNode.data.jiraOperation === 'deleteUser'"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Delete User typically requires Jira admin permissions.
      </p>
      <Label>Account ID / Username <span>*</span></Label>
      <ExpressionInput
        ref="jiraAccountIdExpressionInputRef"
        :model-value="selectedNode.data.jiraAccountId || ''"
        placeholder="712020:... or username"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="jiraAccountId"
        v-bind="jiraExpressionNavBindings('jiraAccountId')"
        @update:model-value="updateNodeData('jiraAccountId', $event)"
        @navigate="handleJiraExpressionFieldNavigate"
        @register-field-index="onJiraRegisterExpressionFieldIndex"
      />
    </div>

    <template v-if="selectedNode.data.jiraOperation === 'createUser'">
      <p class="text-xs text-amber-500 flex items-center gap-1">
        <AlertTriangle class="h-3 w-3" />
        Create User typically requires Jira admin permissions.
      </p>
      <div
        class="space-y-2"
        data-testid="jira-user-email-field"
      >
        <Label>User Email <span>*</span></Label>
        <ExpressionInput
          ref="jiraUserEmailExpressionInputRef"
          :model-value="selectedNode.data.jiraUserEmail || ''"
          placeholder="user@example.com"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraUserEmail"
          v-bind="jiraExpressionNavBindings('jiraUserEmail')"
          @update:model-value="updateNodeData('jiraUserEmail', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
      </div>

      <div
        class="space-y-2"
        data-testid="jira-username-field"
      >
        <Label>Username</Label>
        <ExpressionInput
          ref="jiraUsernameExpressionInputRef"
          :model-value="selectedNode.data.jiraUsername || ''"
          placeholder="ada"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraUsername"
          v-bind="jiraExpressionNavBindings('jiraUsername')"
          @update:model-value="updateNodeData('jiraUsername', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
        <p class="text-xs text-muted-foreground">
          Optional. Used as the Data Center / Server username; falls back to User Email.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="jira-user-display-name-field"
      >
        <Label>Display Name</Label>
        <ExpressionInput
          ref="jiraUserDisplayNameExpressionInputRef"
          :model-value="selectedNode.data.jiraUserDisplayName || ''"
          placeholder="Ada Lovelace"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraUserDisplayName"
          v-bind="jiraExpressionNavBindings('jiraUserDisplayName')"
          @update:model-value="updateNodeData('jiraUserDisplayName', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
      </div>

      <div
        class="space-y-2"
        data-testid="jira-user-products-field"
      >
        <Label>Products</Label>
        <ExpressionInput
          ref="jiraUserProductsExpressionInputRef"
          :model-value="selectedNode.data.jiraUserProducts || ''"
          placeholder="[&quot;jira-software&quot;] or comma-separated"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraUserProducts"
          v-bind="jiraExpressionNavBindings('jiraUserProducts')"
          @update:model-value="updateNodeData('jiraUserProducts', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
      </div>
    </template>

    <div
      v-if="isJiraPaginatedOperation()"
      class="grid grid-cols-2 gap-3"
    >
      <div class="space-y-2">
        <Label>Limit</Label>
        <ExpressionInput
          ref="jiraLimitExpressionInputRef"
          :model-value="selectedNode.data.jiraLimit || '50'"
          placeholder="50"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraLimit"
          v-bind="jiraExpressionNavBindings('jiraLimit')"
          @update:model-value="updateNodeData('jiraLimit', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
      </div>
      <div
        v-if="isJiraSearchOperation()"
        class="space-y-2"
      >
        <Label>Next Page Token</Label>
        <ExpressionInput
          ref="jiraNextPageTokenExpressionInputRef"
          :model-value="selectedNode.data.jiraNextPageToken || ''"
          placeholder="Leave empty for first page"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraNextPageToken"
          v-bind="jiraExpressionNavBindings('jiraNextPageToken')"
          @update:model-value="updateNodeData('jiraNextPageToken', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
      </div>
      <div
        v-if="isJiraStartAtPaginatedOperation()"
        class="space-y-2"
      >
        <Label>Start At</Label>
        <ExpressionInput
          ref="jiraStartAtExpressionInputRef"
          :model-value="selectedNode.data.jiraStartAt || '0'"
          placeholder="0"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="jiraStartAt"
          v-bind="jiraExpressionNavBindings('jiraStartAt')"
          @update:model-value="updateNodeData('jiraStartAt', $event)"
          @navigate="handleJiraExpressionFieldNavigate"
          @register-field-index="onJiraRegisterExpressionFieldIndex"
        />
      </div>
    </div>
  </template>
</template>
