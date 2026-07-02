<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { AlertTriangle } from "lucide-vue-next";

import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import {
  getSentryOperationGroups,
  isSentryFieldVisible,
  type SentryFieldKey,
} from "@/lib/sentryExpressionFields";
import { credentialsApi } from "@/services/api";
import type { CredentialListItem } from "@/types/credential";

import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const { selectedNode, workflowStore, updateNodeData } = usePropertiesPanelContext();

const sentryCredentials = ref<CredentialListItem[]>([]);

const sentryCredentialOptions = computed(() => [
  { value: "", label: "Select Sentry credential..." },
  ...sentryCredentials.value.map((credential) => ({
    value: credential.id,
    label: credential.name,
  })),
]);

const sentryOperationGroups = getSentryOperationGroups();

async function loadSentryCredentials(): Promise<void> {
  try {
    sentryCredentials.value = await credentialsApi.listByType("sentry");
  } catch {
    sentryCredentials.value = [];
  }
}

function isOrganizationRequired(operation: string | undefined): boolean {
  return isSentryFieldVisible(operation, "sentryOrganizationSlug");
}

function usesProject(operation: string | undefined): boolean {
  return isSentryFieldVisible(operation, "sentryProjectSlug");
}

function usesLimit(operation: string | undefined): boolean {
  return isSentryFieldVisible(operation, "sentryLimit");
}

function fieldVisible(field: SentryFieldKey, operation: string | undefined): boolean {
  return isSentryFieldVisible(operation, field);
}

onMounted(() => {
  void loadSentryCredentials();
});

watch(
  () => selectedNode.value?.type,
  (type) => {
    if (type === "sentry") {
      void loadSentryCredentials();
    }
  },
);
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Sentry Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="sentryCredentialOptions"
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

    <div
      class="space-y-2"
      data-testid="sentry-operation-field"
    >
      <Label>Operation</Label>
      <SearchableSelect
        :model-value="selectedNode.data.sentryOperation || 'listIssues'"
        :groups="sentryOperationGroups"
        search-placeholder="Search Sentry operations..."
        @update:model-value="updateNodeData('sentryOperation', $event)"
      />
    </div>

    <div
      v-if="isOrganizationRequired(selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Organization Slug</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryOrganizationSlug || ''"
        placeholder="acme"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryOrganizationSlug"
        @update:model-value="updateNodeData('sentryOrganizationSlug', $event)"
      />
    </div>

    <div
      v-if="usesProject(selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>{{ selectedNode.data.sentryOperation === "listIssues" ? "Project ID or Slug" : "Project Slug" }}</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryProjectSlug || ''"
        placeholder="web-app"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryProjectSlug"
        @update:model-value="updateNodeData('sentryProjectSlug', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentryTeamSlug', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Team Slug</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryTeamSlug || ''"
        placeholder="frontend"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryTeamSlug"
        @update:model-value="updateNodeData('sentryTeamSlug', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentryName', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Name</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryName || ''"
        placeholder="Web App"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryName"
        @update:model-value="updateNodeData('sentryName', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentrySlug', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Slug</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentrySlug || ''"
        placeholder="web-app"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentrySlug"
        @update:model-value="updateNodeData('sentrySlug', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentryPlatform', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Platform</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryPlatform || ''"
        placeholder="javascript"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryPlatform"
        @update:model-value="updateNodeData('sentryPlatform', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentryQuery', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Query</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryQuery || ''"
        placeholder="is:unresolved level:error"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryQuery"
        @update:model-value="updateNodeData('sentryQuery', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentryStatsPeriod', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Stats Period</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryStatsPeriod || '14d'"
        placeholder="14d"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryStatsPeriod"
        @update:model-value="updateNodeData('sentryStatsPeriod', $event)"
      />
    </div>

    <div
      v-if="usesLimit(selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Limit</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryLimit || '25'"
        placeholder="25"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryLimit"
        @update:model-value="updateNodeData('sentryLimit', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentryIssueId', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Issue ID</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryIssueId || ''"
        placeholder="PROJECT-1"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryIssueId"
        @update:model-value="updateNodeData('sentryIssueId', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentryStatus', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Status</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryStatus || ''"
        placeholder="resolved"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryStatus"
        @update:model-value="updateNodeData('sentryStatus', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentryAssignedTo', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Assigned To</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryAssignedTo || ''"
        placeholder="user@example.com"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryAssignedTo"
        @update:model-value="updateNodeData('sentryAssignedTo', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentryEventId', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Event ID</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryEventId || ''"
        placeholder="event-id"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryEventId"
        @update:model-value="updateNodeData('sentryEventId', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentryReleaseVersion', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Release Version</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryReleaseVersion || ''"
        placeholder="1.0.0"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryReleaseVersion"
        @update:model-value="updateNodeData('sentryReleaseVersion', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentryReleaseProjects', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Release Projects JSON</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryReleaseProjects || '[]'"
        placeholder="[&quot;web-app&quot;]"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryReleaseProjects"
        @update:model-value="updateNodeData('sentryReleaseProjects', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentryReleaseRefs', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Release Refs JSON</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryReleaseRefs || '[]'"
        placeholder="[{&quot;repository&quot;:&quot;repo&quot;,&quot;commit&quot;:&quot;sha&quot;}]"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryReleaseRefs"
        @update:model-value="updateNodeData('sentryReleaseRefs', $event)"
      />
    </div>

    <div
      v-if="fieldVisible('sentryPayload', selectedNode.data.sentryOperation)"
      class="space-y-2"
    >
      <Label>Payload JSON</Label>
      <ExpressionInput
        :model-value="selectedNode.data.sentryPayload || '{}'"
        placeholder="{&quot;name&quot;:&quot;New name&quot;}"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="sentryPayload"
        @update:model-value="updateNodeData('sentryPayload', $event)"
      />
    </div>
  </template>
</template>
