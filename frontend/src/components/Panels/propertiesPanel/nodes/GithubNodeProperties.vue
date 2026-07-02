<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import AgentFieldToggle from "@/components/ui/AgentFieldToggle.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  githubOwnerExpressionInputRef,
  githubRepoExpressionInputRef,
  githubOrganizationExpressionInputRef,
  githubInviteEmailExpressionInputRef,
  githubIssueNumberExpressionInputRef,
  githubAssigneeExpressionInputRef,
  githubCreatorExpressionInputRef,
  githubMentionedExpressionInputRef,
  githubLabelsFilterExpressionInputRef,
  githubSinceExpressionInputRef,
  githubTitleExpressionInputRef,
  githubBodyExpressionInputRef,
  githubCommentBodyExpressionInputRef,
  githubLabelsExpressionInputRef,
  githubAssigneesExpressionInputRef,
  githubHeadExpressionInputRef,
  githubBaseExpressionInputRef,
  githubPullRequestNumberExpressionInputRef,
  githubReviewIdExpressionInputRef,
  githubReviewBodyExpressionInputRef,
  githubCommitIdExpressionInputRef,
  githubFilePathExpressionInputRef,
  githubFileContentExpressionInputRef,
  githubCommitMessageExpressionInputRef,
  githubBranchExpressionInputRef,
  githubTagNameExpressionInputRef,
  githubReleaseIdExpressionInputRef,
  githubWorkflowIdExpressionInputRef,
  githubWorkflowInputsExpressionInputRef,
  selectedNode,
  githubExpressionNavBindings,
  handleGitHubExpressionFieldNavigate,
  onGitHubRegisterExpressionFieldIndex,
  githubCredentialOptions,
  githubOperationOptions,
  githubStateOptions,
  githubIssueSortOptions,
  githubPullRequestSortOptions,
  githubDirectionOptions,
  githubUpdateIssueStateOptions,
  githubIssueStateReasonOptions,
  githubLockReasonOptions,
  githubReviewEventOptions,
  isGitHubRepoRequired,
  isGitHubOwnerRequired,
  usesGitHubPerPage,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>GitHub Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="githubCredentialOptions"
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
        :model-value="selectedNode.data.githubOperation || 'getRepository'"
        :options="githubOperationOptions"
        @update:model-value="updateNodeData('githubOperation', $event)"
      />
    </div>

    <div
      class="grid gap-3"
      :class="isGitHubRepoRequired(selectedNode.data.githubOperation) ? 'grid-cols-2' : 'grid-cols-1'"
    >
      <div
        v-if="isGitHubOwnerRequired(selectedNode.data.githubOperation)"
        class="space-y-2"
      >
        <Label>
          {{ selectedNode.data.githubOperation === 'listOrganizationRepositories' ? 'Organization' : 'Owner' }}
        </Label>
        <ExpressionInput
          ref="githubOwnerExpressionInputRef"
          :model-value="selectedNode.data.githubOwner || ''"
          placeholder="octocat"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubOwner"
          v-bind="githubExpressionNavBindings('githubOwner')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubOwner', $event)"
        />
      </div>
      <div
        v-if="isGitHubRepoRequired(selectedNode.data.githubOperation)"
        class="space-y-2"
      >
        <Label>Repository</Label>
        <ExpressionInput
          ref="githubRepoExpressionInputRef"
          :model-value="selectedNode.data.githubRepo || ''"
          placeholder="hello-world"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubRepo"
          v-bind="githubExpressionNavBindings('githubRepo')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubRepo', $event)"
        />
      </div>
    </div>

    <template v-if="selectedNode.data.githubOperation === 'inviteUser'">
      <div class="space-y-2">
        <Label>Organization</Label>
        <ExpressionInput
          ref="githubOrganizationExpressionInputRef"
          :model-value="selectedNode.data.githubOrganization || ''"
          placeholder="octo-org"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubOrganization"
          v-bind="githubExpressionNavBindings('githubOrganization')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubOrganization', $event)"
        />
      </div>
      <div class="space-y-2">
        <Label>Email</Label>
        <ExpressionInput
          ref="githubInviteEmailExpressionInputRef"
          :model-value="selectedNode.data.githubInviteEmail || ''"
          placeholder="user@example.com"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubInviteEmail"
          v-bind="githubExpressionNavBindings('githubInviteEmail')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubInviteEmail', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'getIssue' || selectedNode.data.githubOperation === 'updateIssue' || selectedNode.data.githubOperation === 'createComment' || selectedNode.data.githubOperation === 'lockIssue'">
      <div class="space-y-2">
        <Label>Issue Number</Label>
        <ExpressionInput
          ref="githubIssueNumberExpressionInputRef"
          :model-value="selectedNode.data.githubIssueNumber || ''"
          placeholder="123"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubIssueNumber"
          v-bind="githubExpressionNavBindings('githubIssueNumber')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubIssueNumber', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'listIssues' || selectedNode.data.githubOperation === 'getRepositoryIssues' || selectedNode.data.githubOperation === 'getUserIssues' || selectedNode.data.githubOperation === 'listPullRequests' || selectedNode.data.githubOperation === 'getRepositoryPullRequests' || selectedNode.data.githubOperation === 'updateIssue'">
      <div
        class="grid gap-3"
        :class="usesGitHubPerPage(selectedNode.data.githubOperation) ? 'grid-cols-2' : 'grid-cols-1'"
      >
        <div class="space-y-2">
          <div class="flex items-center justify-between gap-2">
            <Label>State</Label>
            <AgentFieldToggle
              :node-id="selectedNode.id"
              field-key="githubState"
            />
          </div>
          <Select
            :model-value="selectedNode.data.githubOperation === 'updateIssue' ? (selectedNode.data.githubState ?? '') : (selectedNode.data.githubState || 'open')"
            :options="selectedNode.data.githubOperation === 'updateIssue' ? githubUpdateIssueStateOptions : githubStateOptions"
            @update:model-value="updateNodeData('githubState', $event)"
          />
        </div>
        <div
          v-if="usesGitHubPerPage(selectedNode.data.githubOperation)"
          class="space-y-2"
        >
          <div class="flex items-center justify-between gap-2">
            <Label>Per Page</Label>
            <AgentFieldToggle
              :node-id="selectedNode.id"
              field-key="githubPerPage"
            />
          </div>
          <Input
            type="number"
            min="1"
            max="100"
            :model-value="selectedNode.data.githubPerPage || '30'"
            placeholder="30"
            @update:model-value="updateNodeData('githubPerPage', $event)"
          />
        </div>
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'listIssues' || selectedNode.data.githubOperation === 'getRepositoryIssues' || selectedNode.data.githubOperation === 'getUserIssues'">
      <div class="grid grid-cols-2 gap-3">
        <div
          v-if="selectedNode.data.githubOperation !== 'getUserIssues'"
          class="space-y-2"
        >
          <Label>Assignee</Label>
          <ExpressionInput
            ref="githubAssigneeExpressionInputRef"
            :model-value="selectedNode.data.githubAssignee || ''"
            placeholder="octocat"
            single-line
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="githubAssignee"
            v-bind="githubExpressionNavBindings('githubAssignee')"
            @navigate="handleGitHubExpressionFieldNavigate"
            @register-field-index="onGitHubRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('githubAssignee', $event)"
          />
        </div>
        <div
          v-if="selectedNode.data.githubOperation !== 'getUserIssues'"
          class="space-y-2"
        >
          <Label>Creator</Label>
          <ExpressionInput
            ref="githubCreatorExpressionInputRef"
            :model-value="selectedNode.data.githubCreator || ''"
            placeholder="octocat"
            single-line
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="githubCreator"
            v-bind="githubExpressionNavBindings('githubCreator')"
            @navigate="handleGitHubExpressionFieldNavigate"
            @register-field-index="onGitHubRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('githubCreator', $event)"
          />
        </div>
        <div class="space-y-2">
          <Label>
            {{ selectedNode.data.githubOperation === 'getUserIssues' ? 'Mentioned Filter' : 'Mentioned User' }}
          </Label>
          <ExpressionInput
            ref="githubMentionedExpressionInputRef"
            :model-value="selectedNode.data.githubMentioned || ''"
            :placeholder="selectedNode.data.githubOperation === 'getUserIssues' ? 'true' : 'octocat'"
            single-line
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="githubMentioned"
            v-bind="githubExpressionNavBindings('githubMentioned')"
            @navigate="handleGitHubExpressionFieldNavigate"
            @register-field-index="onGitHubRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('githubMentioned', $event)"
          />
          <p
            v-if="selectedNode.data.githubOperation === 'getUserIssues'"
            class="text-xs text-muted-foreground"
          >
            Set any non-empty value to return issues mentioning the authenticated user
            instead of issues assigned to them.
          </p>
        </div>
        <div class="space-y-2">
          <Label>Labels</Label>
          <ExpressionInput
            ref="githubLabelsFilterExpressionInputRef"
            :model-value="selectedNode.data.githubLabelsFilter || ''"
            placeholder="bug,backend"
            single-line
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="githubLabelsFilter"
            v-bind="githubExpressionNavBindings('githubLabelsFilter')"
            @navigate="handleGitHubExpressionFieldNavigate"
            @register-field-index="onGitHubRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('githubLabelsFilter', $event)"
          />
        </div>
      </div>
      <div class="space-y-2">
        <Label>Updated Since</Label>
        <ExpressionInput
          ref="githubSinceExpressionInputRef"
          :model-value="selectedNode.data.githubSince || ''"
          placeholder="2026-01-01T00:00:00Z"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubSince"
          v-bind="githubExpressionNavBindings('githubSince')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubSince', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'listIssues' || selectedNode.data.githubOperation === 'getRepositoryIssues' || selectedNode.data.githubOperation === 'getUserIssues' || selectedNode.data.githubOperation === 'listPullRequests' || selectedNode.data.githubOperation === 'getRepositoryPullRequests'">
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-2">
          <div class="flex items-center justify-between gap-2">
            <Label>Sort</Label>
            <AgentFieldToggle
              :node-id="selectedNode.id"
              field-key="githubSort"
            />
          </div>
          <Select
            :model-value="selectedNode.data.githubSort || ''"
            :options="selectedNode.data.githubOperation === 'listPullRequests' || selectedNode.data.githubOperation === 'getRepositoryPullRequests' ? githubPullRequestSortOptions : githubIssueSortOptions"
            @update:model-value="updateNodeData('githubSort', $event)"
          />
        </div>
        <div class="space-y-2">
          <div class="flex items-center justify-between gap-2">
            <Label>Direction</Label>
            <AgentFieldToggle
              :node-id="selectedNode.id"
              field-key="githubDirection"
            />
          </div>
          <Select
            :model-value="selectedNode.data.githubDirection || ''"
            :options="githubDirectionOptions"
            @update:model-value="updateNodeData('githubDirection', $event)"
          />
        </div>
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'updateIssue'">
      <div class="space-y-2">
        <div class="flex items-center justify-between gap-2">
          <Label>State Reason</Label>
          <AgentFieldToggle
            :node-id="selectedNode.id"
            field-key="githubStateReason"
          />
        </div>
        <Select
          :model-value="selectedNode.data.githubStateReason ?? ''"
          :options="githubIssueStateReasonOptions"
          @update:model-value="updateNodeData('githubStateReason', $event)"
        />
      </div>
    </template>

    <template v-if="usesGitHubPerPage(selectedNode.data.githubOperation) && selectedNode.data.githubOperation !== 'listIssues' && selectedNode.data.githubOperation !== 'listPullRequests'">
      <div class="space-y-2">
        <div class="flex items-center justify-between gap-2">
          <Label>Per Page</Label>
          <AgentFieldToggle
            :node-id="selectedNode.id"
            field-key="githubPerPage"
          />
        </div>
        <Input
          type="number"
          min="1"
          max="100"
          :model-value="selectedNode.data.githubPerPage || '30'"
          placeholder="30"
          @update:model-value="updateNodeData('githubPerPage', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'createIssue' || selectedNode.data.githubOperation === 'updateIssue' || selectedNode.data.githubOperation === 'createPullRequest' || selectedNode.data.githubOperation === 'createRelease' || selectedNode.data.githubOperation === 'updateRelease'">
      <div class="space-y-2">
        <Label>{{ selectedNode.data.githubOperation === 'createRelease' || selectedNode.data.githubOperation === 'updateRelease' ? 'Name / Title' : 'Title' }}</Label>
        <ExpressionInput
          ref="githubTitleExpressionInputRef"
          :model-value="selectedNode.data.githubTitle || ''"
          placeholder="Fix flaky workflow run"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubTitle"
          v-bind="githubExpressionNavBindings('githubTitle')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubTitle', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'createIssue' || selectedNode.data.githubOperation === 'updateIssue' || selectedNode.data.githubOperation === 'createPullRequest' || selectedNode.data.githubOperation === 'createRelease' || selectedNode.data.githubOperation === 'updateRelease'">
      <div class="space-y-2">
        <Label>Body</Label>
        <ExpressionInput
          ref="githubBodyExpressionInputRef"
          :model-value="selectedNode.data.githubBody || ''"
          placeholder="$input.text"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubBody"
          v-bind="githubExpressionNavBindings('githubBody')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubBody', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'createComment'">
      <div class="space-y-2">
        <Label>Comment Body</Label>
        <ExpressionInput
          ref="githubCommentBodyExpressionInputRef"
          :model-value="selectedNode.data.githubCommentBody || '$input.text'"
          placeholder="$input.text"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubCommentBody"
          v-bind="githubExpressionNavBindings('githubCommentBody')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubCommentBody', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'createIssue' || selectedNode.data.githubOperation === 'updateIssue'">
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-2">
          <Label>Labels (JSON Array)</Label>
          <ExpressionInput
            ref="githubLabelsExpressionInputRef"
            :model-value="selectedNode.data.githubLabels ?? ''"
            placeholder="[&quot;bug&quot;, &quot;backend&quot;]"
            :rows="2"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="githubLabels"
            v-bind="githubExpressionNavBindings('githubLabels')"
            @navigate="handleGitHubExpressionFieldNavigate"
            @register-field-index="onGitHubRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('githubLabels', $event)"
          />
        </div>
        <div class="space-y-2">
          <Label>Assignees (JSON Array)</Label>
          <ExpressionInput
            ref="githubAssigneesExpressionInputRef"
            :model-value="selectedNode.data.githubAssignees ?? ''"
            placeholder="[&quot;octocat&quot;]"
            :rows="2"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="githubAssignees"
            v-bind="githubExpressionNavBindings('githubAssignees')"
            @navigate="handleGitHubExpressionFieldNavigate"
            @register-field-index="onGitHubRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('githubAssignees', $event)"
          />
        </div>
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'lockIssue'">
      <div class="space-y-2">
        <div class="flex items-center justify-between gap-2">
          <Label>Lock Reason</Label>
          <AgentFieldToggle
            :node-id="selectedNode.id"
            field-key="githubLockReason"
          />
        </div>
        <Select
          :model-value="selectedNode.data.githubLockReason ?? ''"
          :options="githubLockReasonOptions"
          @update:model-value="updateNodeData('githubLockReason', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'createPullRequest'">
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-2">
          <Label>Head Branch</Label>
          <ExpressionInput
            ref="githubHeadExpressionInputRef"
            :model-value="selectedNode.data.githubHead || ''"
            placeholder="feature/my-branch"
            single-line
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="githubHead"
            v-bind="githubExpressionNavBindings('githubHead')"
            @navigate="handleGitHubExpressionFieldNavigate"
            @register-field-index="onGitHubRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('githubHead', $event)"
          />
        </div>
        <div class="space-y-2">
          <Label>Base Branch</Label>
          <ExpressionInput
            ref="githubBaseExpressionInputRef"
            :model-value="selectedNode.data.githubBase || 'main'"
            placeholder="main"
            single-line
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="githubBase"
            v-bind="githubExpressionNavBindings('githubBase')"
            @navigate="handleGitHubExpressionFieldNavigate"
            @register-field-index="onGitHubRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('githubBase', $event)"
          />
        </div>
      </div>
      <div class="flex items-center gap-2">
        <input
          id="github-draft-pr"
          type="checkbox"
          :checked="selectedNode.data.githubDraft === true"
          class="rounded border-border"
          @change="updateNodeData('githubDraft', ($event.target as HTMLInputElement).checked)"
        >
        <label
          for="github-draft-pr"
          class="text-sm cursor-pointer select-none"
        >Create as draft pull request</label>
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'createReview' || selectedNode.data.githubOperation === 'getReview' || selectedNode.data.githubOperation === 'listReviews' || selectedNode.data.githubOperation === 'updateReview'">
      <div class="space-y-2">
        <Label>Pull Request Number</Label>
        <ExpressionInput
          ref="githubPullRequestNumberExpressionInputRef"
          :model-value="selectedNode.data.githubPullRequestNumber || ''"
          placeholder="123"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubPullRequestNumber"
          v-bind="githubExpressionNavBindings('githubPullRequestNumber')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubPullRequestNumber', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'getReview' || selectedNode.data.githubOperation === 'updateReview'">
      <div class="space-y-2">
        <Label>Review ID</Label>
        <ExpressionInput
          ref="githubReviewIdExpressionInputRef"
          :model-value="selectedNode.data.githubReviewId || ''"
          placeholder="987654"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubReviewId"
          v-bind="githubExpressionNavBindings('githubReviewId')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubReviewId', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'createReview'">
      <div class="space-y-2">
        <div class="flex items-center justify-between gap-2">
          <Label>Review Event</Label>
          <AgentFieldToggle
            :node-id="selectedNode.id"
            field-key="githubReviewEvent"
          />
        </div>
        <Select
          :model-value="selectedNode.data.githubReviewEvent || 'APPROVE'"
          :options="githubReviewEventOptions"
          @update:model-value="updateNodeData('githubReviewEvent', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'createReview' || selectedNode.data.githubOperation === 'updateReview'">
      <div class="space-y-2">
        <Label>Review Body</Label>
        <ExpressionInput
          ref="githubReviewBodyExpressionInputRef"
          :model-value="selectedNode.data.githubReviewBody || ''"
          placeholder="Looks good to me"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubReviewBody"
          v-bind="githubExpressionNavBindings('githubReviewBody')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubReviewBody', $event)"
        />
        <p
          v-if="selectedNode.data.githubOperation === 'createReview'"
          class="text-xs text-muted-foreground"
        >
          Required for Comment and Request Changes events.
        </p>
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'createReview'">
      <div class="space-y-2">
        <Label>Commit ID <span class="text-muted-foreground font-normal">(optional)</span></Label>
        <ExpressionInput
          ref="githubCommitIdExpressionInputRef"
          :model-value="selectedNode.data.githubCommitId || ''"
          placeholder="Latest PR commit when empty"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubCommitId"
          v-bind="githubExpressionNavBindings('githubCommitId')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubCommitId', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'getRelease' || selectedNode.data.githubOperation === 'updateRelease' || selectedNode.data.githubOperation === 'deleteRelease'">
      <div class="space-y-2">
        <Label>Release ID</Label>
        <ExpressionInput
          ref="githubReleaseIdExpressionInputRef"
          :model-value="selectedNode.data.githubReleaseId || ''"
          placeholder="123456"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubReleaseId"
          v-bind="githubExpressionNavBindings('githubReleaseId')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubReleaseId', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'createRelease' || selectedNode.data.githubOperation === 'updateRelease'">
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-2">
          <Label>Tag Name</Label>
          <ExpressionInput
            ref="githubTagNameExpressionInputRef"
            :model-value="selectedNode.data.githubTagName || ''"
            placeholder="v1.2.3"
            single-line
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="githubTagName"
            v-bind="githubExpressionNavBindings('githubTagName')"
            @navigate="handleGitHubExpressionFieldNavigate"
            @register-field-index="onGitHubRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('githubTagName', $event)"
          />
        </div>
        <div class="space-y-2">
          <Label>Target Commitish / Branch</Label>
          <ExpressionInput
            ref="githubBranchExpressionInputRef"
            :model-value="selectedNode.data.githubBranch || ''"
            placeholder="main"
            single-line
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="githubBranch"
            v-bind="githubExpressionNavBindings('githubBranch')"
            @navigate="handleGitHubExpressionFieldNavigate"
            @register-field-index="onGitHubRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('githubBranch', $event)"
          />
        </div>
      </div>
      <div class="flex items-center gap-4">
        <label class="flex items-center gap-2 text-sm cursor-pointer select-none">
          <input
            id="github-release-draft"
            type="checkbox"
            :checked="selectedNode.data.githubDraft === true"
            class="rounded border-border"
            @change="updateNodeData('githubDraft', ($event.target as HTMLInputElement).checked)"
          >
          <span>Draft release</span>
        </label>
        <label class="flex items-center gap-2 text-sm cursor-pointer select-none">
          <input
            id="github-release-prerelease"
            type="checkbox"
            :checked="selectedNode.data.githubPrerelease === true"
            class="rounded border-border"
            @change="updateNodeData('githubPrerelease', ($event.target as HTMLInputElement).checked)"
          >
          <span>Prerelease</span>
        </label>
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'getWorkflow' || selectedNode.data.githubOperation === 'dispatchWorkflow' || selectedNode.data.githubOperation === 'dispatchWorkflowAndWait' || selectedNode.data.githubOperation === 'enableWorkflow' || selectedNode.data.githubOperation === 'disableWorkflow' || selectedNode.data.githubOperation === 'getWorkflowUsage'">
      <div class="space-y-2">
        <Label>Workflow ID or File Name</Label>
        <ExpressionInput
          ref="githubWorkflowIdExpressionInputRef"
          :model-value="selectedNode.data.githubWorkflowId || ''"
          placeholder="build.yml"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubWorkflowId"
          v-bind="githubExpressionNavBindings('githubWorkflowId')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubWorkflowId', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'dispatchWorkflow' || selectedNode.data.githubOperation === 'dispatchWorkflowAndWait'">
      <div class="space-y-2">
        <Label>Ref or Branch</Label>
        <ExpressionInput
          ref="githubBranchExpressionInputRef"
          :model-value="selectedNode.data.githubBranch || ''"
          placeholder="main"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubBranch"
          v-bind="githubExpressionNavBindings('githubBranch')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubBranch', $event)"
        />
      </div>
      <div class="space-y-2">
        <Label>Workflow Inputs (JSON Object)</Label>
        <ExpressionInput
          ref="githubWorkflowInputsExpressionInputRef"
          :model-value="selectedNode.data.githubWorkflowInputs ?? ''"
          placeholder="{&quot;environment&quot;:&quot;prod&quot;}"
          :rows="3"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubWorkflowInputs"
          v-bind="githubExpressionNavBindings('githubWorkflowInputs')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubWorkflowInputs', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'dispatchWorkflowAndWait'">
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-2">
          <div class="flex items-center justify-between gap-2">
            <Label>Wait Timeout (seconds)</Label>
            <AgentFieldToggle
              :node-id="selectedNode.id"
              field-key="githubWaitTimeoutSeconds"
            />
          </div>
          <Input
            type="number"
            min="1"
            :model-value="selectedNode.data.githubWaitTimeoutSeconds || '600'"
            @update:model-value="updateNodeData('githubWaitTimeoutSeconds', $event)"
          />
        </div>
        <div class="space-y-2">
          <div class="flex items-center justify-between gap-2">
            <Label>Poll Interval (seconds)</Label>
            <AgentFieldToggle
              :node-id="selectedNode.id"
              field-key="githubPollIntervalSeconds"
            />
          </div>
          <Input
            type="number"
            min="0.1"
            step="0.1"
            :model-value="selectedNode.data.githubPollIntervalSeconds || '5'"
            @update:model-value="updateNodeData('githubPollIntervalSeconds', $event)"
          />
        </div>
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'getFile' || selectedNode.data.githubOperation === 'listFiles' || selectedNode.data.githubOperation === 'upsertFile' || selectedNode.data.githubOperation === 'deleteFile'">
      <div class="space-y-2">
        <Label>{{ selectedNode.data.githubOperation === 'listFiles' ? 'Directory Path' : 'File Path' }}</Label>
        <ExpressionInput
          ref="githubFilePathExpressionInputRef"
          :model-value="selectedNode.data.githubFilePath || ''"
          placeholder="docs/README.md"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubFilePath"
          v-bind="githubExpressionNavBindings('githubFilePath')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubFilePath', $event)"
        />
      </div>
      <div class="space-y-2">
        <Label>{{ selectedNode.data.githubOperation === 'getFile' || selectedNode.data.githubOperation === 'listFiles' ? 'Ref or Branch' : 'Target Branch' }}</Label>
        <ExpressionInput
          ref="githubBranchExpressionInputRef"
          :model-value="selectedNode.data.githubBranch || ''"
          placeholder="main"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubBranch"
          v-bind="githubExpressionNavBindings('githubBranch')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubBranch', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'upsertFile' || selectedNode.data.githubOperation === 'deleteFile'">
      <div class="space-y-2">
        <Label>Commit Message</Label>
        <ExpressionInput
          ref="githubCommitMessageExpressionInputRef"
          :model-value="selectedNode.data.githubCommitMessage || ''"
          placeholder="Update generated report"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubCommitMessage"
          v-bind="githubExpressionNavBindings('githubCommitMessage')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubCommitMessage', $event)"
        />
      </div>
    </template>

    <template v-if="selectedNode.data.githubOperation === 'upsertFile'">
      <div class="space-y-2">
        <Label>File Content</Label>
        <ExpressionInput
          ref="githubFileContentExpressionInputRef"
          :model-value="selectedNode.data.githubFileContent || '$input.text'"
          placeholder="$input.text"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="githubFileContent"
          v-bind="githubExpressionNavBindings('githubFileContent')"
          @navigate="handleGitHubExpressionFieldNavigate"
          @register-field-index="onGitHubRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('githubFileContent', $event)"
        />
      </div>
    </template>

    <div class="space-y-2 pt-2 border-t">
      <Label class="text-muted-foreground">Output</Label>
      <div class="text-xs font-mono space-y-1 text-muted-foreground">
        <template v-if="selectedNode.data.githubOperation === 'getRepository'">
          <div>${{ selectedNode.data.label }}.repository - Repository payload</div>
          <div>${{ selectedNode.data.label }}.full_name - owner/repo</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'getRepositoryLicense'">
          <div>${{ selectedNode.data.label }}.license - License payload</div>
          <div>${{ selectedNode.data.label }}.spdx_id - SPDX identifier</div>
          <div>${{ selectedNode.data.label }}.content - Decoded license content</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'getRepositoryProfile'">
          <div>${{ selectedNode.data.label }}.profile - Community profile payload</div>
          <div>${{ selectedNode.data.label }}.health_percentage - Health score</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'listPopularPaths'">
          <div>${{ selectedNode.data.label }}.paths - Popular path array</div>
          <div>${{ selectedNode.data.label }}.count - Number of paths</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'listReferrers'">
          <div>${{ selectedNode.data.label }}.referrers - Referrer array</div>
          <div>${{ selectedNode.data.label }}.count - Number of referrers</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'listOrganizationRepositories' || selectedNode.data.githubOperation === 'listUserRepositories' || selectedNode.data.githubOperation === 'getUserRepositories'">
          <div>${{ selectedNode.data.label }}.repositories - Repository array</div>
          <div>${{ selectedNode.data.label }}.count - Number of repositories</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'inviteUser'">
          <div>${{ selectedNode.data.label }}.invitation - Invitation payload</div>
          <div>${{ selectedNode.data.label }}.id - Invitation ID</div>
          <div>${{ selectedNode.data.label }}.email - Invited email</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'getIssue' || selectedNode.data.githubOperation === 'createIssue' || selectedNode.data.githubOperation === 'updateIssue'">
          <div>${{ selectedNode.data.label }}.issue - Issue payload</div>
          <div>${{ selectedNode.data.label }}.number - Issue number</div>
          <div>${{ selectedNode.data.label }}.url - GitHub URL</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'createComment'">
          <div>${{ selectedNode.data.label }}.comment - Comment payload</div>
          <div>${{ selectedNode.data.label }}.id - Comment ID</div>
          <div>${{ selectedNode.data.label }}.url - Comment URL</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'lockIssue'">
          <div>${{ selectedNode.data.label }}.locked - Boolean</div>
          <div>${{ selectedNode.data.label }}.issue_number - Locked issue number</div>
          <div>${{ selectedNode.data.label }}.lock_reason - Lock reason if provided</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'listIssues' || selectedNode.data.githubOperation === 'getRepositoryIssues' || selectedNode.data.githubOperation === 'getUserIssues'">
          <div>${{ selectedNode.data.label }}.issues - Issue array</div>
          <div>${{ selectedNode.data.label }}.count - Number of issues</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'listPullRequests' || selectedNode.data.githubOperation === 'getRepositoryPullRequests'">
          <div>${{ selectedNode.data.label }}.pull_requests - PR array</div>
          <div>${{ selectedNode.data.label }}.count - Number of pull requests</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'createPullRequest'">
          <div>${{ selectedNode.data.label }}.pull_request - PR payload</div>
          <div>${{ selectedNode.data.label }}.number - Pull request number</div>
          <div>${{ selectedNode.data.label }}.url - Pull request URL</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'getReview' || selectedNode.data.githubOperation === 'createReview' || selectedNode.data.githubOperation === 'updateReview'">
          <div>${{ selectedNode.data.label }}.review - Review payload</div>
          <div>${{ selectedNode.data.label }}.id - Review ID</div>
          <div>${{ selectedNode.data.label }}.state - Review state</div>
          <div>${{ selectedNode.data.label }}.url - Review URL</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'listReviews'">
          <div>${{ selectedNode.data.label }}.reviews - Review array</div>
          <div>${{ selectedNode.data.label }}.count - Number of reviews</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'listReleases'">
          <div>${{ selectedNode.data.label }}.releases - Release array</div>
          <div>${{ selectedNode.data.label }}.count - Number of releases</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'getRelease' || selectedNode.data.githubOperation === 'createRelease' || selectedNode.data.githubOperation === 'updateRelease'">
          <div>${{ selectedNode.data.label }}.release - Release payload</div>
          <div>${{ selectedNode.data.label }}.id - Release ID</div>
          <div>${{ selectedNode.data.label }}.tag_name - Tag name</div>
          <div>${{ selectedNode.data.label }}.url - Release URL</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'deleteRelease'">
          <div>${{ selectedNode.data.label }}.deleted - Boolean</div>
          <div>${{ selectedNode.data.label }}.release_id - Deleted release ID</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'listWorkflows'">
          <div>${{ selectedNode.data.label }}.workflows - Workflow array</div>
          <div>${{ selectedNode.data.label }}.count - Number of workflows</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'getWorkflow'">
          <div>${{ selectedNode.data.label }}.workflow - Workflow payload</div>
          <div>${{ selectedNode.data.label }}.id - Workflow ID</div>
          <div>${{ selectedNode.data.label }}.path - Workflow file path</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'enableWorkflow'">
          <div>${{ selectedNode.data.label }}.enabled - Boolean</div>
          <div>${{ selectedNode.data.label }}.workflow_id - Workflow target</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'disableWorkflow'">
          <div>${{ selectedNode.data.label }}.disabled - Boolean</div>
          <div>${{ selectedNode.data.label }}.workflow_id - Workflow target</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'getWorkflowUsage'">
          <div>${{ selectedNode.data.label }}.usage - Workflow usage payload</div>
          <div>${{ selectedNode.data.label }}.billable - Usage by runner OS</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'dispatchWorkflow'">
          <div>${{ selectedNode.data.label }}.dispatched - Boolean</div>
          <div>${{ selectedNode.data.label }}.workflow_id - Workflow target</div>
          <div>${{ selectedNode.data.label }}.ref - Workflow ref</div>
          <div>${{ selectedNode.data.label }}.inputs - Dispatch inputs object</div>
          <div>${{ selectedNode.data.label }}.workflow_run_id - Run ID when returned</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'dispatchWorkflowAndWait'">
          <div>${{ selectedNode.data.label }}.completed - Boolean</div>
          <div>${{ selectedNode.data.label }}.workflow_run - Completed run payload</div>
          <div>${{ selectedNode.data.label }}.conclusion - Run conclusion</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'listFiles'">
          <div>${{ selectedNode.data.label }}.path - Directory path</div>
          <div>${{ selectedNode.data.label }}.items - Directory entries</div>
          <div>${{ selectedNode.data.label }}.count - Number of items</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'getFile'">
          <div>${{ selectedNode.data.label }}.file - File payload</div>
          <div>${{ selectedNode.data.label }}.path - Repository path</div>
          <div>${{ selectedNode.data.label }}.sha - File SHA</div>
          <div>${{ selectedNode.data.label }}.content - Decoded text content</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'upsertFile'">
          <div>${{ selectedNode.data.label }}.file - File payload</div>
          <div>${{ selectedNode.data.label }}.path - Repository path</div>
          <div>${{ selectedNode.data.label }}.sha - File SHA</div>
          <div>${{ selectedNode.data.label }}.commit_sha - Commit SHA</div>
          <div>${{ selectedNode.data.label }}.created - True when file was newly created</div>
        </template>
        <template v-else-if="selectedNode.data.githubOperation === 'deleteFile'">
          <div>${{ selectedNode.data.label }}.deleted - Boolean</div>
          <div>${{ selectedNode.data.label }}.path - Deleted repository path</div>
          <div>${{ selectedNode.data.label }}.sha - Deleted file SHA</div>
          <div>${{ selectedNode.data.label }}.commit_sha - Deletion commit SHA</div>
        </template>
        <template v-else>
          <div>Select an operation to see output fields</div>
        </template>
      </div>
    </div>
  </template>
</template>
