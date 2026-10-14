<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Eye, EyeOff } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import {
  jiraAuthHelpText,
  jiraSecretLabel,
  type JiraAuthMode,
  type JiraDeployment,
} from "./jiraCredentialConfig";

const props = defineProps<{
  saving: boolean;
  isEditing: boolean;
  testing: boolean;
  canTest: boolean;
  testSuccess: boolean | null;
  testMessage: string;
}>();

const emit = defineEmits<{ test: [] }>();

const email = defineModel<string>("email", { required: true });
const secret = defineModel<string>("secret", { required: true });
const baseUrl = defineModel<string>("baseUrl", { required: true });
const deployment = defineModel<JiraDeployment>("deployment", { required: true });
const apiVersion = defineModel<string>("apiVersion", { required: true });
const authMode = defineModel<JiraAuthMode>("authMode", { required: true });

const showSecret = ref(false);

const isDataCenter = computed((): boolean => deployment.value === "data_center");
const isPat = computed((): boolean => isDataCenter.value && authMode.value === "pat");

const userLabel = computed((): string => (isDataCenter.value ? "Jira Username" : "Jira Email"));
const userPlaceholder = computed((): string =>
  isDataCenter.value ? "jira-user" : "you@example.com",
);
const secretLabel = computed((): string => jiraSecretLabel(deployment.value, authMode.value));
const secretPlaceholder = computed((): string => {
  if (props.isEditing) {
    return "••••••• (re-enter to update)";
  }
  if (isPat.value) {
    return "Jira personal access token";
  }
  return isDataCenter.value ? "Jira password" : "Atlassian API token";
});
const helpText = computed((): string => jiraAuthHelpText(deployment.value, authMode.value));

// Personal access tokens only exist for Data Center / Server.
watch(deployment, (value): void => {
  if (value === "cloud") {
    authMode.value = "basic";
  }
});
</script>

<template>
  <div class="space-y-4">
    <div class="space-y-2">
      <Label for="cred-jira-deployment">Deployment</Label>
      <Select
        id="cred-jira-deployment"
        v-model="deployment"
        :options="[
          { value: 'cloud', label: 'Jira Cloud' },
          { value: 'data_center', label: 'Jira Data Center / Server' },
        ]"
        :disabled="saving"
      />
    </div>
    <div
      v-if="isDataCenter"
      class="space-y-2"
    >
      <Label for="cred-jira-auth-mode">Authentication</Label>
      <Select
        id="cred-jira-auth-mode"
        v-model="authMode"
        :options="[
          { value: 'basic', label: 'Username and password' },
          { value: 'pat', label: 'Personal Access Token' },
        ]"
        :disabled="saving"
      />
    </div>
    <div
      v-if="!isPat"
      class="space-y-2"
    >
      <Label for="cred-jira-email">{{ userLabel }}</Label>
      <Input
        id="cred-jira-email"
        v-model="email"
        :placeholder="userPlaceholder"
        :disabled="saving"
      />
    </div>
    <div class="space-y-2">
      <Label for="cred-jira-api-token">{{ secretLabel }}</Label>
      <div class="relative">
        <Input
          id="cred-jira-api-token"
          v-model="secret"
          :type="showSecret ? 'text' : 'password'"
          :placeholder="secretPlaceholder"
          :disabled="saving"
          class="pr-10"
        />
        <button
          type="button"
          class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          @click="showSecret = !showSecret"
        >
          <EyeOff
            v-if="showSecret"
            class="w-4 h-4"
          />
          <Eye
            v-else
            class="w-4 h-4"
          />
        </button>
      </div>
    </div>
    <div class="space-y-2">
      <Label for="cred-jira-base-url">Jira Base URL</Label>
      <Input
        id="cred-jira-base-url"
        v-model="baseUrl"
        placeholder="https://your-domain.atlassian.net"
        :disabled="saving"
      />
    </div>
    <div class="space-y-2">
      <Label for="cred-jira-api-version">REST API Version</Label>
      <Input
        id="cred-jira-api-version"
        :model-value="isDataCenter ? '2' : apiVersion"
        placeholder="3"
        :disabled="saving || isDataCenter"
        @update:model-value="apiVersion = String($event)"
      />
      <p class="text-xs text-muted-foreground">
        {{ helpText }} Use the Jira site URL, not a REST path. Jira Cloud defaults to v3; Data
        Center and Server use REST API v2.
      </p>
    </div>
    <div class="flex items-center gap-3">
      <Button
        type="button"
        variant="outline"
        size="sm"
        data-testid="jira-test-connection-button"
        :loading="testing"
        :disabled="saving || testing || !canTest"
        @click="emit('test')"
      >
        Test Connection
      </Button>
      <p
        v-if="testMessage"
        class="text-xs"
        :class="testSuccess ? 'text-emerald-600' : 'text-destructive'"
      >
        {{ testMessage }}
      </p>
    </div>
  </div>
</template>
